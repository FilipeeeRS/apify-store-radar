import json
from pathlib import Path

from radar.normalize import SCHEMA, normalize, primary_price

# Real items from GET /v2/store (2026-11-10), trimmed: pictures and long texts removed.
ITEMS = json.loads((Path(__file__).parent / "fixtures" / "store_items.json").read_text(encoding="utf-8"))
BY_SLUG = {f"{i['username']}/{i['name']}": i for i in ITEMS}


def test_rows_have_exactly_the_schema_columns():
    for item in ITEMS:
        assert set(normalize(item)) == set(SCHEMA)


def test_basic_fields():
    row = normalize(BY_SLUG["compass/crawler-google-places"])
    assert row["slug"] == "compass/crawler-google-places"
    assert row["owner"] == "compass"
    assert row["users_30d"] == 47424
    assert row["runs_30d"] == row["runs_ok_30d"] + row["runs_failed_30d"] + row["runs_aborted_30d"] + row["runs_timeout_30d"]
    assert row["categories"] == ["LEAD_GENERATION", "TRAVEL"]
    assert row["rating"] == 4.71


def test_timestamps_are_naive_utc_strings():
    row = normalize(BY_SLUG["compass/crawler-google-places"])
    assert "T" not in row["last_run_at"] and not row["last_run_at"].endswith("Z")


def test_primary_event_price_comes_from_the_free_tier():
    assert normalize(BY_SLUG["streamers/youtube-scraper"])["price_usd"] == 0.004


def test_flat_event_price_is_supported():
    pricing = {"pricingPerEvent": {"actorChargeEvents": {"a": {"isPrimaryEvent": True, "eventPriceUsd": 0.5}}}}
    assert primary_price(pricing) == 0.5


def test_actor_without_pay_per_event_has_no_price():
    free = next(i for i in ITEMS if i["currentPricingInfo"]["pricingModel"] == "FREE")
    row = normalize(free)
    assert row["price_usd"] is None and row["pricing_model"] == "FREE"
