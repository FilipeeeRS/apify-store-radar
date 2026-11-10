"""Flatten one raw Store item into the compact row kept in each daily snapshot."""

from __future__ import annotations

# Column -> DuckDB type. This is also the Parquet schema (see store.py).
# Left out on purpose: description, picture URLs and event texts (heavy, and git keeps every day forever).
SCHEMA: dict[str, str] = {
    "actor_id": "VARCHAR",
    "slug": "VARCHAR",  # username/name
    "owner": "VARCHAR",
    "title": "VARCHAR",
    "categories": "VARCHAR[]",
    "users_total": "BIGINT",
    "users_90d": "INTEGER",
    "users_30d": "INTEGER",
    "users_7d": "INTEGER",
    "runs_total": "BIGINT",
    "runs_30d": "INTEGER",
    "runs_ok_30d": "INTEGER",
    "runs_failed_30d": "INTEGER",
    "runs_aborted_30d": "INTEGER",
    "runs_timeout_30d": "INTEGER",
    "builds_total": "INTEGER",
    "last_run_at": "TIMESTAMP",
    "rating": "DECIMAL(3,2)",
    "reviews": "INTEGER",
    "bookmarks": "INTEGER",
    "pricing_model": "VARCHAR",
    "price_usd": "DOUBLE",  # primary pay-per-event price, free-plan tier
    "pricing_started_at": "TIMESTAMP",  # when the current pricing began; a lower bound for "monetized since"
    "agentic": "BOOLEAN",
    "badge": "VARCHAR",
    "notice": "VARCHAR",
    "rank_popularity": "INTEGER",  # 1-based position in today's `popularity` listing (as returned, see README)
    "rank_newest": "INTEGER",  # 1-based position in today's `newest` listing, null when outside the pages we read
    "collected_at": "TIMESTAMP",
}


def _ts(value: str | None) -> str | None:
    """'2026-11-10T16:23:46.816Z' -> '2026-11-10 16:23:46.816' (naive UTC, what DuckDB parses as TIMESTAMP)."""
    return value.rstrip("Z").replace("T", " ") if value else None


def primary_price(pricing: dict) -> float | None:
    """USD price of the primary pay-per-event charge on the free-plan tier, if the Actor has one."""
    events = (pricing.get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
    for event in events.values():
        if event.get("isPrimaryEvent"):
            tier = (event.get("eventTieredPricingUsd") or {}).get("FREE") or {}
            return tier.get("tieredEventPriceUsd", event.get("eventPriceUsd"))
    return None


def normalize(item: dict) -> dict:
    """One raw `GET /v2/store` item -> one flat row (rank_* and collected_at are filled by the collector)."""
    stats = item.get("stats") or {}
    runs = stats.get("publicActorRunStats30Days") or {}
    pricing = item.get("currentPricingInfo") or {}
    rating = item.get("actorReviewRating", stats.get("actorReviewRating"))
    return {
        "actor_id": item["id"],
        "slug": f"{item['username']}/{item['name']}",
        "owner": item["username"],
        "title": item.get("title"),
        "categories": item.get("categories") or [],
        "users_total": stats.get("totalUsers"),
        "users_90d": stats.get("totalUsers90Days"),
        "users_30d": stats.get("totalUsers30Days"),
        "users_7d": stats.get("totalUsers7Days"),
        "runs_total": stats.get("totalRuns"),
        "runs_30d": runs.get("TOTAL"),
        "runs_ok_30d": runs.get("SUCCEEDED"),
        "runs_failed_30d": runs.get("FAILED"),
        "runs_aborted_30d": runs.get("ABORTED"),
        "runs_timeout_30d": runs.get("TIMED-OUT"),
        "builds_total": stats.get("totalBuilds"),
        "last_run_at": _ts(stats.get("lastRunStartedAt")),
        "rating": round(rating, 2) if rating is not None else None,
        "reviews": item.get("actorReviewCount", stats.get("actorReviewCount")),
        "bookmarks": item.get("bookmarkCount", stats.get("bookmarkCount")),
        "pricing_model": pricing.get("pricingModel"),
        "price_usd": primary_price(pricing),
        "pricing_started_at": _ts(pricing.get("startedAt")),
        "agentic": item.get("isWhiteListedForAgenticPayments"),
        "badge": item.get("badge"),
        "notice": item.get("notice"),
        "rank_popularity": None,
        "rank_newest": None,
        "collected_at": None,
    }
