"""Group Actors into niches using only their titles (the slug is a fallback).

An Actor's *target* is the site or product it works on ("instagram", "google maps", "mercado livre").
Its *niche* adds what it pulls from there ("instagram reel", "amazon review"). Both are heuristics:
cheap, deterministic and easy to audit, not NLP. Titles on the Store follow "<Target> <Thing> Scraper"
closely enough for that to work; the rest is long tail and gets filtered by minimum support.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

STOP = frozenset(
    "a an the and or for to of in on at by with without from into your you any all no not com br "
    "de do da dos das para em e o os as um uma la el los las del con por".split()
)

# Marketing and tooling words that say nothing about the target.
GENERIC = frozenset(
    """scraper scrapers scraping scrape scraped scrapper scrappers crawler crawlers crawl crawling spider
    extractor extract extraction api apis data dataset datasets monitor monitoring tracker tracking checker
    finder bot bots tool tools actor actors lite pro plus premium free cheap cheaper cheapest best easy simple
    fast faster fastest powerful advanced ultimate unofficial official reliable mass bulk multi mega super
    smart auto automatic instant quick new cookies cookie login nocookies collector harvester grabber
    fetcher parser mcp server servers verifier verify validator validate verification generator downloader
    download enrichment enricher converter analyzer scanner lookup run runs per like vs alternative
    alternatives""".split()
)

# Words that say what is extracted rather than where from. Variants map to one canonical word.
_FUNCTION_GROUPS = {
    "review": "review reviews rating ratings",
    "job": "job jobs career careers hiring vacancies",
    "profile": "profile profiles user users account accounts",
    "post": "post posts",
    "comment": "comment comments",
    "follower": "follower followers following",
    "hashtag": "hashtag hashtags",
    "reel": "reel reels",
    "story": "story stories",
    "video": "video videos",
    "image": "image images photo photos picture pictures",
    "search": "search results serp",
    "product": "product products item items",
    "price": "price prices pricing",
    "listing": "listing listings",
    "ad": "ad ads",
    "email": "email emails mail",
    "phone": "phone phones",
    "contact": "contact contacts",
    "lead": "lead leads",
    "detail": "detail details info information",
    "url": "url urls link links",
    "page": "page pages",
    "content": "content text",
    "transcript": "transcript transcripts subtitles captions",
    "keyword": "keyword keywords",
    "seller": "seller sellers",
    "shop": "shop shops",
    "store": "store stores",
    "trend": "trend trends trending",
}
FUNCTION = {word: canon for canon, words in _FUNCTION_GROUPS.items() for word in words.split()}

ALIAS = {"tweet": "twitter", "tweets": "twitter", "x": "twitter", "insta": "instagram", "ig": "instagram",
         "yt": "youtube", "fb": "facebook"}

# Signals that a niche probably handles personal data (LGPD/GDPR). A hint, not a legal analysis.
PII_WORDS = frozenset(
    "profile follower email phone contact lead people person resume cv dating friend "
    "linkedin facebook instagram tiktok twitter snapchat tinder onlyfans whatsapp telegram".split()
)

MIN_PAIR = 3  # a two-word target ("mercado livre") needs this many Actors ...
PAIR_RATIO = 0.6  # ... and its first word must be followed by the second at least this often

_PRE = (
    (re.compile(r"tik\s*tok"), "tiktok"),
    (re.compile(r"you\s*tube"), "youtube"),
    (re.compile(r"linked\s*in"), "linkedin"),
    (re.compile(r"\$\s?[\d.,]+(?:\s?/\s?\w+)?"), " "),  # prices such as "$1.5/1k"
    (re.compile(r"\b([a-z0-9-]+)\.(?:com|net|org|io|co|ca|uk|br|de|fr|es|it|in|jp|au|ai|app|dev)\b"), r"\1"),
)
_CUT = re.compile(r"\s[-|/]\s|\s[+&]\s|\s(?:like|vs|versus|alternatives?)\s|[:|(\[{]")  # the marketing tail starts here
_WORD = re.compile(r"[a-z0-9]+")
_NOISE = re.compile(r"^(?:(?:19|20)\d\d|\d{1,3}[a-z]{0,2}|v\d+)$")  # 2025, 1k, 24h, v2 (but 1688 and 99acres are sites)


@dataclass(frozen=True)
class Niche:
    target: str
    niche: str
    pii: bool


def tokenize(text: str, *, head_only: bool = True) -> list[str]:
    """Meaningful lowercase words of the title's head ("Google Maps Scraper - fast..." -> ["google", "maps"])."""
    text = text.replace("—", " - ").replace("–", " - ")
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))  # strip accents
    text = re.sub(r"[^\x00-\x7f]", " ", text).lower()  # emoji, CJK and symbols become plain separators
    for pattern, repl in _PRE:
        text = pattern.sub(repl, text)
    if head_only:
        text = _CUT.split(text, maxsplit=1)[0]
    words = []
    for word in _WORD.findall(text):
        if word in STOP or word in GENERIC or _NOISE.match(word) or (len(word) == 1 and word != "x"):
            continue
        words.append(ALIAS.get(word, word))
    return words


def _head(words: list[str]) -> int:
    """Index of the target word: the first one that is not a 'what is extracted' word."""
    return next((i for i, w in enumerate(words) if w not in FUNCTION), 0)


def classify(actors: list[tuple[str, str | None, str]]) -> dict[str, Niche]:
    """(actor_id, title, slug) for every Actor -> {actor_id: Niche}. Two passes so that two-word targets are learned."""
    parsed: dict[str, list[str]] = {}
    first: Counter[str] = Counter()
    pair: Counter[tuple[str, str]] = Counter()
    for actor_id, title, slug in actors:
        # head of the title; else the whole title (e.g. "<CJK> API | Douyin Video Search"); else the slug
        words = (
            tokenize(title or "")
            or tokenize(title or "", head_only=False)
            or tokenize(slug.split("/", 1)[-1].replace("-", " ").replace("_", " "), head_only=False)
        )
        parsed[actor_id] = words
        if words:
            i = _head(words)
            first[words[i]] += 1
            if i + 1 < len(words) and words[i + 1] not in FUNCTION:
                pair[(words[i], words[i + 1])] += 1

    out: dict[str, Niche] = {}
    for actor_id, words in parsed.items():
        if not words:
            out[actor_id] = Niche("(outros)", "(outros)", False)
            continue
        i = _head(words)
        word, nxt, target = words[i], i + 1, words[i]
        if nxt < len(words) and pair[(word, words[nxt])] >= MIN_PAIR and pair[(word, words[nxt])] / first[word] >= PAIR_RATIO:
            target, nxt = f"{word} {words[nxt]}", nxt + 1
        # what is extracted: the nearest other word after the target, else the nearest one before it
        taken = {FUNCTION.get(w, w) for w in target.split()}
        around = [FUNCTION.get(w, w) for w in words[nxt:] + words[:i][::-1]]
        extra = next((w for w in around if w not in taken), None)
        niche = f"{target} {extra}" if extra else target
        canonical = {FUNCTION.get(w, w) for w in words}
        out[actor_id] = Niche(target, niche, bool(canonical & PII_WORDS))
    return out
