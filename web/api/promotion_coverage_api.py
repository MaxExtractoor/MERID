"""Promotion Coverage Diagnostics API.

Endpoints:
  GET /api/v1/crypto/promotion-coverage   — Asset × timeframe coverage matrix
  GET /api/v1/crypto/promotion-status     — Full PromotionEngine status for crypto

These endpoints expose PromotionEngine state **only for crypto** (never for
non-crypto domains).  Querying them for non-crypto assets raises an explicit
error rather than silently falling back to BTC-only logic.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from utils.logger import get_logger

logger = get_logger("web.api.promotion_coverage_api")

router = APIRouter(
    prefix="/api/v1/crypto",
    tags=["promotion-coverage"],
)


def _get_engine():
    from merid.risk.promotion_engine import get_promotion_engine
    return get_promotion_engine()


def _get_supported():
    from merid.risk.btc_promotion_config import SUPPORTED_ASSETS, SUPPORTED_TIMEFRAMES
    return SUPPORTED_ASSETS, SUPPORTED_TIMEFRAMES


@router.get("/promotion-coverage")
async def get_promotion_coverage() -> Dict[str, Any]:
    """
    Return the full asset × timeframe coverage matrix for the current
    PromotionEngine phase.

    Each cell reports:
      - unlocked: True when both the asset AND the timeframe are unlocked
        by the current phase
      - asset_unlocked: whether the asset alone is unlocked
      - timeframe_unlocked: whether the timeframe alone is unlocked

    Operators can use this to spot gaps (e.g. ETH not showing at 4h) at a
    glance before filing a bug.
    """
    try:
        engine = _get_engine()
        supported_assets, supported_timeframes = _get_supported()
        matrix = engine.get_coverage_matrix()

        # Build summary counts per asset
        asset_summaries: Dict[str, Any] = {}
        for asset in supported_assets:
            unlocked_tfs = [
                tf for tf in supported_timeframes
                if matrix.get(asset, {}).get(tf, {}).get("unlocked", False)
            ]
            asset_summaries[asset] = {
                "unlocked_timeframes": unlocked_tfs,
                "unlocked_count": len(unlocked_tfs),
                "total_timeframes": len(supported_timeframes),
            }

        return {
            "current_phase": engine.current_phase.name,
            "supported_assets": list(supported_assets),
            "supported_timeframes": list(supported_timeframes),
            "matrix": matrix,
            "asset_summaries": asset_summaries,
            "total_unlocked_combinations": sum(
                1
                for asset in supported_assets
                for tf in supported_timeframes
                if matrix.get(asset, {}).get(tf, {}).get("unlocked", False)
            ),
            "total_combinations": len(supported_assets) * len(supported_timeframes),
        }
    except Exception as exc:
        logger.error("promotion_coverage failed: %s", exc)
        return {
            "current_phase": "unknown",
            "supported_assets": [],
            "supported_timeframes": [],
            "matrix": {},
            "asset_summaries": {},
            "total_unlocked_combinations": 0,
            "total_combinations": 0,
            "error": str(exc),
        }


@router.get("/promotion-status")
async def get_crypto_promotion_status(
    asset: str = Query(..., description="Crypto asset: BTC, ETH, SOL, XRP, DOGE"),
    timeframe: str = Query(..., description="Timeframe: 15m, 1h, 4h, 1d"),
) -> Dict[str, Any]:
    """
    Return PromotionEngine status for a specific (asset, timeframe) combination.

    Returns 400 if the asset or timeframe is not in the supported canonical set.
    This endpoint is crypto-only; it never falls back to BTC-only logic for
    unknown assets.
    """
    try:
        engine = _get_engine()
        # Validate inputs — fail fast instead of silently defaulting to BTC
        engine.assert_combination_supported(asset, timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("promotion_status engine init failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"PromotionEngine unavailable: {exc}") from exc

    return {
        "asset": asset,
        "timeframe": timeframe,
        "current_phase": engine.current_phase.name,
        "asset_unlocked": engine.is_asset_unlocked(asset),
        "timeframe_unlocked": engine.is_timeframe_unlocked(timeframe),
        "combination_unlocked": engine.is_asset_unlocked(asset) and engine.is_timeframe_unlocked(timeframe),
        "can_go_live": engine.can_go_live(),
        "caps": engine.get_caps(equity=0.0),  # equity=0 for display; callers supply real equity
        "last_eval": (
            engine._last_eval.isoformat() if engine._last_eval else None
        ),
    }
