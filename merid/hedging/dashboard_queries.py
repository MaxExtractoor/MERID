"""Hedge Effectiveness Dashboard Queries (Task 10)

Query functions for the hedge effectiveness dashboard:
- PnL attribution by hedge strategy
- Effectiveness metrics by asset and timeframe
- Real-time hedge coverage visualization
- Historical hedge performance analysis
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from decimal import Decimal
import logging

# Import configurable constants from exposure module
from merid.hedging.exposure import (
    CRYPTO_BASKET_ASSETS,
    HEDGE_NEUTRAL_THRESHOLD_CENTS,
    MAX_HEDGE_COVERAGE_RATIO,
)

logger = logging.getLogger(__name__)


@dataclass
class HedgeDashboardMetrics:
    """Aggregate metrics for hedge effectiveness dashboard."""
    
    # Time window
    start_time: datetime
    end_time: datetime
    
    # Overall counts
    total_alpha_fills: int = 0
    total_hedge_fills: int = 0
    active_hedges: int = 0
    closed_hedges: int = 0
    
    # PnL (cents)
    gross_alpha_pnl: int = 0
    gross_hedge_pnl: int = 0
    net_pnl: int = 0
    
    # Effectiveness
    hedge_cost_cents: int = 0
    hedge_benefit_cents: int = 0
    effectiveness_ratio: Optional[float] = None
    
    # Coverage
    avg_coverage_ratio: float = 0.0
    fully_hedged_count: int = 0
    partially_hedged_count: int = 0
    unhedged_count: int = 0
    
    # By asset breakdown
    by_asset: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.by_asset is None:
            self.by_asset = {}


def get_hedge_dashboard_metrics(
    fills_ledger: Any,  # KalshiFillsLedger
    pnl_tracker: Any,  # HedgePnLTracker
    hours_lookback: int = 24,
) -> HedgeDashboardMetrics:
    """Get comprehensive hedge effectiveness metrics for dashboard.
    
    Task 10: Main dashboard query aggregating all hedge-related metrics.
    
    Args:
        fills_ledger: KalshiFillsLedger instance
        pnl_tracker: HedgePnLTracker instance
        hours_lookback: Hours of history to include
        
    Returns:
        HedgeDashboardMetrics with full breakdown
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours_lookback)
    
    metrics = HedgeDashboardMetrics(
        start_time=start_time,
        end_time=end_time,
    )
    
    # Get fills from ledger
    alpha_fills = fills_ledger.get_alpha_fills(since=start_time, limit=10000)
    hedge_fills = fills_ledger.get_hedge_fills(since=start_time, limit=10000)
    
    metrics.total_alpha_fills = len(alpha_fills)
    metrics.total_hedge_fills = len(hedge_fills)
    
    # Get PnL metrics
    pnl_metrics = pnl_tracker.get_metrics(lookback_days=1)
    
    metrics.active_hedges = pnl_metrics.active_hedges
    metrics.closed_hedges = pnl_metrics.closed_hedges
    metrics.gross_alpha_pnl = pnl_metrics.total_alpha_pnl
    metrics.gross_hedge_pnl = pnl_metrics.total_hedge_pnl
    metrics.net_pnl = pnl_metrics.total_net_pnl
    metrics.hedge_cost_cents = pnl_metrics.total_cost_of_hedge
    metrics.hedge_benefit_cents = pnl_metrics.total_benefit
    metrics.effectiveness_ratio = pnl_metrics.avg_effectiveness
    
    # Calculate coverage by asset
    asset_exposure: Dict[str, Dict] = {}
    
    for fill in alpha_fills:
        asset = _extract_asset_from_ticker(fill.market_ticker)
        if asset not in asset_exposure:
            asset_exposure[asset] = {"alpha": 0, "hedge": 0, "fills": 0}
        asset_exposure[asset]["alpha"] += fill.notional_usd * 100  # Convert to cents
        asset_exposure[asset]["fills"] += 1
    
    for fill in hedge_fills:
        asset = _extract_asset_from_ticker(fill.market_ticker)
        if asset not in asset_exposure:
            asset_exposure[asset] = {"alpha": 0, "hedge": 0, "fills": 0}
        asset_exposure[asset]["hedge"] += fill.notional_usd * 100
        asset_exposure[asset]["fills"] += 1
    
    # Calculate per-asset coverage
    total_coverage_ratios = []
    for asset, data in asset_exposure.items():
        alpha = data["alpha"]
        hedge = data["hedge"]
        
        if alpha > 0:
            coverage = min(hedge / alpha, MAX_HEDGE_COVERAGE_RATIO)
            total_coverage_ratios.append(coverage)
            
            if coverage >= 1.0:
                metrics.fully_hedged_count += 1
            elif coverage > 0:
                metrics.partially_hedged_count += 1
            else:
                metrics.unhedged_count += 1
            
            metrics.by_asset[asset] = {
                "alpha_exposure_cents": int(alpha),
                "hedge_exposure_cents": int(hedge),
                "coverage_ratio": coverage,
                "coverage_pct": coverage * 100,
                "fill_count": data["fills"],
            }
    
    if total_coverage_ratios:
        metrics.avg_coverage_ratio = sum(total_coverage_ratios) / len(total_coverage_ratios)
    
    logger.debug(
        "[HEDGE-DASHBOARD] %dh metrics: alpha=%d hedge=%d net_pnl=%d¢ coverage=%.1f%%",
        hours_lookback, metrics.total_alpha_fills, metrics.total_hedge_fills,
        metrics.net_pnl, metrics.avg_coverage_ratio * 100
    )
    
    return metrics


