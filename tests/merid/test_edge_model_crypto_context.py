"""Edge model applies macro/context nudges across all five crypto assets."""

from __future__ import annotations

from merid.prediction.edge_model import EdgeModel


def test_context_signal_nonzero_for_all_primary_crypto_assets() -> None:
    m = EdgeModel()
    m._messari_features = {"messari_btc_dom_high": 0.0, "messari_btc_7d": 6.0, "messari_eth_7d": 6.0}
    m._fg_features = {"fg_contrarian": 0.02}
    for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        adj, conf = m._context_signal(0.5, asset, f"KX{asset}15M-TEST")
        assert adj is not None
        assert conf > 0.0
