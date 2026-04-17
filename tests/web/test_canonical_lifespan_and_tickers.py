from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient


def test_repo_root_main_delegates_to_web_main_app():
    import main
    import web.main as wm

    assert main.app is wm.app


def test_canonical_lifespan_marker_runs_in_test_mode(monkeypatch):
    # Keep lifespan cheap: web.main._app_lifespan checks this flag.
    monkeypatch.setenv("MERID_TEST_MODE", "1")

    from main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        # We just need lifespan side effects, not any particular endpoint.
        assert getattr(client.app.state, "canonical_lifespan", "") == "web.main._app_lifespan"
        assert getattr(client.app.state, "test_mode", False) is True


def test_compute_kalshi_ws_tickers_non_empty_and_dedupes():
    from web.main import compute_kalshi_ws_tickers

    def m(asset: str, mid: str):
        return SimpleNamespace(asset=asset, market=SimpleNamespace(market_id=mid))

    markets = [
        m("BTC", "KXBTCD-1"),
        m("BTC", "KXBTCD-2"),
        m("ETH", "KETHD-1"),
        m("SOL", "KSOLD-1"),
        m("DOGE", "KDOGED-1"),
        # Duplicate ID should be deduped by seen-set fill logic
        m("ETH", "KETHD-1"),
    ]

    tickers = compute_kalshi_ws_tickers(markets=markets, limit=10, target_assets=["BTC", "ETH"])
    assert isinstance(tickers, list)
    assert len(tickers) > 0
    assert len(tickers) == len(set(tickers))
