"""Walk the public Store listing (no auth) and return normalized rows.

Quirks of `GET https://api.apify.com/v2/store`, measured on 2026-11-10:
  * `offset` stops working at 15,000 for every `sortBy`: later pages come back empty. So one
    sweep sees at most 15,000 positions, no matter what `total` (~115k) says.
  * ~15% of each page is silently dropped (a limit=1000 page may hold 855 items), and smaller
    pages do not recover them. Pagination is positional, so always advance by the requested limit.
  * `total` wobbles between calls and `desc` is ignored.
That is why the collector reads `popularity` until an empty page, plus a few `newest` pages.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Iterator

import httpx

from radar.normalize import normalize

log = logging.getLogger("radar.collect")

API = "https://api.apify.com/v2/store"
# Neutral on purpose; set RADAR_USER_AGENT to add your own contact info.
USER_AGENT = os.environ.get("RADAR_USER_AGENT", "store-snapshot-client/0.1")
PAGE_SIZE = 1000
MAX_PAGES = 130  # safety stop (~the whole store); in practice the API ends the sweep at page 15
MIN_ROWS = 8_000  # fewer rows than this means the API changed or blocked us: save nothing


class CollectError(RuntimeError):
    pass


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(90.0))


def _get(client: httpx.Client, params: dict, *, retries: int = 4, backoff: float = 2.0) -> dict:
    for attempt in range(retries):
        try:
            resp = client.get(API, params=params)
            resp.raise_for_status()
            return resp.json()["data"]
        except (httpx.TransportError, httpx.HTTPStatusError, ValueError, KeyError) as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            retryable = status is None or status == 429 or status >= 500
            if not retryable or attempt == retries - 1:
                raise CollectError(f"GET {params} failed: {exc!r}") from exc
            wait = backoff * 2**attempt
            log.warning("GET %s failed (%r); retrying in %.0fs", params, exc, wait)
            time.sleep(wait)
    raise AssertionError("unreachable")


def sweep(client: httpx.Client, sort_by: str, max_pages: int, pause: float) -> Iterator[list[dict]]:
    """Yield raw pages for one ordering until the API returns an empty page."""
    for page in range(max_pages):
        data = _get(client, {"limit": PAGE_SIZE, "offset": page * PAGE_SIZE, "sortBy": sort_by})
        if not data["items"]:
            return
        log.info("%s page %d: %d items", sort_by, page, len(data["items"]))
        yield data["items"]
        time.sleep(pause)


def collect(client: httpx.Client, collected_at: str, *, newest_pages: int = 3, pause: float = 1.0) -> list[dict]:
    """Rows for every distinct Actor seen: all of `popularity` the API will give, plus `newest_pages` of `newest`."""
    rows: dict[str, dict] = {}
    for sort_by, rank_key, pages in (
        ("popularity", "rank_popularity", MAX_PAGES),
        ("newest", "rank_newest", newest_pages),
    ):
        rank = 0
        for items in sweep(client, sort_by, pages, pause):
            for item in items:
                rank += 1
                row = rows.get(item["id"])
                if row is None:
                    row = rows[item["id"]] = normalize(item)
                    row["collected_at"] = collected_at
                if row[rank_key] is None:  # an Actor can repeat when the listing shifts mid-crawl: keep its first position
                    row[rank_key] = rank
        log.info("%s: %d listed, %d distinct Actors so far", sort_by, rank, len(rows))
    if len(rows) < MIN_ROWS:
        raise CollectError(f"only {len(rows)} Actors collected (expected >= {MIN_ROWS}); nothing was saved")
    return list(rows.values())
