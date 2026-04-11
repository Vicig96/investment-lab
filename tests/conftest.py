"""Shared pytest fixtures."""
import os
from pathlib import Path

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_csv_path() -> Path:
    return FIXTURES_DIR / "sample_prices.csv"


@pytest.fixture
def sample_csv_bytes(sample_csv_path) -> bytes:
    return sample_csv_path.read_bytes()


@pytest.fixture
def sample_df(sample_csv_path) -> pd.DataFrame:
    df = pd.read_csv(sample_csv_path, parse_dates=["date"])
    df.set_index("date", inplace=True)
    df.columns = [c.lower() for c in df.columns]
    return df
