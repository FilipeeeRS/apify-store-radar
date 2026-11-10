"""Parquet storage: one immutable file per day, Hive-partitioned by snapshot_date, queried with DuckDB."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import duckdb

from radar.normalize import SCHEMA


def partition_file(root: str | Path, day: str) -> Path:
    return Path(root) / "snapshots" / f"snapshot_date={day}" / "actors.parquet"


def _lit(path: str | Path) -> str:
    """SQL string literal for a path (COPY targets cannot be bound parameters)."""
    return "'" + str(path).replace("\\", "/").replace("'", "''") + "'"


def write_snapshot(rows: list[dict], root: str | Path, day: str) -> Path:
    """Write today's rows as `snapshots/snapshot_date=<day>/actors.parquet` (replaces a same-day file)."""
    target = partition_file(root, day)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".parquet.tmp")
    columns = ", ".join(f"'{name}': '{sql_type}'" for name, sql_type in SCHEMA.items())
    with tempfile.TemporaryDirectory() as work:
        ndjson = Path(work) / "rows.ndjson"
        with ndjson.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        con = duckdb.connect()
        try:
            # Sorted by slug (similar strings sit together) + ZSTD 19: ~15% smaller than the defaults, and deterministic.
            con.execute(
                f"COPY (SELECT * FROM read_json({_lit(ndjson)}, format = 'newline_delimited', "
                f"columns = {{{columns}}}) ORDER BY slug, actor_id) "
                f"TO {_lit(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 19)"
            )
        finally:
            con.close()
    os.replace(tmp, target)
    return target


def connect(root: str | Path) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with a `snap` view over every daily file under `root`."""
    if not any(Path(root).glob("snapshots/snapshot_date=*/actors.parquet")):
        raise FileNotFoundError(f"no snapshots under {root}; run `radar collect` first")
    pattern = (Path(root) / "snapshots" / "snapshot_date=*" / "actors.parquet").as_posix()
    con = duckdb.connect()
    con.execute(
        "CREATE VIEW snap AS SELECT * REPLACE (CAST(snapshot_date AS DATE) AS snapshot_date) "
        f"FROM read_parquet({_lit(pattern)}, hive_partitioning = true, union_by_name = true)"
    )
    return con
