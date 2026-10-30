from datetime import datetime

import scripts.fx_vol_40_fast_profit as fast_profit_runner
from scripts.fx_vol_40_fast_profit import (
    FIXED_PROFIT_USD,
    FIXED_RISK_USD,
    _balance_supports_fixed_risk,
    _configure_fixed_dollar_setup,
    _has_sufficient_margin,
    _order_was_accepted,
    _recent_trade_times,
    _close_position,
)


def test_margin_gate_uses_required_margin_and_keeps_ten_percent_reserve():
    assert _has_sufficient_margin(free_margin=10.0, required_margin=9.0) is True
    assert _has_sufficient_margin(free_margin=10.0, required_margin=9.01) is False
    assert _has_sufficient_margin(free_margin=10.0, required_margin=0.0) is False
    assert _has_sufficient_margin(free_margin=0.0, required_margin=1.0) is False


def test_order_result_requires_an_accepted_mt5_retcode():
    assert _order_was_accepted({"retcode": 10009}) is True
    assert _order_was_accepted({"retcode": 10008}) is True
    assert (
        _order_was_accepted({"retcode": 10030, "comment": "Unsupported filling mode"})
        is False
    )
    assert _order_was_accepted(None) is False


class FakeMT5:
    TRADE_ACTION_DEAL = 1
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0


class CloseRequestService:
    def __init__(self):
        self.request = None

    def preferred_filling_mode(self, symbol):
        return 0

    def order_send(self, request):
        self.request = request
        return {"retcode": 10009}


def test_close_position_sends_position_ticket_to_mt5(monkeypatch):
    monkeypatch.setattr(fast_profit_runner, "mt5", FakeMT5())
    service = CloseRequestService()
    position = {
        "ticket": 12345,
        "type": "BUY",
        "volume": 0.01,
        "current_price": 100.0,
    }

    closed = _close_position(service, "FX Vol 40", position)

    assert closed is True
    assert service.request["position"] == 12345
    assert service.request["type"] == FakeMT5.ORDER_TYPE_SELL


def test_close_position_refuses_to_send_without_ticket(monkeypatch):
    monkeypatch.setattr(fast_profit_runner, "mt5", FakeMT5())
    service = CloseRequestService()
    position = {
        "type": "BUY",
        "volume": 0.01,
        "current_price": 100.0,
    }

    closed = _close_position(service, "FX Vol 40", position)

    assert closed is False
    assert service.request is None


class LinearProfitService:
    def estimate_order_profit(
        self, symbol, volume, order_type, open_price, close_price
    ):
        direction = 1 if order_type == "BUY" else -1
        return (close_price - open_price) * direction * volume * 10


def make_trade_setup(stop_loss=90.0):
    return {
        "signal_type": "BUY",
        "entry_price": 100.0,
        "stop_loss": stop_loss,
        "take_profit": 120.0,
        "lot_size": 0.01,
        "position_size": 0.01,
    }


def make_trade_context(stops_level=0):
    return {
        "volume_min": 0.01,
        "volume_max": 1.0,
        "volume_step": 0.01,
        "trade_tick_size": 1.0,
        "point": 1.0,
        "trade_stops_level": stops_level,
    }


def test_fixed_dollar_setup_caps_risk_and_targets_two_dollars():
    setup, rejection = _configure_fixed_dollar_setup(
        LinearProfitService(),
        "FX Vol 40",
        make_trade_setup(stop_loss=70.0),
        make_trade_context(),
    )

    assert rejection is None
    assert setup is not None
    assert setup["lot_size"] == 0.01
    assert setup["stop_loss"] == 80.0
    assert setup["take_profit"] == 120.0
    assert setup["actual_risk_amount"] == FIXED_RISK_USD
    assert setup["profit_target_amount"] == FIXED_PROFIT_USD


def test_fixed_dollar_setup_rejects_when_minimum_stop_distance_breaks_cap():
    setup, rejection = _configure_fixed_dollar_setup(
        LinearProfitService(),
        "FX Vol 40",
        make_trade_setup(stop_loss=70.0),
        make_trade_context(stops_level=21),
    )

    assert setup is None
    assert rejection == "$2 stop or target is inside the broker's minimum stop distance"


def test_balance_below_two_dollars_cannot_open_a_trade():
    assert _balance_supports_fixed_risk(2.0) is True
    assert _balance_supports_fixed_risk(1.99) is False


def test_recent_trade_times_counts_only_this_strategy_entries():
    class TradeHistoryService:
        def get_trade_history(self, start, end, symbol):
            now = datetime.now().timestamp()
            return [
                {"comment": "fx_vol_40_fast_profit", "entry_time": now},
                {"comment": "fx_vol_40_fast_profit_close", "entry_time": now},
                {"comment": "another_strategy", "entry_time": now},
            ]

    trade_times = _recent_trade_times(TradeHistoryService(), "FX Vol 40")

    assert len(trade_times) == 1
