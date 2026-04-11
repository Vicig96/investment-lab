# Investment Lab

Private investment analysis application for personal use.

**What it does:** Analyse market data, compute technical indicators, generate trading signals, evaluate risk, run backtests, and simulate portfolios — all locally, with no real order execution.

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web framework | FastAPI |
| Database | **SQLite** (local dev, zero config) / PostgreSQL 16 (Docker/prod) |
| ORM | SQLAlchemy 2 (async) |
| Migrations | Alembic (PostgreSQL) / auto create_all (SQLite) |
| Containers | Docker Compose (optional) |
| Tests | pytest + pytest-asyncio |
| Logging | structlog (JSON in prod, colored in dev) |

---

## ⚡ Quick Start — Windows PowerShell (local, no Docker)

**Prerequisite:** Python 3.11 installed and on PATH.  
Check with: `python --version`

```powershell
# 1. Enter the project folder
cd C:\Users\vici3\investment-lab

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate it
.\.venv\Scripts\Activate.ps1
# If you get a script execution error, run this first (once):
#   Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# 4. Install all dependencies
pip install -e ".[dev]"

# 5. Copy the example environment file
Copy-Item .env.example .env
# No edits needed — SQLite is the default, no DB server required.

# 6. Start the server
uvicorn app.main:app --reload
```

**That's it.** The server will:
- Create `investlab.db` (SQLite file) automatically on first run
- Print startup logs in the terminal
- Be available at **http://127.0.0.1:8000/docs**

> **PowerShell tip:** to stop the server press `Ctrl+C`.

### Re-starting later

```powershell
cd C:\Users\vici3\investment-lab
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

### Running tests (no database required)

```powershell
# Unit tests only — pure functions, no DB
pytest tests/unit/ -v

# All tests
pytest -v

# With coverage report
pytest --cov=app --cov-report=term-missing
```

---

## Quick Start (Docker + PostgreSQL)

**Prerequisites:** Docker Desktop running.

```bash
# 1. Clone and enter the project
git clone <repo-url> investment-lab
cd investment-lab

# 2. Copy environment file and switch to PostgreSQL URLs
cp .env.example .env
# In .env, comment the SQLite lines and uncomment the PostgreSQL lines

# 3. Start the stack
docker compose up --build

# 4. In another terminal — run migrations
docker compose exec app alembic upgrade head

# 5. Open the API docs
# http://localhost:8000/docs
```

---

## Quick Start (local, without Docker — macOS/Linux with SQLite)

**Prerequisites:** Python 3.11.

```bash
# 1. Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Configure environment (SQLite default — no changes needed)
cp .env.example .env

# 4. Start server (tables created automatically on first run)
uvicorn app.main:app --reload

# 5. Open the API docs
# http://localhost:8000/docs
```

---

## Loading Historical Data

The API accepts CSV files with the following columns (case-insensitive):

| Column | Required | Description |
|---|---|---|
| `date` | Yes | ISO 8601 date (YYYY-MM-DD) |
| `open` | Yes | Opening price |
| `high` | Yes | High price |
| `low` | Yes | Low price |
| `close` | Yes | Closing price |
| `adj_close` | No | Adjusted close |
| `volume` | No | Volume |

**Step 1:** Create an instrument

```bash
curl -X POST http://localhost:8000/api/v1/instruments \
  -H "Content-Type: application/json" \
  -d '{"ticker": "AAPL", "name": "Apple Inc.", "asset_class": "equity"}'
```

**Step 2:** Upload a CSV

```bash
curl -X POST http://localhost:8000/api/v1/prices/ingest \
  -F "instrument_id=<uuid-from-step-1>" \
  -F "file=@/path/to/aapl.csv"
```

---

## API Endpoints

Base URL: `http://localhost:8000`

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/readiness` | DB connectivity check |
| GET | `/api/v1/instruments` | List instruments |
| POST | `/api/v1/instruments` | Create instrument |
| GET | `/api/v1/instruments/{id}` | Get instrument |
| DELETE | `/api/v1/instruments/{id}` | Delete instrument |
| POST | `/api/v1/prices/ingest` | Upload CSV (multipart) |
| GET | `/api/v1/instruments/{id}/prices` | List candles |
| GET | `/api/v1/instruments/{id}/prices/summary` | Price summary |
| GET | `/api/v1/indicators` | List available indicators |
| GET | `/api/v1/instruments/{id}/indicators/{name}` | Compute indicator |
| GET | `/api/v1/strategies` | List available strategies |
| POST | `/api/v1/signals/run` | Run a strategy |
| GET | `/api/v1/instruments/{id}/signals` | Get persisted signals |
| POST | `/api/v1/backtest/run` | Run a backtest |
| GET | `/api/v1/backtest` | List backtest runs |
| GET | `/api/v1/backtest/{run_id}` | Get run status |
| GET | `/api/v1/backtest/{run_id}/results` | Get results + equity curve |
| POST | `/api/v1/portfolio/simulate` | Portfolio simulation |
| GET | `/api/v1/portfolio/snapshot` | Latest portfolio snapshot |
| POST | `/api/v1/portfolio/rebalance` | Compute rebalance orders |

Full interactive docs: `http://localhost:8000/docs`

---

## Available Indicators

| Name | Description | Key params |
|---|---|---|
| `sma` | Simple Moving Average | `period` (default 20) |
| `ema` | Exponential Moving Average | `period` (default 20) |
| `rsi` | Relative Strength Index | `period` (default 14) |
| `macd` | MACD line | `fast`, `slow`, `signal` |
| `atr` | Average True Range | `period` (default 14) |
| `hvol` | Historical Volatility (annualised) | `period`, `trading_days` |
| `daily_returns` | Simple daily % returns | — |
| `log_returns` | Log daily returns | — |
| `cumulative_returns` | Cumulative returns | — |

---

## Available Strategies

| Name | Description | Key params |
|---|---|---|
| `ma_crossover` | Long when fast MA > slow MA | `fast`, `slow`, `ma_type` |
| `relative_momentum` | Long/short on n-period return | `lookback`, `threshold` |
| `trend_filter` | Long when price > long SMA | `period` |

---

## Running Tests

```bash
# Unit tests only (no database required)
pytest tests/unit/ -v

# All tests
pytest -v

# With coverage
pytest --cov=app --cov-report=html
```

---

## Project Structure

```
investment-lab/
├── app/
│   ├── main.py                     # FastAPI app factory
│   ├── core/                       # Config, logging, dependencies
│   ├── db/                         # Session, Base
│   ├── models/                     # SQLAlchemy ORM models
│   ├── schemas/                    # Pydantic schemas
│   ├── services/
│   │   ├── data_ingestion/         # CSV parsing & DB upsert
│   │   ├── indicators/             # SMA, EMA, RSI, MACD, ATR, vol, returns
│   │   ├── signals/                # MA crossover, momentum, trend filter
│   │   ├── risk/                   # Position sizing, stop-loss, exposure
│   │   ├── backtest/               # Engine, broker, metrics
│   │   └── portfolio/              # Simulator, rebalancer
│   └── api/v1/                     # FastAPI routers
├── alembic/                        # Migrations
├── tests/
│   ├── unit/                       # Pure function tests (no DB)
│   └── integration/                # API tests with mocked DB
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── .env.example
```

---

## Notes

- **No real order execution.** The `SimulatedBroker` only manipulates in-memory state.
- **Single user, private use.** No auth layer, no multi-tenancy.
- **LLM-ready.** Indicator and strategy registries expose clean `{name: class}` dicts so a future LLM tool-calling layer can enumerate and invoke them by name.
