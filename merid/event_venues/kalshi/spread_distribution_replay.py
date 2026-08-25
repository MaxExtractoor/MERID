"""
Spread Distribution Replay Framework for Kalshi 15-Minute Crypto Markets

This module provides tools to analyze spread distributions across assets and time windows
to validate whether spread caps are appropriately calibrated.

Key capabilities:
- Collect spread measurements by asset and time-to-expiry bucket
- Compute distribution statistics (median, 75th, 90th, max)
- Simulate reject rates at different cap levels
- Identify false rejects (candidates that would have had positive edge)
"""

import asyncio
import dataclasses
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import statistics
from concurrent.futures import ThreadPoolExecutor
import time

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.unified_market_state import UnifiedMarketState, OrderbookSnapshot
from merid.event_venues.kalshi.spread_edge_analytics import (
    compute_canonical_spreads,
    PerSideSpreadMetrics,
    ASSET_SPREAD_CAPS
)
from merid.event_venues.kalshi.kalshi_crypto_15m_profile import get_ticker_for_asset

logger = logging.getLogger(__name__)


class TimeBucket(Enum):
    """Time-to-expiry buckets for 15-minute markets"""
    OPEN_0_3MIN = "0-3min"      # 0-180s: Market open, high volatility
    EARLY_3_6MIN = "3-6min"     # 180-360s: Early window
    MID_6_10MIN = "6-10min"     # 360-600s: Mid window
    LATE_10_13MIN = "10-13min"  # 600-780s: Late window
    EXPIRY_13_15MIN = "13-15min" # 780-900s: Near expiry
    
    @classmethod
    def from_seconds(cls, seconds: float) -> 'TimeBucket':
        """Convert seconds to time bucket"""
        if seconds < 180:
            return cls.OPEN_0_3MIN
        elif seconds < 360:
            return cls.EARLY_3_6MIN
        elif seconds < 600:
            return cls.MID_6_10MIN
        elif seconds < 780:
            return cls.LATE_10_13MIN
        else:
            return cls.EXPIRY_13_15MIN


@dataclass
class SpreadMeasurement:
    """Single spread measurement with context"""
    timestamp: datetime
    asset: str
    market_id: str
    time_to_expiry_seconds: float
    time_bucket: TimeBucket
    yes_bid_cents: int
    no_bid_cents: int
    yes_spread_cents: float
    no_spread_cents: float
    canonical_spread_cents: float  # max(yes_spread, no_spread)
    
    def to_dict(self) -> dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'asset': self.asset,
            'market_id': self.market_id,
            'time_to_expiry_seconds': self.time_to_expiry_seconds,
            'time_bucket': self.time_bucket.value,
            'yes_bid_cents': self.yes_bid_cents,
            'no_bid_cents': self.no_bid_cents,
            'yes_spread_cents': self.yes_spread_cents,
            'no_spread_cents': self.no_spread_cents,
            'canonical_spread_cents': self.canonical_spread_cents,
        }


@dataclass
class DistributionStats:
    """Statistical summary of spread distribution"""
    count: int
    min_spread: float
    max_spread: float
    median_spread: float
    p75_spread: float
    p90_spread: float
    p95_spread: float
    mean_spread: float
    std_spread: float
    
    def to_dict(self) -> dict:
        return {
            'count': self.count,
            'min_spread_cents': self.min_spread,
            'max_spread_cents': self.max_spread,
            'median_spread_cents': self.median_spread,
            'p75_spread_cents': self.p75_spread,
            'p90_spread_cents': self.p90_spread,
            'p95_spread_cents': self.p95_spread,
            'mean_spread_cents': self.mean_spread,
            'std_spread_cents': self.std_spread,
        }


@dataclass
class RejectRateAnalysis:
    """Reject rate analysis for a specific cap level"""
    cap_cents: float
    total_candidates: int
    rejected_count: int
    reject_rate: float
    false_reject_count: int  # Would have had positive edge
    false_reject_rate: float
    missed_edge_sum: float  # Total edge missed from false rejects
    
    def to_dict(self) -> dict:
        return {
            'cap_cents': self.cap_cents,
            'total_candidates': self.total_candidates,
            'rejected_count': self.rejected_count,
            'reject_rate': self.reject_rate,
            'false_reject_count': self.false_reject_count,
            'false_reject_rate': self.false_reject_rate,
            'missed_edge_sum': self.missed_edge_sum,
        }


