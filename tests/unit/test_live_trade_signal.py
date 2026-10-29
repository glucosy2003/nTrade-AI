from scripts.live_trade_signal import _normalize_volume, build_trade_setup


def test_normalize_volume_clamps_to_step_and_limits():
    assert _normalize_volume(0.007, 0.01, 2.0, 0.01) == 0.01
    assert _normalize_volume(1.234, 0.01, 2.0, 0.1) == 1.2
    assert _normalize_volume(5.0, 0.01, 2.0, 0.1) == 1.9


def test_build_trade_setup_uses_broker_context_for_lots():
    trade_setup = build_trade_setup(
        symbol="XAUUSD_i",
        signal=1,
        entry_price=4016.41,
        account_balance=10000.0,
        risk_per_trade_pct=2.0,
        reward_to_risk_ratio=2.0,
        trade_context={
            "ask": 4016.61,
            "bid": 4016.31,
            "volume_min": 0.01,
            "volume_max": 50.0,
            "volume_step": 0.01,
            "trade_contract_size": 100.0,
            "trade_tick_size": 0.01,
            "trade_tick_value": 1.0,
            "spread": 30,
            "filling_mode": 1,
            "trade_mode": 4,
        },
        max_spread_points=50,
    )

    assert trade_setup["signal_type"] == "BUY"
    assert trade_setup["order_type"] == "MARKET"
    assert trade_setup["position_size"] > 0
    assert trade_setup["position_size"] <= 50.0
    assert trade_setup["volume_step"] == 0.01
    assert trade_setup["spread_points"] == 30
    assert trade_setup["warnings"] == []
