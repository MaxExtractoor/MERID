"""PM feed for crypto realized-vol bands (``Crypto15mIndicatorStack``).

KalshiContinuousTrader keeps its **own** per-asset stacks for bias/trace. This module
maintains **PM-only** stacks updated from ``KalshiTradingAgent._build_snapshot`` spot
prices (at most one synthetic 1m bar per asset per wall-clock minute) so AgentGrid
sizing can read ``vol_band`` / ``vol_size_mult`` without importing CT.

Enable periodic INFO snapshots with ``MERID_CRYPTO_VOL_BANDS_LOG=true``.
"""

from __future__ import annotations

import json
import math
import threading
import time
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.signals.crypto_pm_vol_bridge")

_lock = threading.Lock()
_STACKS: Dict[str, Any] = {}
_LAST_MINUTE_BUCKET: Dict[str, int] = {}
_LAST_CTX: Dict[str, Dict[str, Any]] = {}
_LAST_BAND_LOG_TS: float = 0.0


def _pm_bridge_enabled() -> bool:
    try:
        from merid.settings import settings

        return bool(getattr(settings, "MERID_CRYPTO_PM_VOL_BRIDGE_ENABLED", True))
    except Exception:
        return True


def _bands_log_enabled() -> bool:
    try:
        from merid.settings import settings

        return bool(getattr(settings, "MERID_CRYPTO_VOL_BANDS_LOG", False))
    except Exception:
        return False


def _indicator_config() -> Any:
    from merid.signals.crypto_15m_indicators import IndicatorConfig

    cfg = IndicatorConfig()
    try:
        from merid.settings import settings

        lo = getattr(settings, "MERID_CRYPTO_VOL_LOW_THRESHOLD", None)
        hi = getattr(settings, "MERID_CRYPTO_VOL_HIGH_THRESHOLD", None)
        if lo is not None:
            cfg.vol_low_threshold = float(lo)
        if hi is not None:
            cfg.vol_high_threshold = float(hi)
    except Exception:
        pass
    return cfg


def _classify_vol_band(rv: float, lo: float, hi: float) -> tuple[str, bool]:
    """Match ``Crypto15mIndicatorStack.snapshot`` vol band rules (annualized realized vol)."""
    if rv < lo:
        return "low", False
    if rv > hi:
        return "high", False
    return "mid", True


def _size_mult_for_band(
    band: str,
    matrix_mults: Optional[Dict[str, Optional[float]]] = None,
) -> float:
    if matrix_mults:
        b = (band or "mid").lower()
        if b == "low" and matrix_mults.get("low") is not None:
            return float(matrix_mults["low"])
        if b == "high" and matrix_mults.get("high") is not None:
            return float(matrix_mults["high"])
        if b == "mid" and matrix_mults.get("mid") is not None:
            return float(matrix_mults["mid"])
    try:
        from merid.settings import settings

        m_low = float(getattr(settings, "MERID_CRYPTO_VOL_BAND_LOW_SIZE_MULT", 0.7))
        m_mid = float(getattr(settings, "MERID_CRYPTO_VOL_BAND_MID_SIZE_MULT", 1.0))
        m_high = float(getattr(settings, "MERID_CRYPTO_VOL_BAND_HIGH_SIZE_MULT", 0.4))
    except Exception:
        m_low, m_mid, m_high = 0.7, 1.0, 0.4
    b = (band or "mid").lower()
    if b == "low":
        return m_low
    if b == "high":
        return m_high
    return m_mid


def _get_stack(asset: str) -> Any:
    from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack

    a = asset.upper().strip()
    if a not in _STACKS:
        _STACKS[a] = Crypto15mIndicatorStack(config=_indicator_config())
    return _STACKS[a]