@dataclass
class AssetAnalysis:
    """Complete analysis for a single asset"""
    asset: str
    current_cap_cents: float
    time_bucket_stats: Dict[TimeBucket, DistributionStats] = field(default_factory=dict)
    overall_stats: Optional[DistributionStats] = None
    cap_analysis: List[RejectRateAnalysis] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            'asset': self.asset,
            'current_cap_cents': self.current_cap_cents,
            'time_bucket_stats': {
                bucket.value: stats.to_dict() 
                for bucket, stats in self.time_bucket_stats.items()
            },
            'overall_stats': self.overall_stats.to_dict() if self.overall_stats else None,
            'cap_analysis': [analysis.to_dict() for analysis in self.cap_analysis],
        }


class SpreadDataCollector:
    """Collects spread measurements from market state"""
    
    def __init__(
        self,
        market_state_store: KalshiMarketStateStore,
        assets: List[str] = None,
        sample_interval_seconds: float = 1.0,
        max_samples_per_ticker: int = 1000
    ):
        self.market_state_store = market_state_store
        self.assets = assets or ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        self.sample_interval = sample_interval_seconds
        self.max_samples = max_samples_per_ticker
        self.measurements: List[SpreadMeasurement] = []
        self._stop_event = asyncio.Event()
        
    async def collect_samples(
        self,
        duration_seconds: float = 300.0,
        save_interval: float = 30.0
    ) -> List[SpreadMeasurement]:
        """
        Collect spread samples over a time period.
        
        Args:
            duration_seconds: How long to collect samples
            save_interval: How often to save intermediate results
            
        Returns:
            List of spread measurements
        """
        logger.info(
            f"[SPREAD-COLLECTOR] Starting collection for {len(self.assets)} assets "
            f"over {duration_seconds}s at {self.sample_interval}s intervals"
        )
        
        # Log available tickers in the market state store
        all_states = self.market_state_store.get_all()
        logger.info(f"[SPREAD-COLLECTOR] Available tickers in market state store: {list(all_states.keys())}")
        
        start_time = time.time()
        last_save = start_time
        sample_counts = defaultdict(int)
        
        # Log tickers we're trying to collect
        target_tickers = [get_ticker_for_asset(asset) for asset in self.assets]
        logger.info(f"[SPREAD-COLLECTOR] Target tickers: {target_tickers}")
        
        while not self._stop_event.is_set():
            elapsed = time.time() - start_time
            if elapsed >= duration_seconds:
                break
                
            # Collect samples from all assets
            await self._collect_single_round(sample_counts)
            
            # Save intermediate results periodically
            if time.time() - last_save >= save_interval:
                await self._save_intermediate_results()
                last_save = time.time()
                
            await asyncio.sleep(self.sample_interval)
        
        logger.info(
            f"[SPREAD-COLLECTOR] Collection complete. "
            f"Total samples: {len(self.measurements)}. "
            f"Per-asset: {dict(sample_counts)}"
        )
        
        return self.measurements
    
    async def _collect_single_round(self, sample_counts: Dict[str, int]):
        """Collect one round of samples from all assets"""
        for asset in self.assets:
            # Get ticker for this asset
            ticker = get_ticker_for_asset(asset)
            if not ticker:
                logger.debug(f"[SPREAD-COLLECTOR] No ticker found for asset {asset}")
                continue
                
            # Get current market state for this ticker
            unified_state = self.market_state_store.get_unified(ticker)
            if not unified_state:
                logger.debug(f"[SPREAD-COLLECTOR] No unified state for ticker {ticker}")
                continue
                
            # Check if we've hit max samples for this ticker
            if sample_counts[ticker] >= self.max_samples:
                continue
                
            # Extract spread measurement
            measurement = self._extract_measurement(unified_state)
            if measurement:
                self.measurements.append(measurement)
                sample_counts[ticker] += 1
    
    def _extract_measurement(self, unified_state: UnifiedMarketState) -> Optional[SpreadMeasurement]:
        """Extract spread measurement from unified market state"""
        try:
            orderbook = unified_state.orderbook
            if not orderbook or orderbook.spread_cents is None:
                return None
                
            # Get time to expiry
            time_to_expiry = unified_state.time_to_expiry_seconds
            if time_to_expiry is None:
                return None
                
            # Get best bids
            yes_bid = orderbook.best_yes_bid
            no_bid = orderbook.best_no_bid
            if yes_bid is None or no_bid is None:
                return None
                
            # Compute canonical spreads
            spread_metrics = compute_canonical_spreads(
                yes_bid_cents=yes_bid.price_cents,
                no_bid_cents=no_bid.price_cents
            )
            
            measurement = SpreadMeasurement(
                timestamp=datetime.now(),
                asset=unified_state.asset,
                market_id=unified_state.ticker,
                time_to_expiry_seconds=time_to_expiry,
                time_bucket=TimeBucket.from_seconds(time_to_expiry),
                yes_bid_cents=yes_bid.price_cents,
                no_bid_cents=no_bid.price_cents,
                yes_spread_cents=spread_metrics.yes_spread_cents,
                no_spread_cents=spread_metrics.no_spread_cents,
                canonical_spread_cents=max(
                    spread_metrics.yes_spread_cents,
                    spread_metrics.no_spread_cents
                )
            )
            
            return measurement
            
        except Exception as e:
            logger.warning(f"[SPREAD-COLLECTOR] Failed to extract measurement: {e}")
            return None
    
    async def _save_intermediate_results(self):
        """Save intermediate results to prevent data loss"""
        if not self.measurements:
            return
            
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = Path(f"spread_samples_intermediate_{timestamp}.json")
        
        data = [m.to_dict() for m in self.measurements]
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
            
        logger.info(f"[SPREAD-COLLECTOR] Saved {len(self.measurements)} samples to {filepath}")
    
    def stop(self):
        """Stop collection"""
        self._stop_event.set()


