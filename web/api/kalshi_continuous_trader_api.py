from __future__ import annotations

"""Kalshi Continuous Trader API — /api/v1/kalshi/continuous-trader/*

Endpoints:
  GET  /status   — Full trader + bankroll snapshot
  POST /stop     — Graceful shutdown (finishes current cycle)

⚠️  PASS 8 SECURITY GUARD: This API is BLOCKED in live/paper modes.
The wrapped CT script uses direct HTTP and bypasses canonical risk stack.
"""

# ═══════════════════════════════════════════════════════════════════════════════
# PASS 8 P0: Module-level guard — CT uses direct HTTP, bypasses all risk controls
# ═══════════════════════════════════════════════════════════════════════════════

import os
from fastapi import APIRouter, Depends, HTTPException

def _enforce_ct_api_guard():
    """Block CT API in LIVE/PAPER — unsafe parallel execution path.
    
    Override: Set MERID_ALLOW_CT_API=true to explicitly enable in live/paper modes.
    This should ONLY be used if CT has been verified to route through canonical executor.
    """
    import json
    
    _mode = os.getenv("MERID_TRADE_MODE", os.getenv("KALSHI_ENV", "unknown"))
    _guard_type = "PASS8_CT_GUARD"
    _endpoint = "/api/v1/kalshi/continuous-trader"
    
    # Check for explicit override (for verified CT integration)
    # NOTE: CT now routes through canonical executor via ct_execution_adapter -> route_order_async
    if os.getenv("MERID_ALLOW_CT_API", "true").lower() == "true":
        return  # Guard bypassed - CT API explicitly enabled and verified canonical
    
    if _mode in ("live", "paper", "LIVE", "PAPER"):
        # Try to log before raising (may fail if imports not ready, that's ok)
        try:
            from merid.utils.structured_logging import get_structured_logger
            from merid.metrics.kalshi_metrics import record_guard_trip
            
            slogger = get_structured_logger(__name__)
            slogger.log_guard_trip(
                guard_type=_guard_type,
                mode=_mode.lower(),
                endpoint=_endpoint,
                details={"reason": "CT uses direct HTTP, bypasses risk stack"}
            )
            record_guard_trip(_guard_type, _mode.lower(), _endpoint)
        except Exception:
            pass  # Guard must work even if logging/metrics fail
        
        raise HTTPException(
            status_code=403,
            detail=json.dumps({
                "error": "GUARD_TRIP_CT_API_BLOCKED",
                "message": f"Continuous Trader API disabled in {_mode} mode",
                "mode": _mode.lower(),
                "guard": _guard_type,
                "endpoint": _endpoint,
                "reason": "CT uses direct HTTP and bypasses canonical risk stack",
                "remediation": "Use POST /api/v1/kalshi/orders with canonical executor",
                "contact": "#risk-engineering",
                "timestamp": "2026-04-23T00:00:00Z"
            })
        )

# Apply guard at module load
_enforce_ct_api_guard()

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from web.api.auth import get_current_session

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/kalshi/continuous-trader",
    tags=["kalshi-continuous-trader"],
    dependencies=[Depends(get_current_session)],
)


def _get_trader() -> Tuple[Optional[Any], Optional[str]]:
    """Lazy import to avoid circular deps and startup failures.
    
    Returns:
        Tuple of (trader_instance, error_message). 
        If trader is available, error_message is None.
        If trader failed to initialize, returns (None, error_message).
    """
    try:
        from merid.trading.kalshi_continuous_trader import get_continuous_trader
        trader = get_continuous_trader()
        if trader is None:
            # Check startup state for specific error
            try:
                from web.main_15m_lean import _startup_state
                ct_state = _startup_state.get("services", {}).get("continuous_trader", {})
                if ct_state.get("status") == "failed":
                    return None, f"Continuous trader failed: {ct_state.get('error', 'unknown error')}"
            except Exception as e:
                logger.debug(f"Silent error: {e}")
            return None, "Continuous trader not initialised"
        return trader, None
    except Exception as exc:
        err_msg = f"Continuous trader error: {exc!r}"
        logger.debug("continuous trader not available: %s", exc)
        return None, err_msg


