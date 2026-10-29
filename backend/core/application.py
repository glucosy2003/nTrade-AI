"""
Main application orchestrator for the nTrade AI trading system.

This module provides the central application controller that initializes all
system components and orchestrates the trading pipeline.
"""

from typing import Optional
import logging

from backend.core.settings import settings
from backend.core.logger import setup_logger
from backend.market_data.data_collector import mt5_collector


logger = logging.getLogger(__name__)


class TradingApplication:
    """
    Main application controller for the AI trading system.
    
    Responsibilities:
    - Initialize all system components
    - Manage application lifecycle
    - Provide centralized access to key services
    """

    def __init__(self):
        """Initialize the trading application."""
        self.settings = settings
        self.logger = setup_logger(__name__)
        self.market_data = mt5_collector
        self._initialized = False

    def initialize(self) -> None:
        """
        Initialize all application components.
        
        Performs setup in order:
        1. Validate configuration
        2. Connect to database
        3. Initialize data collectors
        4. Load models
        5. Setup trading engine
        """
        try:
            self.logger.info("=" * 60)
            self.logger.info("Initializing nTrade AI Trading System")
            self.logger.info("=" * 60)
            
            # Log configuration (non-sensitive)
            self._log_configuration()
            self._initialize_market_data()
            
            # TODO: Initialize database connection
            # TODO: Load ML models
            # TODO: Initialize data collectors
            # TODO: Setup trading engine
            
            self._initialized = True
            self.logger.info("✓ Application initialization complete")
            
        except Exception as e:
            self.logger.error(f"✗ Application initialization failed: {str(e)}", exc_info=True)
            raise

    def start(self) -> None:
        """
        Start the trading application and main loop.
        
        Raises:
            RuntimeError: If application not initialized
        """
        if not self._initialized:
            self.initialize()
        
        try:
            self.logger.info("Starting trading system...")
            # TODO: Start main trading loop
            self.logger.info("Trading system is now running")
            
        except KeyboardInterrupt:
            self.logger.info("Trading system interrupted by user")
            self.shutdown()
        except Exception as e:
            self.logger.error(f"Trading system error: {str(e)}", exc_info=True)
            self.shutdown()
            raise

    def shutdown(self) -> None:
        """
        Gracefully shutdown the application.
        
        Cleanup:
        - Close database connections
        - Stop active trades
        - Save state
        """
        try:
            self.logger.info("Shutting down trading system...")
            # TODO: Stop active trades
            # TODO: Close database connections
            # TODO: Save state
            self.logger.info("✓ Trading system shutdown complete")
        except Exception as e:
            self.logger.error(f"Error during shutdown: {str(e)}", exc_info=True)

    def _log_configuration(self) -> None:
        """Log current configuration settings (non-sensitive)."""
        config_dict = self.settings.to_dict()
        self.logger.info(f"Project: {self.settings.project_name}")
        self.logger.info(f"Version: {self.settings.app_version}")
        self.logger.info(f"Environment: {self.settings.app_env}")
        self.logger.info(f"Debug Mode: {self.settings.app_debug}")
        self.logger.info(f"Trading Mode: {self.settings.trading_mode}")
        self.logger.info(f"Default Symbol: {self.settings.default_symbol}")
        self.logger.info(f"Default Timeframe: {self.settings.default_timeframe} minutes")
        self.logger.info(f"Max Risk Per Trade: {self.settings.max_risk_per_trade}%")
        self.logger.info(f"Max Daily Loss Limit: {self.settings.max_daily_loss_percent}%")
        self.logger.info(f"MT5 Demo Mode: {self.settings.mt5_demo_mode}")
        self.logger.info(f"MT5 Server: {self.settings.mt5_server}")

    def _initialize_market_data(self) -> None:
        """Perform a startup health check against the local MT5 terminal."""
        if not self.settings.mt5_auto_connect:
            self.logger.info("MT5 auto-connect is disabled; startup will stay in manual mode")
            return

        self.logger.info("Checking MT5 core connectivity...")

        if not self.market_data.connect():
            self.logger.warning("MT5 core is offline; continuing in local/offline mode")
            return

        account_info = self.market_data.get_account_info()
        if account_info:
            login = account_info.get("login") or self.settings.mt5_account_number or "unknown"
            balance = account_info.get("balance")
            equity = account_info.get("equity")
            currency = account_info.get("currency", "")
            self.logger.info(
                "MT5 account ready: %s | Balance: %s %s | Equity: %s %s",
                login,
                balance,
                currency,
                equity,
                currency,
            )

        default_symbol = self.settings.default_symbol
        if self.market_data.validate_symbol(default_symbol):
            symbol_snapshot = self.market_data.get_symbol_snapshot(default_symbol)
            if symbol_snapshot:
                self.logger.info("MT5 %s live price: %s", default_symbol, symbol_snapshot.get("live_price"))
                self.logger.info(
                    "MT5 %s quote: bid=%s ask=%s spread=%s time=%s",
                    default_symbol,
                    symbol_snapshot.get("bid"),
                    symbol_snapshot.get("ask"),
                    symbol_snapshot.get("spread"),
                    symbol_snapshot.get("time"),
                )
            else:
                current_price = self.market_data.get_current_price(default_symbol)
                if current_price is not None:
                    self.logger.info("MT5 %s live price: %s", default_symbol, current_price)
        else:
            self.logger.warning("Default symbol %s is not available", default_symbol)

    def is_initialized(self) -> bool:
        """Check if application has been initialized."""
        return self._initialized


# Global application instance
app = TradingApplication()
