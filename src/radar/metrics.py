"""Niche metrics on top of the daily snapshots, computed in DuckDB.

Per niche (target, target + thing extracted, or Store category) for the latest snapshot:
demand (sum of 30d users), supply (Actors, and "active" Actors), concentration (leader's share),
growth (weekly change between snapshots, plus a single-snapshot "ritmo" that works from day 1)
and quality gaps (share of demand sitting on Actors that fail often or are rated badly).
"""

from __future__ import annotations

from datetime import timedelta

from radar import niches

# Tunable thresholds ---------------------------------------------------------------------------
MIN_ACTIVE_USERS = 5  # an Actor "competes" in its niche when it has at least this many 30d users
MIN_NICHE_DEMAND = 100  # rankings ignore niches below this many 30d users ...
MIN_NICHE_ACTORS = 3  # ... and, for targets, niches with fewer Actors than this
MIN_PREV_USERS7 = 20  # weekly growth needs a base at least this large to mean anything
MAX_COMPETITORS = 12  # "under-served": at most this many active Actors,
MAX_TOP_SHARE = 0.8  # no monopoly (the leader holds at most this share of the niche's users),
MAX_APIFY_SHARE = 0.5  # and official `apify/` Actors hold at most this share
GAP_MIN_USERS = 30  # quality gap: an Actor with this many 30d users that ...
GAP_MIN_RUNS, GAP_MAX_SUCCESS = 100, 0.85  # ... succeeds in under 85% of at least 100 runs, or ...
GAP_MIN_REVIEWS, GAP_MAX_RATING = 5, 3.5  # ... is rated under 3.5 by at least 5 reviewers
ENTRANT_DAYS = 14  # "recent entrant": first seen in the last 14 days (and after the very first snapshot)
REF_MIN_DAYS, REF_MAX_DAYS = 7, 14  # growth compares with the newest snapshot that is 7-14 days old
TOP = 20  # rows per ranking

GAP_SQL = (
    f"(users_30d >= {GAP_MIN_USERS} AND ("
    f"(runs_30d >= {GAP_MIN_RUNS} AND runs_ok_30d::DOUBLE / runs_30d < {GAP_MAX_SUCCESS}) "
    f"OR (reviews >= {GAP_MIN_REVIEWS} AND rating < {GAP_MAX_RATING})))"
)
_KEY_SQL = {"target": "target", "niche": "niche", "category": "unnest(categories)"}


def _rows(con, sql: str) -> list[dict]:
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def pick_reference(dates: list, latest) -> object | None:
    """Newest snapshot that is 7-14 days older than `latest`, or None."""
    ok = [d for d in dates if timedelta(days=REF_MIN_DAYS) <= latest - d <= timedelta(days=REF_MAX_DAYS)]
    return max(ok) if ok else None


def _load_niches(con) -> None:
    """Classify every Actor in the history by its latest title into the temp table `niche_map`."""
    rows = con.execute("SELECT actor_id, arg_max(title, snapshot_date), arg_max(slug, snapshot_date) FROM snap GROUP BY actor_id").fetchall()
    mapping = niches.classify(rows)
    con.execute("CREATE OR REPLACE TEMP TABLE niche_map (actor_id VARCHAR, target VARCHAR, niche VARCHAR, pii BOOLEAN)")
    con.executemany("INSERT INTO niche_map VALUES (?, ?, ?, ?)", [(a, n.target, n.niche, n.pii) for a, n in mapping.items()])


def _niche_table(con, kind: str) -> list[dict]:
    """One row per niche of `kind` (target | niche | category) from the temp tables `cur` and `prev`."""
    key = _KEY_SQL[kind]
    con.execute(f"CREATE OR REPLACE TEMP TABLE cur_k AS SELECT *, {key} AS k FROM cur")
    con.execute(f"CREATE OR REPLACE TEMP TABLE prev_k AS SELECT *, {key} AS k FROM prev")
    return _rows(
        con,
        f"""
        WITH g AS (SELECT sum(users_30d)::DOUBLE AS u30, sum(users_90d)::DOUBLE AS u90 FROM cur),
        agg AS (
          SELECT k AS name,
                 count(*) AS actors,
                 count(*) FILTER (WHERE users_30d >= {MIN_ACTIVE_USERS}) AS active,
                 count(DISTINCT owner) AS owners,
                 sum(users_30d) AS users30,
                 sum(users_90d) AS users90,
                 sum(users_7d) AS users7,
                 max(users_30d) AS top_users,
                 arg_max(slug, users_30d) AS leader,
                 coalesce(sum(users_30d) FILTER (WHERE owner = 'apify'), 0) AS apify_users,
                 coalesce(sum(users_30d) FILTER (WHERE {GAP_SQL}), 0) AS gap_users,
                 avg(CAST(pii AS INTEGER)) AS pii_share,
                 median(price_usd) AS median_price
          FROM cur_k GROUP BY k),
        grow AS (  -- same-store growth: only Actors present in both snapshots
          SELECT c.k AS name, sum(c.users_7d)::DOUBLE AS now7, sum(p.users_7d)::DOUBLE AS prev7
          FROM cur_k c JOIN prev_k p ON c.actor_id = p.actor_id AND c.k = p.k GROUP BY c.k)
        SELECT a.name, a.actors, a.active, a.owners, a.users30, a.users7, a.leader, a.pii_share, a.median_price,
               a.top_users::DOUBLE / nullif(a.users30, 0) AS top_share,
               a.apify_users::DOUBLE / nullif(a.users30, 0) AS apify_share,
               a.gap_users::DOUBLE / nullif(a.users30, 0) AS gap_share,
               a.users30::DOUBLE / nullif(a.active, 0) AS users_per_active,
               (a.users30::DOUBLE / nullif(a.users90, 0)) / (g.u30 / g.u90) AS ritmo,
               CASE WHEN gr.prev7 >= {MIN_PREV_USERS7} THEN gr.now7 / gr.prev7 - 1 END AS wow
        FROM agg a CROSS JOIN g LEFT JOIN grow gr USING (name)
        """,
    )


