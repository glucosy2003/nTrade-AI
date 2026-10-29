"""
Settings and configuration management for the nTrade AI system.

This module provides centralized configuration management using environment variables,
with support for different environments (development, production, testing).

Follows 12-factor app principles: configuration stored in environment variables,
never hardcoded or committed to version control.
"""

import logging
import os
from urllib.parse import quote_plus
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _load_dotenv_file() -> None:
    """Load environment values from a local .env file when present."""
    env_path = os.getenv("ENV_FILE")
    if not env_path:
        env_path = str(Path(__file__).resolve().parents[2] / ".env")

    if not os.path.exists(env_path):
        return

    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # Prefer the active .env file over any already-exported shell values so
            # the configured account is used consistently across runs.
            os.environ[key] = value


_load_dotenv_file()


class Settings:
    """Application settings loaded from environment variables and defaults."""

    def __init__(self, **data):
        """Initialize settings from explicit values or environment variables."""
        self.project_name = data.get("project_name") or os.getenv(
            "PROJECT_NAME", "nTrade AI"
        )
        self.app_env = data.get("app_env") or os.getenv("APP_ENV", "development")
        self.app_debug = self._get_bool(
            data.get("app_debug"), os.getenv("APP_DEBUG"), True
        )
        self.app_version = data.get("app_version") or os.getenv("APP_VERSION", "1.0.0")

        # For backwards compatibility
        self.VERSION = "1.0.0"
        self.TRADING_MODE = "manual"
        self.DEFAULT_SYMBOL = "XAUUSD"
        self.RISK_PER_TRADE = 0.02
        self.DEBUG = True

        # Database Settings
        self.database_host = data.get("database_host") or os.getenv(
            "DATABASE_HOST", "localhost"
        )
        self.database_port = self._get_int(
            data.get("database_port"), os.getenv("DATABASE_PORT"), 5432
        )
        self.database_name = data.get("database_name") or os.getenv(
            "DATABASE_NAME", "ntrade_ai_dev"
        )
        self.database_user = data.get("database_user") or os.getenv("DATABASE_USER")
        self.database_password = data.get("database_password") or os.getenv(
            "DATABASE_PASSWORD"
        )
        self.database_admin_user = data.get("database_admin_user") or os.getenv(
            "DATABASE_ADMIN_USER",
            self.database_user or "postgres",
        )
        self.database_admin_password = data.get("database_admin_password") or os.getenv(
            "DATABASE_ADMIN_PASSWORD",
            self.database_password,
        )
        self.database_url = (
            data.get("database_url")
            or os.getenv("DATABASE_URL")
            or self._build_database_url()
        )
        self.database_pool_size = self._get_int(
            data.get("database_pool_size"), os.getenv("DATABASE_POOL_SIZE"), 10
        )
        self.database_max_overflow = self._get_int(
            data.get("database_max_overflow"), os.getenv("DATABASE_MAX_OVERFLOW"), 20
        )
        self.database_echo = self._get_bool(
            data.get("database_echo"), os.getenv("DATABASE_ECHO"), False
        )

        # MetaTrader 5 Settings
        self.mt5_account_number = data.get("mt5_account_number") or os.getenv(
            "MT5_ACCOUNT_NUMBER"
        )
        self.mt5_password = data.get("mt5_password") or os.getenv("MT5_PASSWORD")
        self.mt5_server = data.get("mt5_server") or os.getenv(
            "MT5_SERVER", "Weltrade-Demo"
        )
        self.mt5_demo_mode = self._get_bool(
            data.get("mt5_demo_mode"), os.getenv("MT5_DEMO_MODE"), True
        )
        self.mt5_auto_connect = self._get_bool(
            data.get("mt5_auto_connect"),
            os.getenv("MT5_AUTO_CONNECT"),
            False,
        )
        self.synthetic_mt5_account_number = data.get(
            "synthetic_mt5_account_number"
        ) or os.getenv("SYNTHETIC_MT5_ACCOUNT_NUMBER")
        self.synthetic_mt5_password = data.get("synthetic_mt5_password") or os.getenv(
            "SYNTHETIC_MT5_PASSWORD"
        )
        self.synthetic_mt5_server = data.get("synthetic_mt5_server") or os.getenv(
            "SYNTHETIC_MT5_SERVER"
        )
        self.synthetic_mt5_terminal_path = data.get(
            "synthetic_mt5_terminal_path"
        ) or os.getenv("SYNTHETIC_MT5_TERMINAL_PATH")
        self.synthetic_mt5_demo_mode = self._get_bool(
            data.get("synthetic_mt5_demo_mode"),
            os.getenv("SYNTHETIC_MT5_DEMO_MODE"),
            True,
        )
        self.synthetic_account_ids = self._get_csv(
            data.get("synthetic_account_ids"),
            os.getenv("SYNTHETIC_ACCOUNT_IDS"),
            ["synthetic"],
        )

        # Trading Settings
        self.default_symbol = data.get("default_symbol") or os.getenv(
            "DEFAULT_SYMBOL", "XAUUSD"
        )
        self.gold_history_symbol = data.get("gold_history_symbol") or os.getenv(
            "GOLD_HISTORY_SYMBOL", "XAUUSD_i"
        )
        self.default_timeframe = self._get_int(
            data.get("default_timeframe"), os.getenv("DEFAULT_TIMEFRAME"), 60
        )
        self.trading_mode = data.get("trading_mode") or os.getenv(
            "TRADING_MODE", "manual"
        )

        # Synthetic index Settings
        self.synthetic_index_20_symbol = data.get(
            "synthetic_index_20_symbol"
        ) or os.getenv("SYNTHETIC_INDEX_20_SYMBOL", "FX Vol 20")
        self.synthetic_index_40_symbol = data.get(
            "synthetic_index_40_symbol"
        ) or os.getenv("SYNTHETIC_INDEX_40_SYMBOL", "FX Vol 40")
        self.synthetic_index_80_symbol = data.get(
            "synthetic_index_80_symbol"
        ) or os.getenv("SYNTHETIC_INDEX_80_SYMBOL", "FX Vol 80")
        self.synthetic_index_20_search_terms = self._get_csv(
            data.get("synthetic_index_20_search_terms"),
            os.getenv("SYNTHETIC_INDEX_20_SEARCH_TERMS"),
            ["fx", "vol", "20"],
        )
        self.synthetic_index_40_search_terms = self._get_csv(
            data.get("synthetic_index_40_search_terms"),
            os.getenv("SYNTHETIC_INDEX_40_SEARCH_TERMS"),
            ["fx", "vol", "40"],
        )
        self.synthetic_index_80_search_terms = self._get_csv(
            data.get("synthetic_index_80_search_terms"),
            os.getenv("SYNTHETIC_INDEX_80_SEARCH_TERMS"),
            ["fx", "vol", "80"],
        )
        self.synthetic_max_trades_per_day = self._get_int(
            data.get("synthetic_max_trades_per_day"),
            os.getenv("SYNTHETIC_MAX_TRADES_PER_DAY"),
            6,
        )
        self.synthetic_max_trades_per_symbol_per_day = self._get_int(
            data.get("synthetic_max_trades_per_symbol_per_day"),
            os.getenv("SYNTHETIC_MAX_TRADES_PER_SYMBOL_PER_DAY"),
            2,
        )
        self.synthetic_demo_only = self._get_bool(
            data.get("synthetic_demo_only"),
            os.getenv("SYNTHETIC_DEMO_ONLY"),
            True,
        )

        # Risk Management Settings
        self.max_risk_per_trade = self._get_float(
            data.get("max_risk_per_trade"), os.getenv("MAX_RISK_PER_TRADE"), 2.0
        )
        self.max_daily_loss_percent = self._get_float(
            data.get("max_daily_loss_percent"), os.getenv("MAX_DAILY_LOSS_PERCENT"), 5.0
        )
        self.max_concurrent_trades = self._get_int(
            data.get("max_concurrent_trades"), os.getenv("MAX_CONCURRENT_TRADES"), 3
        )

        # Data Collection Settings
        self.historical_data_years = self._get_int(
            data.get("historical_data_years"), os.getenv("HISTORICAL_DATA_YEARS"), 5
        )
        self.backtest_data_start_date = data.get(
            "backtest_data_start_date"
        ) or os.getenv("BACKTEST_DATA_START_DATE", "2020-01-01")
        self.broker_base_url = data.get("broker_base_url") or os.getenv(
            "BROKER_BASE_URL", "http://127.0.0.1:8001"
        )

        # Logging Settings
        self.log_level = data.get("log_level") or os.getenv("LOG_LEVEL", "INFO")
        self.log_dir = data.get("log_dir") or os.getenv("LOG_DIR", "./logs")

        # External API Keys (Optional)
        self.news_api_key = data.get("news_api_key") or os.getenv("NEWS_API_KEY")
        self.sentiment_api_key = data.get("sentiment_api_key") or os.getenv(
            "SENTIMENT_API_KEY"
        )

        self._validate_configuration()

    @staticmethod
    def _get_bool(value, env_value, default: bool) -> bool:
        if value is not None:
            return bool(value)
        if env_value is None:
            return default
        return str(env_value).strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _get_int(value, env_value, default: int) -> int:
        if value is not None:
            return int(value)
        if env_value is None:
            return default
        return int(env_value)

    @staticmethod
    def _get_float(value, env_value, default: float) -> float:
        if value is not None:
            return float(value)
        if env_value is None:
            return default
        return float(env_value)

    @staticmethod
    def _get_csv(value, env_value, default: list[str]) -> list[str]:
        source = value if value is not None else env_value
        if source is None:
            return default
        if isinstance(source, (list, tuple)):
            return [str(item).strip() for item in source if str(item).strip()]
        return [item.strip() for item in str(source).split(",") if item.strip()]

    def _build_database_url(self) -> str:
        """Construct a PostgreSQL connection URL from discrete settings."""
        user = self.database_user
        password = self.database_password
        host = self.database_host
        port = self.database_port
        name = self.database_name

        if user and password:
            return (
                "postgresql+psycopg://"
                f"{quote_plus(str(user))}:{quote_plus(str(password))}"
                f"@{host}:{port}/{name}"
            )

        if user:
            return f"postgresql+psycopg://{quote_plus(str(user))}@{host}:{port}/{name}"

        return f"postgresql+psycopg://{host}:{port}/{name}"

    def _validate_configuration(self) -> None:
        """Validate critical configuration values."""
        if self.app_env not in ["development", "production", "testing"]:
            logger.warning(f"Unknown APP_ENV: {self.app_env}. Using 'development'.")
            self.app_env = "development"

        if self.trading_mode not in ["manual", "automatic"]:
            logger.warning(
                f"Unknown TRADING_MODE: {self.trading_mode}. Using 'manual'."
            )
            self.trading_mode = "manual"

        if self.max_risk_per_trade < 0.1 or self.max_risk_per_trade > 10:
            logger.warning(
                f"MAX_RISK_PER_TRADE {self.max_risk_per_trade}% seems unusual. "
                "Should typically be 1-2%."
            )

        if not self.database_user or not self.database_password:
            logger.warning(
                "DATABASE_USER/DATABASE_PASSWORD are not fully set. "
                "PostgreSQL may still work with trust authentication, but migrations "
                "and first-time database creation usually need explicit credentials."
            )

    def is_production(self) -> bool:
        """Check if running in production."""
        return self.app_env == "production"

    def is_development(self) -> bool:
        """Check if running in development."""
        return self.app_env == "development"

    def is_testing(self) -> bool:
        """Check if running in testing."""
        return self.app_env == "testing"

    def mt5_account_profile(self, profile_name: str = "default") -> dict:
        """Return a named MT5 account profile."""
        if profile_name == "synthetic":
            return {
                "name": "synthetic",
                "account_id": os.getenv("NTRADE_SYNTHETIC_ACCOUNT_ID", "synthetic"),
                "account_number": self.synthetic_mt5_account_number,
                "password": self.synthetic_mt5_password,
                "server": self.synthetic_mt5_server,
                "terminal_path": self.synthetic_mt5_terminal_path,
                "demo_mode": self.synthetic_mt5_demo_mode,
            }

        return {
            "name": "default",
            "account_number": self.mt5_account_number,
            "password": self.mt5_password,
            "server": self.mt5_server,
            "demo_mode": self.mt5_demo_mode,
        }

    def synthetic_account_profiles(self) -> list[dict]:
        """Return configured synthetic account profiles for multi-account runners."""
        profiles: list[dict] = []
        for account_id in self.synthetic_account_ids:
            env_key = "".join(
                character if character.isalnum() else "_" for character in account_id
            ).upper()
            prefix = f"SYNTHETIC_{env_key}"
            if account_id == "synthetic":
                profile = self.mt5_account_profile("synthetic")
            else:
                profile = {
                    "name": account_id,
                    "account_id": account_id,
                    "account_number": os.getenv(f"{prefix}_ACCOUNT_NUMBER"),
                    "password": os.getenv(f"{prefix}_PASSWORD"),
                    "server": os.getenv(f"{prefix}_SERVER"),
                    "terminal_path": os.getenv(f"{prefix}_TERMINAL_PATH"),
                    "demo_mode": self._get_bool(
                        None, os.getenv(f"{prefix}_DEMO_MODE"), True
                    ),
                }
            profile["enabled"] = self._get_bool(
                None, os.getenv(f"{prefix}_ENABLED"), True
            )
            profiles.append(profile)
        return profiles

    def to_dict(self) -> dict:
        """Return settings as dictionary (non-sensitive values only)."""
        return {
            "app_env": self.app_env,
            "app_debug": self.app_debug,
            "app_version": self.app_version,
            "default_symbol": self.default_symbol,
            "gold_history_symbol": self.gold_history_symbol,
            "synthetic_index_20_symbol": self.synthetic_index_20_symbol,
            "synthetic_index_40_symbol": self.synthetic_index_40_symbol,
            "synthetic_index_80_symbol": self.synthetic_index_80_symbol,
            "synthetic_index_20_search_terms": self.synthetic_index_20_search_terms,
            "synthetic_index_40_search_terms": self.synthetic_index_40_search_terms,
            "synthetic_index_80_search_terms": self.synthetic_index_80_search_terms,
            "synthetic_max_trades_per_day": self.synthetic_max_trades_per_day,
            "synthetic_max_trades_per_symbol_per_day": self.synthetic_max_trades_per_symbol_per_day,
            "synthetic_demo_only": self.synthetic_demo_only,
            "database_host": self.database_host,
            "database_port": self.database_port,
            "database_name": self.database_name,
            "database_user": self.database_user,
            "database_admin_user": self.database_admin_user,
            "database_echo": self.database_echo,
            "trading_mode": self.trading_mode,
            "max_risk_per_trade": self.max_risk_per_trade,
            "max_daily_loss_percent": self.max_daily_loss_percent,
            "mt5_server": self.mt5_server,
            "mt5_demo_mode": self.mt5_demo_mode,
            "mt5_auto_connect": self.mt5_auto_connect,
            "synthetic_mt5_server": self.synthetic_mt5_server,
            "synthetic_mt5_terminal_path": self.synthetic_mt5_terminal_path,
            "synthetic_mt5_demo_mode": self.synthetic_mt5_demo_mode,
            "synthetic_account_ids": self.synthetic_account_ids,
            "synthetic_mt5_configured": bool(
                self.synthetic_mt5_account_number
                and self.synthetic_mt5_password
                and self.synthetic_mt5_server
            ),
        }


# Global settings instance (loaded once on import)
settings = Settings()
