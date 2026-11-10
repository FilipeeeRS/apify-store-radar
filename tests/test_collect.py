import httpx
import pytest

from radar import collect as c


def item(i):
    return {"id": f"id{i}", "username": "dev", "name": f"actor-{i}", "title": f"Actor {i}", "stats": {"totalUsers30Days": i}}


def client_for(pages, status=None):
    """Fake API: pages maps (sortBy, offset) -> items; anything else is an empty page."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        key = (params["sortBy"], int(params["offset"]))
        calls.append(key)
        if status:
            code = status.pop(0) if status else 200
            if code != 200:
                return httpx.Response(code, json={"error": "boom"})
        return httpx.Response(200, json={"data": {"total": 115000, "count": 1000, "items": pages.get(key, [])}})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(c.time, "sleep", lambda _s: None)


def test_dedupes_ranks_and_stops_at_the_first_empty_page(monkeypatch):
    monkeypatch.setattr(c, "MIN_ROWS", 1)
    pages = {
        ("popularity", 0): [item(1), item(2), item(3)],
        ("popularity", 1000): [item(3), item(4)],  # id3 repeats: the listing shifted while we crawled
        ("newest", 0): [item(4), item(5)],
    }
    client, calls = client_for(pages)
    rows = {r["actor_id"]: r for r in c.collect(client, "2026-11-10 00:00:00", newest_pages=3, pause=0)}

    assert sorted(rows) == ["id1", "id2", "id3", "id4", "id5"]
    assert rows["id3"]["rank_popularity"] == 3  # first position wins
    assert rows["id4"]["rank_popularity"] == 5 and rows["id4"]["rank_newest"] == 1
    assert rows["id5"]["rank_popularity"] is None and rows["id5"]["rank_newest"] == 2
    assert rows["id1"]["collected_at"] == "2026-11-10 00:00:00"
    assert calls == [("popularity", 0), ("popularity", 1000), ("popularity", 2000), ("newest", 0), ("newest", 1000)]


def test_refuses_to_save_a_suspiciously_small_snapshot():
    client, _ = client_for({("popularity", 0): [item(1)]})
    with pytest.raises(c.CollectError, match="nothing was saved"):
        c.collect(client, "2026-11-10 00:00:00", pause=0)


def test_server_errors_are_retried():
    client, calls = client_for({("popularity", 0): [item(1)]}, status=[500, 503])
    data = c._get(client, {"limit": 1000, "offset": 0, "sortBy": "popularity"})
    assert len(data["items"]) == 1 and len(calls) == 3


def test_client_errors_are_not_retried():
    client, calls = client_for({}, status=[400])
    with pytest.raises(c.CollectError):
        c._get(client, {"limit": 1000, "offset": 0, "sortBy": "popularity"})
    assert len(calls) == 1
