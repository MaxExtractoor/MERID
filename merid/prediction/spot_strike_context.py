"""Spot vs Kalshi strike — resolution, distance metrics, trace logging, optional veto.

Asset Resolution Rules (CRITICAL for macro vs crypto separation):
- ``resolve_asset_for_snapshot()`` infers asset from ticker using ``infer_asset_from_kalshi_market_ticker()``.
- For crypto tickers (KXBTC, KXETH, KXSOL, KXXRP, KXDOGE): Returns the inferred crypto asset.
- For macro tickers (KXFED, KXFEDDECISION, KXECON-*): Returns "" (empty string), NOT config_assets[0].
- This prevents macro markets from being incorrectly tagged with crypto assets.
- Use ``is_crypto_market_ticker()`` and ``get_market_category()`` for explicit category detection.

Environment (all optional; defaults in code are fallbacks only):

- ``MERID_PM_SPOT_STRIKE_TRACE`` / ``MERID_PM_SPOT_STRIKE_TRACE_EVERY_N`` — ``[CRYPTO_SPOT_STRIKE]`` JSON lines.
- ``MERID_PM_SPOT_STRIKE_WARN_ABS_DIST_PCT`` — warn when ``|dist_pct|`` exceeds (fraction, default 0.85).
- ``MERID_PM_SPOT_STRIKE_VETO_TRADES`` / ``MERID_PM_SPOT_STRIKE_VETO_ABS_DIST_PCT`` — optional ``NO_ACTION`` before archetypes.
- ``MERID_PM_SIGNAL_INCLUDE_SPOT_STRIKE`` — ``[PM_SIGNAL]`` includes ``spot``, ``strike``, ``dist_frac`` (same as ``distance_to_strike_pct``: (spot−strike)/strike), ``dist_pct_pct`` (×100 for display), ``spot_strike_basis`` (``ok`` / ``missing_spot`` / …).
- Spot freshness for ``PredictionMarketModel.get_spot_price``: ``MERID_PM_MAX_SPOT_AGE_SECONDS`` (in ``model.py``).
- Spot–distance scaling in ``compute_edge``: ``MERID_PM_SPOT_DIST_PROB_SCALE`` (in ``model.py``).
- ``MERID_PM_CYCLE_TRACE_CONSENSUS_DETAIL`` — append ``consensus_hold_by_reason=`` to ``[PM_CYCLE_TRACE]`` (default on).
"""

from __future__ import annotations

import json
import os
import threading
from decimal import Decimal
from typing import Any, Dict, Optional, Tuple

from utils.logger import get_logger

# Import invariant checker for production logging
from merid.validation.spot_strike_distance_invariants import (
    SpotStrikeDistanceInvariantChecker,
)

logger = get_logger("merid.prediction.spot_strike")

# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection
_trace_counters: Dict[str, int] = {}


def spot_strike_trace_enabled() -> bool:
    return os.getenv("MERID_PM_SPOT_STRIKE_TRACE", "").lower() in (
        "1", "true", "yes", "on",
    )


def spot_strike_trace_every_n() -> int:
    try:
        n = int(os.getenv("MERID_PM_SPOT_STRIKE_TRACE_EVERY_N", "1"))
        return max(1, n)
    except ValueError:
        return 1


def _trace_key(agent_name: str, market_id: str) -> str:
    return f"{agent_name}|{market_id}"


def should_emit_trace_line(agent_name: str, market_id: str) -> bool:
    if not spot_strike_trace_enabled():
        return False
    every = spot_strike_trace_every_n()
    if every <= 1:
        return True
    with _trace_lock:
        k = _trace_key(agent_name, market_id)
        _trace_counters[k] = _trace_counters.get(k, 0) + 1
        return _trace_counters[k] % every == 0


def resolve_asset_for_snapshot(
    config_assets: list,
    market_id: str,
) -> str:
    """Resolve spot asset for this market.

    Prefer Kalshi ticker inference so multi-asset agents (e.g. BTC first in config)
    still use ETH/SOL spot on KXETH-/KXSOL- markets.

    IMPORTANT: For macro/non-crypto tickers (e.g., KXFED-*), returns "" instead of
    falling back to config_assets[0]. This prevents macro markets from being
    incorrectly tagged with crypto assets and sent to crypto-only strike selector.

    Asset resolution rules:
    - Crypto tickers (KXBTC, KXETH, KXSOL, KXXRP, KXDOGE): Return inferred asset
    - Macro tickers (KXFED, KXFEDDECISION, etc.): Return "" (empty string)
    - Unknown/non-crypto tickers: Return "" (empty string)
    - Only fall back to config_assets[0] if explicitly requested via config
    """
    try:
        from config.kalshi_crypto_series_meta import infer_asset_from_kalshi_market_ticker

        a = infer_asset_from_kalshi_market_ticker(market_id)
        if a:
            return str(a).upper()
    except Exception:
        pass

    # For macro/non-crypto tickers, return empty string instead of falling back
    # to config_assets[0]. This prevents incorrect asset assignment for macro markets.
    # Examples: KXFED-27APR-T4.25, KXFEDDECISION-*, KXECON-* should all return "".
    return ""


def resolve_timeframe_for_snapshot(
    config_timeframes: list,
    market_id: str,
) -> str:
    """Prefer timeframe inferred from ticker so 15m vs 1h matches the actual market."""
    try:
        from config.kalshi_crypto_series_meta import infer_asset_timeframe_from_ticker

        prefix = market_id.split("-")[0].upper() if market_id and "-" in market_id else (market_id or "").upper()
        _a, tf = infer_asset_timeframe_from_ticker(prefix)
        if tf and tf != "UNK":
            return str(tf)
    except Exception:
        pass
    if config_timeframes and config_timeframes[0]:
        return str(config_timeframes[0])
    return "UNK"


