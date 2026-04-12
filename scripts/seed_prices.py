#!/usr/bin/env python3
"""Bulk seed instruments and price history from local CSV files.

The backend must be running. Each CSV file must be named <TICKER>.csv.

Usage
-----
    # defaults: --data-dir data/seed_prices  --base-url http://localhost:8000
    python scripts/seed_prices.py

    # override:
    python scripts/seed_prices.py --data-dir /path/to/csvs --base-url http://localhost:8000

Expected CSV format (Yahoo Finance compatible)
----------------------------------------------
    Date,Open,High,Low,Close,Adj Close,Volume
    2023-01-03,382.49,383.53,379.78,380.46,380.46,81246900
    ...

Required columns : Date, Open, High, Low, Close
Optional columns : Adj Close (or Adj_Close), Volume
"""
import argparse
import sys
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("ERROR: httpx is not installed.  Run: pip install httpx")

# ── Default universe ──────────────────────────────────────────────────────────
TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD", "XLK", "XLF", "XLV"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_instrument_map(client: httpx.Client) -> dict[str, str]:
    """Return {TICKER: id} for every instrument already in the database."""
    r = client.get("/api/v1/instruments", params={"limit": 500})
    r.raise_for_status()
    return {item["ticker"]: item["id"] for item in r.json().get("items", [])}


def get_or_create(client: httpx.Client, ticker: str, existing: dict[str, str]) -> str:
    """Return instrument id, creating the instrument if it is not present."""
    if ticker in existing:
        return existing[ticker]

    r = client.post("/api/v1/instruments", json={"ticker": ticker})
    if r.status_code == 409:
        # Race condition: created between the list call and now — re-fetch
        return fetch_instrument_map(client)[ticker]
    r.raise_for_status()
    instrument_id = r.json()["id"]
    existing[ticker] = instrument_id          # update local cache
    return instrument_id


def upload_csv(client: httpx.Client, instrument_id: str, csv_path: Path) -> int:
    """POST the CSV to /prices/ingest and return the number of rows upserted."""
    with csv_path.open("rb") as fh:
        r = client.post(
            "/api/v1/prices/ingest",
            data={"instrument_id": instrument_id},
            files={"file": (csv_path.name, fh, "text/csv")},
            timeout=120.0,
        )
    r.raise_for_status()
    return r.json().get("rows_upserted", 0)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk seed price data into investment-lab")
    parser.add_argument(
        "--data-dir", default="data/seed_prices",
        help="Folder containing <TICKER>.csv files  (default: data/seed_prices)",
    )
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="Backend base URL  (default: http://localhost:8000)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    base_url  = args.base_url.rstrip("/")

    # ── Pre-flight checks ─────────────────────────────────────────────────────
    if not data_dir.exists():
        sys.exit(
            f"ERROR: directory not found: {data_dir}\n"
            f"       Create it and place SPY.csv, QQQ.csv … inside."
        )

    try:
        with httpx.Client(base_url=base_url, timeout=5.0) as probe:
            probe.get("/health").raise_for_status()
    except Exception as exc:
        sys.exit(
            f"ERROR: backend not reachable at {base_url}  ({exc})\n"
            f"       Start it with:  uvicorn app.main:app --reload"
        )

    # ── Seed loop ─────────────────────────────────────────────────────────────
    print(f"Backend : {base_url}")
    print(f"Data dir: {data_dir.resolve()}")
    print()

    ok = failed = skipped = 0

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        existing = fetch_instrument_map(client)

        for ticker in TICKERS:
            csv_path = data_dir / f"{ticker}.csv"

            if not csv_path.exists():
                print(f"  SKIP   {ticker:<6}  {csv_path} not found")
                skipped += 1
                continue

            try:
                instrument_id = get_or_create(client, ticker, existing)
                rows = upload_csv(client, instrument_id, csv_path)
                created = "created" if ticker not in existing else "exists "
                print(f"  OK     {ticker:<6}  {rows:>6} rows upserted  [{created}]  id={instrument_id}")
                ok += 1

            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:200].replace("\n", " ")
                print(f"  FAIL   {ticker:<6}  HTTP {exc.response.status_code}: {body}")
                failed += 1

            except Exception as exc:
                print(f"  FAIL   {ticker:<6}  {exc}")
                failed += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    print(f"Done — {ok} seeded, {skipped} skipped, {failed} failed")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
