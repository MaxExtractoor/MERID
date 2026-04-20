"""Market Regime Config — parses ``config/market_regime.yaml``.

All dataclasses are frozen to enforce immutability after load.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.market_regime.config")

_DEFAULT_CONFIG_PATH = str(
    Path(__file__).resolve().parents[2] / "config" / "market_regime.yaml"
)


# ── Dataclasses ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FlatnessThresholds:
    """Thresholds for determining if a single asset is "flat"."""

    max_abs_return_pct: float = 0.75  # |return| < 0.75% → flat
    min_atr_pct: float = 0.35         # ATR% < 0.35% → flat
    min_volume_ratio: float = 0.80    # vol / avg_vol < 0.8 → flat


@dataclass(frozen=True)
class BasketRules:
    """Basket-level aggregation rules.

    block_if_flat_count_gte: Block new entries when N or more assets are flat
    reduce_if_flat_count_gte: Reduce position size when N or more assets are flat
    """

    block_if_flat_count_gte: int = 4   # 4 of 5 flat → block
    reduce_if_flat_count_gte: int = 3  # 3 of 5 flat → reduce


@dataclass(frozen=True)
class LookbackConfig:
    """Lookback period for regime detection."""

    bar_interval: str = "15m"
    bars: int = 16  # 16 × 15m = 4 hours of data


@dataclass(frozen=True)
class TrendConfirmation:
    """Optional trend confirmation filters (ADX, breakout)."""

    adx_min: Optional[float] = 18.0
    breakout_range_pct_min: Optional[float] = 1.2


@dataclass(frozen=True)
class MarketRegimeConfig:
    """Top-level market regime configuration — immutable after load."""

    enabled: bool = True
    universe: Tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP", "DOGE")
    lookback: LookbackConfig = field(default_factory=LookbackConfig)
    flatness: FlatnessThresholds = field(default_factory=FlatnessThresholds)
    basket_rules: BasketRules = field(default_factory=BasketRules)
    trend_confirmation: TrendConfirmation = field(default_factory=TrendConfirmation)
    shadow_mode: bool = False  # If True: log only, don't block

    def __post_init__(self):
        # Validate universe is not empty
        if not self.universe:
            object.__setattr__(self, "enabled", False)


# ── Loader ────────────────────────────────────────────────────────────────


def load_regime_config(path: Optional[str] = None) -> MarketRegimeConfig:
    """Load market regime config from YAML. Returns disabled config on error."""
    import yaml  # deferred import

    fpath = path or os.getenv("MERID_MARKET_REGIME_CONFIG_PATH", _DEFAULT_CONFIG_PATH)
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("[market-regime-config] file not found: %s — using defaults", fpath)
        return MarketRegimeConfig()
    except Exception as exc:
        logger.error("[market-regime-config] parse error: %s — using defaults", exc)
        return MarketRegimeConfig()

    mr = raw.get("market_regime_gate", {})
    if not mr:
        return MarketRegimeConfig(enabled=False)

    # Parse lookback
    lookback_raw = mr.get("lookback", {})
    lookback = LookbackConfig(
        bar_interval=str(lookback_raw.get("bar_interval", "15m")),
        bars=int(lookback_raw.get("bars", 16)),
    )

    # Parse flatness thresholds
    flatness_raw = mr.get("flatness", {})
    flatness = FlatnessThresholds(
        max_abs_return_pct=float(flatness_raw.get("max_abs_return_pct", 0.75)),
        min_atr_pct=float(flatness_raw.get("min_atr_pct", 0.35)),
        min_volume_ratio=float(flatness_raw.get("min_volume_ratio", 0.80)),
    )

    # Parse basket rules
    basket_raw = mr.get("basket_rules", {})
    basket_rules = BasketRules(
        block_if_flat_count_gte=int(basket_raw.get("block_if_flat_count_gte", 4)),
        reduce_if_flat_count_gte=int(basket_raw.get("reduce_if_flat_count_gte", 3)),
    )

    # Parse trend confirmation
    trend_raw = mr.get("trend_confirmation", {})
    adx_min = trend_raw.get("adx_min")
    breakout_min = trend_raw.get("breakout_range_pct_min")
    trend_confirmation = TrendConfirmation(
        adx_min=float(adx_min) if adx_min is not None else None,
        breakout_range_pct_min=float(breakout_min) if breakout_min is not None else None,
    )

    # Parse universe
    universe_raw = mr.get("universe", ["BTC", "ETH", "SOL", "XRP", "DOGE"])
    universe = tuple(str(u).upper() for u in universe_raw)

    return MarketRegimeConfig(
        enabled=bool(mr.get("enabled", True)),
        universe=universe,
        lookback=lookback,
        flatness=flatness,
        basket_rules=basket_rules,
        trend_confirmation=trend_confirmation,
        shadow_mode=bool(mr.get("shadow_mode", False)),
    )


# ── Singleton ─────────────────────────────────────────────────────────────

_regime_config: Optional[MarketRegimeConfig] = None
_regime_config_lock = threading.Lock()


def get_regime_config() -> MarketRegimeConfig:
    """Thread-safe singleton accessor."""
    global _regime_config
    if _regime_config is None:
        with _regime_config_lock:
            if _regime_config is None:
                _regime_config = load_regime_config()
    return _regime_config


def _reset_regime_config() -> None:
    """Test helper — clears cached config so next ``get_regime_config`` reloads."""
    global _regime_config
    with _regime_config_lock:
        _regime_config = None
