"""Kalshi Crypto Hedging — Deterministic rule-based hedge engine.

Modules:
    config   — YAML config loader & dataclasses
    exposure — ExposureSnapshot builder from position cache / pending orders
    engine   — CryptoHedgeEngine: compute_hedge_orders()

Usage::

    from merid.hedging import get_hedge_engine, get_hedge_config
    from merid.hedging.exposure import build_exposure_snapshot

    cfg = get_hedge_config()
    engine = get_hedge_engine()
    snap = build_exposure_snapshot()
    orders = engine.compute_hedge_orders(snap, cfg)
"""

from __future__ import annotations

from merid.hedging.config import (
    HedgeConfig,
    AssetSliceConfig,
    TimeframeHedgeRule,
    CrossAssetPairConfig,
    load_hedge_config,
    get_hedge_config,
)
from merid.hedging.engine import CryptoHedgeEngine, get_hedge_engine

__all__ = [
    "HedgeConfig",
    "AssetSliceConfig",
    "TimeframeHedgeRule",
    "CrossAssetPairConfig",
    "CryptoHedgeEngine",
    "load_hedge_config",
    "get_hedge_config",
    "get_hedge_engine",
]
