from backend.market_data.providers.mt5_provider import MT5Provider


def test_mt5_provider_connect_returns_false_when_bridge_is_unavailable():
    provider = MT5Provider(base_url="http://127.0.0.1:1", timeout=0.1)

    assert provider.connect() is False
