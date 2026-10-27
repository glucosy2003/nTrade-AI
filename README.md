# nTrade AI

A Windows-first, MT5-backed trading system focused on synthetic indices (e.g., Deriv-style FX Volatility indices). Built for research, backtesting, and disciplined demo execution with strict risk controls.

## Features

- **Direct MT5 integration** - Connects to MetaTrader 5 for live/demo accounts, candles, ticks, and order execution
- **Synthetic index specialist** - Pre-configured strategies for FX Vol 20, 40, and 80 with multi-timeframe analysis
- **Risk management** - Position sizing, daily trade caps, spread checks, margin validation, and drawdown limits
- **Deep analysis gating** - Validates setups across timeframes before placing trades
- **Adaptive feedback** - Adjusts behavior based on recent closed trades
- **PostgreSQL storage** - Persists candles, signals, trades, and metrics for analysis
- **Backtesting** - Test strategies on historical data before going live on demo
- **Continuous monitoring** - Auto-runner watches markets and trades only when setups meet strict criteria

## Requirements

- Windows 10/11
- Python 3.11+
- [MetaTrader 5](https://www.metatrader5.com/) installed and logged into a demo account
- [PostgreSQL](https://www.postgresql.org/) (for storing market data and trade history)

## Quick Start

### 1) Clone and set up environment

```powershell
git clone https://github.com/yourusername/ntrade-ai.git
cd ntrade-ai
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

### 2) Configure environment

Copy the example config and fill in your credentials:

```powershell
Copy-Item .env.example .env
```

Edit `.env` with your MT5 and database details:

```env
# PostgreSQL
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=ntrade_ai_dev
DATABASE_USER=your_db_user
DATABASE_PASSWORD=your_db_password
DATABASE_ADMIN_USER=postgres
DATABASE_ADMIN_PASSWORD=your_admin_password

# Synthetic MT5 account (demo recommended)
SYNTHETIC_MT5_ACCOUNT_NUMBER=12345678
SYNTHETIC_MT5_PASSWORD=your_password
SYNTHETIC_MT5_SERVER=your_broker_server
```

### 3) Set up database

```powershell
python scripts/setup_db.py --migrate
```

### 4) Run

Test MT5 connection:
```powershell
python scripts/mt5_inspect.py
```

Run synthetic auto-trader (demo):
```powershell
python scripts/synthetic_auto_runner.py
```

Run backtests:
```powershell
python main.py --backtest --symbol "FX Vol 40" --timeframe 5
```

## Project Structure

```
ntrade-ai/
├── backend/           # Core logic (MT5, strategies, risk, indicators, AI)
├── config/            # Configuration helpers
├── database/          # DB models and connection management
├── scripts/           # CLI tools (runners, backtests, setup)
├── strategies/        # Strategy experiments
├── models/            # Saved ML models
├── datasets/          # Local data storage
├── tests/             # Unit tests
├── alembic/           # Database migrations
├── main.py            # Application entry point
└── requirements.txt   # Dependencies
```

## Safety Notes

- **Demo first** - Always test on a demo account before considering live trading
- **Risk management is enforced** - Daily caps, position sizing, and margin checks are built-in
- **No credentials in repo** - `.env` is gitignored; use `.env.example` as template
- **Windows-specific** - This project is designed for Windows with the official MT5 Python package

## License

This project is provided as-is for research and educational purposes. Use at your own risk.
