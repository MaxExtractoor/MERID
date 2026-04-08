"""Crypto-specific edge threshold profiles and vol-band sizing for Kalshi PM agents.

Provides:
- ``MERID_CRYPTO_EDGE_PRODUCTION_PROFILE`` env-var selector (``modern`` | ``legacy``).
- ``get_crypto_thresholds(profile)`` — returns per-timeframe min-edge thresholds.
- ``apply_crypto_strategy_thresholds_to_config(config, agent_name, profile)`` — mutates a
  :class:`~merid.prediction.strategy.StrategyConfig` in-place with profile values.
- ``VolBand`` enum + ``classify_vol_band()`` — classifies realised vol into low/mid/high.
- ``vol_band_size_multiplier()`` — returns a size multiplier for a given vol band.
- ``is_crypto_agent()`` — returns True if the agent name or asset list indicates a crypto cell.

Usage::

    from merid.prediction.crypto_thresholds import (
        apply_crypto_strategy_thresholds_to_config,
        classify_vol_band,
        vol_band_size_multiplier,
        is_crypto_agent,
    )
    apply_crypto_strategy_thresholds_to_config(strategy.config, agent_name="BTC_15M")
    band = classify_vol_band(realized_vol_pct=0.045)
    mult = vol_band_size_multiplier(band)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.crypto_thresholds")

# ── Profile selector ────────────────────────────────────────────────────────
# Set MERID_CRYPTO_EDGE_PRODUCTION_PROFILE=modern (default) or =legacy
_PROFILE_ENV = "MERID_CRYPTO_EDGE_PRODUCTION_PROFILE"
_SUPPORTED_PROFILES = frozenset({"modern", "legacy"})

_CRYPTO_AGENT_NAME_TOKENS = frozenset(
    {"btc", "eth", "sol", "xrp", "doge", "crypto", "crypto_15m_mm"}
)
_CRYPTO_ASSETS = frozenset({"BTC", "ETH", "SOL", "XRP", "DOGE"})


@dataclass(frozen=True)
class CryptoThresholds:
    """Min-edge thresholds (probability fractions) for a crypto cell."""
    # Thresholds per :class:`~merid.prediction.strategy.ExpiryPhase`
    min_edge_early: Decimal = Decimal("0.05")
    min_edge_mid: Decimal = Decimal("0.04")
    min_edge_late: Decimal = Decimal("0.03")
    min_edge_terminal: Decimal = Decimal("0.02")
    # Kelly fraction
    kelly_fraction: Decimal = Decimal("0.25")
    # Edge-floor profile name passed to StrategyConfig
    edge_floor_profile: str = "strict"
    # Vol-band thresholds (realised vol as fraction, e.g. 0.02 = 2 %)
    vol_low_threshold: float = 0.02    # below this → LOW band
    vol_high_threshold: float = 0.05   # above this → HIGH band (mid in between)
    # Size multipliers per vol band
    size_mult_low: float = 0.75        # reduce size in quiet/thin markets
    size_mult_mid: float = 1.0
    size_mult_high: float = 0.50       # reduce size in very volatile conditions


# ── Built-in profiles ────────────────────────────────────────────────────────

_MODERN_BASE = CryptoThresholds(
    min_edge_early=Decimal("0.04"),
    min_edge_mid=Decimal("0.03"),
    min_edge_late=Decimal("0.025"),
    min_edge_terminal=Decimal("0.015"),
    kelly_fraction=Decimal("0.25"),
    edge_floor_profile="medium",
    vol_low_threshold=0.015,
    vol_high_threshold=0.04,
    size_mult_low=0.80,
    size_mult_mid=1.0,
    size_mult_high=0.55,
)

_LEGACY_BASE = CryptoThresholds(
    min_edge_early=Decimal("0.05"),
    min_edge_mid=Decimal("0.04"),
    min_edge_late=Decimal("0.03"),
    min_edge_terminal=Decimal("0.02"),
    kelly_fraction=Decimal("0.25"),
    edge_floor_profile="strict",
    vol_low_threshold=0.02,
    vol_high_threshold=0.05,
    size_mult_low=0.75,
    size_mult_mid=1.0,
    size_mult_high=0.50,
)

_PROFILES: Dict[str, CryptoThresholds] = {
    "modern": _MODERN_BASE,
    "legacy": _LEGACY_BASE,
}


def get_active_profile() -> str:
    """Return the active profile name from env (``modern`` | ``legacy``)."""
    raw = os.environ.get(_PROFILE_ENV, "modern").strip().lower()
    if raw not in _SUPPORTED_PROFILES:
        logger.warning(
            "Unsupported %s=%r — falling back to 'modern'. Supported: %s",
            _PROFILE_ENV, raw, sorted(_SUPPORTED_PROFILES),
        )
        return "modern"
    return raw


def get_crypto_thresholds(profile: Optional[str] = None) -> CryptoThresholds:
    """Return :class:`CryptoThresholds` for the given profile.

    Args:
        profile: ``"modern"`` or ``"legacy"``.  If ``None`` the env var
            ``MERID_CRYPTO_EDGE_PRODUCTION_PROFILE`` is consulted (default
            ``"modern"``).

    Returns:
        Immutable :class:`CryptoThresholds` dataclass.
    """
    p = profile or get_active_profile()
    if p not in _PROFILES:
        logger.warning("Unknown crypto threshold profile %r, using 'modern'", p)
        p = "modern"
    return _PROFILES[p]


def apply_crypto_strategy_thresholds_to_config(
    config: object,
    agent_name: str = "",
    assets: Optional[List[str]] = None,
    profile: Optional[str] = None,
) -> bool:
    """Mutate a :class:`~merid.prediction.strategy.StrategyConfig` with crypto thresholds.

    The thresholds are applied only if the agent is identified as a crypto agent
    (via name tokens or asset list).  Non-crypto agents are left unchanged.

    Args:
        config: A :class:`~merid.prediction.strategy.StrategyConfig` instance.
        agent_name: Agent name string (e.g. ``"BTC_15M"`` or ``"CRYPTO_15M_MM"``).
        assets: Optional explicit asset list (``["BTC", "ETH", ...]``).
        profile: Override profile; defaults to env var.

    Returns:
        ``True`` if thresholds were applied, ``False`` if agent was not crypto.
    """
    if not is_crypto_agent(agent_name=agent_name, assets=assets):
        return False

    thresholds = get_crypto_thresholds(profile)

    # Apply to config fields (duck-typed; works for StrategyConfig and any
    # compatible mapping/object).
    try:
        config.min_edge_early = thresholds.min_edge_early  # type: ignore[attr-defined]
        config.min_edge_mid = thresholds.min_edge_mid  # type: ignore[attr-defined]
        config.min_edge_late = thresholds.min_edge_late  # type: ignore[attr-defined]
        config.min_edge_terminal = thresholds.min_edge_terminal  # type: ignore[attr-defined]
        config.kelly_fraction = thresholds.kelly_fraction  # type: ignore[attr-defined]
        config.edge_floor_profile = thresholds.edge_floor_profile  # type: ignore[attr-defined]
    except AttributeError as exc:
        logger.warning("apply_crypto_strategy_thresholds_to_config: config missing field: %s", exc)
        return False

    logger.info(
        "[CRYPTO-THRESH] applied profile=%s agent=%s "
        "min_edge early=%.3f mid=%.3f late=%.3f terminal=%.3f kelly=%.2f floor=%s",
        profile or get_active_profile(),
        agent_name,
        float(thresholds.min_edge_early),
        float(thresholds.min_edge_mid),
        float(thresholds.min_edge_late),
        float(thresholds.min_edge_terminal),
        float(thresholds.kelly_fraction),
        thresholds.edge_floor_profile,
    )
    return True


# ── Vol-band classification ──────────────────────────────────────────────────

class VolBand(str, Enum):
    """Realised-volatility band for size adjustment."""
    LOW = "low"
    MID = "mid"
    HIGH = "high"


def classify_vol_band(
    realized_vol_frac: float,
    thresholds: Optional[CryptoThresholds] = None,
    profile: Optional[str] = None,
) -> VolBand:
    """Classify realised volatility into a :class:`VolBand`.

    Args:
        realized_vol_frac: Annualised (or short-window) vol as a fraction,
            e.g. ``0.035`` for 3.5 %.
        thresholds: Optional explicit :class:`CryptoThresholds` to use for band
            boundaries.  If ``None``, the active profile is loaded.
        profile: Profile name override (ignored if *thresholds* is supplied).

    Returns:
        :class:`VolBand` value.
    """
    t = thresholds or get_crypto_thresholds(profile)
    if realized_vol_frac < t.vol_low_threshold:
        return VolBand.LOW
    if realized_vol_frac > t.vol_high_threshold:
        return VolBand.HIGH
    return VolBand.MID


def vol_band_size_multiplier(
    band: VolBand,
    thresholds: Optional[CryptoThresholds] = None,
    profile: Optional[str] = None,
) -> float:
    """Return the size multiplier for a given :class:`VolBand`.

    Args:
        band: Vol band.
        thresholds: Optional explicit thresholds; loaded from active profile if ``None``.
        profile: Profile override (ignored when *thresholds* is given).

    Returns:
        Float multiplier (0.0 – 2.0 range; 1.0 = no adjustment).
    """
    t = thresholds or get_crypto_thresholds(profile)
    return {
        VolBand.LOW: t.size_mult_low,
        VolBand.MID: t.size_mult_mid,
        VolBand.HIGH: t.size_mult_high,
    }[band]


# ── Crypto agent detection ───────────────────────────────────────────────────

def is_crypto_agent(
    agent_name: str = "",
    assets: Optional[List[str]] = None,
) -> bool:
    """Return ``True`` if the agent is a crypto cell.

    Matches on:
    - Any of ``_CRYPTO_AGENT_NAME_TOKENS`` appearing in the lower-cased agent name.
    - Any asset in *assets* being in ``_CRYPTO_ASSETS``.

    Args:
        agent_name: Agent display name (case-insensitive).
        assets: Optional list of asset symbols.

    Returns:
        ``True`` if the agent is identified as a crypto agent.
    """
    name_lower = agent_name.lower()
    if any(tok in name_lower for tok in _CRYPTO_AGENT_NAME_TOKENS):
        return True
    if assets and any(a.upper() in _CRYPTO_ASSETS for a in assets):
        return True
    return False
