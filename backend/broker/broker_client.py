"""Small HTTP client for broker-side connector services."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from urllib import parse, request
from urllib.error import HTTPError, URLError


class BrokerClient:
    """Thin wrapper around a local HTTP broker bridge service.

    The client intentionally stays small and transport-specific so the AI layer
    can consume broker data without knowing the details of the Windows/MT5 side.
    """

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{parse.urlencode(params)}"

        try:
            with request.urlopen(url, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                return __import__("json").loads(payload)
        except (HTTPError, URLError, ValueError):
            return None

    def ping(self) -> bool:
        """Check whether the bridge service is reachable."""
        payload = self._request("/health")
        return payload is not None and payload.get("status") == "ok"

    def get_historical_data(self, symbol: str, timeframe: int, start: str, end: str) -> Optional[Dict[str, Any]]:
        """Fetch historical candles from the broker bridge."""
        return self._request(
            "/historical-data",
            params={
                "symbol": symbol,
                "timeframe": timeframe,
                "start": start,
                "end": end,
            },
        )

    def get_latest_price(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest price for the symbol from the broker bridge."""
        return self._request("/latest-price", params={"symbol": symbol})