def get_hedge_pnl_time_series(
    pnl_tracker: Any,  # HedgePnLTracker
    hours_lookback: int = 24,
    bucket_minutes: int = 15,
) -> List[Dict[str, Any]]:
    """Get time-series of hedge PnL for charting.
    
    Task 10: Provides data for hedge effectiveness trend charts.
    
    Args:
        pnl_tracker: HedgePnLTracker instance
        hours_lookback: Hours of history to include
        bucket_minutes: Time bucket size for aggregation
        
    Returns:
        List of time buckets with PnL metrics
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours_lookback)
    
    # Create time buckets
    buckets = []
    current = start_time
    while current < end_time:
        bucket_end = min(current + timedelta(minutes=bucket_minutes), end_time)
        buckets.append({
            "start": current,
            "end": bucket_end,
            "alpha_pnl": 0,
            "hedge_pnl": 0,
            "net_pnl": 0,
            "hedge_count": 0,
        })
        current = bucket_end
    
    # Assign records to buckets
    for record in pnl_tracker._records.values():
        if record.created_at < start_time:
            continue
        
        for bucket in buckets:
            if bucket["start"] <= record.created_at < bucket["end"]:
                bucket["alpha_pnl"] += record.alpha_pnl_cents
                bucket["hedge_pnl"] += record.hedge_pnl_cents
                bucket["net_pnl"] += record.net_pnl_cents
                bucket["hedge_count"] += 1
                break
    
    # Format output
    return [
        {
            "time": b["start"].isoformat(),
            "alpha_pnl_cents": b["alpha_pnl"],
            "hedge_pnl_cents": b["hedge_pnl"],
            "net_pnl_cents": b["net_pnl"],
            "hedge_count": b["hedge_count"],
        }
        for b in buckets
    ]


def get_hedge_effectiveness_by_reason(
    pnl_tracker: Any,  # HedgePnLTracker
    lookback_days: int = 7,
) -> Dict[str, Dict[str, Any]]:
    """Get hedge effectiveness breakdown by hedge reason/strategy.
    
    Task 10: Compare effectiveness of different hedging strategies.
    
    Args:
        pnl_tracker: HedgePnLTracker instance
        lookback_days: Days of history to include
        
    Returns:
        Dict mapping hedge_reason to effectiveness metrics
    """
    by_reason: Dict[str, Dict] = {}
    
    for record in pnl_tracker._records.values():
        reason = record.hedge_reason
        
        if reason not in by_reason:
            by_reason[reason] = {
                "count": 0,
                "total_alpha_pnl": 0,
                "total_hedge_pnl": 0,
                "total_net_pnl": 0,
                "profitable_count": 0,
                "effectiveness_ratios": [],
            }
        
        data = by_reason[reason]
        data["count"] += 1
        data["total_alpha_pnl"] += record.alpha_pnl_cents
        data["total_hedge_pnl"] += record.hedge_pnl_cents
        data["total_net_pnl"] += record.net_pnl_cents
        
        if record.hedge_pnl_cents > 0:
            data["profitable_count"] += 1
        
        if record.effectiveness_ratio is not None:
            data["effectiveness_ratios"].append(record.effectiveness_ratio)
    
    # Calculate averages
    result = {}
    for reason, data in by_reason.items():
        count = data["count"]
        ratios = data.pop("effectiveness_ratios")
        
        result[reason] = {
            **data,
            "avg_effectiveness": sum(ratios) / len(ratios) if ratios else None,
            "hedge_win_rate": data["profitable_count"] / count if count > 0 else 0,
        }
    
    return result


def get_realtime_hedge_coverage(
    exposure_snapshot: Any,  # ExposureSnapshot
    basket_assets: List[str] = None,
) -> Dict[str, Any]:
    """Get real-time hedge coverage status for dashboard.
    
    Task 10: Live view of current hedge coverage across portfolio.
    
    Args:
        exposure_snapshot: ExposureSnapshot from build_exposure_snapshot()
        basket_assets: List of assets to check (defaults to crypto basket)
        
    Returns:
        Real-time coverage metrics
    """
    if basket_assets is None:
        basket_assets = CRYPTO_BASKET_ASSETS
    
    total_alpha = 0
    total_hedge = 0
    asset_status = {}
    
    for cell in exposure_snapshot.cells.values():
        if cell.asset in basket_assets:
            alpha = cell.alpha_net_delta_cents
            hedge = cell.hedge_net_delta_cents
            
            total_alpha += abs(alpha)
            total_hedge += abs(hedge)
            
            coverage = 0.0
            if alpha != 0:
                # Hedge reduces exposure, so coverage = hedge / alpha
                if (alpha > 0 and hedge < 0) or (alpha < 0 and hedge > 0):
                    coverage = min(abs(hedge) / abs(alpha), MAX_HEDGE_COVERAGE_RATIO)
            
            asset_status[cell.asset] = {
                "alpha_exposure_cents": alpha,
                "hedge_exposure_cents": hedge,
                "coverage_ratio": coverage,
                "coverage_pct": coverage * 100,
                "status": (
                    "fully_hedged" if coverage >= 1.0
                    else "partially_hedged" if coverage > 0
                    else "unhedged"
                ),
            }
    
    overall_coverage = 0.0
    if total_alpha > 0:
        overall_coverage = min(total_hedge / total_alpha, MAX_HEDGE_COVERAGE_RATIO)
    
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_coverage_ratio": overall_coverage,
        "overall_coverage_pct": overall_coverage * 100,
        "total_alpha_exposure_cents": total_alpha,
        "total_hedge_exposure_cents": total_hedge,
        "by_asset": asset_status,
        "hedged_assets": sum(1 for s in asset_status.values() if s["status"] == "fully_hedged"),
        "partial_assets": sum(1 for s in asset_status.values() if s["status"] == "partially_hedged"),
        "unhedged_assets": sum(1 for s in asset_status.values() if s["status"] == "unhedged"),
    }


def _extract_asset_from_ticker(ticker: str) -> str:
    """Extract asset symbol from market ticker.
    
    Task 3 Fix: Dynamic extraction without hardcoded asset map.
    Supports any Kalshi ticker format automatically.
    
    Examples:
        KXBTC-15M -> BTC
        KXETH-26MAR25 -> ETH
        KXLTC-DAILY -> LTC
        KXADA-Weekly -> ADA
    """
    if not ticker:
        return "UNKNOWN"
    
    # Remove KX prefix and extract base asset
    if ticker.startswith("KX"):
        ticker = ticker[2:]
    
    # Task 3 Fix: Use regex for robust extraction (handles any asset code)
    match = re.match(r'^([A-Za-z]+)', ticker)
    if match:
        return match.group(1).upper()
    
    # Fallback: extract before first hyphen
    if "-" in ticker:
        return ticker.split("-")[0].upper()
    
    return "UNKNOWN"


# Dashboard query convenience functions


def format_dashboard_summary(metrics: HedgeDashboardMetrics) -> str:
    """Format dashboard metrics for display/logging."""
    hours = (metrics.end_time - metrics.start_time).total_seconds() / 3600
    
    lines = [
        "=== Hedge Effectiveness Dashboard ===",
        f"Period: Last {hours:.0f}h ({metrics.start_time:%H:%M} - {metrics.end_time:%H:%M} UTC)",
        "",
        "Volume:",
        f"  Alpha Fills: {metrics.total_alpha_fills}",
        f"  Hedge Fills: {metrics.total_hedge_fills} ({metrics.active_hedges} active, {metrics.closed_hedges} closed)",
        "",
        "PnL (cents):",
        f"  Alpha: {metrics.gross_alpha_pnl:+d}",
        f"  Hedge: {metrics.gross_hedge_pnl:+d}",
        f"  Net:   {metrics.net_pnl:+d}",
        "",
        "Effectiveness:",
        f"  Cost of Hedging: {metrics.hedge_cost_cents}¢",
        f"  Benefit: {metrics.hedge_benefit_cents}¢",
        f"  Effectiveness Ratio: {metrics.effectiveness_ratio:.2f}" if metrics.effectiveness_ratio else "  Effectiveness Ratio: N/A",
        "",
        "Coverage:",
        f"  Average: {metrics.avg_coverage_ratio*100:.1f}%",
        f"  Fully Hedged: {metrics.fully_hedged_count}",
        f"  Partially Hedged: {metrics.partially_hedged_count}",
        f"  Unhedged: {metrics.unhedged_count}",
    ]
    
    return "\n".join(lines)