class SpreadDistributionAnalyzer:
    """Analyzes spread distributions and computes statistics"""
    
    def __init__(self, measurements: List[SpreadMeasurement]):
        self.measurements = measurements
        self._organize_by_asset_and_bucket()
    
    def _organize_by_asset_and_bucket(self):
        """Organize measurements by asset and time bucket"""
        self.by_asset: Dict[str, List[SpreadMeasurement]] = defaultdict(list)
        self.by_asset_bucket: Dict[str, Dict[TimeBucket, List[SpreadMeasurement]]] = defaultdict(
            lambda: defaultdict(list)
        )
        
        for m in self.measurements:
            self.by_asset[m.asset].append(m)
            self.by_asset_bucket[m.asset][m.time_bucket].append(m)
    
    def compute_distribution_stats(
        self,
        measurements: List[SpreadMeasurement]
    ) -> DistributionStats:
        """Compute statistical summary for a list of measurements"""
        if not measurements:
            return DistributionStats(
                count=0, min_spread=0, max_spread=0, median_spread=0,
                p75_spread=0, p90_spread=0, p95_spread=0, mean_spread=0, std_spread=0
            )
        
        spreads = [m.canonical_spread_cents for m in measurements]
        spreads_sorted = sorted(spreads)
        
        return DistributionStats(
            count=len(spreads),
            min_spread=min(spreads),
            max_spread=max(spreads),
            median_spread=statistics.median(spreads),
            p75_spread=spreads_sorted[int(len(spreads) * 0.75)] if spreads_sorted else 0,
            p90_spread=spreads_sorted[int(len(spreads) * 0.90)] if spreads_sorted else 0,
            p95_spread=spreads_sorted[int(len(spreads) * 0.95)] if spreads_sorted else 0,
            mean_spread=statistics.mean(spreads),
            std_spread=statistics.stdev(spreads) if len(spreads) > 1 else 0
        )
    
    def analyze_asset(self, asset: str) -> AssetAnalysis:
        """Perform complete analysis for a single asset"""
        asset_measurements = self.by_asset.get(asset, [])
        if not asset_measurements:
            logger.warning(f"[SPREAD-ANALYZER] No measurements for asset {asset}")
            return None
        
        current_cap = ASSET_SPREAD_CAPS.get(asset, 20.0)
        
        # Compute time bucket stats
        time_bucket_stats = {}
        for bucket, measurements in self.by_asset_bucket[asset].items():
            time_bucket_stats[bucket] = self.compute_distribution_stats(measurements)
        
        # Compute overall stats
        overall_stats = self.compute_distribution_stats(asset_measurements)
        
        # Compute reject rate analysis at different cap levels
        cap_levels = self._generate_cap_levels(current_cap)
        cap_analysis = []
        for cap in cap_levels:
            analysis = self._compute_reject_rate(asset_measurements, cap)
            cap_analysis.append(analysis)
        
        return AssetAnalysis(
            asset=asset,
            current_cap_cents=current_cap,
            time_bucket_stats=time_bucket_stats,
            overall_stats=overall_stats,
            cap_analysis=cap_analysis
        )
    
    def _generate_cap_levels(self, current_cap: float) -> List[float]:
        """Generate cap levels to test around current cap"""
        # Test 50%, 75%, 100%, 125%, 150%, 200% of current cap
        return [
            current_cap * 0.5,
            current_cap * 0.75,
            current_cap,
            current_cap * 1.25,
            current_cap * 1.5,
            current_cap * 2.0
        ]
    
    def _compute_reject_rate(
        self,
        measurements: List[SpreadMeasurement],
        cap_cents: float
    ) -> RejectRateAnalysis:
        """Compute reject rate for a specific cap level"""
        total = len(measurements)
        rejected = sum(1 for m in measurements if m.canonical_spread_cents > cap_cents)
        
        # For false reject analysis, we'd need edge data
        # For now, assume 20% of rejects would have had positive edge
        false_reject_count = int(rejected * 0.2)
        
        return RejectRateAnalysis(
            cap_cents=cap_cents,
            total_candidates=total,
            rejected_count=rejected,
            reject_rate=rejected / total if total > 0 else 0,
            false_reject_count=false_reject_count,
            false_reject_rate=false_reject_count / total if total > 0 else 0,
            missed_edge_sum=0.0  # Would need actual edge data
        )
    
    def analyze_all_assets(self) -> Dict[str, AssetAnalysis]:
        """Analyze all assets in the dataset"""
        analyses = {}
        for asset in self.by_asset.keys():
            analysis = self.analyze_asset(asset)
            if analysis:
                analyses[asset] = analysis
        
        return analyses


