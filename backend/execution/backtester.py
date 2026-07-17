"""
Backtesting engine for strategy validation.

Simulates strategy execution on historical data to evaluate:
- Win rate and profit factor
- Risk-adjusted returns (Sharpe ratio)
- Maximum drawdown
- Entry/exit logic validity

Used in Phase 1 to validate strategies before live trading.
"""

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime
import numpy as np
import pandas as pd

from backend.core.settings import settings


logger = logging.getLogger(__name__)


class BacktestResult:
    """Result of a backtest run."""

    def __init__(self):
        """Initialize backtest result."""
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[float] = []
        self.timestamps: List[datetime] = []
        
        # Statistics (calculated on demand)
        self._stats_cache: Optional[Dict[str, Any]] = None

    def add_trade(
        self,
        entry_time: datetime,
        entry_price: float,
        exit_time: datetime,
        exit_price: float,
        position_size: float,
        trade_type: str = "BUY"
    ) -> None:
        """
        Record a completed trade.
        
        Args:
            entry_time: Trade entry timestamp
            entry_price: Entry price
            exit_time: Trade exit timestamp
            exit_price: Exit price
            position_size: Position size
            trade_type: 'BUY' or 'SELL'
        """
        profit_loss = (exit_price - entry_price) * position_size
        if trade_type == "SELL":
            profit_loss = (entry_price - exit_price) * position_size
        
        profit_loss_pips = (exit_price - entry_price) if trade_type == "BUY" else (entry_price - exit_price)
        
        self.trades.append({
            "entry_time": entry_time,
            "entry_price": entry_price,
            "exit_time": exit_time,
            "exit_price": exit_price,
            "position_size": position_size,
            "trade_type": trade_type,
            "profit_loss": profit_loss,
            "profit_loss_pips": profit_loss_pips,
            "bars_held": None  # Set by caller if needed
        })
        
        # Invalidate stats cache
        self._stats_cache = None

    def add_equity_point(self, timestamp: datetime, equity: float) -> None:
        """Record an equity curve point."""
        self.timestamps.append(timestamp)
        self.equity_curve.append(equity)

    def get_stats(self) -> Dict[str, Any]:
        """
        Calculate and return backtest statistics.
        
        Returns:
            Dictionary with all key metrics
        """
        if self._stats_cache is not None:
            return self._stats_cache

        stats = {
            "total_trades": len(self.trades),
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0,
            "total_profit_loss": 0,
            "gross_profit": 0,
            "gross_loss": 0,
            "profit_factor": 0,
            "largest_win": 0,
            "largest_loss": 0,
            "average_win": 0,
            "average_loss": 0,
            "sharpe_ratio": None,
            "max_drawdown": 0,
            "consecutive_wins": 0,
            "consecutive_losses": 0,
            "max_consecutive_wins": 0,
            "max_consecutive_losses": 0,
        }

        if len(self.trades) == 0:
            return stats

        # Calculate trade statistics
        for trade in self.trades:
            pnl = trade["profit_loss"]
            stats["total_profit_loss"] += pnl
            
            if pnl > 0:
                stats["winning_trades"] += 1
                stats["gross_profit"] += pnl
                stats["largest_win"] = max(stats["largest_win"], pnl)
                stats["consecutive_wins"] += 1
                stats["consecutive_losses"] = 0
                stats["max_consecutive_wins"] = max(
                    stats["max_consecutive_wins"],
                    stats["consecutive_wins"]
                )
            else:
                stats["losing_trades"] += 1
                stats["gross_loss"] += abs(pnl)
                stats["largest_loss"] = min(stats["largest_loss"], pnl)
                stats["consecutive_losses"] += 1
                stats["consecutive_wins"] = 0
                stats["max_consecutive_losses"] = max(
                    stats["max_consecutive_losses"],
                    stats["consecutive_losses"]
                )

        # Calculate percentages
        stats["win_rate"] = stats["winning_trades"] / stats["total_trades"] * 100
        stats["average_win"] = stats["gross_profit"] / max(stats["winning_trades"], 1)
        stats["average_loss"] = stats["gross_loss"] / max(stats["losing_trades"], 1)
        stats["profit_factor"] = (
            stats["gross_profit"] / stats["gross_loss"]
            if stats["gross_loss"] > 0 else 0
        )

        # Calculate risk-adjusted returns
        if len(self.equity_curve) > 1:
            returns = np.diff(self.equity_curve) / self.equity_curve[:-1]
            stats["sharpe_ratio"] = (
                np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
            )
            
            # Maximum drawdown
            cummax = np.maximum.accumulate(self.equity_curve)
            drawdown = (np.array(self.equity_curve) - cummax) / cummax
            stats["max_drawdown"] = np.min(drawdown) * 100

        self._stats_cache = stats
        return stats

    def to_dataframe(self) -> pd.DataFrame:
        """Convert trades to DataFrame for analysis."""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame(self.trades)

    def print_summary(self) -> None:
        """Print summary of backtest results."""
        stats = self.get_stats()
        
        logger.info("=" * 60)
        logger.info("BACKTEST RESULTS SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Trades: {stats['total_trades']}")
        logger.info(f"Winning Trades: {stats['winning_trades']}")
        logger.info(f"Losing Trades: {stats['losing_trades']}")
        logger.info(f"Win Rate: {stats['win_rate']:.2f}%")
        logger.info("")
        logger.info(f"Total P&L: {stats['total_profit_loss']:.2f}")
        logger.info(f"Gross Profit: {stats['gross_profit']:.2f}")
        logger.info(f"Gross Loss: {stats['gross_loss']:.2f}")
        logger.info(f"Profit Factor: {stats['profit_factor']:.2f}")
        logger.info("")
        logger.info(f"Largest Win: {stats['largest_win']:.2f}")
        logger.info(f"Largest Loss: {stats['largest_loss']:.2f}")
        logger.info(f"Average Win: {stats['average_win']:.2f}")
        logger.info(f"Average Loss: {stats['average_loss']:.2f}")
        logger.info("")
        logger.info(f"Sharpe Ratio: {stats['sharpe_ratio']:.2f}" if stats['sharpe_ratio'] else "N/A")
        logger.info(f"Max Drawdown: {stats['max_drawdown']:.2f}%")
        logger.info(f"Max Consecutive Wins: {stats['max_consecutive_wins']}")
        logger.info(f"Max Consecutive Losses: {stats['max_consecutive_losses']}")
        logger.info("=" * 60)


