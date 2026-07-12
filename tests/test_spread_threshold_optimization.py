"""
Spread Threshold Optimization Test

This script tests multiple spread threshold levels to find the optimal balance
between trade frequency and execution quality for the 15m crypto trading system.

Based on 2026 research on prediction market liquidity:
- 1-2 cents: High-liquidity markets (major sports, political events)
- 3-5 cents: Moderate-liquidity markets (crypto price markets typical range)
- 6-10 cents: Lower-liquidity markets (niche events, new contracts)
- 10+ cents: Illiquid or stale markets

Current threshold: 20c (too strict, generating zero candidates)
Test range: 5c, 10c, 15c, 20c, 25c, 30c
"""

import sys
import os
import yaml
import logging
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger("test_spread_threshold_optimization")

# Test Configuration
TEST_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
TEST_THRESHOLDS = [5, 10, 15, 20, 25, 30]  # Spread thresholds in cents
CONFIG_FILES = {
    "profile": "config/profiles/kalshi_crypto_15m_v2.yaml",
    "thresholds": "config/kalshi_15m_thresholds.yaml",
}


@dataclass
class ThresholdTestResult:
    """Result of testing a specific spread threshold."""
    threshold_cents: int
    total_markets_tested: int = 0
    markets_passing_filter: int = 0
    pass_rate_pct: float = 0.0
    avg_spread_cents: float = 0.0
    avg_depth_yes: float = 0.0
    avg_depth_no: float = 0.0
    avg_liquidity_score: float = 0.0
    avg_quality_score: float = 0.0
    candidates_per_asset: Dict[str, int] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class OptimizationReport:
    """Complete optimization report."""
    test_date: str
    results: List[ThresholdTestResult] = field(default_factory=list)
    optimal_threshold: int = 0
    rationale: str = ""
    
    def print_summary(self):
        print(f"\n{'='*80}")
        print("SPREAD THRESHOLD OPTIMIZATION REPORT")
        print(f"Test Date: {self.test_date}")
        print(f"{'='*80}\n")
        
        print(f"{'Threshold':<12} {'Pass Rate':<12} {'Avg Spread':<12} {'Avg Depth':<12} {'Avg Quality':<12}")
        print("-" * 80)
        
        for result in self.results:
            print(f"{result.threshold_cents:<12}c {result.pass_rate_pct:<12.1f}% "
                  f"{result.avg_spread_cents:<12.1f}c {result.avg_depth_yes:<12.0f} "
                  f"{result.avg_quality_score:<12.2f}")
        
        print("\n" + "="*80)
        print(f"OPTIMAL THRESHOLD: {self.optimal_threshold}c")
        print(f"RATIONALE: {self.rationale}")
        print("="*80 + "\n")


class ConfigLoader:
    """Load configuration files."""
    
    def __init__(self, base_path: str = None):
        if base_path is None:
            base_path = str(Path(__file__).parent.parent)
        self.base_path = Path(base_path)
        self.configs: Dict[str, Any] = {}
        self.load_all_configs()
    
    def load_all_configs(self):
        """Load all configuration files."""
        for name, path in CONFIG_FILES.items():
            full_path = self.base_path / path
            try:
                with open(full_path, 'r', encoding='utf-8') as f:
                    self.configs[name] = yaml.safe_load(f)
                logger.info(f"Loaded config: {name}")
            except Exception as e:
                logger.error(f"Failed to load config {name}: {e}")
                self.configs[name] = {}
    
    def get_config(self, name: str) -> Dict[str, Any]:
        """Get a specific configuration."""
        return self.configs.get(name, {})


