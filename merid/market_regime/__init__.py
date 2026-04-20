"""Market Regime Gate — Crypto basket flatness filter for MERID.

Provides a config-driven gate that evaluates BTC, ETH, SOL, XRP, DOGE on every
cycle and returns ALLOW, REDUCE, or BLOCK based on per-asset and basket-level
flatness tests.

Modules:
    config   — YAML config loader & frozen dataclasses
    gate     — MarketRegimeGate: evaluate() → RegimeDecision

Usage::

    from merid.market_regime import get_regime_gate, get_regime_config
    from merid.market_regime.gate import RegimeAction

    cfg = get_regime_config()
    gate = get_regime_gate()

    snapshot = {
        "BTC": {"return_pct": 0.5, "atr_pct": 0.8, "vol_ratio": 1.2, "adx": 22},
        "ETH": {"return_pct": -0.3, "atr_pct": 0.6, "vol_ratio": 0.9, "adx": 18},
        # ... etc
    }
    decision = gate.evaluate(snapshot)
    if decision.action == RegimeAction.BLOCK:
        logger.info("Trading blocked: %s", decision.reason_codes)
"""

from __future__ import annotations

from merid.market_regime.config import (
    FlatnessThresholds,
    BasketRules,
    LookbackConfig,
    MarketRegimeConfig,
    load_regime_config,
    get_regime_config,
    _reset_regime_config as _reset_config_singleton,
)
from merid.market_regime.gate import (
    RegimeAction,
    RegimeDecision,
    AssetMetrics,
    BasketSnapshot,
    MarketRegimeGate,
    get_regime_gate,
    _reset_regime_gate as _reset_gate_singleton,
)

__all__ = [
    # Config
    "FlatnessThresholds",
    "BasketRules",
    "LookbackConfig",
    "MarketRegimeConfig",
    "load_regime_config",
    "get_regime_config",
    # Gate
    "RegimeAction",
    "RegimeDecision",
    "AssetMetrics",
    "BasketSnapshot",
    "MarketRegimeGate",
    "get_regime_gate",
]


# ── Test utilities (not part of public API) ────────────────────────────────

def _reset_regime_config() -> None:
    """Reset config singleton (for testing only)."""
    _reset_config_singleton()


def _reset_regime_gate() -> None:
    """Reset gate singleton (for testing only)."""
    _reset_gate_singleton()
