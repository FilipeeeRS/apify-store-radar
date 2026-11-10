"""Command line: `radar collect | report | run`."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from radar import collect as collector
from radar import metrics, report, store


def cmd_collect(args: argparse.Namespace) -> None:
    now = datetime.now(timezone.utc)
    day = args.date or now.date().isoformat()
    with collector.make_client() as client:
        rows = collector.collect(
            client, now.strftime("%Y-%m-%d %H:%M:%S"), newest_pages=args.newest_pages, pause=args.pause
        )
    path = store.write_snapshot(rows, args.data, day)
    print(f"snapshot {day}: {len(rows):,} Actors -> {path} ({path.stat().st_size / 1e6:.2f} MB)")


def cmd_report(args: argparse.Namespace) -> None:
    con = store.connect(args.data)
    result = metrics.analyze(con)
    out = Path(args.site)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(report.render_markdown(result), encoding="utf-8")
    (out / "index.html").write_text(report.render_html(result), encoding="utf-8")
    meta = result["meta"]
    print(f"report for {meta['latest']} ({meta['snapshots']} snapshot(s)) -> {out / 'index.html'}, {out / 'report.md'}")


def cmd_run(args: argparse.Namespace) -> None:
    cmd_collect(args)
    cmd_report(args)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to cp1252
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    parser = argparse.ArgumentParser(prog="radar", description="Daily Apify Store snapshots and niche metrics.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func, helptext in (
        ("collect", cmd_collect, "fetch today's snapshot and save it as Parquet"),
        ("report", cmd_report, "build the Markdown and HTML report from the saved snapshots"),
        ("run", cmd_run, "collect, then report"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.set_defaults(func=func)
        p.add_argument("--data", default="data", help="snapshot directory (default: data)")
        if name != "collect":
            p.add_argument("--site", default="site", help="report output directory (default: site)")
        if name != "report":
            p.add_argument("--newest-pages", type=int, default=3, help="pages of the `newest` listing to add (default: 3)")
            p.add_argument("--pause", type=float, default=1.0, help="seconds between API calls (default: 1.0)")
            p.add_argument("--date", help="snapshot_date to write, YYYY-MM-DD (default: today, UTC; for tests and backfills)")
    args = parser.parse_args(argv)
    args.func(args)
    return 0
