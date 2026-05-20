#!/usr/bin/env python3
"""
Analyze 15m crypto forensics logs to compute EV and win rate by bucket.

This script parses [15M-FORENSICS] log lines and buckets trades by:
- Model probability band (0.60-0.70, 0.70-0.80, 0.80-0.90, 0.90+)
- Time window phase (early, mid, late, terminal)
- Distance from target bucket (near, medium, far)

For each bucket, compute:
- Average edge at order time
- Win rate
- Realized EV per dollar risked
- Trade count

Usage:
    python scripts/analyze_15m_forensics.py --log-file server_diag.log --output output/forensics_analysis.json
"""

import argparse
import json
import re
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ForensicsRecord:
    """Parsed forensics log record."""
    timestamp: str
    asset: str
    decision: str
    spot: Optional[float]
    strike: Optional[float]
    distance_pct: Optional[float]
    market_price_cents: int
    implied_prob: float
    model_prob: float
    edge: float
    kelly_fraction: Optional[float]
    notional_usd: Optional[float]
    phase: Optional[str]
    skip_reason: Optional[str] = None


@dataclass
class BucketStats:
    """Statistics for a single bucket."""
    trade_count: int = 0
    total_edge: float = 0.0
    avg_edge: float = 0.0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_notional: float = 0.0
    ev_per_dollar: float = 0.0