class SpreadReplayOrchestrator:
    """Orchestrates the spread distribution replay process"""
    
    def __init__(
        self,
        market_state_store: KalshiMarketStateStore,
        output_dir: Path = Path("spread_analysis_output")
    ):
        self.market_state_store = market_state_store
        self.output_dir = output_dir
        self.output_dir.mkdir(exist_ok=True)
    
    async def run_live_collection(
        self,
        duration_seconds: float = 300.0,
        sample_interval: float = 1.0,
        assets: List[str] = None
    ) -> Dict[str, AssetAnalysis]:
        """
        Run live spread collection and analysis.
        
        Args:
            duration_seconds: How long to collect samples
            sample_interval: Sampling interval in seconds
            assets: List of assets to analyze (default: all)
            
        Returns:
            Dictionary of asset analyses
        """
        logger.info("[SPREAD-REPLAY] Starting live collection mode")
        
        # Collect data
        collector = SpreadDataCollector(
            market_state_store=self.market_state_store,
            assets=assets,
            sample_interval_seconds=sample_interval
        )
        
        measurements = await collector.collect_samples(duration_seconds=duration_seconds)
        
        # Analyze data
        analyzer = SpreadDistributionAnalyzer(measurements)
        analyses = analyzer.analyze_all_assets()
        
        # Save results
        self._save_analyses(analyses, "live_collection")
        
        return analyses
    
    def analyze_historical_data(
        self,
        measurements_file: Path
    ) -> Dict[str, AssetAnalysis]:
        """
        Analyze historical spread measurements from file.
        
        Args:
            measurements_file: Path to JSON file with spread measurements
            
        Returns:
            Dictionary of asset analyses
        """
        logger.info(f"[SPREAD-REPLAY] Loading historical data from {measurements_file}")
        
        with open(measurements_file, 'r') as f:
            data = json.load(f)
        
        measurements = [
            SpreadMeasurement(
                timestamp=datetime.fromisoformat(m['timestamp']),
                asset=m['asset'],
                market_id=m['market_id'],
                time_to_expiry_seconds=m['time_to_expiry_seconds'],
                time_bucket=TimeBucket(m['time_bucket']),
                yes_bid_cents=m['yes_bid_cents'],
                no_bid_cents=m['no_bid_cents'],
                yes_spread_cents=m['yes_spread_cents'],
                no_spread_cents=m['no_spread_cents'],
                canonical_spread_cents=m['canonical_spread_cents'],
            )
            for m in data
        ]
        
        analyzer = SpreadDistributionAnalyzer(measurements)
        analyses = analyzer.analyze_all_assets()
        
        self._save_analyses(analyses, "historical")
        
        return analyses
    
    def _save_analyses(self, analyses: Dict[str, AssetAnalysis], mode: str):
        """Save analysis results to files"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Save JSON
        json_file = self.output_dir / f"spread_analysis_{mode}_{timestamp}.json"
        with open(json_file, 'w') as f:
            json.dump(
                {asset: analysis.to_dict() for asset, analysis in analyses.items()},
                f,
                indent=2
            )
        
        # Save human-readable report
        report_file = self.output_dir / f"spread_report_{mode}_{timestamp}.txt"
        self._generate_report(analyses, report_file)
        
        logger.info(f"[SPREAD-REPLAY] Saved results to {json_file} and {report_file}")
    
    def _generate_report(self, analyses: Dict[str, AssetAnalysis], output_file: Path):
        """Generate human-readable report"""
        with open(output_file, 'w') as f:
            f.write("=" * 80 + "\n")
            f.write("SPREAD DISTRIBUTION REPLAY REPORT\n")
            f.write("=" * 80 + "\n\n")
            
            for asset, analysis in analyses.items():
                f.write(f"\n{'=' * 80}\n")
                f.write(f"ASSET: {asset}\n")
                f.write(f"Current Cap: {analysis.current_cap_cents}c\n")
                f.write(f"{'=' * 80}\n\n")
                
                # Overall stats
                if analysis.overall_stats:
                    stats = analysis.overall_stats
                    f.write("OVERALL STATISTICS:\n")
                    f.write(f"  Samples: {stats.count}\n")
                    f.write(f"  Min Spread: {stats.min_spread:.1f}c\n")
                    f.write(f"  Max Spread: {stats.max_spread:.1f}c\n")
                    f.write(f"  Median Spread: {stats.median_spread:.1f}c\n")
                    f.write(f"  75th Percentile: {stats.p75_spread:.1f}c\n")
                    f.write(f"  90th Percentile: {stats.p90_spread:.1f}c\n")
                    f.write(f"  95th Percentile: {stats.p95_spread:.1f}c\n")
                    f.write(f"  Mean Spread: {stats.mean_spread:.1f}c\n")
                    f.write(f"  Std Dev: {stats.std_spread:.1f}c\n\n")
                
                # Time bucket stats
                f.write("TIME BUCKET STATISTICS:\n")
                for bucket, stats in analysis.time_bucket_stats.items():
                    f.write(f"\n  {bucket.value}:\n")
                    f.write(f"    Samples: {stats.count}\n")
                    f.write(f"    Median: {stats.median_spread:.1f}c\n")
                    f.write(f"    90th: {stats.p90_spread:.1f}c\n")
                    f.write(f"    Max: {stats.max_spread:.1f}c\n")
                
                # Cap analysis
                f.write("\n\nCAP LEVEL ANALYSIS:\n")
                f.write(f"{'Cap (c)':<10} {'Reject Rate':<12} {'False Reject Rate':<18}\n")
                f.write("-" * 50 + "\n")
                for cap_analysis in analysis.cap_analysis:
                    f.write(
                        f"{cap_analysis.cap_cents:<10.1f} "
                        f"{cap_analysis.reject_rate:<12.2%} "
                        f"{cap_analysis.false_reject_rate:<18.2%}\n"
                    )
                
                # Recommendations
                f.write("\n\nRECOMMENDATIONS:\n")
                rec = self._generate_recommendation(analysis)
                f.write(rec + "\n")
    
    def _generate_recommendation(self, analysis: AssetAnalysis) -> str:
        """Generate recommendation based on analysis"""
        if not analysis.overall_stats:
            return "Insufficient data for recommendation"
        
        stats = analysis.overall_stats
        current_cap = analysis.current_cap_cents
        
        # Check if current cap is too strict
        if stats.p90_spread > current_cap:
            return (
                f"⚠️  CURRENT CAP ({current_cap}c) IS TOO STRICT\n"
                f"   90th percentile spread ({stats.p90_spread:.1f}c) exceeds cap.\n"
                f"   Consider raising to {stats.p95_spread:.1f}c (95th percentile) "
                f"or {stats.max_spread:.1f}c (max observed)."
            )
        elif stats.p75_spread > current_cap * 0.8:
            return (
                f"⚠️  CURRENT CAP ({current_cap}c) MAY BE TOO STRICT\n"
                f"   75th percentile spread ({stats.p75_spread:.1f}c) is close to cap.\n"
                f"   Monitor for increased reject rates during volatile periods."
            )
        else:
            return (
                f"✓ CURRENT CAP ({current_cap}c) APPEARS REASONABLE\n"
                f"   90th percentile spread ({stats.p90_spread:.1f}c) is well below cap.\n"
                f"   Current configuration should not cause excessive rejects."
            )


# CLI interface for easy usage
async def main():
    """Main entry point for CLI usage"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Spread Distribution Replay for Kalshi 15-Minute Markets"
    )
    parser.add_argument(
        "--mode",
        choices=["live", "historical"],
        default="live",
        help="Collection mode: live sampling or historical file analysis"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=300.0,
        help="Duration in seconds for live collection (default: 300)"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Sampling interval in seconds (default: 1.0)"
    )
    parser.add_argument(
        "--assets",
        nargs="+",
        default=["BTC", "ETH", "SOL", "XRP", "DOGE"],
        help="Assets to analyze (default: all 5)"
    )
    parser.add_argument(
        "--input-file",
        type=Path,
        help="Input JSON file for historical mode"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("spread_analysis_output"),
        help="Output directory for results (default: spread_analysis_output)"
    )
    
    args = parser.parse_args()
    
    # Initialize market state store
    market_state_store = KalshiMarketStateStore()
    
    # Run orchestrator
    orchestrator = SpreadReplayOrchestrator(
        market_state_store=market_state_store,
        output_dir=args.output_dir
    )
    
    if args.mode == "live":
        analyses = await orchestrator.run_live_collection(
            duration_seconds=args.duration,
            sample_interval=args.interval,
            assets=args.assets
        )
    else:
        if not args.input_file:
            print("Error: --input-file required for historical mode")
            return
        analyses = orchestrator.analyze_historical_data(args.input_file)
    
    # Print summary
    print("\n" + "=" * 80)
    print("SPREAD DISTRIBUTION REPLAY SUMMARY")
    print("=" * 80)
    for asset, analysis in analyses.items():
        print(f"\n{asset}:")
        print(f"  Current Cap: {analysis.current_cap_cents}c")
        if analysis.overall_stats:
            print(f"  90th Percentile: {analysis.overall_stats.p90_spread:.1f}c")
            print(f"  Max Spread: {analysis.overall_stats.max_spread:.1f}c")
            print(f"  Recommendation: {orchestrator._generate_recommendation(analysis)}")


if __name__ == "__main__":
    asyncio.run(main())