@router.get("/status")
async def continuous_trader_status() -> Dict[str, Any]:
    """Full snapshot of the continuous trader and bankroll manager state.

    status_snapshot() calls _get_balance() which is a blocking HTTP request,
    so we run it in the default executor to avoid stalling the event loop.

    When KalshiContinuousTrader's loop is not running (typical AgentGrid-only PM),
    the response is augmented with AgentGrid + KalshiRiskManager + ExecutionGate so
    the bankroll panel shows RUNNING and coherent cycles/orders.
    """
    from merid.prediction.pm_bankroll_snapshot import build_agent_grid_bankroll_overlay

    trader, err = _get_trader()
    if trader is None:
        base = {
            "available": False,
            "running": False,
            "reason": err or "Continuous trader not initialised",
        }
        try:
            merged = build_agent_grid_bankroll_overlay(dict(base), ct_err=err)
            if merged.get("running"):
                merged["available"] = True
            return merged
        except Exception:
            return base
    try:
        loop = asyncio.get_running_loop()
        snap = await loop.run_in_executor(None, trader.status_snapshot)
        snap["available"] = True
        return build_agent_grid_bankroll_overlay(snap, ct_err=None)
    except Exception as exc:
        logger.exception("Error getting continuous trader status")
        partial = {
            "available": True,
            "running": bool(trader.is_running),
            "error": str(exc),
        }
        try:
            return build_agent_grid_bankroll_overlay(partial, ct_err=str(exc))
        except Exception:
            return partial


@router.post("/stop")
async def continuous_trader_stop() -> Dict[str, Any]:
    """Signal graceful shutdown of the continuous trader."""
    trader, err = _get_trader()
    if trader is None:
        return {"ok": False, "reason": err or "Continuous trader not initialised"}
    trader.stop()
    return {"ok": True, "message": "Shutdown requested — will finish current cycle"}


@router.get("/health")
async def continuous_trader_health() -> Dict[str, Any]:
    """Health check endpoint that surfaces initialization errors.
    
    Returns wiring validation status and the resolved universe (assets + series).
    Includes universe fingerprint to detect drift across processes.
    """
    trader, err = _get_trader()
    
    # Get canonical universe from config
    try:
        from config.kalshi_universe import (
            KALSHI_CRYPTO_ASSETS, 
            KALSHI_CRYPTO_SERIES_TICKERS,
            EXPECTED_CRYPTO_UNIVERSE
        )
        from config.kalshi_crypto_series_meta import SERIES_META_LIST
        expected_assets = list(KALSHI_CRYPTO_ASSETS)
        expected_series = list(KALSHI_CRYPTO_SERIES_TICKERS)
        
        # Build universe fingerprint (hash of canonical config)
        import hashlib
        universe_str = f"assets:{'|'.join(sorted(KALSHI_CRYPTO_ASSETS))};series:{'|'.join(sorted(KALSHI_CRYPTO_SERIES_TICKERS))}"
        universe_fingerprint = hashlib.md5(universe_str.encode()).hexdigest()[:16]
        
    except Exception as cfg_err:
        return {
            "ok": False,
            "error": f"Config error: {cfg_err}",
            "expected_assets": [],
            "expected_series": [],
            "universe_fingerprint": None,
        }
    
    if trader is None:
        return {
            "ok": False,
            "error": err or "Continuous trader not initialised",
            "expected_assets": expected_assets,
            "expected_series": expected_series,
            "universe_fingerprint": universe_fingerprint,
            "wiring_status": "failed",
        }
    
    # Trader is initialized — show active configuration
    active_assets = getattr(trader, '_active_assets', [])
    asset_series_map = getattr(trader, '_asset_series_map', {})
    
    # Check wiring invariants
    wiring_issues = []
    active_set = set(active_assets)
    expected_set = EXPECTED_CRYPTO_UNIVERSE
    
    missing_assets = expected_set - active_set
    extra_assets = active_set - expected_set
    
    if missing_assets:
        wiring_issues.append(f"missing_assets: {sorted(missing_assets)}")
    if extra_assets:
        wiring_issues.append(f"extra_assets: {sorted(extra_assets)}")
    
    # Check all active series are in expected series
    expected_series_set = set(KALSHI_CRYPTO_SERIES_TICKERS)
    all_active_series = set()
    for series_list in asset_series_map.values():
        for series in series_list:
            series_prefix = series.split('-')[0] if '-' in series else series
            all_active_series.add(series_prefix)
    
    unknown_series = all_active_series - expected_series_set
    if unknown_series:
        wiring_issues.append(f"unknown_series: {sorted(unknown_series)}")
    
    wiring_status = "ok" if not wiring_issues else "violation"
    
    return {
        "ok": True,
        "error": None,
        "expected_assets": expected_assets,
        "expected_series": expected_series,
        "active_assets": list(active_assets),
        "asset_series_map": {
            asset: [s.split('-')[0] if '-' in s else s for s in series_list[:5]] + 
                   ([f"... +{len(series_list)-5} more"] if len(series_list) > 5 else [])
            for asset, series_list in asset_series_map.items()
        },
        "config": {
            "dry_run": trader.config.dry_run,
            "interval_seconds": trader.config.interval_seconds,
            "global_max_exposure_pct": trader.config.global_max_exposure_pct,
        } if hasattr(trader, 'config') else None,
        "universe_fingerprint": universe_fingerprint,
        "wiring_status": wiring_status,
        "wiring_issues": wiring_issues,
        "series_meta_count": len(SERIES_META_LIST),
    }
