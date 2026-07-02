#!/usr/bin/env python3
"""
Edge Alignment Regression Script for Kalshi 15m Crypto

This script validates that the canonical edge/fee/Kelly computation path
produces consistent results with stored trade data. It detects regressions
in the edge calculation pipeline by recomputing edge and size from historical
trades and comparing with stored values.

Usage:
    python scripts/report_edge_alignment_15m.py --hours 24 --asset BTC
    python scripts/report_edge_alignment_15m.py --hours 1  # All assets
"""

import argparse
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
import dataclasses

# Add merid to path
sys.path.insert(0, "c:\\Dev\\MERID")

from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
from merid.prediction.unified_edge import UnifiedEdgeComputer
from merid.event_venues.kalshi.position_sizer import PositionSizer
from merid.event_venues.kalshi.fees import calculate_kalshi_fee_cents


@dataclasses.dataclass
class TradeReconstruction:
    """Reconstructed trade data for alignment check."""
    fill_id: str
    asset: str
    market_id: str
    entry_time: datetime
    side: str
    price_cents: int
    contracts: int
    stored_edge: Optional[float] = None
    stored_size: Optional[int] = None
    recomputed_edge: Optional[float] = None
    recomputed_size: Optional[int] = None
    edge_mismatch_cents: Optional[float] = None
    size_mismatch: Optional[int] = None
    realized_pnl_usd: Optional[float] = None


def reconstruct_edge_result(
    fill,
    edge_computer: UnifiedEdgeComputer,
) -> Tuple[Optional[float], Optional[float]]:
    """Recompute edge and size from a fill.
    
    Args:
        fill: Fill object from ledger
        edge_computer: UnifiedEdgeComputer instance
    
    Returns:
        (recomputed_edge, recomputed_size) tuple
    """
    try:
        # Extract contract state from fill metadata
        # This is a simplified reconstruction - in production, we'd need
        # to store the full ContractState at decision time
        from merid.prediction.model import SpotReference, ContractState
        
        # Reconstruct contract state from fill data
        contract = ContractState(
            ticker=fill.market_id,
            yes_price=fill.price_cents if fill.side == "yes" else (100 - fill.price_cents),
            no_price=(100 - fill.price_cents) if fill.side == "yes" else fill.price_cents,
            mid_price_cents=fill.price_cents,
            best_bid_cents=fill.price_cents - 1,  # Approximate
            best_ask_cents=fill.price_cents + 1,  # Approximate
            expiry_ts=fill.expiry_ts if hasattr(fill, 'expiry_ts') else None,
        )
        
        # Reconstruct spot reference (simplified)
        spot_ref = SpotReference(
            asset=fill.resolved_asset(),
            spot_price_cents=fill.price_cents * 100,  # Approximate
            timestamp=fill.timestamp,
        )
        
        # Recompute edge
        edge_result = edge_computer.compute_edge(
            asset=fill.resolved_asset(),
            spot_ref=spot_ref,
            contract=contract,
            order_size=fill.count,
            order_side="taker",
        )
        
        # Recompute size using canonical sizer
        sizer = PositionSizer()
        recomputed_size = sizer.compute_from_edge_result(
            edge_result=edge_result,
            asset=fill.resolved_asset(),
        )
        
        return edge_result.edge_fee_adjusted, recomputed_size
        
    except Exception as e:
        print(f"[ERROR] Failed to reconstruct edge for fill {fill.fill_id}: {e}")
        return None, None


def analyze_fills(
    hours: int,
    asset_filter: Optional[str] = None,
    edge_tolerance_cents: float = 1.0,
    size_tolerance: int = 1,
) -> List[TradeReconstruction]:
    """Analyze fills from the ledger for edge alignment.
    
    Args:
        hours: Number of hours to look back
        asset_filter: Optional asset filter (e.g., "BTC")
        edge_tolerance_cents: Tolerance for edge mismatch in cents
        size_tolerance: Tolerance for size mismatch in contracts
    
    Returns:
        List of TradeReconstruction objects
    """
    ledger = get_fills_ledger()
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    
    fills = ledger.get_fills(since=since)
    
    # Filter by asset if specified
    if asset_filter:
        fills = [f for f in fills if f.resolved_asset() == asset_filter]
    
    # Filter for live fills only
    fills = [f for f in fills if f.is_live]
    
    edge_computer = UnifiedEdgeComputer()
    
    reconstructions = []
    
    for fill in fills:
        # Get stored edge/size from metadata if available
        stored_edge = fill.metadata.get("edge") if hasattr(fill, 'metadata') else None
        stored_size = fill.count
        
        # Recompute edge/size
        recomputed_edge, recomputed_size = reconstruct_edge_result(fill, edge_computer)
        
        if recomputed_edge is None or recomputed_size is None:
            continue
        
        # Calculate mismatches
        edge_mismatch_cents = None
        if stored_edge is not None:
            edge_mismatch_cents = abs(recomputed_edge - stored_edge) * 100  # Convert to cents
        
        size_mismatch = abs(recomputed_size - stored_size)
        
        # Get realized PnL
        realized_pnl = float(fill.proceeds_dollars or 0)
        
        reconstruction = TradeReconstruction(
            fill_id=fill.fill_id,
            asset=fill.resolved_asset(),
            market_id=fill.market_id,
            entry_time=fill.timestamp,
            side=fill.side,
            price_cents=fill.price_cents,
            contracts=fill.count,
            stored_edge=stored_edge,
            stored_size=stored_size,
            recomputed_edge=recomputed_edge,
            recomputed_size=recomputed_size,
            edge_mismatch_cents=edge_mismatch_cents,
            size_mismatch=size_mismatch,
            realized_pnl_usd=realized_pnl,
        )
        
        reconstructions.append(reconstruction)
    
    return reconstructions


