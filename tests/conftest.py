"""Shared pytest fixtures."""
import os
import tempfile
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
WORKSPACE_TMP_DIR = Path(__file__).resolve().parents[1] / ".tmp_pytest"
WORKSPACE_TMP_DIR.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(WORKSPACE_TMP_DIR.resolve())
os.environ["TMP"] = tempfile.tempdir
os.environ["TEMP"] = tempfile.tempdir


@pytest.fixture
def tmp_path() -> Path:
    path = WORKSPACE_TMP_DIR / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


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