class SpreadThresholdOptimizer:
    """Optimize spread threshold based on market data simulation."""
    
    def __init__(self, loader: ConfigLoader):
        self.loader = loader
        self.profile = loader.get_config("profile")
        self.thresholds = loader.get_config("thresholds")
        self.report = OptimizationReport(test_date=datetime.now(timezone.utc).isoformat())
    
    def simulate_market_data(self, threshold_cents: int) -> List[Dict[str, Any]]:
        """
        Simulate market data for testing spread thresholds.
        
        This creates realistic market data based on observed patterns from
        Kalshi 15m crypto markets. The simulation accounts for:
        - Spread distribution (most markets cluster around certain spread levels)
        - Depth correlation with spread (tighter spreads = deeper books)
        - Asset-specific characteristics (BTC deeper than DOGE)
        """
        markets = []
        
        # Asset-specific spread characteristics (based on research)
        asset_spread_profiles = {
            "BTC": {"mean_spread": 8, "std_spread": 3, "depth_multiplier": 1.5},
            "ETH": {"mean_spread": 10, "std_spread": 4, "depth_multiplier": 1.3},
            "SOL": {"mean_spread": 12, "std_spread": 5, "depth_multiplier": 1.0},
            "XRP": {"mean_spread": 14, "std_spread": 6, "depth_multiplier": 0.9},
            "DOGE": {"mean_spread": 16, "std_spread": 7, "depth_multiplier": 0.8},
        }
        
        # Generate 5 markets per asset (typical 15m cycle)
        for asset in TEST_ASSETS:
            profile = asset_spread_profiles[asset]
            
            for i in range(5):
                # Generate spread with some randomness
                import random
                random.seed(f"{asset}_{i}_{threshold_cents}")  # Reproducible
                
                spread = max(1, int(random.gauss(profile["mean_spread"], profile["std_spread"])))
                
                # Depth correlates inversely with spread
                base_depth = 50 * profile["depth_multiplier"]
                depth_factor = max(0.3, 1.0 - (spread / 30.0))  # Tighter spread = more depth
                depth_yes = int(base_depth * depth_factor * random.uniform(0.8, 1.2))
                depth_no = int(base_depth * depth_factor * random.uniform(0.8, 1.2))
                
                # Quality score based on spread and depth
                quality_score = self._calculate_quality_score(spread, depth_yes, depth_no)
                
                markets.append({
                    "asset": asset,
                    "market_id": f"{asset}_15M_{i}",
                    "spread_cents": spread,
                    "depth_yes": depth_yes,
                    "depth_no": depth_no,
                    "quality_score": quality_score,
                    "liquidity_score": (depth_yes + depth_no) / 2,
                })
        
        return markets
    
    def _calculate_quality_score(self, spread_cents: int, depth_yes: int, depth_no: int) -> float:
        """Calculate quality score based on spread and depth."""
        # Lower spread = higher quality
        spread_score = max(0, 1.0 - (spread_cents / 50.0))
        
        # Higher depth = higher quality
        depth_score = min(1.0, (depth_yes + depth_no) / 200.0)
        
        # Weighted average (spread more important than depth)
        quality = 0.7 * spread_score + 0.3 * depth_score
        return quality
    
    def test_threshold(self, threshold_cents: int) -> ThresholdTestResult:
        """Test a specific spread threshold."""
        result = ThresholdTestResult(threshold_cents=threshold_cents)
        
        # Simulate market data
        markets = self.simulate_market_data(threshold_cents)
        result.total_markets_tested = len(markets)
        
        # Filter by spread threshold
        passing_markets = [m for m in markets if m["spread_cents"] <= threshold_cents]
        result.markets_passing_filter = len(passing_markets)
        result.pass_rate_pct = (result.markets_passing_filter / result.total_markets_tested) * 100
        
        # Calculate averages for passing markets
        if passing_markets:
            result.avg_spread_cents = sum(m["spread_cents"] for m in passing_markets) / len(passing_markets)
            result.avg_depth_yes = sum(m["depth_yes"] for m in passing_markets) / len(passing_markets)
            result.avg_depth_no = sum(m["depth_no"] for m in passing_markets) / len(passing_markets)
            result.avg_liquidity_score = sum(m["liquidity_score"] for m in passing_markets) / len(passing_markets)
            result.avg_quality_score = sum(m["quality_score"] for m in passing_markets) / len(passing_markets)
            
            # Count candidates per asset
            for asset in TEST_ASSETS:
                asset_candidates = [m for m in passing_markets if m["asset"] == asset]
                result.candidates_per_asset[asset] = len(asset_candidates)
        
        # Generate recommendations
        result.recommendations = self._generate_recommendations(result)
        
        return result
    
    def _generate_recommendations(self, result: ThresholdTestResult) -> List[str]:
        """Generate recommendations for this threshold."""
        recommendations = []
        
        if result.pass_rate_pct < 10:
            recommendations.append("TOO STRICT: Very few markets pass filter")
        elif result.pass_rate_pct < 30:
            recommendations.append("STRICT: Limited trading opportunities")
        elif result.pass_rate_pct < 50:
            recommendations.append("MODERATE: Balanced trade frequency")
        elif result.pass_rate_pct < 70:
            recommendations.append("RELAXED: Good trade frequency")
        else:
            recommendations.append("VERY RELAXED: May include low-quality markets")
        
        if result.avg_quality_score < 0.5:
            recommendations.append("LOW QUALITY: Average quality below 0.5")
        elif result.avg_quality_score < 0.7:
            recommendations.append("MODERATE QUALITY: Acceptable quality")
        else:
            recommendations.append("HIGH QUALITY: Good market quality")
        
        if result.avg_depth_yes < 20:
            recommendations.append("SHALLOW DEPTH: Risk of slippage")
        elif result.avg_depth_yes < 40:
            recommendations.append("MODERATE DEPTH: Manageable slippage")
        else:
            recommendations.append("DEEP LIQUIDITY: Low slippage risk")
        
        return recommendations
    
    def run_optimization(self) -> OptimizationReport:
        """Run full optimization across all thresholds."""
        print(f"\n{'='*80}")
        print("RUNNING SPREAD THRESHOLD OPTIMIZATION")
        print(f"Testing thresholds: {TEST_THRESHOLDS}")
        print(f"Assets: {TEST_ASSETS}")
        print(f"{'='*80}\n")
        
        results = []
        for threshold in TEST_THRESHOLDS:
            print(f"Testing threshold: {threshold}c...")
            result = self.test_threshold(threshold)
            results.append(result)
            
            print(f"  Pass rate: {result.pass_rate_pct:.1f}%")
            print(f"  Avg spread: {result.avg_spread_cents:.1f}c")
            print(f"  Avg quality: {result.avg_quality_score:.2f}")
            print(f"  Candidates per asset: {result.candidates_per_asset}")
            print(f"  Recommendations: {', '.join(result.recommendations)}")
            print()
        
        self.report.results = results
        self.report.optimal_threshold = self._find_optimal_threshold(results)
        self.report.rationale = self._generate_rationale(results, self.report.optimal_threshold)
        
        return self.report
    
    def _find_optimal_threshold(self, results: List[ThresholdTestResult]) -> int:
        """
        Find optimal threshold based on multi-criteria optimization.
        
        Optimization criteria:
        1. Pass rate between 30-60% (balanced trade frequency)
        2. Quality score >= 0.6 (acceptable market quality)
        3. Depth >= 30 contracts (manageable slippage)
        4. Prefer lower threshold (tighter spread = better execution)
        """
        optimal = None
        best_score = -1
        
        for result in results:
            score = 0
            
            # Pass rate score (target: 30-60%)
            if 30 <= result.pass_rate_pct <= 60:
                score += 30
            elif 20 <= result.pass_rate_pct < 30:
                score += 20
            elif 60 < result.pass_rate_pct <= 70:
                score += 20
            elif result.pass_rate_pct >= 70:
                score += 10  # Too relaxed
            
            # Quality score (target: >= 0.6)
            if result.avg_quality_score >= 0.7:
                score += 30
            elif result.avg_quality_score >= 0.6:
                score += 20
            elif result.avg_quality_score >= 0.5:
                score += 10
            
            # Depth score (target: >= 30)
            if result.avg_depth_yes >= 50:
                score += 30
            elif result.avg_depth_yes >= 30:
                score += 20
            elif result.avg_depth_yes >= 20:
                score += 10
            
            # Prefer lower threshold (tighter spread)
            score += max(0, 10 - (result.threshold_cents / 5))
            
            if score > best_score:
                best_score = score
                optimal = result.threshold_cents
        
        return optimal if optimal else 20  # Default to 20c if no optimal found
    
    def _generate_rationale(self, results: List[ThresholdTestResult], optimal_threshold: int) -> str:
        """Generate rationale for optimal threshold selection."""
        optimal_result = next(r for r in results if r.threshold_cents == optimal_threshold)
        
        rationale_parts = [
            f"Threshold {optimal_threshold}c achieves {optimal_result.pass_rate_pct:.1f}% pass rate, "
            f"providing balanced trade frequency without sacrificing quality.",
            f"Average quality score of {optimal_result.avg_quality_score:.2f} indicates "
            f"acceptable market conditions.",
            f"Average depth of {optimal_result.avg_depth_yes:.0f} contracts suggests "
            f"manageable slippage risk for $1 exposure model."
        ]
        
        # Compare with current 20c threshold
        current_result = next(r for r in results if r.threshold_cents == 20)
        if optimal_threshold != 20:
            quality_improvement = optimal_result.avg_quality_score - current_result.avg_quality_score
            depth_improvement = optimal_result.avg_depth_yes - current_result.avg_depth_yes
            rationale_parts.append(
                f"Compared to current 20c threshold ({current_result.pass_rate_pct:.1f}% pass rate, "
                f"{current_result.avg_quality_score:.2f} quality, {current_result.avg_depth_yes:.0f} depth), "
                f"this provides {quality_improvement:+.2f} higher quality and {depth_improvement:+.0f} more depth "
                f"with {optimal_result.pass_rate_pct:.1f}% pass rate."
            )
        
        return " ".join(rationale_parts)


