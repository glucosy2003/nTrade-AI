# nTrade AI Trading System

Windows-first AI trading platform for MetaTrader 5, built as a single project folder with one operating system, one runtime path, and one deployment target.

**Prepared for:** Gracious  
**Current Version:** 3.0  
**Migration State:** Windows-only workspace  
**Last Updated:** July 2026

---

## Overview

nTrade AI is a personal trading research and execution system focused on gold trading first, then broader market expansion later. The project now lives entirely inside one Windows workspace and no longer depends on a split Linux/Windows development flow.

The goal is to move through the stack in a controlled order:

1. Connect directly to MT5 on Windows
2. Build a reliable data pipeline for gold history
3. Engineer the features needed for model training
4. Train and evaluate an AI model on real market data
5. Backtest the model properly
6. Run demo trading with strong safety controls

The system starts in manual AI recommendation mode and only advances toward semi-automatic and automatic execution once the earlier stages are stable.

---

## What Changed After Migration

- Development is now Windows-only
- The project now stays in one local folder and one venv
- MT5 is treated as the direct broker connection layer
- Linux-only setup and dual-OS workflow are retired
- The roadmap now starts at Phase 4 because the earlier migration work is complete
- Console logging is UTF-8 safe on Windows, so status symbols no longer crash the app
- MT5 startup health checks are opt-in with `MT5_AUTO_CONNECT=1`
- Gold history defaults to `XAUUSD_i` via `GOLD_HISTORY_SYMBOL`

---

## Current Goals

- Build a clean MT5 core for account, symbol, candle, and live price access
- Pull and validate XAUUSD_i history into PostgreSQL
- Add feature engineering for indicators and regime detection
- Train on real gold data instead of synthetic placeholders
- Replace rule-based logic with model-driven predictions
- Backtest with proper trading metrics
- Move into demo trading with strict safety controls

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
- Download and validate `XAUUSD_i` history
- Store data in PostgreSQL
- Support incremental updates

Deliverables:
- Normalized price history tables
- Data validation rules
- Repeatable import/update scripts
- A trusted source of historical gold data

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
- Train on real gold data
- Save and load models
- Evaluate performance

Deliverables:
- Baseline model trained on historical XAUUSD data
- Reusable model artifacts
- Evaluation reports for precision, recall, and trading value

### Phase 8 — AI Backtesting

Focus:
- Replace rule-based strategy with AI predictions
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
- One instrument at a time until the system proves itself
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
- synced candles are turned into model features with the gold feature pipeline before training
- the baseline Random Forest model is trained from stored candles and saved with metrics

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
GOLD_HISTORY_SYMBOL=XAUUSD_i
MT5_SERVER=Weltrade-Demo
```

### Common commands

```powershell
python main.py
python main.py --test
python main.py --backtest
python main.py --backtest --strategy gold_model --model-path models\\gold_xgboost_XAUUSD_i_60.pkl
python main.py --sync-history --years 5
python main.py --build-features --symbol XAUUSD_i
python main.py --train-model --symbol XAUUSD_i
python scripts\\setup_db.py
python scripts\\setup_db.py --migrate
python scripts\\mt5_inspect.py
python scripts\\mt5_connector_test.py
python scripts\\sync_gold_history.py
python scripts\\build_feature_dataset.py
python scripts\\train_gold_model.py
```

Recommended setup flow:

1. Create the PostgreSQL role and database.
2. Put the values in `.env`.
3. Run `python scripts\\setup_db.py --migrate` to apply the schema.
4. Use `python scripts\\sync_gold_history.py` to begin storing candles.
5. Use `python scripts\\build_feature_dataset.py` or `python main.py --build-features` to create training rows.
6. Use `python scripts\\train_gold_model.py` or `python main.py --train-model` to train and save the first gold model.
7. Use `python main.py --backtest --strategy gold_model --model-path ...` to measure model-driven trading performance.

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
