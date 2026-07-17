from backend.market_data import mt5_service as mt5_module
from backend.market_data.mt5_service import MT5Service


class FakeTick:
    def __init__(self) -> None:
        self.bid = 2345.1
        self.ask = 2345.3
        self.last = 2345.2
        self.spread = 2
        self.time = 1710000000

    def _asdict(self) -> dict:
        return {
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "spread": self.spread,
            "time": self.time,
        }


class FakeSymbolInfo:
    def __init__(self, name: str) -> None:
        self.name = name
        self.visible = True

    def _asdict(self) -> dict:
        return {"name": self.name, "visible": self.visible}


class FakeMT5:
    def symbol_info(self, symbol: str) -> FakeSymbolInfo:
        return FakeSymbolInfo(symbol)

    def symbol_info_tick(self, symbol: str) -> FakeTick:
        return FakeTick()


def test_mt5_service_symbol_snapshot_includes_price_and_tick(monkeypatch):
    monkeypatch.setattr(mt5_module, "mt5", FakeMT5())

    service = MT5Service()
    service.is_connected = True

    snapshot = service.symbol_snapshot("XAUUSD")

    assert snapshot is not None
    assert snapshot["symbol"] == "XAUUSD"
    assert snapshot["available"] is True
    assert snapshot["live_price"] == 2345.1
    assert snapshot["bid"] == 2345.1
    assert snapshot["ask"] == 2345.3
    assert snapshot["spread"] == 2


def test_mt5_service_tick_info_returns_tick_dictionary(monkeypatch):
    monkeypatch.setattr(mt5_module, "mt5", FakeMT5())

    service = MT5Service()
    service.is_connected = True

    tick_info = service.tick_info("XAUUSD")

    assert tick_info is not None
    assert tick_info["bid"] == 2345.1
    assert tick_info["ask"] == 2345.3
