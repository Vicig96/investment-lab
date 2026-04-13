#!/usr/bin/env python3
"""Safely reset the local SQLite DB and reimport real OHLCV CSV files.

This is intentionally a local-development utility:
  1. Backup the current SQLite DB file (and any -wal / -shm sidecars)
  2. Remove the live local DB
  3. Recreate the schema
  4. Reimport all CSVs from data/real_prices/

The goal is to eliminate stale mixed candle data so the local API/UI reads
only the real imported history.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def _sanitize_debug_env() -> None:
    valid = {"0", "1", "true", "false", "yes", "no", "on", "off", ""}
    debug = os.getenv("DEBUG", "").strip().lower()
    if debug not in valid:
        os.environ["DEBUG"] = "false"


_sanitize_debug_env()

from app.core.config import get_settings

RELEVANT_TABLES = [
    "instruments",
    "price_candles",
    "indicator_cache",
    "signals",
    "backtest_runs",
    "backtest_results",
    "portfolio_snapshots",
]
REQUIRED_TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]


def _sqlite_path_from_url(url: str) -> Path:
    prefixes = ("sqlite:///", "sqlite+aiosqlite:///")
    for prefix in prefixes:
        if url.startswith(prefix):
            raw = url[len(prefix):]
            return Path(raw)
    raise ValueError(f"Unsupported SQLite URL: {url}")


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _db_summary(db_path: Path) -> dict:
    summary = {
        "exists": db_path.exists(),
        "path": str(db_path.resolve()),
        "counts": {},
        "tickers": [],
    }
    if not db_path.exists():
        return summary

    conn = sqlite3.connect(db_path)
    try:
        for table in RELEVANT_TABLES:
            if _table_exists(conn, table):
                summary["counts"][table] = conn.execute(
                    f"select count(*) from {table}"
                ).fetchone()[0]
        if _table_exists(conn, "instruments"):
            summary["tickers"] = [
                row[0]
                for row in conn.execute(
                    "select ticker from instruments order by ticker"
                ).fetchall()
            ]
    finally:
        conn.close()
    return summary


def _print_summary(label: str, summary: dict) -> None:
    print(label)
    print(f"  db_path: {summary['path']}")
    print(f"  exists: {summary['exists']}")
    if summary["counts"]:
        for table in RELEVANT_TABLES:
            if table in summary["counts"]:
                print(f"  {table}: {summary['counts'][table]}")
    if summary["tickers"]:
        print(f"  tickers: {', '.join(summary['tickers'])}")
    print()


def _backup_sqlite_artifacts(db_path: Path, backup_dir: Path) -> list[Path]:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)

    artifacts = [
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ]
    moved: list[Path] = []
    for artifact in artifacts:
        if not artifact.exists():
            continue
        destination = backup_dir / f"{artifact.name}.{timestamp}.bak"
        shutil.move(str(artifact), str(destination))
        moved.append(destination)
    return moved


async def _reset_and_import(
    db_path: Path,
    data_dir: Path,
    min_history_warning: int,
    backup_dir: Path,
) -> int:
    backups = _backup_sqlite_artifacts(db_path, backup_dir)
    if backups:
        print("Backups created")
        for backup in backups:
            print(f"  {backup.resolve()}")
        print()
    else:
        print("No existing SQLite DB found to back up.\n")

    from import_real_prices import run as import_real_prices_run

    result = await import_real_prices_run(data_dir, min_history_warning)
    print()

    after = _db_summary(db_path)
    _print_summary("After reset/import", after)

    tickers_present = set(after["tickers"])
    missing_tickers = [ticker for ticker in REQUIRED_TICKERS if ticker not in tickers_present]
    if missing_tickers:
        print(f"ERROR: required tickers missing after import: {', '.join(missing_tickers)}")
        return 1

    if result != 0:
        print("ERROR: CSV import reported failures.")
        return result

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backup, reset, and repopulate the local SQLite DB from real OHLCV CSVs"
    )
    parser.add_argument(
        "--data-dir",
        default="data/real_prices",
        help="Folder containing one CSV per ticker (default: data/real_prices)",
    )
    parser.add_argument(
        "--min-history-warning",
        type=int,
        default=200,
        help="Warn when a ticker has fewer valid rows than this threshold (default: 200)",
    )
    parser.add_argument(
        "--backup-dir",
        default="data/db_backups",
        help="Folder where the current SQLite DB backup will be stored",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually perform the reset. Without this flag the script only prints what it would reset.",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        sys.exit(
            f"ERROR: directory not found: {data_dir}\n"
            f"Create it and place files like SPY.csv, QQQ.csv, IWM.csv, TLT.csv, GLD.csv inside."
        )

    settings = get_settings()
    if not settings.is_sqlite:
        sys.exit("ERROR: this reset workflow is only for the local SQLite database.")

    db_path = _sqlite_path_from_url(settings.database_url_sync).resolve()
    repo_root = Path.cwd().resolve()
    if not db_path.is_relative_to(repo_root):
        sys.exit(
            f"ERROR: refusing to reset a SQLite DB outside the repo workspace: {db_path}"
        )

    backup_dir = Path(args.backup_dir).resolve()

    print("Reset mode: FULL LOCAL SQLITE RESET")
    print(f"Data dir: {data_dir.resolve()}")
    print(f"Backup dir: {backup_dir}")
    print()

    before = _db_summary(db_path)
    _print_summary("Before reset", before)

    if not args.yes:
        print("Dry run only. Re-run with --yes to back up, reset, and reimport the local DB.")
        raise SystemExit(0)

    raise SystemExit(
        asyncio.run(
            _reset_and_import(
                db_path=db_path,
                data_dir=data_dir.resolve(),
                min_history_warning=args.min_history_warning,
                backup_dir=backup_dir,
            )
        )
    )


if __name__ == "__main__":
    main()
