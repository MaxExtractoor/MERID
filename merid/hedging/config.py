"""Hedge config loader — parses ``config/kalshi_crypto_hedging.yaml``.

All dataclasses are frozen to enforce immutability after load.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.hedging.config")

_DEFAULT_CONFIG_PATH = str(
    Path(__file__).resolve().parents[2] / "config" / "kalshi_crypto_hedging.yaml"
)


# ── Dataclasses ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AssetSliceConfig:
    """Per-asset bankroll slice."""

    slice_pct_of_bankroll: float = 0.10
    per_trade_risk_pct_of_slice: float = 1.0
    max_drawdown_pct_of_slice: float = 3.0


@dataclass(frozen=True)
class TimeframeHedgeRule:
    """Per-timeframe hedge parameters (shared across assets)."""

    max_net_exposure_pct_of_slice: float = 10.0
    target_hedge_ratio: float = 0.5
    prefer_same_timeframe: bool = True
    allow_adjacent_horizons: Tuple[str, ...] = ()


@dataclass(frozen=True)
class CrossAssetPairConfig:
    """One cross-asset hedge pair."""

    base: str = "BTC"
    hedge: str = "ETH"


@dataclass(frozen=True)
class HedgeConfig:
    """Top-level hedge configuration — immutable after load."""

    enabled: bool = True
    use_cross_asset_hedging: bool = False
    max_drawdown_pct: float = 40.0

    asset_slices: Dict[str, AssetSliceConfig] = field(default_factory=dict)
    timeframes: Dict[str, TimeframeHedgeRule] = field(default_factory=dict)

    # Cross-asset section
    cross_asset_enabled: bool = False
    cross_asset_max_pair_correlation: float = 0.85
    cross_asset_max_hedge_pct_of_base: float = 0.20
    cross_asset_pairs: Tuple[CrossAssetPairConfig, ...] = ()

    # ── Helpers ────────────────────────────────────────────────────────

    def get_slice(self, asset: str) -> AssetSliceConfig:
        """Return slice config for *asset*, falling back to a conservative default."""
        return self.asset_slices.get(asset.upper(), AssetSliceConfig())

    def get_timeframe_rule(self, tf: str) -> TimeframeHedgeRule:
        """Return hedge rule for *tf*, falling back to a safe default."""
        return self.timeframes.get(tf, TimeframeHedgeRule())

    def slice_value_cents(self, asset: str, bankroll_cents: int) -> float:
        """Absolute slice value in cents for *asset*."""
        s = self.get_slice(asset)
        return bankroll_cents * s.slice_pct_of_bankroll

    def max_net_exposure_cents(self, asset: str, tf: str, bankroll_cents: int) -> float:
        """Absolute max net exposure in cents for one (asset, tf) cell."""
        rule = self.get_timeframe_rule(tf)
        slice_cents = self.slice_value_cents(asset, bankroll_cents)
        return slice_cents * rule.max_net_exposure_pct_of_slice / 100.0


# ── Loader ────────────────────────────────────────────────────────────────


def load_hedge_config(path: Optional[str] = None) -> HedgeConfig:
    """Load hedge config from YAML.  Returns ``HedgeConfig(enabled=False)`` on error."""
    import yaml  # deferred import — yaml not needed at module level

    fpath = path or os.getenv("MERID_HEDGE_CONFIG_PATH", _DEFAULT_CONFIG_PATH)
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("[hedge-config] file not found: %s — hedging disabled", fpath)
        return HedgeConfig(enabled=False)
    except Exception as exc:
        logger.error("[hedge-config] parse error: %s — hedging disabled", exc)
        return HedgeConfig(enabled=False)

    h = raw.get("hedging", {})
    if not h:
        return HedgeConfig(enabled=False)

    # Parse asset slices
    slices: Dict[str, AssetSliceConfig] = {}
    for asset, s in (h.get("asset_slices") or {}).items():
        slices[asset.upper()] = AssetSliceConfig(
            slice_pct_of_bankroll=float(s.get("slice_pct_of_bankroll", 0.10)),
            per_trade_risk_pct_of_slice=float(s.get("per_trade_risk_pct_of_slice", 1.0)),
            max_drawdown_pct_of_slice=float(s.get("max_drawdown_pct_of_slice", 3.0)),
        )

    # Parse timeframe rules
    tf_rules: Dict[str, TimeframeHedgeRule] = {}
    for tf, r in (h.get("timeframes") or {}).items():
        adj = r.get("allow_adjacent_horizons") or []
        tf_rules[str(tf)] = TimeframeHedgeRule(
            max_net_exposure_pct_of_slice=float(r.get("max_net_exposure_pct_of_slice", 10.0)),
            target_hedge_ratio=float(r.get("target_hedge_ratio", 0.5)),
            prefer_same_timeframe=bool(r.get("prefer_same_timeframe", True)),
            allow_adjacent_horizons=tuple(str(a) for a in adj),
        )

    # Parse cross-asset
    ca = h.get("cross_asset") or {}
    pairs = tuple(
        CrossAssetPairConfig(base=str(p.get("base", "")), hedge=str(p.get("hedge", "")))
        for p in (ca.get("pairs") or [])
    )

    return HedgeConfig(
        enabled=bool(h.get("enabled", True)),
        use_cross_asset_hedging=bool(h.get("use_cross_asset_hedging", False)),
        max_drawdown_pct=float(h.get("max_drawdown_pct", 40.0)),
        asset_slices=slices,
        timeframes=tf_rules,
        cross_asset_enabled=bool(ca.get("enabled", False)),
        cross_asset_max_pair_correlation=float(ca.get("max_pair_correlation", 0.85)),
        cross_asset_max_hedge_pct_of_base=float(ca.get("max_cross_hedge_pct_of_base", 0.20)),
        cross_asset_pairs=pairs,
    )


# ── Singleton ─────────────────────────────────────────────────────────────

_hedge_config: Optional[HedgeConfig] = None
_hedge_config_lock = threading.Lock()


def get_hedge_config() -> HedgeConfig:
    """Thread-safe singleton accessor."""
    global _hedge_config
    if _hedge_config is None:
        with _hedge_config_lock:
            if _hedge_config is None:
                _hedge_config = load_hedge_config()
    return _hedge_config


def _reset_hedge_config() -> None:
    """Test helper — clears cached config so next ``get_hedge_config`` reloads."""
    global _hedge_config
    with _hedge_config_lock:
        _hedge_config = None
