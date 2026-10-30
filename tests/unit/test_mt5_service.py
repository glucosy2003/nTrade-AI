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
    def __init__(self, name: str, filling_mode: int = 1) -> None:
        self.name = name
        self.visible = True
        self.filling_mode = filling_mode

    def _asdict(self) -> dict:
        return {
            "name": self.name,
            "visible": self.visible,
            "filling_mode": self.filling_mode,
        }


class FakeMT5:
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1
    ORDER_FILLING_RETURN = 2
    SYMBOL_FILLING_FOK = 1
    SYMBOL_FILLING_IOC = 2

    def symbol_info(self, symbol: str) -> FakeSymbolInfo:
        return FakeSymbolInfo(symbol)

    def symbol_info_tick(self, symbol: str) -> FakeTick:
        return FakeTick()

    def order_calc_profit(self, order_type, symbol, volume, open_price, close_price):
        direction = 1 if order_type == self.ORDER_TYPE_BUY else -1
        return (close_price - open_price) * direction * volume


class FakeInitializableMT5:
    def __init__(self) -> None:
        self.initialize_called = False

    def initialize(self) -> bool:
        self.initialize_called = True
        return True


class FakeCredentialMT5:
    def __init__(self) -> None:
        self.initialize_kwargs = None
        self.login_kwargs = None

    def terminal_info(self):
        return None

    def initialize(self, **kwargs) -> bool:
        self.initialize_kwargs = kwargs
        return True

    def login(self, **kwargs) -> bool:
        self.login_kwargs = kwargs
        return True


def test_non_default_mt5_profile_requires_own_credentials(monkeypatch):
    fake_mt5 = FakeInitializableMT5()
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)

    service = MT5Service(profile_name="synthetic")

    assert service.connect() is False
    assert service.last_error == "MT5 synthetic profile is incomplete"
    assert fake_mt5.initialize_called is False


def test_mt5_service_logs_in_with_selected_profile_credentials(monkeypatch):
    fake_mt5 = FakeCredentialMT5()
    monkeypatch.setattr(mt5_module, "mt5", fake_mt5)
    service = MT5Service(
        account_number="123456",
        password="demo-password",
        server="Demo-Server",
        terminal_path="C:/MT5/terminal64.exe",
        profile_name="synthetic",
    )

    assert service.connect() is True
    assert fake_mt5.initialize_kwargs == {
        "path": "C:/MT5/terminal64.exe",
    }
    assert fake_mt5.login_kwargs == {
        "login": 123456,
        "password": "demo-password",
        "server": "Demo-Server",
    }


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


def test_preferred_filling_mode_maps_symbol_flag_to_order_enum(monkeypatch):
    monkeypatch.setattr(mt5_module, "mt5", FakeMT5())

    service = MT5Service()
    service.is_connected = True

    assert service.supported_filling_modes("FX Vol 20") == [0]
    assert service.preferred_filling_mode("FX Vol 20") == 0


def test_estimate_order_profit_uses_mt5_contract_calculation(monkeypatch):
    monkeypatch.setattr(mt5_module, "mt5", FakeMT5())

    service = MT5Service()
    service.is_connected = True

    assert service.estimate_order_profit("FX Vol 40", 0.1, "BUY", 100, 110) == 1.0
