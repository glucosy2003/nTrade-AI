"""Trading strategies used by the nTrade AI system."""

from .base_strategy import BaseStrategy
from .synthetic_indices import (
    SyntheticBalancedMomentumStrategy,
    SyntheticBreakoutStrategy,
    SyntheticTrendStrategy,
    get_synthetic_strategy,
)
from .simple_ma_crossover import SimpleMAcrossover

__all__ = [
    "BaseStrategy",
    "SimpleMAcrossover",
    "SyntheticTrendStrategy",
    "SyntheticBalancedMomentumStrategy",
    "SyntheticBreakoutStrategy",
    "get_synthetic_strategy",
]
