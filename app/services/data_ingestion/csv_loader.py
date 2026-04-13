"""Parse OHLCV CSV files into validated row dicts."""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {"date", "open", "high", "low", "close"}
OPTIONAL_COLUMNS = {"adj_close", "volume"}

COLUMN_ALIASES: dict[str, str] = {
    "adjclose": "adj_close",
    "adj_close": "adj_close",
    "adjusted_close": "adj_close",
    "adjustedclose": "adj_close",
    "vol": "volume",
}


@dataclass
class CSVValidationReport:
    normalized_columns: list[str] = field(default_factory=list)
    total_rows: int = 0
    imported_rows: int = 0
    dropped_rows: int = 0
    first_date: date | None = None
    last_date: date | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    issue_counts: dict[str, int] = field(default_factory=dict)


@dataclass
class CSVValidationResult:
    rows: list[dict[str, Any]]
    report: CSVValidationReport


def _normalize_column_name(name: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return COLUMN_ALIASES.get(normalized, normalized)


def _read_csv(source: str | bytes | io.IOBase) -> pd.DataFrame:
    if isinstance(source, bytes):
        source = io.BytesIO(source)

    try:
        return pd.read_csv(source)
    except Exception as exc:
        raise ValueError(f"Failed to read CSV: {exc}") from exc


def validate_ohlcv_csv(
    source: str | bytes | io.IOBase,
    *,
    min_history_warning: int = 200,
) -> CSVValidationResult:
    """Validate and clean an OHLCV CSV for import."""
    report = CSVValidationReport()
    df = _read_csv(source)
    report.total_rows = len(df)

    if df.empty:
        report.errors.append("CSV contains no data rows.")
        return CSVValidationResult(rows=[], report=report)

    df = df.copy()
    df.columns = [_normalize_column_name(column) for column in df.columns]
    df["__row_order"] = range(len(df))
    report.normalized_columns = [column for column in df.columns if not column.startswith("__")]

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        report.errors.append(f"CSV is missing required columns: {sorted(missing)}")
        return CSVValidationResult(rows=[], report=report)

    try:
        df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    except Exception as exc:
        report.errors.append(f"Cannot parse 'date' column: {exc}")
        return CSVValidationResult(rows=[], report=report)

    invalid_dates = int(df["date"].isna().sum())
    if invalid_dates:
        report.issue_counts["invalid_dates"] = invalid_dates
        report.warnings.append(f"Dropped {invalid_dates} row(s) with invalid or missing dates.")
        df = df.dropna(subset=["date"]).copy()

    if df.empty:
        report.errors.append("No valid rows remain after dropping invalid dates.")
        return CSVValidationResult(rows=[], report=report)

    if not pd.Series(df["date"]).is_monotonic_increasing:
        report.issue_counts["unsorted_dates"] = 1
        report.warnings.append("Dates were not sorted ascending; rows were sorted before import.")

    df = df.sort_values(["date", "__row_order"]).reset_index(drop=True)

    numeric_columns = ["open", "high", "low", "close"] + [
        column for column in ["adj_close", "volume"] if column in df.columns
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    missing_ohlc_mask = df[["open", "high", "low", "close"]].isnull().any(axis=1)
    missing_ohlc = int(missing_ohlc_mask.sum())
    if missing_ohlc:
        report.issue_counts["missing_ohlc"] = missing_ohlc
        report.warnings.append(f"Dropped {missing_ohlc} row(s) with missing OHLC values.")
        df = df.loc[~missing_ohlc_mask].copy()

    non_positive_mask = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)
    non_positive = int(non_positive_mask.sum())
    if non_positive:
        report.issue_counts["non_positive_prices"] = non_positive
        report.warnings.append(f"Dropped {non_positive} row(s) with zero or negative prices.")
        df = df.loc[~non_positive_mask].copy()

    impossible_ohlc_mask = (
        (df["low"] > df["high"])
        | (df["open"] < df["low"])
        | (df["open"] > df["high"])
        | (df["close"] < df["low"])
        | (df["close"] > df["high"])
    )
    impossible_ohlc = int(impossible_ohlc_mask.sum())
    if impossible_ohlc:
        report.issue_counts["impossible_ohlc"] = impossible_ohlc
        report.warnings.append(f"Dropped {impossible_ohlc} impossible OHLC row(s).")
        df = df.loc[~impossible_ohlc_mask].copy()

    weekend_mask = pd.Series([value.weekday() >= 5 for value in df["date"]], index=df.index)
    weekend_rows = int(weekend_mask.sum())
    if weekend_rows:
        report.issue_counts["weekend_rows"] = weekend_rows
        report.warnings.append(f"Dropped {weekend_rows} weekend row(s).")
        df = df.loc[~weekend_mask].copy()

    duplicate_rows = int(df.duplicated(subset=["date"], keep="last").sum())
    if duplicate_rows:
        report.issue_counts["duplicate_dates"] = duplicate_rows
        report.warnings.append(f"Dropped {duplicate_rows} duplicate date row(s); kept the last occurrence per date.")
        df = df.drop_duplicates(subset=["date"], keep="last").copy()

    if "volume" in df.columns:
        suspicious_rows = int(
            ((df["volume"] == 0) & pd.Series([value.weekday() < 5 for value in df["date"]], index=df.index)).sum()
        )
        if suspicious_rows:
            report.issue_counts["suspicious_non_trading_rows"] = suspicious_rows
            report.warnings.append(
                f"Found {suspicious_rows} weekday row(s) with zero volume; kept them but review the source."
            )

    if df.empty:
        report.errors.append("No valid OHLCV rows remain after validation.")
        return CSVValidationResult(rows=[], report=report)

    if len(df) < min_history_warning:
        report.issue_counts["short_history"] = len(df)
        report.warnings.append(
            f"History is short: {len(df)} valid row(s), below the recommended {min_history_warning}."
        )

    report.imported_rows = len(df)
    report.dropped_rows = report.total_rows - report.imported_rows
    report.first_date = df["date"].min()
    report.last_date = df["date"].max()

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        rows.append(
            {
                "date": row["date"],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "adj_close": None if "adj_close" not in df.columns or pd.isna(row.get("adj_close")) else float(row["adj_close"]),
                "volume": None if "volume" not in df.columns or pd.isna(row.get("volume")) else int(row["volume"]),
            }
        )

    return CSVValidationResult(rows=rows, report=report)


def parse_ohlcv_csv(source: str | bytes | io.IOBase) -> list[dict[str, Any]]:
    """Parse a CSV source into validated OHLCV rows or raise on fatal errors."""
    result = validate_ohlcv_csv(source)
    if result.report.errors:
        raise ValueError("; ".join(result.report.errors))
    return result.rows
