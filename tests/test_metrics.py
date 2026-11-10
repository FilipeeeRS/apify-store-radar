from datetime import date

import pytest

from radar import metrics, store
from radar.normalize import SCHEMA


def row(actor_id, slug, title, users30, users7, users90, **extra):
    base = dict.fromkeys(SCHEMA)
    base.update(
        actor_id=actor_id, slug=slug, owner=slug.split("/")[0], title=title, categories=["OTHER"],
        users_30d=users30, users_7d=users7, users_90d=users90, users_total=users90,
        runs_30d=0, runs_ok_30d=0, reviews=0, rating=0,
    )
    base.update(extra)
    return base


@pytest.fixture
def con(tmp_path):
    week1 = [
        row("a1", "dev/foo-scraper", "Foo Scraper", 100, 20, 200),
        row("a2", "dev2/foo-profile", "Foo Profile Scraper", 60, 20, 100),
        # popular but fails half of its runs: a quality gap
        row("a3", "dev3/foo-jobs", "Foo Jobs Scraper", 40, 10, 80, runs_30d=200, runs_ok_30d=100),
        row("b1", "dev/baz-scraper", "Baz Scraper", 100, 30, 150),
        row("b2", "dev2/baz-fast", "Baz Fast Scraper", 50, 10, 70),
    ]
    week2 = [
        row("a1", "dev/foo-scraper", "Foo Scraper", 110, 30, 210),
        row("a2", "dev2/foo-profile", "Foo Profile Scraper", 60, 20, 100),
        row("a3", "dev3/foo-jobs", "Foo Jobs Scraper", 40, 10, 80, runs_30d=200, runs_ok_30d=100),
        row("b1", "dev/baz-scraper", "Baz Scraper", 100, 30, 150),
        row("b2", "dev2/baz-fast", "Baz Fast Scraper", 50, 10, 70),
        row("n1", "dev4/foo-new", "Foo New Scraper", 5, 5, 5, rank_newest=1),  # first seen on day 2
    ]
    store.write_snapshot(week1, tmp_path, "2026-11-01")
    store.write_snapshot(week2, tmp_path, "2026-11-08")
    return store.connect(tmp_path)


def test_reference_snapshot_is_the_one_a_week_earlier(con):
    meta = metrics.analyze(con)["meta"]
    assert meta["snapshots"] == 2
    assert meta["ref"] == date(2026, 11, 1) and meta["latest"] == date(2026, 11, 8)


def test_weekly_growth_only_counts_actors_present_in_both_snapshots(con):
    rising = metrics.analyze(con)["rising"]
    foo = next(r for r in rising if r["name"] == "foo")
    assert foo["actors"] == 4  # a1, a2, a3 and the entrant
    assert foo["wow"] == pytest.approx((30 + 20 + 10) / (20 + 20 + 10) - 1)  # n1 is excluded: it has no past


def test_quality_gap_and_entrant_are_detected(con):
    result = metrics.analyze(con)
    assert [g["slug"] for g in result["gaps"]] == ["dev3/foo-jobs"]
    assert result["gaps"][0]["success"] == pytest.approx(0.5)
    assert [e["slug"] for e in result["entrants"]] == ["dev4/foo-new"]


def test_underserved_niche_has_demand_few_competitors_and_no_monopoly(con):
    names = [r["name"] for r in metrics.analyze(con)["underserved"]]
    assert "baz" in names
    baz = next(r for r in metrics.analyze(con)["underserved"] if r["name"] == "baz")
    assert baz["users30"] == 150 and baz["active"] == 2 and baz["users_per_active"] == 75
    assert baz["top_share"] == pytest.approx(100 / 150)


def test_without_a_week_of_history_growth_falls_back_to_ritmo(tmp_path):
    store.write_snapshot([row("a1", "dev/foo-scraper", "Foo Scraper", 100, 20, 200)] * 1, tmp_path, "2026-11-01")
    result = metrics.analyze(store.connect(tmp_path))
    assert result["meta"]["ref"] is None and result["entrants"] == []


def test_connect_explains_when_there_is_no_data(tmp_path):
    with pytest.raises(FileNotFoundError, match="radar collect"):
        store.connect(tmp_path)
