"""
Risk Pipeline Coordinator — Coordinate old and new risk pipelines with feature flag gating

This module provides the integration point for the new risk projection pipeline,
with feature flag gating to control which pipeline is used.

Usage:
    from merid.event_venues.kalshi.risk_pipeline_coordinator import (
        get_risk_projection,
        run_parallel_diff,
    )
    
    # Get projection (uses new pipeline if feature flag enabled)
    projection = await get_risk_projection()
    
    # Run parallel diff for validation
    diff = await run_parallel_diff()
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from utils.logger import get_logger

from merid.settings import settings
from merid.event_venues.kalshi.risk_projection import (
    RiskProjection,
    RiskProjectionEngine,
)
from merid.event_venues.kalshi.backend_snapshot_fetcher import (
    fetch_and_validate_snapshot,
)
from merid.event_venues.kalshi.parallel_risk_runner import (
    DiffResult,
    ParallelRiskRunner,
)

logger = get_logger("merid.event_venues.kalshi.risk_pipeline_coordinator")


async def get_risk_projection(
    force_new: bool = False,
    kalshi_client: Optional[Any] = None,
) -> RiskProjection:
    """Get risk projection using appropriate pipeline based on feature flag.
    
    This is the main entry point for risk projections. It uses the new pipeline
    if USE_NEW_RISK_PIPELINE is enabled, otherwise falls back to legacy.
    
    Args:
        force_new: Force use of new pipeline regardless of feature flag
        kalshi_client: Optional Kalshi client instance
        
    Returns:
        RiskProjection from appropriate pipeline
    """
    use_new = force_new or settings.USE_NEW_RISK_PIPELINE
    
    if use_new:
        logger.info("[SOURCE=new_pipeline] Using new pure-function risk projection pipeline")
        return await _get_new_projection(kalshi_client)
    else:
        logger.info("[SOURCE=legacy_pipeline] Using legacy risk pipeline (position cache)")
        return await _get_legacy_projection(kalshi_client)


async def _get_new_projection(kalshi_client: Optional[Any] = None) -> RiskProjection:
    """Get projection from new pure-function pipeline."""
    try:
        # Fetch backend snapshot
        snapshot = await fetch_and_validate_snapshot(kalshi_client)
        
        # Compute projection
        engine = RiskProjectionEngine()
        projection = engine.compute_projection(snapshot)
        
        logger.info(
            "[SOURCE=new_pipeline] Projection computed: positions=%d exposure=$%.2f equity=$%.2f",
            projection.position_count,
            projection.total_exposure_dollars,
            projection.equity_dollars,
        )
        
        return projection
        
    except Exception as e:
        logger.error(f"[SOURCE=new_pipeline] Failed to compute projection: {e}")
        # Fallback to legacy on error
        logger.warning("[SOURCE=new_pipeline] Falling back to legacy pipeline due to error")
        return await _get_legacy_projection(kalshi_client)


async def _get_legacy_projection(kalshi_client: Optional[Any] = None) -> RiskProjection:
    """Get projection from legacy pipeline (position cache)."""
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache
        from merid.event_venues.kalshi.risk_projection import (
            BackendPosition,
            RiskProjection,
        )
        from decimal import Decimal
        
        # Get positions from cache
        cache = get_position_cache()
        cached_positions = cache.get_all_positions(validate_freshness=False)
        
        # Convert to BackendPosition format
        positions = []
        for ticker, pos in cached_positions.items():
            backend_pos = BackendPosition(
                ticker=ticker,
                side=pos.side,
                count=pos.contracts,
                avg_price_dollars=Decimal(pos.avg_price_cents) / 100,
                total_cost_dollars=Decimal(pos.contracts * pos.avg_price_cents) / 100,
                unrealized_pnl_dollars=pos.unrealized_pnl_usd,
                realized_pnl_dollars=pos.realized_pnl_usd,
                created_at=pos.last_updated,
            )
            positions.append(backend_pos)
        
        # Get balance
        try:
            if kalshi_client:
                balance_result = await kalshi_client.get_balance_result()
                if balance_result.success:
                    available_usd = balance_result.data.available_usd
                else:
                    available_usd = 0
            else:
                from merid.event_venues.kalshi.client import get_kalshi_client
                client = get_kalshi_client()
                balance_result = await client.get_balance_result()
                if balance_result.success:
                    available_usd = balance_result.data.available_usd
                else:
                    available_usd = 0
        except Exception:
            available_usd = 0
        
        # Compute totals
        total_exposure = sum(p.total_cost_dollars for p in positions)
        unrealized_pnl = sum(p.unrealized_pnl_dollars for p in positions)
        realized_pnl = sum(p.realized_pnl_dollars for p in positions)
        equity = available_usd + unrealized_pnl
        
        projection = RiskProjection(
            positions_by_ticker={p.ticker: p for p in positions},
            total_exposure_dollars=total_exposure,
            unrealized_pnl_dollars=unrealized_pnl,
            realized_pnl_dollars=realized_pnl,
            equity_dollars=equity,
            position_count=len(positions),
            backend_timestamp=cache._last_sync_time if hasattr(cache, '_last_sync_time') else None,
            backend_positions_raw=[p.to_dict() for p in positions],
            backend_balance_raw={"available_usd": str(available_usd), "locked_usd": "0"},
        )
        
        logger.info(
            "[SOURCE=legacy_pipeline] Projection computed: positions=%d exposure=$%.2f equity=$%.2f",
            projection.position_count,
            projection.total_exposure_dollars,
            projection.equity_dollars,
        )
        
        return projection
        
    except Exception as e:
        logger.error(f"[SOURCE=legacy_pipeline] Failed to compute projection: {e}")
        # Return empty projection on failure
        from datetime import datetime, timezone
        return RiskProjection(
            positions_by_ticker={},
            total_exposure_dollars=Decimal("0"),
            unrealized_pnl_dollars=Decimal("0"),
            realized_pnl_dollars=Decimal("0"),
            equity_dollars=Decimal("0"),
            position_count=0,
            backend_timestamp=datetime.now(timezone.utc),
            backend_positions_raw=[],
            backend_balance_raw={"available_usd": "0", "locked_usd": "0"},
        )


async def run_parallel_diff(kalshi_client: Optional[Any] = None) -> DiffResult:
    """Run old and new pipelines in parallel and compare outputs.
    
    This is for validation during the parallel run phase. Once the new pipeline
    is stable and cutover criteria are met, this can be removed.
    
    Args:
        kalshi_client: Optional Kalshi client instance
        
    Returns:
        DiffResult with comparison details
    """
    try:
        # Fetch backend snapshot
        snapshot = await fetch_and_validate_snapshot(kalshi_client)
        
        # Run parallel diff
        runner = ParallelRiskRunner()
        diff = await runner.run_and_diff(snapshot)
        
        logger.info(
            "[SOURCE=parallel_diff] Diff complete: significant=%s count_diff=%d pnl_diff=$%.2f total_runs=%d significant_runs=%d",
            diff.has_significant_discrepancy,
            diff.position_count_diff,
            float(diff.unrealized_pnl_diff_dollars + diff.realized_pnl_diff_dollars),
            runner.diff_count,
            runner.significant_diff_count,
        )
        
        return diff
        
    except Exception as e:
        logger.error(f"[SOURCE=parallel_diff] Failed to run parallel diff: {e}")
        raise


def get_pipeline_status() -> Dict[str, Any]:
    """Get current pipeline status for monitoring.
    
    Returns:
        Dict with pipeline status info
    """
    return {
        "use_new_pipeline": settings.USE_NEW_RISK_PIPELINE,
        "pipeline_type": "new" if settings.USE_NEW_RISK_PIPELINE else "legacy",
        "feature_flag": "USE_NEW_RISK_PIPELINE",
        "cutover_ready": False,  # Will be True after validation
    }
