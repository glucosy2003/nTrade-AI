# nTrade AI Trading System

Windows-first AI trading platform for MetaTrader 5, built as a single project folder for synthetic indices research and execution.

**Prepared for:** Gracious  
**Current Version:** 3.1  
**Migration State:** Windows-only workspace  
**Last Updated:** July 2026

---

## Overview

nTrade AI is a personal trading research and execution system specialized for synthetic indices. The project now lives entirely inside one Windows workspace and focuses on live market scanning, multi-timeframe analysis, and disciplined execution for synthetic instruments.

The goal is to move through the stack in a controlled order:

1. Connect directly to MT5 on Windows
2. Scan synthetic indices with deep multi-timeframe analysis
3. Apply adaptive feedback from recent closed trades
4. Backtest and validate strategies before demo execution
5. Run synthetic demo trading with strong guardrails

The system starts with a conservative synthetic specialist workflow and only expands its coverage once the earlier stages are stable.

---

## What Changed After Migration

- Development is now Windows-only
- The project now stays in one local folder and one venv
- MT5 is treated as the direct broker connection layer
- Linux-only setup and dual-OS workflow are retired
- The roadmap now starts at Phase 4 because the earlier migration work is complete
- Console logging is UTF-8 safe on Windows, so status symbols no longer crash the app
- MT5 startup health checks are opt-in with `MT5_AUTO_CONNECT=1`
- Synthetic symbols default to the configured FX Vol profiles via the synthetic settings

---

## Current Goals

- Build a clean MT5 core for account, symbol, candle, and live price access
- Scan and analyze synthetic indices with deep multi-timeframe logic
- Apply adaptive feedback from recent closed trades
- Backtest strategies on synthetic index data before execution
- Move into synthetic demo trading with strict safety controls

## Synthetic trading guardrails

The synthetic auto-runner now behaves as a continuous watcher rather than a one-shot scan:

- It re-evaluates the market on a repeating loop and only trades when a high-quality setup passes strategy and deep-analysis gates.
- Deep analysis is mandatory before any order is sent; the runner no longer offers a bypass flag for that guardrail.
- Daily caps are enforced using both local trade records and recent MT5 trade history, so closed trades count toward the 24-hour limit.
- The active MT5 account is derived from the current synthetic profile from the environment, so the runner uses the intended account instead of a stale identifier.

---

## Roadmap

### Phase 4 — MT5 Core

Focus:

- Direct MT5 connection
- Account information
- Symbols
- Historical candles
- Live prices

Deliverables:

- Stable Windows MT5 connection
- Terminal, account, and symbol inspection tools
- Candle and tick retrieval helpers
- A clear integration boundary for the rest of the system

### Phase 5 — Data Pipeline

Focus:

- Download and validate synthetic index history
- Store data in PostgreSQL
- Support incremental updates

Deliverables:

- Normalized price history tables
- Data validation rules
- Repeatable import/update scripts
- A trusted source of historical synthetic index data

### Phase 6 — Feature Engineering

Focus:

- EMA
- RSI
- ATR
- MACD
- Bollinger Bands
- Volatility
- Market regime features

Deliverables:

- Feature generation pipeline
- Consistent training dataset schema
- Feature versioning for experiments

### Phase 7 — AI Model

Focus:

- Train on synthetic-index data
- Save and load models
- Evaluate performance

Deliverables:

- Baseline model trained on historical synthetic index data
- Reusable model artifacts
- Evaluation reports for precision, recall, and trading value

### Phase 8 — AI Backtesting

Focus:

- Compare rule-based and model-based synthetic strategies
- Measure win rate, drawdown, Sharpe ratio, and profit factor

Deliverables:

- Backtest engine wired to model outputs
- Performance reports across multiple periods
- Clear comparison against the rule-based baseline

### Phase 9 — Demo Trading

Focus:

- Manual AI recommendations
- Semi-automatic execution
- Fully automatic execution with safety controls

Deliverables:

- Live demo signal workflow
- Semi-auto trade placement
- Risk controls, kill switch, and monitoring
- Demo performance review before any real-money step

---

## Operating Principles

- Demo first, always
- Risk management is mandatory, not optional
- One synthetic family at a time until the system proves itself
- Backtest before live demo trading
- Keep the implementation simple before adding complexity
- Treat every model as a candidate, not a guarantee

---

## Repository Layout

```text
ntrade_ai/
├── main.py
├── README.md
├── requirements.txt
├── backend/
├── config/
├── database/
├── datasets/
├── logs/
├── models/
├── scripts/
├── services/
├── strategies/
├── tests/
└── venv/               # Local virtual environment, not committed
```

