"""Direct Windows MT5 service for market data and account access."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd

try:
    import MetaTrader5 as mt5
except ImportError:  # pragma: no cover - dependency is installed on Windows
    mt5 = None

from backend.core.settings import settings


logger = logging.getLogger(__name__)


class MT5Service:
    """Windows-native MetaTrader 5 service wrapper.

    The service keeps MT5 access in one place so the rest of the application can
    treat broker connectivity as a simple dependency instead of scattering
    MetaTrader5 calls across modules.
    """

    _TIMEFRAME_MAP = {
        1: "TIMEFRAME_M1",
        5: "TIMEFRAME_M5",
        15: "TIMEFRAME_M15",
        30: "TIMEFRAME_M30",
        60: "TIMEFRAME_H1",
        240: "TIMEFRAME_H4",
        1440: "TIMEFRAME_D1",
        10080: "TIMEFRAME_W1",
        43200: "TIMEFRAME_MN1",
    }

    _TIMEFRAME_LABELS = {
        "M1": "TIMEFRAME_M1",
        "M5": "TIMEFRAME_M5",
        "M15": "TIMEFRAME_M15",
        "M30": "TIMEFRAME_M30",
        "H1": "TIMEFRAME_H1",
        "H4": "TIMEFRAME_H4",
        "D1": "TIMEFRAME_D1",
        "W1": "TIMEFRAME_W1",
        "MN1": "TIMEFRAME_MN1",
    }

    def __init__(self) -> None:
        self.is_connected = False
        self.last_error: Optional[str] = None

    def connect(self) -> bool:
        """Initialize MT5 and log in when credentials are available."""
        if mt5 is None:
            logger.warning("MetaTrader5 package is not installed")
            self.last_error = "MetaTrader5 package missing"
            return False

        if self.is_connected:
            return True

        if not mt5.initialize():
            self.last_error = str(mt5.last_error())
            logger.error("MT5 initialization failed: %s", self.last_error)
            return False

        account_number = self._coerce_int(settings.mt5_account_number)
        password = settings.mt5_password
        server = settings.mt5_server

        if account_number is not None and password and server:
            if not mt5.login(login=account_number, password=password, server=server):
                self.last_error = str(mt5.last_error())
                logger.error("MT5 login failed: %s", self.last_error)
                mt5.shutdown()
                return False

        self.is_connected = True
        self.last_error = None
        logger.info("MT5 terminal initialized successfully")
        return True

    def disconnect(self) -> None:
        """Shut down the MT5 terminal connection."""
        if mt5 is not None and self.is_connected:
            mt5.shutdown()
        self.is_connected = False

    def health_check(self) -> dict[str, Any]:
        """Return a compact MT5 readiness summary."""
        result: dict[str, Any] = {"connected": self.connect()}
        if not result["connected"]:
            result["error"] = self.last_error or "MT5 unavailable"
            return result

        result["terminal"] = self.terminal_info()
        result["account"] = self.account_info()
        result["version"] = self.version()
        return result

    def terminal_info(self) -> Optional[dict[str, Any]]:
        """Return MT5 terminal metadata as a dictionary."""
        if not self.connect() or mt5 is None:
            return None
        info = mt5.terminal_info()
        return info._asdict() if info is not None else None

    def account_info(self) -> Optional[dict[str, Any]]:
        """Return MT5 account metadata as a dictionary."""
        if not self.connect() or mt5 is None:
            return None
        info = mt5.account_info()
        return info._asdict() if info is not None else None

    def version(self) -> Optional[tuple[int, int, int]]:
        """Return the MT5 terminal version."""
        if not self.connect() or mt5 is None:
            return None
        version_info = mt5.version()
        return tuple(version_info) if version_info is not None else None

    def symbols(self) -> list[str]:
        """Return all available symbol names."""
        if not self.connect() or mt5 is None:
            return []

        symbols = mt5.symbols_get(group="*")
        if symbols is None:
            logger.error("symbols_get failed: %s", mt5.last_error())
            return []

        return [symbol.name for symbol in symbols]

    def symbol_info(self, symbol: str) -> Optional[dict[str, Any]]:
        """Return symbol metadata."""
        if not self.connect() or mt5 is None:
            return None

        info = mt5.symbol_info(symbol)
        return info._asdict() if info is not None else None

    def symbol_trade_context(self, symbol: str) -> Optional[dict[str, Any]]:
        """Return broker-specific trading constraints for a symbol."""
        symbol_info = self.symbol_info(symbol)
        if symbol_info is None:
            return None

        tick_info = self.tick_info(symbol) or {}
        return {
            "symbol": symbol,
            "trade_mode": symbol_info.get("trade_mode"),
            "order_mode": symbol_info.get("order_mode"),
            "filling_mode": symbol_info.get("filling_mode"),
            "expiration_mode": symbol_info.get("expiration_mode"),
            "volume_min": symbol_info.get("volume_min"),
            "volume_max": symbol_info.get("volume_max"),
            "volume_step": symbol_info.get("volume_step"),
            "volume_limit": symbol_info.get("volume_limit"),
            "trade_contract_size": symbol_info.get("trade_contract_size"),
            "trade_tick_size": symbol_info.get("trade_tick_size"),
            "trade_tick_value": symbol_info.get("trade_tick_value"),
            "point": symbol_info.get("point"),
            "digits": symbol_info.get("digits"),
            "spread": tick_info.get("spread"),
            "ask": tick_info.get("ask"),
            "bid": tick_info.get("bid"),
            "last": tick_info.get("last"),
            "time": tick_info.get("time"),
            "trade_stops_level": symbol_info.get("trade_stops_level"),
            "trade_freeze_level": symbol_info.get("trade_freeze_level"),
            "visible": symbol_info.get("visible"),
        }

    def estimate_order_margin(self, symbol: str, volume: float, order_type: str, price: float) -> Optional[float]:
        """Estimate required margin for a market order."""
        if not self.connect() or mt5 is None:
            return None

        order_type_map = {
            "BUY": getattr(mt5, "ORDER_TYPE_BUY", None),
            "SELL": getattr(mt5, "ORDER_TYPE_SELL", None),
        }
        mt5_order_type = order_type_map.get(order_type.upper())
        if mt5_order_type is None:
            return None

        try:
            margin = mt5.order_calc_margin(mt5_order_type, symbol, volume, price)
            return float(margin) if margin is not None else None
        except Exception as exc:  # pragma: no cover - broker/library failure
            logger.warning("Margin estimate failed for %s: %s", symbol, exc)
            return None

    def order_check(self, request: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Run a broker-side order check when supported."""
        if not self.connect() or mt5 is None:
            return None

        try:
            result = mt5.order_check(request)
            return result._asdict() if result is not None else None
        except Exception as exc:  # pragma: no cover - broker/library failure
            logger.warning("Order check failed: %s", exc)
            return None

    def tick_info(self, symbol: str) -> Optional[dict[str, Any]]:
        """Return the latest tick metadata for a symbol."""
        if not self.validate_symbol(symbol) or mt5 is None:
            return None

        tick = mt5.symbol_info_tick(symbol)
        return tick._asdict() if tick is not None else None

    def symbol_snapshot(self, symbol: str) -> Optional[dict[str, Any]]:
        """Return combined symbol, tick, and price details."""
        symbol_info = self.symbol_info(symbol)
        if symbol_info is None:
            return None

        tick_info = self.tick_info(symbol)
        live_price = self.get_live_price(symbol)
        snapshot: dict[str, Any] = {
            "symbol": symbol,
            "available": True,
            "live_price": live_price,
            "symbol_info": symbol_info,
            "tick_info": tick_info,
        }

        if tick_info is not None:
            snapshot["bid"] = tick_info.get("bid")
            snapshot["ask"] = tick_info.get("ask")
            snapshot["last"] = tick_info.get("last")
            snapshot["spread"] = tick_info.get("spread")
            snapshot["time"] = tick_info.get("time")

        return snapshot

    def validate_symbol(self, symbol: str) -> bool:
        """Ensure a symbol exists and is visible in MT5."""
        if not self.connect() or mt5 is None:
            return False

        info = mt5.symbol_info(symbol)
        if info is None:
            logger.warning("Symbol %s not found on broker", symbol)
            return False

        if not info.visible and not mt5.symbol_select(symbol, True):
            logger.warning("Symbol %s is not visible", symbol)
            return False

        return True

    def get_live_price(self, symbol: str) -> Optional[float]:
        """Return the latest tradable price for a symbol."""
        if not self.validate_symbol(symbol) or mt5 is None:
            return None

        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            logger.warning("Could not get live tick for %s", symbol)
            return None

        price = tick.bid if tick.bid else tick.last
        if not price:
            price = tick.ask
        return float(price) if price is not None else None

    def get_historical_data(
        self,
        symbol: str,
        timeframe: int | str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        limit: int = 1000,
    ) -> Optional[pd.DataFrame]:
        """Return OHLCV candles as a DataFrame."""
        if not self.validate_symbol(symbol) or mt5 is None:
            return None

        mt5_timeframe = self._resolve_timeframe(timeframe)
        if mt5_timeframe is None:
            logger.error("Unsupported timeframe: %s", timeframe)
            return None

        if end is None:
            end = datetime.utcnow()
        if start is None:
            start = end - timedelta(days=max(settings.historical_data_years, 1) * 365)

        rates = mt5.copy_rates_range(symbol, mt5_timeframe, start, end)
        if rates is None or len(rates) == 0:
            rates = mt5.copy_rates_from_pos(symbol, mt5_timeframe, 0, limit)

        if rates is None or len(rates) == 0:
            logger.warning("No historical data returned for %s", symbol)
            return None

        df = pd.DataFrame(rates)
        if df.empty:
            return None

        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True).dt.tz_convert(None)
        if "tick_volume" in df.columns:
            df = df.rename(columns={"tick_volume": "volume"})

        keep_columns = [column for column in ["time", "open", "high", "low", "close", "volume"] if column in df.columns]
        df = df[keep_columns].copy()
        df["symbol"] = symbol
        df["timeframe"] = self._timeframe_as_label(timeframe)
        return df

    def get_positions(self) -> list[dict[str, Any]]:
        """Return the current open positions."""
        if not self.connect() or mt5 is None:
            return []

        positions = mt5.positions_get()
        if positions is None:
            return []

        result: list[dict[str, Any]] = []
        for position in positions:
            result.append(
                {
                    "ticket": position.ticket,
                    "symbol": position.symbol,
                    "type": "BUY" if position.type == 0 else "SELL",
                    "volume": position.volume,
                    "open_price": position.price_open,
                    "current_price": position.price_current,
                    "profit": position.profit,
                    "open_time": position.time,
                }
            )

        return result

    @classmethod
    def _resolve_timeframe(cls, timeframe: int | str) -> Optional[Any]:
        if mt5 is None:
            return None

        if isinstance(timeframe, str):
            timeframe_key = timeframe.strip().upper()
            attribute_name = cls._TIMEFRAME_LABELS.get(timeframe_key)
        else:
            attribute_name = cls._TIMEFRAME_MAP.get(int(timeframe))

        if attribute_name is None:
            return None

        return getattr(mt5, attribute_name, None)

    @classmethod
    def _timeframe_as_label(cls, timeframe: int | str) -> str:
        if isinstance(timeframe, str):
            return timeframe.strip().upper()
        return {
            1: "M1",
            5: "M5",
            15: "M15",
            30: "M30",
            60: "H1",
            240: "H4",
            1440: "D1",
            10080: "W1",
            43200: "MN1",
        }.get(int(timeframe), str(timeframe))

    @staticmethod
    def _coerce_int(value: Optional[int | str]) -> Optional[int]:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


mt5_service = MT5Service()
