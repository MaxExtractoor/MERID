"""Unit tests for core crypto PM helpers (no live Kalshi)."""

from __future__ import annotations

import pytest

from merid.prediction.agent_grid_config import get_agent_grid_config
from merid.pm_crypto_ops import (
    CORE_CRYPTO_ASSETS,
    crypto_product_key,
    is_core_crypto_pm_config,
    market_id_matches_series,
)


def test_crypto_product_key_all_tenors() -> None:
    for asset in CORE_CRYPTO_ASSETS:
        for tf in ("15m", "1h", "daily", "weekly", "monthly", "annual"):
            k = crypto_product_key(asset, tf)
            assert k.startswith(f"{asset}_")


def test_crypto_product_key_rejects_unknown_tf() -> None:
    with pytest.raises(ValueError, match="Unknown AgentGrid timeframe"):
        crypto_product_key("BTC", "5m")


def test_market_id_matches_series() -> None:
    assert market_id_matches_series("KXBTC15M-FOO", ["KXBTC15M"])
    assert market_id_matches_series("KXBTC", ["KXBTC"])
    assert market_id_matches_series("KXBTC-26APR-B9", ["KXBTC"])
    assert not market_id_matches_series("KXETH15M-X", ["KXBTC15M"])


def test_agent_grid_has_full_crypto_directional_matrix() -> None:
    cfg = get_agent_grid_config()
    pairs = {
        (a.assets[0], a.timeframes[0])
        for a in cfg.agents
        if is_core_crypto_pm_config(a)
    }
    expected = {
        (asset, tf)
        for asset in CORE_CRYPTO_ASSETS
        for tf in ("15m", "1h", "daily", "weekly", "monthly", "annual")
    }
    assert pairs == expected
    assert len(pairs) == 30


def test_all_core_agents_enabled_by_default() -> None:
    cfg = get_agent_grid_config()
    for a in cfg.agents:
        if is_core_crypto_pm_config(a):
            assert a.enabled is True, a.name
