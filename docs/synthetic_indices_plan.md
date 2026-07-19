# Synthetic Indices Live Trading Plan

## Goal

Build a safe demo-only live trading pipeline for synthetic indices, focused on:

- FX Index with 20% volatility
- FX Index with 40% volatility
- FX Index with 80% volatility

The system should:

- connect to the demo MT5 account
- query the broker symbol list instead of hard-coding tradable names
- analyze live market data continuously
- generate trade setups with entry, stop loss, take profit, and lot size
- execute at most 6 trades per 24 hours total
- execute at most 2 trades per instrument per 24 hours
- store trade history for later review and retraining
- keep risk management strict and consistent

## Design Principles

- Keep the live execution path simple.
- Use one shared execution engine for all three instruments.
- Specialize strategy logic per volatility bucket.
- Log everything needed for later research.
- Prefer deterministic rules first, then add learned models later.
- Keep account profiles separate so commodity trading and synthetic trading cannot accidentally share credentials.

## Account Profiles

The default MT5 account profile remains dedicated to the existing commodity/gold flow:

- `MT5_ACCOUNT_NUMBER`
- `MT5_PASSWORD`
- `MT5_SERVER`
- `MT5_DEMO_MODE`

The synthetic indices flow uses a separate SyntX profile:

- `SYNTHETIC_MT5_ACCOUNT_NUMBER`
- `SYNTHETIC_MT5_PASSWORD`
- `SYNTHETIC_MT5_SERVER`
- `SYNTHETIC_MT5_DEMO_MODE`

The synthetic executor must refuse to run if the SyntX profile is incomplete. This prevents the system from accidentally using the commodity/gold MT5 account for synthetic index execution.

## Instruments

The configured symbol names are treated as hints. Before trading, the system should query MT5 for the broker's available symbols and resolve the best matching 20%, 40%, and 80% instruments from that list.

### FX Index 20%

Suggested behavior:

- trend-following bias
- fewer trades
- tighter confirmation filters
- smaller stop distance

Why:

- lower volatility usually benefits cleaner trend entries and stricter confirmation.

### FX Index 40%

Suggested behavior:

- balanced momentum and pullback logic
- moderate trade frequency
- standard stop distance
- medium confirmation threshold

Why:

- this bucket is flexible enough for a mixed trend/pullback approach.

### FX Index 80%

Suggested behavior:

- breakout-focused logic
- wider stop loss
- lower position size
- stricter spread and margin checks

Why:

- high-volatility instruments need stronger protection and fewer impulsive entries.

## Strategy Framework

Use one shared strategy interface with three specialized strategy profiles:

1. `SyntheticTrendStrategy`
   - for 20% volatility
   - prefers trend alignment, moving averages, and regime filters

2. `SyntheticBalancedMomentumStrategy`
   - for 40% volatility
   - combines trend, momentum, and pullback confirmation

3. `SyntheticBreakoutStrategy`
   - for 80% volatility
   - focuses on breakout confirmation, volatility expansion, and fast exits

Each strategy should output:

- `BUY`, `SELL`, or `HOLD`
- confidence score
- suggested entry price
- stop loss
- take profit
- reason string

## Risk Rules

Shared rules for all synthetic indices:

- demo account only
- fixed maximum of 6 trades per 24 hours
- maximum of 2 trades per instrument per 24 hours
- one open position per instrument at a time
- reject trades if spread is too high
- reject trades if free margin is too low
- reject trades if market is closed or symbol is not tradable
- use broker-specific lot sizing
- round lot size to broker volume step
- cap lot size at broker min and max

Suggested per-volatility risk profile:

- 20% vol: smallest lot size, tighter entries
- 40% vol: moderate lot size
- 80% vol: smallest lot size among the three if stops are wide

## Trade Lifecycle

1. Read live tick and recent candles.
2. Build indicators and strategy features.
3. Generate a trade setup.
4. Validate spread, margin, trade mode, and lot size.
5. Check daily trade caps.
6. Submit order to the demo account.
7. Store the signal and executed trade in the database.
8. Monitor open positions until close.
9. Record the outcome and performance metrics.
10. Feed the history into retraining.

## 24/7 Operation

The one-shot command checks the market once:

```powershell
python scripts\synthetic_demo_trade.py --dry-run
```

The continuous runner keeps checking the market on an interval:

