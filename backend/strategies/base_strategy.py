"""Base abstractions for trading strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class BaseStrategy(ABC):
    """Minimal interface for strategy implementations."""

    def __call__(self, data: pd.DataFrame) -> pd.Series:
        """Allow strategy instances to be used directly as callables."""
        return self.generate_signals(data)

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Return a signal series aligned with the input data."""
        raise NotImplementedError
