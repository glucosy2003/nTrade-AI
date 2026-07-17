"""Trading strategies used by the nTrade AI system."""

from .base_strategy import BaseStrategy
from .simple_ma_crossover import SimpleMAcrossover

__all__ = ["BaseStrategy", "SimpleMAcrossover"]
