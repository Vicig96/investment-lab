"""Tests for CSV loader."""
import io

import pytest

from app.services.data_ingestion.csv_loader import parse_ohlcv_csv


def test_parse_valid_csv(sample_csv_bytes):
    rows = parse_ohlcv_csv(sample_csv_bytes)
    assert len(rows) == 252
    first = rows[0]
    assert "date" in first
    assert "open" in first
    assert "close" in first


def test_parse_missing_column():
    csv_data = b"date,open,high,low\n2024-01-01,100,105,98\n"
    with pytest.raises(ValueError, match="missing required columns"):
        parse_ohlcv_csv(csv_data)


def test_parse_bad_date():
    csv_data = b"date,open,high,low,close\nnot-a-date,100,105,98,102\n"
    with pytest.raises(ValueError):
        parse_ohlcv_csv(csv_data)


def test_parse_optional_columns_absent():
    csv_data = b"date,open,high,low,close\n2024-01-01,100,105,98,102\n"
    rows = parse_ohlcv_csv(csv_data)
    assert rows[0]["adj_close"] is None
    assert rows[0]["volume"] is None


def test_parse_sorts_by_date():
    csv_data = (
        b"date,open,high,low,close\n"
        b"2024-01-03,100,105,98,102\n"
        b"2024-01-01,99,104,97,101\n"
        b"2024-01-02,98,103,96,100\n"
    )
    rows = parse_ohlcv_csv(csv_data)
    dates = [r["date"].isoformat() for r in rows]
    assert dates == sorted(dates)


def test_parse_file_path(sample_csv_path):
    rows = parse_ohlcv_csv(str(sample_csv_path))
    assert len(rows) > 0
