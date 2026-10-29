"""Basic position sizing helpers for risk-managed trading."""

from __future__ import annotations


class PositionSizer:
    """Calculate a position size from a fixed risk budget."""

    def __init__(self, risk_per_trade_pct: float = 0.01) -> None:
        if risk_per_trade_pct >= 1:
            risk_per_trade_pct = risk_per_trade_pct / 100.0
        if not 0 < risk_per_trade_pct < 1:
            raise ValueError("risk_per_trade_pct must be between 0 and 1")
        self.risk_per_trade_pct = risk_per_trade_pct

    def _micro_account_risk(self, account_balance: float) -> tuple[str, float]:
        """Return a tier name and a minimum-dollar risk floor for tiny accounts."""
        if account_balance < 5.0:
            return "micro", 0.05
        if account_balance < 20.0:
            return "small", 0.10
        return "standard", 0.0

    def calculate_position_size(
        self,
        account_balance: float,
        entry_price: float,
        stop_loss_price: float,
    ) -> float:
        """Return the position size in units implied by a fixed risk budget."""

        if account_balance <= 0:
            raise ValueError("account_balance must be positive")
        if entry_price <= 0 or stop_loss_price <= 0:
            raise ValueError("prices must be positive")

        stop_distance = abs(entry_price - stop_loss_price)
        if stop_distance <= 0:
            raise ValueError("stop_loss_price must differ from entry_price")

        tier, minimum_risk = self._micro_account_risk(account_balance)
        risk_amount = account_balance * self.risk_per_trade_pct
        if tier == "micro":
            risk_amount = max(risk_amount, minimum_risk)
        elif tier == "small":
            risk_amount = max(risk_amount, minimum_risk)

        return risk_amount / stop_distance