class Backtester:
    """
    Main backtesting engine.
    
    Executes a strategy on historical data and tracks results.
    """

    def __init__(self, initial_balance: float = 10000.0):
        """
        Initialize backtester.
        
        Args:
            initial_balance: Starting account balance
        """
        self.initial_balance = initial_balance
        self.current_balance = initial_balance
        self.result = BacktestResult()

    def run(
        self,
        data: pd.DataFrame,
        strategy_func,
        position_size: float = 0.01,
        max_risk_per_trade: float = settings.max_risk_per_trade
    ) -> BacktestResult:
        """
        Run backtest with given strategy.
        
        Args:
            data: Historical OHLCV data (DataFrame with columns: time, open, high, low, close, volume)
            strategy_func: Strategy function that returns signals (1=BUY, -1=SELL, 0=HOLD)
            position_size: Position size in lots/units
            max_risk_per_trade: Maximum risk per trade as % of balance
            
        Returns:
            BacktestResult instance
        """
        logger.info(f"Starting backtest with {len(data)} candles...")
        
        # Get signals from strategy
        signals = strategy_func(data)
        
        if len(signals) != len(data):
            raise ValueError("Strategy must return signal for each candle")

        # Track positions
        position = None
        entry_price = None
        entry_time = None

        # Track equity
        self.result.add_equity_point(data.iloc[0]['time'], self.current_balance)

        # Process each candle
        for i in range(len(data)):
            candle = data.iloc[i]
            signal = signals[i]

            # Exit position if signal reverses
            if position is not None and signal != 0:
                if (position == 1 and signal == -1) or (position == -1 and signal == 1):
                    # Close trade at close price
                    exit_price = candle['close']
                    self.result.add_trade(
                        entry_time=entry_time,
                        entry_price=entry_price,
                        exit_time=candle['time'],
                        exit_price=exit_price,
                        position_size=position_size,
                        trade_type="BUY" if position == 1 else "SELL"
                    )
                    
                    # Update balance
                    if position == 1:
                        pnl = (exit_price - entry_price) * position_size
                    else:
                        pnl = (entry_price - exit_price) * position_size
                    
                    self.current_balance += pnl
                    position = None

            # Enter new position
            if position is None and signal != 0:
                entry_price = candle['close']
                entry_time = candle['time']
                position = signal

            # Record equity at end of candle
            self.result.add_equity_point(candle['time'], self.current_balance)

        logger.info("Backtest completed")
        return self.result