def main():
    """Run spread threshold optimization."""
    print(f"\n{'='*80}")
    print("SPREAD THRESHOLD OPTIMIZATION TEST")
    print(f"Testing Date: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*80}\n")
    
    # Load configurations
    print("Loading configuration files...")
    loader = ConfigLoader()
    
    # Run optimization
    optimizer = SpreadThresholdOptimizer(loader)
    report = optimizer.run_optimization()
    
    # Print summary
    report.print_summary()
    
    # Save detailed results to file
    output_file = Path(__file__).parent.parent / "output" / f"spread_threshold_optimization_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
    output_file.parent.mkdir(exist_ok=True)
    
    with open(output_file, 'w') as f:
        f.write("="*80 + "\n")
        f.write("SPREAD THRESHOLD OPTIMIZATION REPORT\n")
        f.write(f"Test Date: {report.test_date}\n")
        f.write("="*80 + "\n\n")
        
        f.write(f"{'Threshold':<12} {'Pass Rate':<12} {'Avg Spread':<12} {'Avg Depth':<12} {'Avg Quality':<12}\n")
        f.write("-" * 80 + "\n")
        
        for result in report.results:
            f.write(f"{result.threshold_cents:<12}c {result.pass_rate_pct:<12.1f}% "
                   f"{result.avg_spread_cents:<12.1f}c {result.avg_depth_yes:<12.0f} "
                   f"{result.avg_quality_score:<12.2f}\n")
        
        f.write("\n" + "="*80 + "\n")
        f.write(f"OPTIMAL THRESHOLD: {report.optimal_threshold}c\n")
        f.write(f"RATIONALE: {report.rationale}\n")
        f.write("="*80 + "\n")
        
        f.write("\nDETAILED RESULTS:\n\n")
        for result in report.results:
            f.write(f"Threshold: {result.threshold_cents}c\n")
            f.write(f"  Total markets tested: {result.total_markets_tested}\n")
            f.write(f"  Markets passing filter: {result.markets_passing_filter}\n")
            f.write(f"  Pass rate: {result.pass_rate_pct:.1f}%\n")
            f.write(f"  Avg spread: {result.avg_spread_cents:.1f}c\n")
            f.write(f"  Avg depth YES: {result.avg_depth_yes:.0f}\n")
            f.write(f"  Avg depth NO: {result.avg_depth_no:.0f}\n")
            f.write(f"  Avg liquidity score: {result.avg_liquidity_score:.2f}\n")
            f.write(f"  Avg quality score: {result.avg_quality_score:.2f}\n")
            f.write(f"  Candidates per asset: {result.candidates_per_asset}\n")
            f.write(f"  Recommendations: {', '.join(result.recommendations)}\n")
            f.write("\n")
    
    print(f"Detailed results saved to: {output_file}")
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
