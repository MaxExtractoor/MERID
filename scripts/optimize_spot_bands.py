#!/usr/bin/env python3
"""Spot Band Optimization Script — Find optimal spot band percentages.

Analyzes live Kalshi market data to determine the most profitable spot band
configuration for each (asset, timeframe) pair.

The spot band controls how far from spot price we scan strikes. Tighter bands
(smaller percentages) focus on near-the-money contracts with higher liquidity
but fewer candidates. Wider bands capture more candidates but may include
illiquid far-OTM/ITM strikes.

Usage::

    # Analyze BTC and ETH for short timeframes
    python scripts/optimize_spot_bands.py --assets BTC,ETH --horizons 15m,1h

    # Full analysis with custom band candidates
    python scripts/optimize_spot_bands.py \
        --assets BTC,ETH,SOL,XRP,DOGE \
        --horizons 15m,1h,daily,weekly,monthly \
        --bands 0.10,0.15,0.20,0.25,0.30,0.35

    # Quick test run
    python scripts/optimize_spot_bands.py --assets BTC --horizons 15m --bands 0.15,0.25
"""

import argparse
import asyncio
import csv
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add parent directory to path to import merid modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, get_market_catalog
from merid.event_venues.kalshi.market_filter import MarketCandidate, MarketFilter, MarketFilterConfig
from merid.trading.kalshi_continuous_trader import EDGE_THRESHOLDS, KalshiContinuousTrader
from utils.logger import get_logger

logger = get_logger("scripts.optimize_spot_bands")

# ── Default band candidates per horizon type ──────────────────────────────

DEFAULT_BANDS = {
    "short": [0.10, 0.15, 0.20, 0.25, 0.30, 0.35],  # 15m, 1h
    "medium": [0.15, 0.25, 0.35, 0.45],              # daily
    "long": [0.20, 0.30, 0.40, 0.50],                # weekly, monthly
}

HORIZON_TYPES = {
    "15m": "short",
    "1h": "short",
    "daily": "medium",
    "weekly": "long",
    "monthly": "long",
}


# ── Analysis result ───────────────────────────────────────────────────────

@dataclass
class BandAnalysis:
    """Analysis result for a single (asset, timeframe, band_pct) configuration."""
    asset: str
    timeframe: str
    band_pct: float
    n_input: int = 0           # Markets fed into filter
    n_accepted: int = 0         # Markets passing all filters
    avg_edge: float = 0.0       # Mean edge of accepted candidates
    median_edge: float = 0.0    # Median edge
    p25_edge: float = 0.0       # 25th percentile edge
    p75_edge: float = 0.0       # 75th percentile edge
    avg_spread_cents: float = 0.0  # Average spread
    potential_notional: float = 0.0  # Sum of Kelly notional across candidates
    edge_weighted_opportunity: float = 0.0  # Sum(edge × notional)

    def to_dict(self) -> dict:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "band_pct": self.band_pct,
            "n_input": self.n_input,
            "n_accepted": self.n_accepted,
            "avg_edge": round(self.avg_edge, 4),
            "median_edge": round(self.median_edge, 4),
            "p25_edge": round(self.p25_edge, 4),
            "p75_edge": round(self.p75_edge, 4),
            "avg_spread_cents": round(self.avg_spread_cents, 2),
            "potential_notional": round(self.potential_notional, 2),
            "edge_weighted_opportunity": round(self.edge_weighted_opportunity, 4),
        }


# ── Optimizer ─────────────────────────────────────────────────────────────

