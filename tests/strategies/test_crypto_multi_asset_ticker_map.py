"""Strategy/edge layer uses canonical kalshi_ticker_to_asset (five-asset grid)."""

from __future__ import annotations

from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, kalshi_ticker_to_asset
from merid.prediction.edge_model import EdgeModel, _ASSET_PERP_SLUG
def test_sample_15m_tickers_map_to_all_five_assets() -> None:
    tickers = [
        "KXBTC15M-26MAR-A",
        "KXETH15M-26MAR-B",
        "KXSOL15M-26MAR-C",
        "KXXRP15M-26MAR-D",
        "KXDOGE15M-26MAR-E",
    ]
    got = {kalshi_ticker_to_asset(t) for t in tickers}
    assert got == set(ACTIVE_CRYPTO_ASSETS)


def test_edge_model_perp_slug_covers_five_assets() -> None:
    assert set(_ASSET_PERP_SLUG.keys()) == set(ACTIVE_CRYPTO_ASSETS)


def test_edge_context_signal_is_crypto_for_xrp_doge() -> None:
    m = EdgeModel.__new__(EdgeModel)
    m._macro_features = {"macro_inverted_curve": 0.0}
    m._perp_features = {}
    adj, conf = m._context_signal(0.5, "XRP", "KXXRP-T")
    assert conf == 0.0

    m._macro_features = {"macro_inverted_curve": 1.0}
    adj2, conf2 = m._context_signal(0.5, "XRP", "KXXRP-T")
    assert adj2 is not None and conf2 > 0.0
