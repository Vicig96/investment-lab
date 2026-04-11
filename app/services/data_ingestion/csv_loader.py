"""Parse OHLCV CSV files into validated row dicts.

Pure function — zero database dependencies.
"""
from __future__ import annotations

import io
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {"date", "open", "high", "low", "close"}
OPTIONAL_COLUMNS = {"adj_close", "volume"}
ALL_COLUMNS = REQUIRED_COLUMNS | OPTIONAL_COLUMNS

COLUMN_ALIASES: dict[str, str] = {
    "adj close": "adj_close",
    "adjusted_close": "adj_close",
    "adjusted close": "adj_close",
    "vol": "volume",
}


def parse_ohlcv_csv(source: str | bytes | io.IOBase) -> list[dict[str, Any]]:
    """Parse a CSV source into a list of OHLCV row dicts.

    Args:
        source: File path string, raw bytes, or file-like object.

    Returns:
        List of dicts with keys: date, open, high, low, close, adj_close (optional), volume (optional).

    Raises:
        ValueError: On missing required columns or unparseable data.
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)

    try:
        df = pd.read_csv(source)
    except Exception as exc:
        raise ValueError(f"Failed to read CSV: {exc}") from exc

    # Normalise column names
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df.rename(columns=COLUMN_ALIASES, inplace=True)

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    # Parse dates
    try:
        df["date"] = pd.to_datetime(df["date"]).dt.date
    except Exception as exc:
        raise ValueError(f"Cannot parse 'date' column: {exc}") from exc

    # Coerce numeric columns
    numeric_cols = ["open", "high", "low", "close"] + [
        c for c in ["adj_close", "volume"] if c in df.columns
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    if df[["open", "high", "low", "close"]].isnull().any(axis=None):
        raise ValueError("OHLC columns contain non-numeric or null values after coercion.")

    # Drop rows where date is null
    df = df.dropna(subset=["date"]).copy()
    df = df.sort_values("date").reset_index(drop=True)

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        record: dict[str, Any] = {
            "date": row["date"],
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        if "adj_close" in df.columns and not pd.isna(row.get("adj_close")):
            record["adj_close"] = float(row["adj_close"])
        else:
            record["adj_close"] = None

        if "volume" in df.columns and not pd.isna(row.get("volume")):
            record["volume"] = int(row["volume"])
        else:
            record["volume"] = None

        rows.append(record)

    return rows