def parse_forensics_line(line: str) -> Optional[ForensicsRecord]:
    """Parse a [15M-FORENSICS] log line into a structured record.
    
    Expected format:
        [15M-FORENSICS] asset=BTC decision=TRADE spot=81500.0 strike=81550.0 
        distance_pct=0.0006 market_price=45c implied_prob=0.450 model_prob=0.520 
        edge=0.0700 kelly=0.200 notional=$2.25 phase=mid
    """
    if "[15M-FORENSICS]" not in line:
        return None
    
    # Extract timestamp (assuming standard log format at start)
    timestamp_match = re.match(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
    timestamp = timestamp_match.group(1) if timestamp_match else "unknown"
    
    # Parse key-value pairs
    record = {}
    for match in re.finditer(r'(\w+)=(\S+)', line):
        key, value = match.groups()
        record[key] = value
    
    # Extract fields
    asset = record.get('asset', 'UNKNOWN')
    decision = record.get('decision', 'UNKNOWN')
    
    # Parse numeric fields
    spot = _parse_float(record.get('spot'))
    strike = _parse_float(record.get('strike'))
    distance_pct = _parse_float(record.get('distance_pct'))
    market_price_cents = _parse_int(record.get('market_price', '0').replace('c', ''))
    implied_prob = _parse_float(record.get('implied_prob', '0'))
    model_prob = _parse_float(record.get('model_prob', '0'))
    edge = _parse_float(record.get('edge', '0'))
    kelly_fraction = _parse_float(record.get('kelly'))
    notional_usd = _parse_float(record.get('notional', '0').replace('$', ''))
    phase = record.get('phase')
    skip_reason = record.get('skip_reason')
    
    return ForensicsRecord(
        timestamp=timestamp,
        asset=asset,
        decision=decision,
        spot=spot,
        strike=strike,
        distance_pct=distance_pct,
        market_price_cents=market_price_cents,
        implied_prob=implied_prob,
        model_prob=model_prob,
        edge=edge,
        kelly_fraction=kelly_fraction,
        notional_usd=notional_usd,
        phase=phase,
        skip_reason=skip_reason
    )


def _parse_float(value: Optional[str]) -> Optional[float]:
    """Safely parse a float value."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_int(value: Optional[str]) -> Optional[int]:
    """Safely parse an int value."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def get_probability_bucket(model_prob: float) -> str:
    """Bucket model probability into bands."""
    if model_prob < 0.60:
        return "low_0.50-0.60"
    elif model_prob < 0.70:
        return "med_0.60-0.70"
    elif model_prob < 0.80:
        return "high_0.70-0.80"
    elif model_prob < 0.90:
        return "very_high_0.80-0.90"
    else:
        return "extreme_0.90+"


def get_distance_bucket(distance_pct: Optional[float]) -> str:
    """Bucket distance from target."""
    if distance_pct is None:
        return "unknown"
    elif distance_pct < 0.002:
        return "near_0.0-0.2%"
    elif distance_pct < 0.005:
        return "medium_0.2-0.5%"
    elif distance_pct < 0.010:
        return "far_0.5-1.0%"
    else:
        return "very_far_1.0%+"


def get_phase_bucket(phase: Optional[str]) -> str:
    """Bucket time window phase."""
    if phase is None:
        return "unknown"
    return phase.lower()


def analyze_forensics(records: List[ForensicsRecord]) -> Dict:
    """Analyze forensics records and compute bucket statistics.
    
    Returns nested dictionary structure:
        {
            "by_asset": {
                "BTC": {
                    "by_prob_bucket": {
                        "high_0.70-0.80": BucketStats,
                        ...
                    },
                    "by_phase": {
                        "early": BucketStats,
                        ...
                    },
                    "by_distance": {
                        "near_0.0-0.2%": BucketStats,
                        ...
                    }
                },
                ...
            },
            "summary": {
                "total_trades": int,
                "total_notional": float,
                "overall_win_rate": float,
                ...
            }
        }
    """
    # Initialize nested structure
    analysis = {
        "by_asset": {},
        "summary": {
            "total_trades": 0,
            "total_notional": 0.0,
            "trades_by_asset": defaultdict(int),
            "notional_by_asset": defaultdict(float),
            "guard_reasons_by_asset": defaultdict(lambda: defaultdict(int))  # asset -> reason -> count
        }
    }
    
    # Group records by asset and count guard reasons
    by_asset = defaultdict(list)
    for record in records:
        # Count guard reasons for NO_TRADE decisions
        if record.decision == "NO_TRADE" and record.skip_reason:
            analysis["summary"]["guard_reasons_by_asset"][record.asset][record.skip_reason] += 1
        
        # Only process TRADE decisions for bucket analysis
        if record.decision == "TRADE":
            by_asset[record.asset].append(record)
            analysis["summary"]["total_trades"] += 1
            analysis["summary"]["trades_by_asset"][record.asset] += 1
            if record.notional_usd:
                analysis["summary"]["total_notional"] += record.notional_usd
                analysis["summary"]["notional_by_asset"][record.asset] += record.notional_usd
    
    # Analyze each asset
    for asset, asset_records in by_asset.items():
        asset_analysis = {
            "by_prob_bucket": defaultdict(lambda: asdict(BucketStats())),
            "by_phase": defaultdict(lambda: asdict(BucketStats())),
            "by_distance": defaultdict(lambda: asdict(BucketStats())),
            "combined": defaultdict(lambda: asdict(BucketStats()))  # prob × phase × distance
        }
        
        for record in asset_records:
            prob_bucket = get_probability_bucket(record.model_prob)
            phase_bucket = get_phase_bucket(record.phase)
            distance_bucket = get_distance_bucket(record.distance_pct)
            
            # Update individual buckets
            _update_bucket_stats(asset_analysis["by_prob_bucket"][prob_bucket], record)
            _update_bucket_stats(asset_analysis["by_phase"][phase_bucket], record)
            _update_bucket_stats(asset_analysis["by_distance"][distance_bucket], record)
            
            # Update combined bucket
            combined_key = f"{prob_bucket}|{phase_bucket}|{distance_bucket}"
            _update_bucket_stats(asset_analysis["combined"][combined_key], record)
        
        # Calculate averages for each bucket
        for bucket_dict in [asset_analysis["by_prob_bucket"], 
                           asset_analysis["by_phase"], 
                           asset_analysis["by_distance"],
                           asset_analysis["combined"]]:
            for bucket_stats in bucket_dict.values():
                if bucket_stats["trade_count"] > 0:
                    bucket_stats["avg_edge"] = bucket_stats["total_edge"] / bucket_stats["trade_count"]
                    bucket_stats["win_rate"] = bucket_stats["wins"] / bucket_stats["trade_count"]
                    if bucket_stats["total_notional"] > 0:
                        # Simplified EV calculation (can be refined with actual P&L data)
                        bucket_stats["ev_per_dollar"] = (bucket_stats["avg_edge"] * bucket_stats["total_notional"]) / bucket_stats["total_notional"]
        
        analysis["by_asset"][asset] = asset_analysis
    
    # Calculate overall summary
    if analysis["summary"]["total_trades"] > 0:
        analysis["summary"]["avg_notional_per_trade"] = (
            analysis["summary"]["total_notional"] / analysis["summary"]["total_trades"]
        )
    
    return analysis


def _update_bucket_stats(bucket_stats: Dict, record: ForensicsRecord):
    """Update bucket statistics with a single record."""
    bucket_stats["trade_count"] += 1
    bucket_stats["total_edge"] += record.edge
    if record.notional_usd:
        bucket_stats["total_notional"] += record.notional_usd
    
    # Note: wins/losses would need to be determined from fill data
    # For now, we assume a simplified win/loss based on edge sign
    # This should be refined with actual P&L tracking
    if record.edge > 0:
        bucket_stats["wins"] += 1
    else:
        bucket_stats["losses"] += 1


def main():
    parser = argparse.ArgumentParser(description="Analyze 15m crypto forensics logs")
    parser.add_argument("--log-file", required=True, help="Path to log file containing [15M-FORENSICS] lines")
    parser.add_argument("--output", required=True, help="Path to output JSON file")
    parser.add_argument("--min-trades", type=int, default=5, help="Minimum trades per bucket to include in analysis")
    args = parser.parse_args()
    
    log_file = Path(args.log_file)
    if not log_file.exists():
        print(f"Error: Log file not found: {log_file}")
        return 1
    
    # Parse forensics records
    records = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            record = parse_forensics_line(line)
            if record:
                records.append(record)
    
    print(f"Parsed {len(records)} forensics records from {log_file}")
    
    # Analyze records
    analysis = analyze_forensics(records)
    
    # Filter buckets with insufficient trades
    for asset, asset_analysis in analysis["by_asset"].items():
        for bucket_type in ["by_prob_bucket", "by_phase", "by_distance", "combined"]:
            bucket_dict = asset_analysis[bucket_type]
            keys_to_remove = [
                key for key, stats in bucket_dict.items()
                if stats["trade_count"] < args.min_trades
            ]
            for key in keys_to_remove:
                del bucket_dict[key]
    
    # Write output
    output_file = Path(args.output)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(analysis, f, indent=2, default=str)
    
    print(f"Analysis written to {output_file}")
    
    # Print summary
    print("\n=== SUMMARY ===")
    print(f"Total trades: {analysis['summary']['total_trades']}")
    print(f"Total notional: ${analysis['summary']['total_notional']:.2f}")
    print("\nTrades by asset:")
    for asset, count in analysis['summary']['trades_by_asset'].items():
        notional = analysis['summary']['notional_by_asset'][asset]
        print(f"  {asset}: {count} trades, ${notional:.2f}")
    
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