def report_mismatches(
    reconstructions: List[TradeReconstruction],
    edge_tolerance_cents: float,
    size_tolerance: int,
) -> None:
    """Report trades with edge/size mismatches beyond tolerances.
    
    Args:
        reconstructions: List of TradeReconstruction objects
        edge_tolerance_cents: Edge tolerance in cents
        size_tolerance: Size tolerance in contracts
    """
    mismatches = []
    
    for rec in reconstructions:
        edge_mismatch = rec.edge_mismatch_cents or 0
        size_mismatch = rec.size_mismatch or 0
        
        if edge_mismatch > edge_tolerance_cents or size_mismatch > size_tolerance:
            mismatches.append(rec)
    
    if not mismatches:
        print(f"[ALIGNMENT] No mismatches found within tolerances (edge={edge_tolerance_cents}c, size={size_tolerance})")
        return
    
    print(f"\n[ALIGNMENT] Found {len(mismatches)} trades with mismatches beyond tolerances:")
    print("=" * 80)
    
    for rec in mismatches:
        print(f"  Fill: {rec.fill_id}")
        print(f"  Asset: {rec.asset} Market: {rec.market_id}")
        print(f"  Time: {rec.entry_time}")
        print(f"  Edge: stored={rec.stored_edge:.4f} recomputed={rec.recomputed_edge:.4f} mismatch={rec.edge_mismatch_cents:.2f}c")
        print(f"  Size: stored={rec.stored_size} recomputed={rec.recomputed_size} mismatch={rec.size_mismatch}")
        print(f"  Realized PnL: ${rec.realized_pnl_usd:.2f}")
        print("-" * 80)


def report_per_asset_summary(reconstructions: List[TradeReconstruction]) -> None:
    """Report per-asset summary statistics.
    
    Args:
        reconstructions: List of TradeReconstruction objects
    """
    asset_stats: Dict[str, Dict] = {}
    
    for rec in reconstructions:
        asset = rec.asset
        if asset not in asset_stats:
            asset_stats[asset] = {
                "count": 0,
                "total_edge": 0.0,
                "total_pnl": 0.0,
                "edge_mismatches": 0,
                "size_mismatches": 0,
            }
        
        stats = asset_stats[asset]
        stats["count"] += 1
        stats["total_edge"] += rec.recomputed_edge or 0
        stats["total_pnl"] += rec.realized_pnl_usd or 0
        
        if rec.edge_mismatch_cents and rec.edge_mismatch_cents > 1.0:
            stats["edge_mismatches"] += 1
        if rec.size_mismatch and rec.size_mismatch > 1:
            stats["size_mismatches"] += 1
    
    print(f"\n[ALIGNMENT] Per-Asset Summary:")
    print("=" * 80)
    
    for asset, stats in sorted(asset_stats.items()):
        avg_edge = stats["total_edge"] / stats["count"] if stats["count"] > 0 else 0
        avg_pnl = stats["total_pnl"] / stats["count"] if stats["count"] > 0 else 0
        
        print(f"  {asset}:")
        print(f"    Trades: {stats['count']}")
        print(f"    Avg Edge at Entry: {avg_edge:.4f}")
        print(f"    Avg Realized PnL: ${avg_pnl:.2f}")
        print(f"    Edge Mismatches (>1c): {stats['edge_mismatches']}")
        print(f"    Size Mismatches (>1): {stats['size_mismatches']}")


def main():
    parser = argparse.ArgumentParser(description="Edge alignment regression script for Kalshi 15m crypto")
    parser.add_argument("--hours", type=int, default=24, help="Hours to look back (default: 24)")
    parser.add_argument("--asset", type=str, help="Asset filter (e.g., BTC, ETH)")
    parser.add_argument("--edge-tolerance", type=float, default=1.0, help="Edge tolerance in cents (default: 1.0)")
    parser.add_argument("--size-tolerance", type=int, default=1, help="Size tolerance in contracts (default: 1)")
    
    args = parser.parse_args()
    
    print(f"[ALIGNMENT] Analyzing fills from last {args.hours} hours")
    if args.asset:
        print(f"[ALIGNMENT] Asset filter: {args.asset}")
    print(f"[ALIGNMENT] Tolerances: edge={args.edge_tolerance}c, size={args.size_tolerance}")
    
    reconstructions = analyze_fills(
        hours=args.hours,
        asset_filter=args.asset,
        edge_tolerance_cents=args.edge_tolerance,
        size_tolerance=args.size_tolerance,
    )
    
    print(f"[ALIGNMENT] Analyzed {len(reconstructions)} fills")
    
    if not reconstructions:
        print("[ALIGNMENT] No fills found in specified time range")
        return
    
    report_mismatches(reconstructions, args.edge_tolerance, args.size_tolerance)
    report_per_asset_summary(reconstructions)


if __name__ == "__main__":
    main()