### Key folders

- `backend/` - application core, MT5 integration, market data, execution, and AI helpers
- `database/` - connection and persistence helpers
- `scripts/` - utility scripts for setup, testing, and backtesting
- `strategies/` - trading strategy implementations and experiments
- `models/` - saved model artifacts
- `datasets/` - local data files and exports
- `tests/` - automated tests

---

## Windows Setup

### Prerequisites

- Windows 10/11
- Python 3.11+
- MetaTrader 5 Desktop installed
- PostgreSQL installed and running
- Git installed
- A dedicated project folder for nTrade AI

### PostgreSQL Setup

The trading system stores candles, signals, trades, and metrics in PostgreSQL.
To do that, it needs three things:

- a PostgreSQL server running on your machine
- a database name, such as `ntrade_ai_dev`
- a login role with a password, such as `ntrade_ai_user`

Why this matters:

- `DATABASE_USER` / `DATABASE_PASSWORD` are used by the app to write and read data
- `DATABASE_ADMIN_USER` / `DATABASE_ADMIN_PASSWORD` are used only to create the database the first time
- table creation and later schema changes require the app role to have sufficient privileges on the target database
- Alembic migrations are the preferred schema path; direct table creation is still available as a fallback
- synced candles are turned into synthetic-market features for strategy evaluation and feedback tuning
- the baseline synthetic strategy workflow uses stored candles and saved metrics to improve decision quality

Example first-time setup:

```powershell
psql -U postgres
CREATE ROLE ntrade_ai_user WITH LOGIN PASSWORD 'change_me';
CREATE DATABASE ntrade_ai_dev OWNER ntrade_ai_user;
GRANT ALL PRIVILEGES ON DATABASE ntrade_ai_dev TO ntrade_ai_user;
```

If the database already exists, you only need the app credentials and the connection values in `.env`.

### Setup

```powershell
python -m venv venv
.\\venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
```

Optional:

```powershell
$env:MT5_AUTO_CONNECT="1"
```

Create a `.env` file with values like:

```powershell
PROJECT_NAME=nTrade AI
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=ntrade_ai_dev
DATABASE_USER=ntrade_ai_user
DATABASE_PASSWORD=change_me
DATABASE_ADMIN_USER=postgres
DATABASE_ADMIN_PASSWORD=change_me
SYNTHETIC_INDEX_20_SYMBOL=FX Vol 20
SYNTHETIC_INDEX_40_SYMBOL=FX Vol 40
SYNTHETIC_INDEX_80_SYMBOL=FX Vol 80
MT5_SERVER=Weltrade-Demo
```

### Common commands

```powershell
python main.py
python main.py --test
python main.py --backtest
python scripts\\synthetic_auto_runner.py --skip-wait --max-cycles 1
python scripts\\synthetic_auto_runner.py
python scripts\\setup_db.py
python scripts\\setup_db.py --migrate
python scripts\\mt5_inspect.py
python scripts\\mt5_connector_test.py
```

Recommended setup flow:

1. Create the PostgreSQL role and database.
2. Put the values in `.env`.
3. Run `python scripts\\setup_db.py --migrate` to apply the schema.
4. Start the synthetic runner with `python scripts\\synthetic_auto_runner.py` to scan and trade the configured synthetic instruments.
5. Use `python main.py --backtest` to validate a strategy before live demo execution.
6. Review the scan summaries and trade logs, then refine the rules and feedback profile for the synthetic specialist workflow.

Live signal workflow:

- The runner reads the latest MT5 candles for the configured synthetic symbols.
- It runs the deep-analysis and feedback pipeline and prints `BUY`, `SELL`, or `HOLD` decisions.
- It calculates stop loss, take profit, and position size from the risk settings.
- The system does not retrain itself automatically; improvement comes from saving results, reviewing them, and refining the synthetic specialist logic.

`python scripts\\setup_db.py --init` still exists as a direct ORM table-creation fallback, but migrations are now the primary path.

---

## Logging

The application uses Python logging for both console and file output.

- Console output is configured to handle UTF-8 on Windows
- File logs are written to `logs/app.log`
- Status symbols and warnings no longer break the console on CP1252 systems

---

## Development Notes

- Historical Linux-only notes are no longer the source of truth
- Documentation should describe the Windows workspace and single-folder layout
- New work should be added to the roadmap in Phase 4 and beyond
- Keep MT5, data pipeline, feature engineering, and model work tightly separated

---

## Current Status

- Platform: Windows-only
- Workflow: Single project folder
- Active roadmap: Phase 4 onward
- Main near-term goal: finish MT5 inspection tooling and data pipeline groundwork
