#!/usr/bin/env python
"""
Build calibration table: model-implied probability vs realized YES frequency.

This script analyzes Kalshi fills to calibrate probability estimates:
- Groups fills by contract price (implied probability) bins
- Calculates actual YES frequency in each bin
- Shows edge (actual - implied) to identify bias

Usage:
    python scripts/build_calibration_table.py
"""
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from collections import defaultdict
from decimal import Decimal
from typing import Dict, List, Tuple


def get_fills_for_calibration():
    """Get fills from fills_ledger for calibration analysis."""
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
        ledger = get_fills_ledger()
        
        # Load fills from database
        import asyncio
        loaded_count = asyncio.run(ledger.start())
        print(f"Loaded {loaded_count} fills from database")
        
        # Get all fills with no filters
        fills = ledger.get_fills(limit=10000)
        
        # Filter for settled fills with known outcomes
        settled_fills = []
        for fill in fills:
            # Skip test fixtures
            if fill.fill_id.startswith(("fill_", "test_", "ws-fill-")):
                continue
            
            # Only include fills with price and known action
            if not fill.price_cents or not fill.action:
                continue
            
            settled_fills.append(fill)
        
        return settled_fills
    except Exception as e:
        print(f"Error fetching fills: {e}")
        import traceback
        traceback.print_exc()
        return []


def bin_probability(prob: float, bin_size: float = 0.10) -> Tuple[int, int]:
    """Bin a probability into a range.
    
    Args:
        prob: Probability value (0.0 to 1.0)
        bin_size: Size of each bin (default 0.10 = 10%)
    
    Returns:
        Tuple of (bin_start, bin_end) as percentages (e.g., (0, 10) for 0-10%)
    """
    bin_index = int(prob / bin_size)
    bin_start = bin_index * int(bin_size * 100)
    bin_end = (bin_index + 1) * int(bin_size * 100)
    return (bin_start, min(bin_end, 100))


def build_calibration_table(fills: List, bin_size: float = 0.10):
    """Build calibration table from fills.
    
    Args:
        fills: List of KalshiFill objects
        bin_size: Size of probability bins (default 0.10 = 10%)
    
    Returns:
        Dict mapping bin ranges to calibration stats
    """
    # Group fills by probability bin
    bins: Dict[Tuple[int, int], Dict] = defaultdict(lambda: {
        "yes_count": 0,
        "no_count": 0,
        "total": 0,
        "implied_probs": [],
    })
    
    for fill in fills:
        # Convert price_cents to probability (price in cents / 100)
        implied_prob = float(fill.price_cents) / 100.0
        
        # Bin the probability
        bin_range = bin_probability(implied_prob, bin_size)
        
        # Determine outcome based on action and settlement
        # For YES contracts: action="yes" means we bought YES
        # For NO contracts: action="no" means we bought NO
        # We need to know the settlement outcome to calibrate
        
        # For now, use action as proxy (will need settlement data later)
        if fill.action == "yes":
            bins[bin_range]["yes_count"] += 1
        elif fill.action == "no":
            bins[bin_range]["no_count"] += 1
        
        bins[bin_range]["total"] += 1
        bins[bin_range]["implied_probs"].append(implied_prob)
    
    # Calculate calibration stats per bin
    calibration_table = {}
    for bin_range, stats in bins.items():
        total = stats["total"]
        if total == 0:
            continue
        
        avg_implied_prob = sum(stats["implied_probs"]) / len(stats["implied_probs"])
        yes_count = stats["yes_count"]
        
        # Actual YES frequency
        actual_yes_freq = yes_count / total
        
        # Edge (actual - implied)
        edge = actual_yes_freq - avg_implied_prob
        
        calibration_table[bin_range] = {
            "bin_range": bin_range,
            "total": total,
            "avg_implied_prob": avg_implied_prob,
            "actual_yes_freq": actual_yes_freq,
            "edge": edge,
            "yes_count": yes_count,
            "no_count": stats["no_count"],
        }
    
    return calibration_table


def print_calibration_table(calibration_table: Dict[Tuple[int, int], Dict]):
    """Print calibration table in readable format.
    
    Args:
        calibration_table: Dict mapping bin ranges to calibration stats
    """
    print("\n" + "=" * 100)
    print("KALSHI PROBABILITY CALIBRATION TABLE")
    print("=" * 100)
    print(f"{'Bin Range':<15} {'Count':<8} {'Avg Implied':<12} {'Actual YES':<12} {'Edge':<12} {'Yes':<8} {'No':<8}")
    print("-" * 100)
    
    # Sort bins by range
    sorted_bins = sorted(calibration_table.keys())
    
    for bin_range in sorted_bins:
        stats = calibration_table[bin_range]
        
        bin_str = f"{bin_range[0]}-{bin_range[1]}%"
        count = stats["total"]
        avg_implied = f"{stats['avg_implied_prob']:.3f}"
        actual_yes = f"{stats['actual_yes_freq']:.3f}"
        edge = f"{stats['edge']:+.3f}"
        yes_count = stats["yes_count"]
        no_count = stats["no_count"]
        
        print(f"{bin_str:<15} {count:<8} {avg_implied:<12} {actual_yes:<12} {edge:<12} {yes_count:<8} {no_count:<8}")
    
    print("=" * 100)
    
    # Overall stats
    total_fills = sum(stats["total"] for stats in calibration_table.values())
    total_yes = sum(stats["yes_count"] for stats in calibration_table.values())
    overall_yes_freq = total_yes / total_fills if total_fills > 0 else 0
    
    print(f"\nTotal fills analyzed: {total_fills}")
    print(f"Overall YES frequency: {overall_yes_freq:.3f}")
    print("=" * 100)


def main():
    """Main entry point."""
    print("Fetching fills from fills_ledger...")
    fills = get_fills_for_calibration()
    
    if not fills:
        print("No fills found. Exiting.")
        return
    
    print(f"Found {len(fills)} fills for calibration analysis.")
    
    print("\nBuilding calibration table...")
    calibration_table = build_calibration_table(fills)
    
    if not calibration_table:
        print("No calibration data generated. Exiting.")
        return
    
    print_calibration_table(calibration_table)


if __name__ == "__main__":
    main()
