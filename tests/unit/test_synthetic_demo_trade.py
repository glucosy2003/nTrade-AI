from datetime import datetime

import pandas as pd

from scripts import synthetic_demo_trade
from scripts.synthetic_demo_trade import (
    SyntheticTradeOptions,
    _evaluate_multi_timeframe_signal,
    _list_broker_symbols,
    _resolve_account_id,
    _resolve_symbol,
    _retcode_succeeded,
    _trade_allowed,
    _select_recent_signal,
    _synthetic_magic,
    _sync_broker_open_positions,
    _sync_closed_trades_from_mt5,
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


def test_evaluate_multi_timeframe_signal_requires_confluence():
    signals_by_timeframe = {
        "W1": 1,
        "D1": 1,
        "H4": 1,
        "H1": 1,
        "M30": 1,
        "M15": 0,
        "M5": 1,
    }

    passed, score, reasons = _evaluate_multi_timeframe_signal(
        1, signals_by_timeframe, 0.7
    )

    assert passed is True
    assert score >= 0.7
    assert any("timeframes agree" in reason for reason in reasons)


def test_synthetic_model_version_fits_signal_schema():
    assert _synthetic_model_version("20", "SyntheticTrendStrategy") == "syn_20_trend"
    assert (
        _synthetic_model_version("40", "SyntheticBalancedMomentumStrategy")
        == "syn_40_momentum"
    )
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

        def get_trade_by_ticket(self, ticket, account_id=None):
            return None

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


def test_sync_broker_open_positions_skips_existing_ticket(monkeypatch):
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
        def get_trade_by_ticket(self, ticket, account_id=None):
            return object()

        def insert_trade(self, trade_data):
            inserted.append(trade_data)

    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())
    monkeypatch.setattr(synthetic_demo_trade, "db_manager", FakeDbManager())

    _sync_broker_open_positions("synthetic", {"FX Vol 20"})

    assert inserted == []


def test_sync_closed_trades_from_mt5_updates_existing_open_trade(monkeypatch):
    updated = []

    class FakeService:
        def get_trade_history(self, start=None, end=None):
            return [
                {
                    "ticket": 101,
                    "symbol": "FX Vol 20",
                    "type": "BUY",
                    "entry_time": 1710000000,
                    "price": 123.45,
                    "volume": 1.0,
                    "profit": 5.0,
                }
            ]

    class FakeCollector:
        service = FakeService()

    class DummyTrade:
        status = "OPEN"
        entry_price = 120.0
        profit_loss = None
        notes = "trade_id=101; strategy=broker_sync; source=mt5_open_position"
        id = 1

    class FakeDbManager:
        def get_trade_by_ticket(self, ticket, account_id=None):
            return DummyTrade()

        def update_trade(self, trade_id, data):
            updated.append((trade_id, data))

        def insert_trade(self, trade_data):
            raise AssertionError("Should not insert when ticket already exists")

    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())
    monkeypatch.setattr(synthetic_demo_trade, "db_manager", FakeDbManager())

    _sync_closed_trades_from_mt5("synthetic", {"FX Vol 20"})

    assert len(updated) == 1
    assert updated[0][0] == 1
    assert updated[0][1]["status"] == "CLOSED"
    assert updated[0][1]["profit_loss"] == 5.0


def test_resolve_account_id_uses_configured_mt5_account_number(monkeypatch):
    monkeypatch.delenv("NTRADE_SYNTHETIC_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        synthetic_demo_trade.settings, "synthetic_mt5_account_number", "43065997"
    )

    assert _resolve_account_id(None) == "synthetic_43065997"


def test_score_recent_trade_feedback_is_positive_after_winning_trades():
    trades = [{"profit_loss": 15.0}, {"profit_loss": 6.0}]

    profile = synthetic_demo_trade._build_feedback_profile(trades)

    assert profile["threshold_offset"] < 0
    assert profile["confidence_bias"] > 0
    assert any(
        "win rate" in str(profile["summary"]).lower() for reason in [profile["summary"]]
    )


def test_score_recent_trade_feedback_is_negative_after_losing_trades():
    trades = [{"profit_loss": -12.0}, {"profit_loss": -3.0}]

    profile = synthetic_demo_trade._build_feedback_profile(trades)

    assert profile["threshold_offset"] > 0
    assert profile["confidence_bias"] < 0
    assert any(
        "win rate" in str(profile["summary"]).lower() for reason in [profile["summary"]]
    )


