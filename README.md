# Investment Lab

Private investment analysis application for personal use.

**What it does:** Analyse market data, compute technical indicators, generate trading signals, evaluate risk, run backtests, and simulate portfolios — all locally, with no real order execution.

---

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.11 |
| Web framework | FastAPI |
| Database | PostgreSQL 16 |
| ORM | SQLAlchemy 2 (async) |
| Migrations | Alembic |
| Containers | Docker Compose |
| Tests | pytest + pytest-asyncio |
| Logging | structlog (JSON in prod, colored in dev) |

---

## Quick Start (Docker)

**Prerequisites:** Docker Desktop running.

```bash
# 1. Clone and enter the project
git clone <repo-url> investment-lab
cd investment-lab

# 2. Copy environment file
cp .env.example .env
# Edit .env if you want different credentials (optional for local dev)

# 3. Start the stack
docker compose up --build

# 4. In another terminal — run migrations
docker compose exec app alembic upgrade head

# 5. Open the API docs
# http://localhost:8000/docs
```

---

## Quick Start (local, without Docker)

**Prerequisites:** Python 3.11, PostgreSQL running locally.

```bash
# 1. Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Configure environment
cp .env.example .env
# Edit DATABASE_URL and DATABASE_URL_SYNC in .env to point to your local PG

# 4. Run migrations
alembic upgrade head

# 5. Start the server
uvicorn app.main:app --reload

# 6. Open the API docs
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
