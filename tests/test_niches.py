import pytest

from radar.niches import classify


def one(title, slug="dev/some-actor"):
    return classify([("a", title, slug)])["a"]


@pytest.mark.parametrize(
    ("title", "target", "niche"),
    [
        ("Google Maps Scraper", "google", "google maps"),
        ("Instagram Profile Scraper", "instagram", "instagram profile"),
        ("Profile Scraper for Instagram", "instagram", "instagram profile"),
        ("Tweet Scraper V2 - X Scraper / Twitter Scraper / X.com Scraper", "twitter", "twitter"),
        ("✨Mass Linkedin Profile Scraper with Email 📧 (No Cookies)", "linkedin", "linkedin profile"),
        ("Amazon Email Scraper – Advanced, Cheapest & Reliable 📧🎟️", "amazon", "amazon email"),
        ("Walmart Scraper | Prices, Reviews, Sellers, Availability", "walmart", "walmart"),
        ("TikTok Shop Product Scraper: SKU Matrix & Stock", "tiktok", "tiktok shop"),
        ("Tik Tok Video Downloader", "tiktok", "tiktok video"),
        ("Email Verifier", "email", "email"),
        ("1688 Product Details Scraper", "1688", "1688 product"),  # a number can be the site; years and counts are not
        ("Leads Scraper ✅ $1/1k Leads ✅ 50K/Run With EMAILS✅Like Apollo", "leads", "leads email"),
        ("抖音 API | Douyin Video Search, Comments & Profiles", "douyin", "douyin video"),  # head is empty: use the whole title
    ],
)
def test_title_to_target_and_niche(title, target, niche):
    got = one(title)
    assert (got.target, got.niche) == (target, niche)


def test_two_word_target_is_learned_from_the_data():
    titles = ["Mercado Livre Scraper", "Mercado Livre Product Scraper", "Mercado Livre Prices", "Mercado Livre Reviews"]
    got = classify([(str(i), t, "dev/x") for i, t in enumerate(titles)])
    assert {n.target for n in got.values()} == {"mercado livre"}
    assert sorted(n.niche for n in got.values()) == ["mercado livre", "mercado livre price", "mercado livre product", "mercado livre review"]


def test_falls_back_to_the_slug_when_the_title_has_no_usable_words():
    assert one("🔥🔥", "dev/airbnb-scraper").target == "airbnb"
    assert one("", "dev/scraper").target == "(outros)"


def test_personal_data_hint():
    assert one("Instagram Profile Scraper").pii
    assert one("Contact Details Scraper").pii
    assert not one("Airbnb Scraper").pii
