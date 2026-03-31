"""
CFB RTI Settlement Comparison Logger

Captures and compares:
- CF Benchmarks RTI settlement prices
- Internal spot price proxies
- Edge calculations
- Market mid-prices

This data is used to fine-tune confidence thresholds and validate
that our internal pricing aligns with official Kalshi settlement indices.

Usage:
    from monitoring.cfb_rti_logger import log_settlement_comparison

    # After a trade settles
    log_settlement_comparison(
        asset="BTC",
        timeframe="15m",
        settlement_price_cfb=50123.45,
        internal_spot=50125.10,
        market_mid=0.52,
        edge=0.035
    )
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


# ============================================================================
# Configuration
# ============================================================================

CFB_LOG_DIR = Path("data/cfb_rti_logs")
CFB_LOG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Settlement Comparison Logging
# ============================================================================

def log_settlement_comparison(
    asset: str,
    timeframe: str,
    settlement_price_cfb: float,
    internal_spot: Optional[float] = None,
    market_mid: Optional[float] = None,
    edge: Optional[float] = None,
    market_id: Optional[str] = None,
    notes: Optional[str] = None,
) -> None:
    """
    Log CFB RTI settlement price comparison.

    Args:
        asset: Crypto asset (BTC, ETH, SOL, XRP, DOGE)
        timeframe: Timeframe (15m, 1h, daily, weekly, monthly)
        settlement_price_cfb: Official CF Benchmarks RTI settlement price
        internal_spot: Our internal spot price estimate (from feeds)
        market_mid: Kalshi market mid-price at settlement time
        edge: Our calculated edge vs market
        market_id: Kalshi market ticker (optional)
        notes: Additional notes (optional)
    """
    timestamp = datetime.now()

    # Calculate divergence if both prices available
    divergence_bps = None
    divergence_pct = None
    if internal_spot is not None and settlement_price_cfb > 0:
        divergence = internal_spot - settlement_price_cfb
        divergence_pct = (divergence / settlement_price_cfb) * 100
        divergence_bps = divergence_pct * 100  # Convert to basis points

    # Build log entry
    entry = {
        "timestamp": timestamp.isoformat(),
        "asset": asset,
        "timeframe": timeframe,
        "settlement_price_cfb": settlement_price_cfb,
        "internal_spot": internal_spot,
        "market_mid": market_mid,
        "edge": edge,
        "divergence_bps": round(divergence_bps, 2) if divergence_bps is not None else None,
        "divergence_pct": round(divergence_pct, 4) if divergence_pct is not None else None,
        "market_id": market_id,
        "notes": notes,
    }

    # Write to daily log file
    log_file = CFB_LOG_DIR / f"cfb_settlements_{timestamp.strftime('%Y-%m-%d')}.jsonl"
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Log to console for monitoring
    if divergence_bps is not None and abs(divergence_bps) > 10:  # > 10 bps divergence
        logger.warning(
            f"CFB RTI divergence: {asset} {timeframe} "
            f"settlement=${settlement_price_cfb:.2f} "
            f"internal=${internal_spot:.2f} "
            f"divergence={divergence_bps:.1f}bps"
        )
    else:
        logger.info(
            f"CFB RTI logged: {asset} {timeframe} "
            f"settlement=${settlement_price_cfb:.2f}"
        )


def get_settlement_statistics(
    asset: Optional[str] = None,
    timeframe: Optional[str] = None,
    days: int = 7,
) -> dict:
    """
    Get statistics on settlement comparisons.

    Args:
        asset: Filter by asset (optional)
        timeframe: Filter by timeframe (optional)
        days: Number of days to look back

    Returns:
        dict with statistics: mean divergence, std dev, count, etc.
    """
    from datetime import timedelta

    start_date = datetime.now() - timedelta(days=days)
    entries = []

    # Read all log files in range
    for i in range(days):
        date = start_date + timedelta(days=i)
        log_file = CFB_LOG_DIR / f"cfb_settlements_{date.strftime('%Y-%m-%d')}.jsonl"

        if not log_file.exists():
            continue

        with open(log_file, "r") as f:
            for line in f:
                try:
                    entry = json.loads(line)

                    # Apply filters
                    if asset and entry.get("asset") != asset:
                        continue
                    if timeframe and entry.get("timeframe") != timeframe:
                        continue

                    entries.append(entry)
                except Exception as e:
                    logger.warning(f"Failed to parse log entry: {e}")

    if not entries:
        return {
            "count": 0,
            "mean_divergence_bps": None,
            "std_divergence_bps": None,
            "max_divergence_bps": None,
            "min_divergence_bps": None,
        }

    # Calculate statistics
    divergences = [e["divergence_bps"] for e in entries if e.get("divergence_bps") is not None]

    if not divergences:
        return {"count": len(entries), "mean_divergence_bps": None}

    import statistics

    return {
        "count": len(entries),
        "mean_divergence_bps": round(statistics.mean(divergences), 2),
        "std_divergence_bps": round(statistics.stdev(divergences), 2) if len(divergences) > 1 else 0,
        "max_divergence_bps": round(max(divergences), 2),
        "min_divergence_bps": round(min(divergences), 2),
        "median_divergence_bps": round(statistics.median(divergences), 2),
    }


# ============================================================================
# Analysis Helper
# ============================================================================

def analyze_settlement_drift(asset: str, timeframe: str, days: int = 7) -> str:
    """
    Generate a human-readable analysis of settlement drift.

    Args:
        asset: Crypto asset
        timeframe: Timeframe
        days: Days to analyze

    Returns:
        str: Human-readable analysis
    """
    stats = get_settlement_statistics(asset=asset, timeframe=timeframe, days=days)

    if stats["count"] == 0:
        return f"No settlement data for {asset} {timeframe} in last {days} days"

    if stats["mean_divergence_bps"] is None:
        return f"Found {stats['count']} settlements but no internal spot comparisons"

    mean = stats["mean_divergence_bps"]
    std = stats["std_divergence_bps"]

    # Interpret results
    if abs(mean) < 5:
        assessment = "EXCELLENT - internal pricing very accurate"
    elif abs(mean) < 10:
        assessment = "GOOD - minor systematic bias"
    elif abs(mean) < 20:
        assessment = "FAIR - noticeable bias, consider recalibration"
    else:
        assessment = "POOR - significant drift, investigate feed quality"

    direction = "overestimating" if mean > 0 else "underestimating"

    return f"""
CFB RTI Settlement Analysis ({asset} {timeframe}, {days} days):
  Count: {stats['count']} settlements
  Mean Divergence: {mean:+.1f} bps ({direction})
  Std Deviation: {std:.1f} bps
  Range: [{stats['min_divergence_bps']:.1f}, {stats['max_divergence_bps']:.1f}] bps

  Assessment: {assessment}
    """.strip()