class SpotBandOptimizer:
    """Analyzes spot band configurations and recommends optimal values."""

    def __init__(
        self,
        catalog: Optional[KalshiMarketCatalog] = None,
        bankroll: float = 1000.0,
    ):
        self.catalog = catalog or get_market_catalog()
        self.bankroll = bankroll
        # Create a temporary trader instance for sizing calculations
        self.trader = KalshiContinuousTrader(catalog=self.catalog)

    async def analyze_configuration(
        self,
        asset: str,
        timeframe: str,
        band_pct: float,
    ) -> BandAnalysis:
        """Analyze a single (asset, timeframe, band_pct) configuration.

        Fetches live market data, applies filters with the given band_pct,
        and computes quality metrics.
        """
        result = BandAnalysis(asset=asset, timeframe=timeframe, band_pct=band_pct)

        # Fetch markets from catalog
        catalog_markets = self.catalog.get_markets_by_asset(asset, timeframe=timeframe)
        if not catalog_markets:
            logger.warning(f"No catalog markets for {asset} {timeframe}")
            return result

        result.n_input = len(catalog_markets)

        # Convert to MarketCandidate format
        candidates = [
            MarketCandidate(
                ticker=cm.market.market_id,
                underlying=asset,
                timeframe=timeframe,
                expiry_ts=cm.expires_at.timestamp() if cm.expires_at else 0.0,
                volume=int(cm.market.volume) if cm.market.volume else 0,
                open_interest=int(cm.market.open_interest) if cm.market.open_interest else 0,
                category=cm.category or "",
                strike_price=cm.strike_price,
                spot_price=cm.spot_price if hasattr(cm, 'spot_price') else None,
                best_bid_cents=int(cm.market.last_price * 100) if cm.market.last_price else 0,
                best_ask_cents=int(cm.market.last_price * 100) if cm.market.last_price else 0,
                mid_price_cents=int(cm.market.last_price * 100) if cm.market.last_price else 50,
                spread_cents=0,  # Will be computed from book if available
            )
            for cm in catalog_markets
        ]

        # Create filter with the target band_pct
        filter_config = MarketFilterConfig(
            allowed_underlyings=[asset],
            allowed_timeframes=[timeframe],
            spot_band_pct=band_pct,
        )
        market_filter = MarketFilter(filter_config)

        # Apply filter
        filter_result = market_filter.filter_markets(candidates)
        result.n_accepted = filter_result.passed

        if result.n_accepted == 0:
            logger.debug(f"{asset} {timeframe} band={band_pct:.1%}: 0 candidates passed")
            return result

        # Compute edge and sizing metrics for accepted candidates
        edges: List[float] = []
        spreads: List[float] = []
        notionals: List[float] = []

        for candidate in filter_result.candidates:
            # Wrap as TradingCandidate for sizing
            from merid.trading.kalshi_continuous_trader import TradingCandidate
            tc = TradingCandidate.from_candidate(candidate)

            # Get sizing from trader (uses Kelly + edge thresholds)
            sizing = self.trader.signal_to_sizing(tc, self.bankroll)

            if sizing.edge > 0:
                edges.append(sizing.edge)
                notionals.append(sizing.notional_usd)

            if candidate.spread_cents > 0:
                spreads.append(candidate.spread_cents)

        # Compute statistics
        if edges:
            edges_sorted = sorted(edges)
            result.avg_edge = sum(edges) / len(edges)
            result.median_edge = edges_sorted[len(edges) // 2]
            result.p25_edge = edges_sorted[len(edges) // 4]
            result.p75_edge = edges_sorted[3 * len(edges) // 4]
            result.potential_notional = sum(notionals)
            result.edge_weighted_opportunity = sum(e * n for e, n in zip(edges, notionals))

        if spreads:
            result.avg_spread_cents = sum(spreads) / len(spreads)

        logger.info(
            f"{asset:4s} {timeframe:7s} band={band_pct:5.1%}: "
            f"n={result.n_accepted:3d} avg_edge={result.avg_edge:6.2%} "
            f"opp={result.edge_weighted_opportunity:8.2f}"
        )

        return result

    async def optimize_all(
        self,
        assets: List[str],
        timeframes: List[str],
        bands: Optional[Dict[str, List[float]]] = None,
    ) -> List[BandAnalysis]:
        """Run optimization across all (asset, timeframe, band) combinations.

        Args:
            assets: List of asset symbols (e.g., ["BTC", "ETH"])
            timeframes: List of timeframes (e.g., ["15m", "1h", "daily"])
            bands: Optional dict mapping horizon type to band percentages.
                   If None, uses DEFAULT_BANDS.

        Returns:
            List of BandAnalysis results.
        """
        if bands is None:
            bands = DEFAULT_BANDS

        results: List[BandAnalysis] = []

        for asset in assets:
            for timeframe in timeframes:
                # Get appropriate band candidates for this timeframe
                horizon_type = HORIZON_TYPES.get(timeframe, "medium")
                band_candidates = bands.get(horizon_type, DEFAULT_BANDS["medium"])

                logger.info(f"Analyzing {asset} {timeframe} across {len(band_candidates)} band configs...")

                for band_pct in band_candidates:
                    analysis = await self.analyze_configuration(asset, timeframe, band_pct)
                    results.append(analysis)

        return results


# ── Output formatting ─────────────────────────────────────────────────────

def write_csv(results: List[BandAnalysis], output_path: Path) -> None:
    """Write analysis results to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", newline="") as f:
        if not results:
            logger.warning("No results to write")
            return

        fieldnames = list(results[0].to_dict().keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for result in results:
            writer.writerow(result.to_dict())

    logger.info(f"Wrote {len(results)} results to {output_path}")


def print_summary(results: List[BandAnalysis]) -> None:
    """Print a concise summary of Pareto-optimal configurations."""
    print("\n" + "=" * 80)
    print("SPOT BAND OPTIMIZATION SUMMARY")
    print("=" * 80)

    # Group by (asset, timeframe)
    by_pair: Dict[Tuple[str, str], List[BandAnalysis]] = defaultdict(list)
    for r in results:
        by_pair[(r.asset, r.timeframe)].append(r)

    for (asset, timeframe), analyses in sorted(by_pair.items()):
        # Filter to configs with at least 2 candidates
        viable = [a for a in analyses if a.n_accepted >= 2]
        if not viable:
            print(f"\n{asset:4s} {timeframe:7s}: No viable configurations (all < 2 candidates)")
            continue

        # Find Pareto frontier: max avg_edge and max n_accepted
        best_edge = max(viable, key=lambda a: a.avg_edge)
        best_count = max(viable, key=lambda a: a.n_accepted)
        best_opportunity = max(viable, key=lambda a: a.edge_weighted_opportunity)

        print(f"\n{asset:4s} {timeframe:7s} — Pareto candidates:")
        print(f"  • Highest edge:  band={best_edge.band_pct:5.1%}  "
              f"n={best_edge.n_accepted:3d}  edge={best_edge.avg_edge:6.2%}")
        print(f"  • Most trades:   band={best_count.band_pct:5.1%}  "
              f"n={best_count.n_accepted:3d}  edge={best_count.avg_edge:6.2%}")
        print(f"  • Best opportunity: band={best_opportunity.band_pct:5.1%}  "
              f"opp={best_opportunity.edge_weighted_opportunity:8.2f}")

    print("\n" + "=" * 80)


def propose_spot_bands(results: List[BandAnalysis]) -> Dict[Tuple[str, str], float]:
    """Propose SPOT_BANDS configuration based on analysis results.

    Selection heuristic:
    - Prefer configurations with n_accepted >= 3 (need minimum pool)
    - Maximize edge_weighted_opportunity (quality-adjusted throughput)
    - Break ties by preferring higher avg_edge
    """
    by_pair: Dict[Tuple[str, str], List[BandAnalysis]] = defaultdict(list)
    for r in results:
        by_pair[(r.asset, r.timeframe)].append(r)

    proposed: Dict[Tuple[str, str], float] = {}

    for (asset, timeframe), analyses in sorted(by_pair.items()):
        # Filter to viable configs
        viable = [a for a in analyses if a.n_accepted >= 3]
        if not viable:
            # Fall back to any config with at least 1 candidate
            viable = [a for a in analyses if a.n_accepted >= 1]
            if not viable:
                logger.warning(f"No viable band for {asset} {timeframe}")
                continue

        # Select config with best edge_weighted_opportunity
        best = max(viable, key=lambda a: (a.edge_weighted_opportunity, a.avg_edge))
        proposed[(asset, timeframe)] = best.band_pct

    return proposed


def print_proposed_config(proposed: Dict[Tuple[str, str], float]) -> None:
    """Print the proposed SPOT_BANDS dict in Python code format."""
    print("\n" + "=" * 80)
    print("PROPOSED SPOT_BANDS CONFIGURATION")
    print("=" * 80)
    print("\nSPOT_BANDS: Dict[Tuple[str, str], float] = {")

    # Group by asset for readability
    by_asset: Dict[str, List[Tuple[Tuple[str, str], float]]] = defaultdict(list)
    for key, value in sorted(proposed.items()):
        by_asset[key[0]].append((key, value))

    for asset, items in sorted(by_asset.items()):
        print(f"    # {asset}")
        for (asset_key, timeframe), band_pct in items:
            print(f'    ("{asset_key}", "{timeframe}"): {band_pct:.2f},')

    print("}\n")


# ── CLI ───────────────────────────────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(
        description="Optimize spot band percentages for Kalshi crypto markets",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--assets",
        default="BTC,ETH,SOL,XRP,DOGE",
        help="Comma-separated list of assets (default: all 5 crypto assets)",
    )
    parser.add_argument(
        "--horizons",
        default="15m,1h,daily,weekly,monthly",
        help="Comma-separated list of timeframes (default: all 5 timeframes)",
    )
    parser.add_argument(
        "--bands",
        default=None,
        help="Comma-separated list of band percentages to test (default: horizon-specific defaults)",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory for output CSV (default: output/)",
    )
    parser.add_argument(
        "--bankroll",
        type=float,
        default=1000.0,
        help="Bankroll for Kelly sizing (default: 1000.0)",
    )

    args = parser.parse_args()

    # Parse inputs
    assets = [a.strip().upper() for a in args.assets.split(",")]
    timeframes = [h.strip().lower() for h in args.horizons.split(",")]

    bands_dict = DEFAULT_BANDS
    if args.bands:
        # User provided explicit bands — use for all horizon types
        band_list = [float(b.strip()) for b in args.bands.split(",")]
        bands_dict = {
            "short": band_list,
            "medium": band_list,
            "long": band_list,
        }

    # Run optimization
    logger.info(f"Starting spot band optimization: assets={assets} timeframes={timeframes}")
    optimizer = SpotBandOptimizer(bankroll=args.bankroll)
    results = await optimizer.optimize_all(assets, timeframes, bands_dict)

    # Write CSV
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output_dir) / f"spot_band_analysis_{timestamp}.csv"
    write_csv(results, output_path)

    # Print summary
    print_summary(results)

    # Propose configuration
    proposed = propose_spot_bands(results)
    print_proposed_config(proposed)

    print(f"\n✅ Analysis complete. Results written to {output_path}\n")


if __name__ == "__main__":
    asyncio.run(main())