def is_crypto_market_ticker(ticker: str) -> bool:
    """Return True if ticker is a recognized Kalshi crypto market.

    Used for market category filtering to route crypto vs macro markets
to appropriate agents.

    Args:
        ticker: Kalshi market ticker (e.g., "KXBTC-...", "KXFED-...")

    Returns:
        True for crypto tickers (KXBTC, KXETH, KXSOL, KXXRP, KXDOGE)
        False for macro tickers (KXFED, KXFEDDECISION, etc.)
    """
    if not ticker:
        return False
    upper = ticker.strip().upper()
    return any(
        upper.startswith(prefix)
        for prefix in ("KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE")
    )


def get_market_category(ticker: str) -> str:
    """Determine market category for a ticker.

    Args:
        ticker: Kalshi market ticker

    Returns:
        "crypto" for crypto markets, "macro" for macro markets, "unknown" otherwise
    """
    if is_crypto_market_ticker(ticker):
        return "crypto"
    if not ticker:
        return "unknown"
    upper = ticker.strip().upper()
    # Macro market prefixes
    if any(upper.startswith(p) for p in ("KXFED", "KXECON")):
        return "macro"
    return "unknown"


def distance_to_strike_pct(
    spot: Decimal,
    strike: Optional[float],
) -> Optional[Decimal]:
    if strike is None or float(strike) == 0.0:
        return None
    s = Decimal(str(spot))
    k = Decimal(str(strike))
    return ((s - k) / k).quantize(Decimal("0.0001"))


def warn_abs_dist_pct() -> float:
    try:
        return float(os.getenv("MERID_PM_SPOT_STRIKE_WARN_ABS_DIST_PCT", "0.85"))
    except ValueError:
        return 0.85


def veto_trades_enabled() -> bool:
    return os.getenv("MERID_PM_SPOT_STRIKE_VETO_TRADES", "").lower() in (
        "1", "true", "yes", "on",
    )


def veto_abs_dist_pct() -> float:
    try:
        return float(os.getenv("MERID_PM_SPOT_STRIKE_VETO_ABS_DIST_PCT", "1.50"))
    except ValueError:
        return 1.50


def evaluate_spot_strike_anomaly(
    dist_pct: Optional[Decimal],
    *,
    matrix_hard_veto: bool = False,
) -> Tuple[bool, bool, str]:
    """Return (warned, veto, message).

    ``dist_pct`` is (spot-strike)/strike; compare absolute value to bounds.
    When ``matrix_hard_veto`` is True (from ``crypto_threshold_matrix.yaml``), apply the same
    veto threshold as ``MERID_PM_SPOT_STRIKE_VETO_TRADES`` without requiring that env flag.
    """
    if dist_pct is None:
        return False, False, ""
    try:
        ad = abs(float(dist_pct))
    except (TypeError, ValueError):
        return False, False, ""
    w = warn_abs_dist_pct()
    msg = ""
    warned = False
    if ad >= w:
        warned = True
        msg = f"|dist|={ad:.4f} >= warn {w:.4f}"
    veto = False
    v_thresh = veto_abs_dist_pct()
    if (veto_trades_enabled() or matrix_hard_veto) and ad >= v_thresh:
        veto = True
        msg = f"|dist|={ad:.4f} >= veto {v_thresh:.4f}"
    return warned, veto, msg


def log_crypto_spot_strike(
    *,
    agent_name: str,
    market_id: str,
    asset: str,
    timeframe: str,
    spot: Optional[Decimal],
    strike: Optional[float],
    dist_pct: Optional[Decimal],
    net_edge: Optional[float],
    phase: Optional[str],
    archetype: str = "",
) -> None:
    if not should_emit_trace_line(agent_name, market_id):
        return
    
    # Emit structured SPOT-STRIKE invariant log for production suite parsing
    if spot is not None and strike is not None:
        spot_float = float(spot)
        strike_float = float(strike)
        trade_emitted = net_edge is not None and net_edge > 0
        logger.info(
            "SPOT-STRIKE: spot=%.2f strike=%.2f trade=%s market=%s",
            spot_float, strike_float, str(trade_emitted).lower(), market_id
        )
    payload: Dict[str, Any] = {
        "agent": agent_name,
        "asset": asset,
        "timeframe": timeframe,
        "market_id": market_id,
        "spot": str(spot) if spot is not None else None,
        "strike": strike,
        "basis_or_dist_pct": str(dist_pct) if dist_pct is not None else None,
        "net_edge": net_edge,
        "phase": phase,
        "archetype": archetype or "",
    }
    logger.info("[CRYPTO_SPOT_STRIKE] %s", json.dumps(payload, default=str, sort_keys=True))


def log_spot_out_of_range(
    *,
    asset: str,
    market_id: str,
    spot: Optional[Decimal],
    strike: Optional[float],
    detail: str,
    timeframe: str = "",
    distance_to_strike_pct: Optional[Decimal] = None,
) -> None:
    """Warn-only path: does not block trading unless ``MERID_PM_SPOT_STRIKE_VETO_TRADES`` is set."""
    _dist = str(distance_to_strike_pct) if distance_to_strike_pct is not None else "—"
    _tf = timeframe or "—"
    logger.warning(
        "[CRYPTO-SPOT-OUT-OF-RANGE] asset=%s timeframe=%s market_id=%s spot=%s strike=%s "
        "dist_pct=%s %s",
        asset,
        _tf,
        market_id,
        spot,
        strike,
        _dist,
        detail,
    )
