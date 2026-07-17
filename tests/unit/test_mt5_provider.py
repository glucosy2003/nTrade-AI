from backend.market_data.providers.mt5_provider import MT5Provider


def test_mt5_provider_connect_returns_false_when_bridge_is_unavailable():
    class UnavailableService:
        def connect(self) -> bool:
            return False

    provider = MT5Provider(service=UnavailableService())

    assert provider.connect() is False


class FakeService:
    def connect(self) -> bool:
        return True

    def symbol_snapshot(self, symbol: str) -> dict:
        return {"symbol": symbol, "live_price": 1.23}

    def tick_info(self, symbol: str) -> dict:
        return {"symbol": symbol, "bid": 1.22, "ask": 1.24}

    def account_info(self) -> dict:
        return {"login": 123456, "balance": 1000.0}

    def validate_symbol(self, symbol: str) -> bool:
        return symbol == "XAUUSD"

    def get_positions(self) -> list[dict]:
        return [{"ticket": 1}]

    def health_check(self) -> dict:
        return {"connected": True}


def test_mt5_provider_exposes_snapshot_and_account_helpers():
    provider = MT5Provider(service=FakeService())

    assert provider.get_symbol_snapshot("XAUUSD") == {"symbol": "XAUUSD", "live_price": 1.23}
    assert provider.get_tick_info("XAUUSD") == {"symbol": "XAUUSD", "bid": 1.22, "ask": 1.24}
    assert provider.get_account_info() == {"login": 123456, "balance": 1000.0}
    assert provider.validate_symbol("XAUUSD") is True
    assert provider.get_positions() == [{"ticket": 1}]
    assert provider.health_check() == {"connected": True}
