import os

from fastapi.testclient import TestClient

# Force simulation to run in mock/offline mode so tests have deterministic payloads.
os.environ.setdefault("MERID_POLYMARKET_MOCK", "1")
os.environ.setdefault("MERID_ENABLE_NEWS_AGENT", "0")
os.environ.setdefault("MERID_ENABLE_ONCHAIN_ANALYTICS", "0")
os.environ.setdefault("MERID_ENABLE_PERP_INTEL", "1")

from web.main import create_app  # noqa: E402  (import after env configuration)


client = TestClient(create_app())


def test_heatmap_endpoint_returns_shape():
    response = client.get("/api/v1/heatmap")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) >= {"generated_at", "symbols", "venues", "liquidations", "perp_markets", "arbitrage"}
    assert isinstance(data["symbols"], list)


def test_ticker_endpoint_returns_lists():
    response = client.get("/api/v1/ticker")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) >= {"generated_at", "tickers", "funding_extremes", "arbitrage"}
    assert isinstance(data["tickers"], list)
    assert isinstance(data["funding_extremes"], dict)


def test_assist_endpoint_is_dict():
    response = client.get("/api/v1/assist")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)


def test_hover_metadata_endpoint_is_dict():
    response = client.get("/api/v1/hover-metadata")
    assert response.status_code == 200
    assert isinstance(response.json(), dict)