def analyze(con) -> dict:
    """Everything the report needs, from the `snap` view created by store.connect()."""
    dates = [r[0] for r in con.execute("SELECT DISTINCT snapshot_date FROM snap ORDER BY 1").fetchall()]
    latest, first = dates[-1], dates[0]
    ref = pick_reference(dates, latest)
    _load_niches(con)
    select = (
        "SELECT s.*, m.target, m.niche, m.pii FROM snap s JOIN niche_map m USING (actor_id) "
        "WHERE s.snapshot_date = DATE '{}'"
    )
    con.execute("CREATE OR REPLACE TEMP TABLE cur AS " + select.format(latest))
    con.execute("CREATE OR REPLACE TEMP TABLE prev AS " + select.format(ref or "1970-01-01"))  # no reference: empty

    meta = _rows(
        con,
        """SELECT count(*) AS actors,
                  count(*) FILTER (WHERE users_30d > 0) AS with_users,
                  sum(users_30d) AS users30,
                  sum(users_30d) FILTER (WHERE owner = 'apify')::DOUBLE / nullif(sum(users_30d), 0) AS apify_share
           FROM cur""",
    )[0]
    meta.update(latest=latest, first=first, ref=ref, snapshots=len(dates))

    targets = [r for r in _niche_table(con, "target") if r["name"] != "(outros)"]
    fine = [r for r in _niche_table(con, "niche") if r["name"] != "(outros)"]
    categories = _niche_table(con, "category")

    growth = "wow" if ref else "ritmo"
    rising = sorted(
        (
            r
            for r in targets
            if r["users30"] >= MIN_NICHE_DEMAND and r["actors"] >= MIN_NICHE_ACTORS and r[growth] is not None
        ),
        key=lambda r: r[growth],
        reverse=True,
    )[:TOP]
    underserved = sorted(
        (
            r
            for r in fine
            if r["users30"] >= MIN_NICHE_DEMAND
            and 1 <= r["active"] <= MAX_COMPETITORS
            and r["top_share"] <= MAX_TOP_SHARE
            and r["apify_share"] <= MAX_APIFY_SHARE
        ),
        key=lambda r: r["users_per_active"],
        reverse=True,
    )[:TOP]

    gaps = _rows(
        con,
        f"""SELECT slug, title, niche, users_30d AS users30, runs_30d AS runs30,
                   CASE WHEN runs_30d > 0 THEN runs_ok_30d::DOUBLE / runs_30d END AS success,
                   rating::DOUBLE AS rating, reviews, price_usd
            FROM cur WHERE {GAP_SQL} ORDER BY users_30d DESC LIMIT {TOP + 5}""",
    )
    entrants = _rows(
        con,
        f"""WITH fs AS (SELECT actor_id, min(snapshot_date) AS first_seen FROM snap GROUP BY 1)
            SELECT c.slug, c.title, c.niche, c.users_30d AS users30, c.users_7d AS users7, fs.first_seen, c.rank_newest
            FROM cur c JOIN fs USING (actor_id)
            WHERE fs.first_seen > DATE '{first}' AND fs.first_seen >= DATE '{latest}' - INTERVAL {ENTRANT_DAYS} DAY
            ORDER BY c.users_30d DESC LIMIT {TOP}""",
    )
    return {
        "meta": meta,
        "targets_demand": sorted(targets, key=lambda r: r["users30"], reverse=True)[:TOP],
        "rising": rising,
        "underserved": underserved,
        "gaps": gaps,
        "entrants": entrants,
        "categories": sorted(categories, key=lambda r: r["users30"], reverse=True),
    }