```powershell
python scripts\synthetic_auto_runner.py --interval-minutes 5 --dry-run
```

For real demo execution:

```powershell
python scripts\synthetic_auto_runner.py --interval-minutes 5
```

Local 24/7 operation requires:

- the PC must stay on
- MT5 must stay open and logged into the SyntX demo account
- Algo Trading must be enabled for real execution
- internet connection must stay active
- the runner terminal must remain open

A Windows VPS is recommended later if the system should trade while the local PC is off.

## Data To Store

Store these items for each signal and trade:

- timestamp
- symbol
- volatility bucket
- signal type
- entry price
- stop loss
- take profit
- lot size
- risk amount
- reward amount
- spread
- margin required
- execution price
- execution status
- broker ticket
- exit reason
- profit or loss
- confidence score
- strategy name
- model version

## Retraining Loop

Retraining should happen from saved live history, not automatically after every trade.

Recommended retraining trigger:

- after enough completed trades per instrument
- or after a minimum date window
- or after a defined number of new candles and trade outcomes

Retraining goals:

- improve signal accuracy
- improve entry timing
- reduce drawdown
- keep instrument-specific models separate if needed

## Implementation Phases

### Phase 1: Shared Infrastructure

- add synthetic-symbol configuration
- add broker-aware symbol inspection for synthetic indices
- add broker symbol-list discovery so exact names can vary by broker
- reuse the existing MT5 service and database logging paths

### Phase 2: Strategy Layer

- implement the three synthetic strategies
- make them share one base interface
- keep logic simple and readable

### Phase 3: Demo Execution

- add auto-execution for demo account only
- add order submission checks
- add daily trade cap enforcement

### Phase 4: History and Analytics

- store signals, trades, and outcomes
- compute per-instrument performance statistics
- expose trade-history review commands

### Phase 5: Learning Loop

- train instrument-specific models from live history
- compare strategy performance across the three volatility buckets
- tune risk rules based on measured results

## Non-Goals For Now

- no real-money execution
- no complex multi-agent orchestration
- no over-engineered ML stack
- no automatic strategy switching without review

## Recommended First Build

Start with:

- one shared live demo executor
- one trade logger
- three simple strategy classes
- hard daily trade caps
- broker-aware lot sizing
- margin and spread rejection rules

This keeps the system safe and easy to test while still giving us useful research data.

## Current Implementation

Implemented files:

- `backend/strategies/synthetic_indices.py`
  - adds `SyntheticTrendStrategy` for 20% volatility
  - adds `SyntheticBalancedMomentumStrategy` for 40% volatility
  - adds `SyntheticBreakoutStrategy` for 80% volatility

- `scripts/synthetic_demo_trade.py`
  - runs the demo-only synthetic auto-trader
  - connects through the separate `synthetic` MT5 account profile
  - supports `--dry-run` before live demo execution
  - queries the MT5 broker symbol list before selecting instruments
  - enforces 6 trades per 24 hours across all synthetic instruments
  - enforces 2 trades per 24 hours per instrument
  - blocks a new trade when MT5 or the local database already shows an open position
  - builds MT5 orders with entry, stop loss, take profit, lot size, deviation, filling mode, and time-in-force

- `scripts/synthetic_auto_runner.py`
  - runs the synthetic trade scan repeatedly on a fixed interval
  - supports `--dry-run` for safe monitoring
  - supports `--max-cycles` for short tests
  - exits cleanly with Ctrl+C after the current cycle

- `backend/core/settings.py` and `.env.example`
  - add separate synthetic MT5 credentials, synthetic symbol hints, search terms, and trade-cap settings

- `backend/market_data/mt5_service.py`
  - adds broker filling-mode selection
  - adds order check and order send wrappers
  - supports named MT5 account profiles without falling back from synthetic to default credentials

- `database/database_manager.py`
  - adds recent trade history queries for cap enforcement and later performance review

- `tests/unit/test_synthetic_indices.py`
  - covers the three synthetic strategy classes and registry lookup

First test command:

```powershell
python scripts\synthetic_demo_trade.py --dry-run
```

To inspect the SyntX broker symbol names:

```powershell
python scripts\synthetic_demo_trade.py --list-symbols
```

Dry-run mode may continue when terminal or account trading is disabled because it does not submit orders. Real execution must stop when MT5 trading is disabled.

Only run without `--dry-run` after the demo MT5 credentials and exact broker symbol names are confirmed.
