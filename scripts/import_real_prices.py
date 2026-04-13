#!/usr/bin/env python3
"""Validate and import real daily OHLCV CSV files into the local database.

Expected workflow:
  1. Put one CSV per ticker in data/real_prices/
  2. Run this script once
  3. Review the per-ticker validation/import report
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path


def _sanitize_debug_env() -> None:
    valid = {"0", "1", "true", "false", "yes", "no", "on", "off", ""}
    debug = os.getenv("DEBUG", "").strip().lower()
    if debug not in valid:
        os.environ["DEBUG"] = "false"


_sanitize_debug_env()

from sqlalchemy import select

from app.db.init_db import create_tables
from app.db.session import AsyncSessionLocal
from app.models.instrument import Instrument
from app.services.data_ingestion.csv_loader import CSVValidationReport, validate_ohlcv_csv
from app.services.data_ingestion.ingestor import upsert_price_rows


async def get_or_create_instrument(ticker: str) -> tuple[Instrument, bool]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Instrument).where(Instrument.ticker == ticker))
        instrument = result.scalar_one_or_none()
        created = False
        if instrument is None:
            instrument = Instrument(ticker=ticker)
            session.add(instrument)
            await session.flush()
            created = True
        await session.commit()
        return instrument, created


async def import_one_file(csv_path: Path, min_history_warning: int) -> dict:
    ticker = csv_path.stem.upper()
    validation = validate_ohlcv_csv(csv_path.read_bytes(), min_history_warning=min_history_warning)
    report = validation.report

    if report.errors:
        return {
            "ticker": ticker,
            "instrument_action": "not_imported",
            "imported_rows": 0,
            "report": report,
        }

    instrument, created = await get_or_create_instrument(ticker)

    async with AsyncSessionLocal() as session:
        try:
            imported_rows = await upsert_price_rows(session, instrument.id, validation.rows)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            report.errors.append(f"Database import failed: {exc}")
            imported_rows = 0

    return {
        "ticker": ticker,
        "instrument_action": "created" if created else "existing",
        "imported_rows": imported_rows,
        "report": report,
    }


def render_report(result: dict) -> None:
    ticker = result["ticker"]
    report: CSVValidationReport = result["report"]
    instrument_action = result["instrument_action"]
    imported_rows = result["imported_rows"]

    if report.errors:
        status = "FAIL"
    elif report.warnings:
        status = "WARN"
    else:
        status = "OK"

    print(f"[{status}] {ticker}")
    print(f"  instrument: {instrument_action}")
    print(f"  imported_rows: {imported_rows}")
    print(f"  dropped_rows: {report.dropped_rows}")
    print(f"  total_rows: {report.total_rows}")
    if report.first_date and report.last_date:
        print(f"  date_range: {report.first_date} -> {report.last_date}")
    if report.normalized_columns:
        print(f"  columns: {', '.join(report.normalized_columns)}")
    if report.issue_counts:
        issue_summary = ", ".join(f"{key}={value}" for key, value in sorted(report.issue_counts.items()))
        print(f"  issue_counts: {issue_summary}")
    for warning in report.warnings:
        print(f"  warning: {warning}")
    for error in report.errors:
        print(f"  error: {error}")
    print()


async def run(data_dir: Path, min_history_warning: int) -> int:
    await create_tables()

    csv_files = sorted(path for path in data_dir.glob("*.csv") if path.is_file())
    if not csv_files:
        print(f"ERROR: no CSV files found in {data_dir}")
        return 1

    print(f"Data dir: {data_dir.resolve()}")
    print(f"Files: {len(csv_files)}")
    print()

    ok = warn = fail = 0
    imported_total = 0
    dropped_total = 0

    for csv_path in csv_files:
        result = await import_one_file(csv_path, min_history_warning)
        render_report(result)

        report: CSVValidationReport = result["report"]
        imported_total += result["imported_rows"]
        dropped_total += report.dropped_rows

        if report.errors:
            fail += 1
        elif report.warnings:
            warn += 1
        else:
            ok += 1

    print("Summary")
    print(f"  ok: {ok}")
    print(f"  warn: {warn}")
    print(f"  fail: {fail}")
    print(f"  imported_rows: {imported_total}")
    print(f"  dropped_rows: {dropped_total}")

    return 1 if fail else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-validate and import real OHLCV CSV files")
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
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        sys.exit(
            f"ERROR: directory not found: {data_dir}\n"
            f"Create it and place files like SPY.csv, QQQ.csv, IWM.csv, TLT.csv, GLD.csv inside."
        )

    raise SystemExit(asyncio.run(run(data_dir, args.min_history_warning)))


if __name__ == "__main__":
    main()
