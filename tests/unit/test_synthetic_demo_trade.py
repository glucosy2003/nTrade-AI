import pandas as pd

from scripts import synthetic_demo_trade
from scripts.synthetic_demo_trade import (
    SyntheticTradeOptions,
    _list_broker_symbols,
    _resolve_symbol,
    _retcode_succeeded,
    _select_recent_signal,
    _synthetic_magic,
    _sync_broker_open_positions,
    _synthetic_model_version,
    _trading_disabled_warnings,
)


def test_resolve_symbol_prefers_exact_configured_name():
    symbols = ["Broker FX Index 20", "FXIndex20", "FX Index 20 Pro"]

    resolved = _resolve_symbol("FXIndex20", ["fx", "index", "20"], symbols)

    assert resolved == "FXIndex20"


def test_resolve_symbol_finds_broker_variant_from_terms():
    symbols = ["Volatility 75 Index", "FX Vol 40", "Gold"]

    resolved = _resolve_symbol("FX Vol 40", ["fx", "vol", "40"], symbols)

    assert resolved == "FX Vol 40"


def test_retcode_guard_rejects_failed_orders():
    assert _retcode_succeeded(10009) is True
    assert _retcode_succeeded(10027) is False


def test_trading_disabled_warnings_reports_terminal_and_account():
    warnings = _trading_disabled_warnings(
        {"trade_allowed": False},
        {"trade_allowed": False},
    )

    assert warnings == ["Terminal trading is disabled", "Account trading is disabled"]


def test_list_broker_symbols_filters_normalized_names(monkeypatch):
    class FakeService:
        def symbols(self):
            return ["FX Vol 20", "SFX Vol 40", "XAUUSD"]

    class FakeCollector:
        service = FakeService()

    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())

    assert _list_broker_symbols("sfx") == ["SFX Vol 40"]


def test_select_recent_signal_uses_newest_signal_inside_window():
    signals = pd.Series([0, 1, 0, -1, 0])

    selected, age, index, recent_count, inspected = _select_recent_signal(signals, 3)

    assert selected == -1
    assert age == 1
    assert index == 3
    assert recent_count == 1
    assert inspected == 3


def test_select_recent_signal_holds_when_recent_window_is_empty():
    signals = pd.Series([1, 0, 0, 0])

    selected, age, index, recent_count, inspected = _select_recent_signal(signals, 2)

    assert selected == 0
    assert age is None
    assert index is None
    assert recent_count == 0
    assert inspected == 2


def test_synthetic_model_version_fits_signal_schema():
    assert _synthetic_model_version("20", "SyntheticTrendStrategy") == "syn_20_trend"
    assert _synthetic_model_version("40", "SyntheticBalancedMomentumStrategy") == "syn_40_momentum"
    assert len(_synthetic_model_version("80", "SyntheticBreakoutStrategy")) <= 20


def test_synthetic_magic_is_stable_per_account_and_bucket():
    assert _synthetic_magic("acc1", "20") == _synthetic_magic("acc1", "20")
    assert _synthetic_magic("acc1", "20") != _synthetic_magic("acc2", "20")


def test_sync_broker_open_positions_backfills_missing_trade(monkeypatch):
    inserted = []

    class FakeCollector:
        def get_positions(self):
            return [
                {
                    "ticket": 123,
                    "symbol": "FX Vol 20",
                    "type": "SELL",
                    "volume": 1.0,
                    "open_price": 120000.0,
                    "stop_loss": 120500.0,
                    "take_profit": 119000.0,
                    "open_time": 1710000000,
                }
            ]

    class FakeDbManager:
        def get_open_trades(self, symbol=None, account_id=None):
            return []

        def insert_trade(self, trade_data):
            inserted.append(trade_data)

    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())
    monkeypatch.setattr(synthetic_demo_trade, "db_manager", FakeDbManager())

    _sync_broker_open_positions("synthetic", {"FX Vol 20"})

    assert inserted[0]["signal_id"] is None
    assert inserted[0]["account_id"] == "synthetic"
    assert inserted[0]["symbol"] == "FX Vol 20"
    assert inserted[0]["trade_type"] == "SELL"
    assert inserted[0]["status"] == "OPEN"
    assert "trade_id=123" in inserted[0]["notes"]


def test_trade_options_from_namespace():
    class Args:
        symbol = "20"
        account_id = "acc1"
        timeframe = 5
        lookback_days = 30
        account_balance = 5000.0
        risk_per_trade = 0.5
        reward_to_risk = 1.5
        max_spread_points = 25.0
        signal_lookback_candles = 4
        min_analysis_score = 0.7
        disable_deep_analysis = False
        list_symbols = False
        symbol_filter = "fx"
        dry_run = True

    options = SyntheticTradeOptions.from_namespace(Args())

    assert options.symbol == "20"
    assert options.account_id == "acc1"
    assert options.timeframe == 5
    assert options.lookback_days == 30
    assert options.signal_lookback_candles == 4
    assert options.min_analysis_score == 0.7
    assert options.deep_analysis is True
    assert options.dry_run is True