def feed_spot_and_get_context(
    asset: str,
    price: float,
    *,
    now: Optional[float] = None,
    timeframe: Optional[str] = None,
    archetype: str = "directional",
) -> Optional[Dict[str, Any]]:
    """Append at most one bar per minute per asset; return sizing + band context.

    ``crypto_threshold_matrix.yaml`` rows (by ``timeframe`` / ``archetype``) can set:

    - ``vol_low_threshold`` / ``vol_high_threshold`` — band **placement** vs stack defaults
      (one ``Crypto15mIndicatorStack`` per asset; classification is re-done here after
      ``snapshot()`` so agent context can differ without duplicating price deques).
    - ``vol_size_mult_*`` — sizing multipliers per band.
    """
    if not asset or not _pm_bridge_enabled():
        return _LAST_CTX.get((asset or "").upper().strip())

    a = asset.upper().strip()
    t = float(now or time.time())
    bucket = int(t // 60)

    matrix_mults: Optional[Dict[str, Optional[float]]] = None
    matrix_vol_lo: Optional[float] = None
    matrix_vol_hi: Optional[float] = None
    try:
        from merid.prediction.crypto_threshold_matrix import normalize_crypto_timeframe, resolve_merged_row

        tf_key = normalize_crypto_timeframe(timeframe) if timeframe else normalize_crypto_timeframe("15m")
        row = resolve_merged_row(
            asset=a,
            timeframe=tf_key,
            archetype=archetype or "directional",
        )
        lo_m, hi_m, mid_m = row.get("vol_size_mult_low"), row.get("vol_size_mult_high"), row.get("vol_size_mult_mid")
        if lo_m is not None or hi_m is not None or mid_m is not None:
            matrix_mults = {"low": lo_m, "high": hi_m, "mid": mid_m}
        vlo, vhi = row.get("vol_low_threshold"), row.get("vol_high_threshold")
        if vlo is not None:
            matrix_vol_lo = float(vlo)
        if vhi is not None:
            matrix_vol_hi = float(vhi)
    except Exception as exc:
        logger.debug("crypto_pm_vol_bridge matrix row skipped: %s", exc)

    with _lock:
        if not math.isfinite(price) or price <= 0:
            return _LAST_CTX.get(a)

        if _LAST_MINUTE_BUCKET.get(a) != bucket:
            try:
                stack = _get_stack(a)
                stack.update(float(price))
                _LAST_MINUTE_BUCKET[a] = bucket
                snap = stack.snapshot()
                rv = float(snap.realized_vol_annualized)
                cfg_lo = float(stack.cfg.vol_low_threshold)
                cfg_hi = float(stack.cfg.vol_high_threshold)
                eff_lo = matrix_vol_lo if matrix_vol_lo is not None else cfg_lo
                eff_hi = matrix_vol_hi if matrix_vol_hi is not None else cfg_hi
                band, gate_ok = _classify_vol_band(rv, eff_lo, eff_hi)
                _LAST_CTX[a] = {
                    "vol_band": band,
                    "vol_size_mult": _size_mult_for_band(band, matrix_mults),
                    "realized_vol_annualized": rv,
                    "bars_available": int(snap.bars_available),
                    "vol_gate_ok": gate_ok,
                }
            except Exception as exc:
                logger.debug("crypto_pm_vol_bridge update failed %s: %s", a, exc)
        _maybe_log_all_unlocked(t)
        return _LAST_CTX.get(a)


def _maybe_log_all_unlocked(now: float) -> None:
    global _LAST_BAND_LOG_TS
    if not _bands_log_enabled() or not _LAST_CTX:
        return
    if now - _LAST_BAND_LOG_TS < 60.0:
        return
    _LAST_BAND_LOG_TS = now
    payload = {
        "event": "CRYPTO_VOL_BANDS",
        "assets": {k: v for k, v in sorted(_LAST_CTX.items())},
    }
    logger.info("%s", json.dumps(payload, default=str))


def get_cached_pm_vol_context() -> Dict[str, Dict[str, Any]]:
    """Return last computed context per asset (copy for operators/tests)."""
    with _lock:
        return {k: dict(v) for k, v in _LAST_CTX.items()}
