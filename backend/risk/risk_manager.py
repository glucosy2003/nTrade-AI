"""Simple trade-plan generator for fixed risk and reward targets."""

from __future__ import annotations

from backend.risk.position_sizer import PositionSizer


class RiskManager:
    """Create a consistent trade plan from risk budget inputs."""

    def __init__(self, risk_per_trade_pct: float = 0.01, reward_to_risk_ratio: float = 2.0) -> None:
        if risk_per_trade_pct >= 1:
            risk_per_trade_pct = risk_per_trade_pct / 100.0
        if risk_per_trade_pct <= 0:
            raise ValueError("risk_per_trade_pct must be positive")
        if reward_to_risk_ratio <= 0:
            raise ValueError("reward_to_risk_ratio must be positive")

        self.risk_per_trade_pct = risk_per_trade_pct
        self.reward_to_risk_ratio = reward_to_risk_ratio

    def build_trade_plan(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
        take_profit_price: float | None = None,
    ) -> dict:
        """Return a trade plan dictionary containing sizing and targets."""
        sizer = PositionSizer(risk_per_trade_pct=self.risk_per_trade_pct)
        position_size = sizer.calculate_position_size(
            account_balance=account_balance,
            entry_price=entry_price,
            stop_loss_price=stop_loss_price,
        )

        risk_amount = account_balance * self.risk_per_trade_pct
        risk_distance = abs(entry_price - stop_loss_price)
        if take_profit_price is None:
            take_profit_price = entry_price + (risk_distance * self.reward_to_risk_ratio)

        reward_distance = abs(take_profit_price - entry_price)
        risk_reward_ratio = reward_distance / risk_distance if risk_distance > 0 else 0.0

        return {
            "account_balance": account_balance,
            "entry_price": entry_price,
            "stop_loss_price": stop_loss_price,
            "take_profit_price": take_profit_price,
            "risk_amount": risk_amount,
            "position_size": position_size,
            "risk_distance": risk_distance,
            "reward_distance": reward_distance,
            "risk_reward_ratio": risk_reward_ratio,
        }
