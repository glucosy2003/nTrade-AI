# nTrade AI

nTrade AI is a Windows-first Python project for market research, backtesting, and MetaTrader 5 (MT5) demo trading. It includes several distinct runners; choose a command below based on whether you want a local check, a market-data dry run, a one-scan strategy, or continuous order execution.

## Requirements

- Windows 10 or 11
- Python 3.12 recommended
- MetaTrader 5 desktop installed and a demo account available
- PostgreSQL for database-backed synthetic trading and persisted trade history; it is not required by the dedicated FX Vol 40 runner

## Install

In PowerShell:

```powershell
git clone https://github.com/glucosy2003/nTrade-AI.git
cd nTrade-AI
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Open the local `.env` and set your own demo account values. The real `.env` is intentionally not published and is ignored by Git. For the synthetic-account runners, configure:

```dotenv
SYNTHETIC_MT5_ACCOUNT_NUMBER=your_demo_login
SYNTHETIC_MT5_PASSWORD=your_demo_password
SYNTHETIC_MT5_SERVER=your_exact_broker_server_name
SYNTHETIC_MT5_DEMO_MODE=true
SYNTHETIC_DEMO_ONLY=true
```

If you have more than one MT5 installation, set `SYNTHETIC_MT5_TERMINAL_PATH` to the matching `terminal64.exe`, for example `C:\Program Files\MetaTrader 5\terminal64.exe`. The server name must match the broker's MT5 login screen exactly.

Database-backed synthetic runners also need valid PostgreSQL settings in `.env`, a running PostgreSQL server, and migrations:

```powershell
python scripts/setup_db.py --migrate
```

The FX Vol 40 runner uses the `SYNTHETIC_MT5_*` settings and does not need PostgreSQL to evaluate or execute its strategy.

## Trading Behaviors

Commands marked **No orders** do not submit trades. Commands marked **Can place orders** send requests to the configured MT5 account. Start with a demo account and a no-order check.

### FX Vol 40 Fast Profit

Dedicated FX Vol 40 trend-following behavior. It checks M5, M15, and H1 trend alignment, estimates a maximum $2 stop risk and $2 gross profit target using MT5 contract calculations, checks margin, and monitors the position for its exit limits. It can reject a trade when broker minimum-volume or stop-distance rules cannot satisfy those limits. Live P/L can differ due to spread, slippage, gaps, or commissions.

```powershell
# Local strategy sanity check; no MT5 connection and no orders
python scripts/fx_vol_40_fast_profit.py --demo

# One market-data evaluation; connects to MT5 but sends no orders
python scripts/fx_vol_40_fast_profit.py --dry-run --once --symbol "FX Vol 40"

# Continuous demo execution; scans and manages positions every 30 seconds
python scripts/fx_vol_40_fast_profit.py --live --symbol "FX Vol 40" --interval-seconds 30

# Equivalent main.py shortcut; this always starts the live loop
python main.py --mode fxvol40_fast_profit
```

Use `Ctrl+C` to stop a continuous runner. The `main.py` shortcut does not expose the direct script's `--dry-run` option; run the script itself for dry runs.

### Synthetic Auto Runner

Scans all configured synthetic indices by default, applies the strategy and deep-analysis gates, and repeats every five minutes. Add `--symbol 40` to focus on the configured Vol 40 symbol. The first cycle starts immediately.

```powershell
# One scan of Vol 40; preview only, no orders
python scripts/synthetic_auto_runner.py --symbol 40 --dry-run --max-cycles 1

# Continuous Vol 40 demo trading; remove --dry-run to allow orders
python scripts/synthetic_auto_runner.py --symbol 40 --interval-minutes 5

# Continuous scans of all configured synthetic indices without orders
python scripts/synthetic_auto_runner.py --dry-run --interval-minutes 5
```

### Single-Scan Synthetic Trader

Runs one scan, by default across the configured synthetic symbols. It uses PostgreSQL-backed trade history and caps, so initialize the database first.

```powershell
# Preview one Vol 40 scan without sending orders
python scripts/synthetic_demo_trade.py --symbol 40 --dry-run

# Allow this one scan to submit orders to the configured demo MT5 account
python scripts/synthetic_demo_trade.py --symbol 40
```

### Multi-Account Synthetic Runner

Starts a worker for each enabled, complete profile listed by `SYNTHETIC_ACCOUNT_IDS`. Configure each account's `SYNTHETIC_<ID>_*` values and use a separate terminal path for each account.

```powershell
# Preview scans across configured accounts
python scripts/synthetic_multi_account_runner.py --symbol 40 --interval-minutes 5 --dry-run

# Allow workers to submit orders
python scripts/synthetic_multi_account_runner.py --symbol 40 --interval-minutes 5
```

### Backtesting and Diagnostics

```powershell
# Backtest using MT5 historical data
python scripts/backtest_runner.py --symbol "FX Vol 40" --tf 5 --years 1

# Backtest without MT5
python scripts/backtest_runner.py --symbol "FX Vol 40" --tf 5 --years 1 --no-mt5

# Inspect the default MT5 profile (MT5_* settings, not SYNTHETIC_MT5_* settings)
python scripts/mt5_inspect.py --symbol "FX Vol 40" --timeframe 5

# Run unit tests
python -m pytest tests/unit -q
```

Use `--help` on a script for all of its options, for example `python scripts/synthetic_auto_runner.py --help`.

## Project Map

- `backend/strategies/`: trading signals and trend analysis
- `backend/risk/`: risk plans and position sizing
- `backend/market_data/`: candle collection and MT5 connection/execution services
- `scripts/`: runnable trading modes, diagnostics, backtests, and setup tools
- `database/` and `alembic/`: PostgreSQL models and migrations
- `main.py`: top-level application launcher and FX Vol 40 shortcut

## Safety

- Keep `SYNTHETIC_DEMO_ONLY=true` and `SYNTHETIC_MT5_DEMO_MODE=true` during development.
- A dry run is not an execution guarantee; it may still connect to MT5 and fetch account market data.
- Demo execution can lose the demo balance. Stop a continuous process with `Ctrl+C` and verify open positions in MT5.
- Never commit `.env` or paste account passwords into public issues or logs. `.env.example` contains placeholders only.
- This project is for research and education, not financial advice or a guarantee of results.

## License

MIT. See [LICENSE](LICENSE).