def test_build_feedback_profile_make_stronger_trades_more_aggressive():
    profile = synthetic_demo_trade._build_feedback_profile(
        [{"profit_loss": 20.0}, {"profit_loss": 10.0}, {"profit_loss": 5.0}]
    )

    assert profile["threshold_offset"] < 0
    assert profile["risk_multiplier"] > 1.0
    assert profile["confidence_bias"] > 0


def test_build_feedback_profile_make_losing_streaks_more_conservative():
    profile = synthetic_demo_trade._build_feedback_profile(
        [{"profit_loss": -20.0}, {"profit_loss": -10.0}, {"profit_loss": -4.0}]
    )

    assert profile["threshold_offset"] > 0
    assert profile["risk_multiplier"] < 1.0
    assert profile["confidence_bias"] < 0


def test_trade_allowed_uses_mt5_history_for_caps(monkeypatch):
    class FakeCollector:
        class Service:
            def get_trade_history(self, start=None, end=None, symbol=None):
                return [{"ticket": 101, "symbol": "FX Vol 20"}]

        service = Service()

        def get_positions(self):
            return []

    class FakeDbManager:
        def count_trades_since(self, since, symbol=None, account_id=None):
            if symbol == "FX Vol 20":
                return 1
            return 10

    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())
    monkeypatch.setattr(synthetic_demo_trade, "db_manager", FakeDbManager())

    allowed, warnings = _trade_allowed(
        "synthetic_43065997",
        "FX Vol 20",
        datetime.now(),
        max_total=1,
        max_per_symbol=1,
    )

    assert allowed is False
    assert any("Daily trade cap reached" in warning for warning in warnings)
    assert any("Daily symbol cap reached" in warning for warning in warnings)


def test_trade_allowed_dedupes_repeated_mt5_deals(monkeypatch):
    class FakeCollector:
        class Service:
            def get_trade_history(self, start=None, end=None, symbol=None):
                return [
                    {"ticket": 101, "symbol": "FX Vol 20", "type": "BUY"},
                    {"ticket": 101, "symbol": "FX Vol 20", "type": "BUY"},
                ]

        service = Service()

        def get_positions(self):
            return []

    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())

    allowed, warnings = _trade_allowed(
        "synthetic_43065997",
        "FX Vol 20",
        datetime.now(),
        max_total=1,
        max_per_symbol=1,
    )

    assert allowed is False
    assert any("Daily trade cap reached" in warning for warning in warnings)
    assert any("Daily symbol cap reached" in warning for warning in warnings)


def test_count_recent_mt5_activity_ignores_open_positions(monkeypatch):
    class FakeCollector:
        class Service:
            def get_trade_history(self, start=None, end=None, symbol=None):
                return [{"ticket": 101, "symbol": "FX Vol 20", "type": "BUY"}]

        service = Service()

        def get_positions(self):
            return [{"ticket": 202, "symbol": "FX Vol 20", "type": "BUY"}]

    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())

    total_trades, symbol_trades = synthetic_demo_trade._count_recent_mt5_activity(
        "synthetic_43065997", "FX Vol 20", datetime.now()
    )

    assert total_trades == 1
    assert symbol_trades == 1


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
        analysis_delay_seconds = 35.0
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


def test_run_trade_cycle_skips_when_trading_is_disabled(monkeypatch):
    class FakeCollector:
        def connect(self):
            return True

        service = type(
            "Service",
            (),
            {
                "terminal_info": lambda self: {"trade_allowed": False},
            },
        )()

        def get_account_info(self):
            return {"trade_allowed": False, "balance": 10000.0}

    monkeypatch.setattr(
        synthetic_demo_trade, "_refresh_synthetic_mt5_context", lambda: None
    )
    monkeypatch.setattr(synthetic_demo_trade, "mt5_collector", FakeCollector())
    monkeypatch.setattr(synthetic_demo_trade.settings, "synthetic_demo_only", True)
    monkeypatch.setattr(
        synthetic_demo_trade.settings, "synthetic_max_trades_per_day", 1
    )
    monkeypatch.setattr(
        synthetic_demo_trade.settings, "synthetic_max_trades_per_symbol_per_day", 1
    )

    result = synthetic_demo_trade.run_trade_cycle(SyntheticTradeOptions(dry_run=False))

    assert result == 0
