from backend.risk.risk_manager import RiskManager


def test_risk_manager_builds_trade_plan_with_target_levels():
    manager = RiskManager(risk_per_trade_pct=0.02, reward_to_risk_ratio=2.0)

    plan = manager.build_trade_plan(
        account_balance=10000,
        entry_price=100.0,
        stop_loss_price=98.0,
    )

    assert plan["position_size"] == 100.0
    assert plan["stop_loss_price"] == 98.0
    assert plan["take_profit_price"] == 104.0


def test_risk_manager_treats_one_as_one_percent():
    manager = RiskManager(risk_per_trade_pct=1.0, reward_to_risk_ratio=2.0)

    plan = manager.build_trade_plan(
        account_balance=10000,
        entry_price=100.0,
        stop_loss_price=99.0,
    )

    assert plan["risk_amount"] == 100.0
