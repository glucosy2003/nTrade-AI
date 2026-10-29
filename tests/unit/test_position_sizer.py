from backend.risk.position_sizer import PositionSizer


def test_position_sizer_calculates_position_size_from_risk_budget():
    sizer = PositionSizer(risk_per_trade_pct=0.01)

    position_size = sizer.calculate_position_size(
        account_balance=10000,
        entry_price=100.0,
        stop_loss_price=95.0,
    )

    assert position_size == 20.0


def test_position_sizer_uses_micro_account_minimum_risk_for_small_balance():
    sizer = PositionSizer(risk_per_trade_pct=0.01)

    position_size = sizer.calculate_position_size(
        account_balance=4.0,
        entry_price=100.0,
        stop_loss_price=99.0,
    )

    assert position_size == 0.05
