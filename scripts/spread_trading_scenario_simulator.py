#!/usr/bin/env python3
"""
MERID Spread Trading Scenario Simulator

Comprehensive spread-focused trading scenario simulation for the 15-minute Kalshi crypto trading system.
This script tests spread configuration across different market conditions and volatility regimes.

Based on 2026 industry best practices for algorithmic trading validation.

Usage:
    python scripts/spread_trading_scenario_simulator.py --profile kalshi_crypto_15m_v2
"""

import sys
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from enum import Enum
import json
from datetime import datetime, timezone

# Add project root to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from utils.logger import get_logger

logger = get_logger("scripts.spread_trading_scenario_simulator")


class VolatilityRegime(Enum):
    """Volatility regimes for dynamic spread testing."""
    CALM = "calm"
    ELEVATED = "elevated"
    VIOLENT = "violent"


class SpreadThresholdType(Enum):
    """Types of spread thresholds in the system."""
    COARSE_FILTER = "coarse_filter"  # 40c - guardrails, universe, spread_gate
    EDGE_DEPENDENT = "edge_dependent"  # 25c - max_spread_for_edge
    QUALITY_METRIC = "quality_metric"  # 15c - spread optimizer quality assessment
    DYNAMIC_CALM = "dynamic_calm"  # 2c - calm regime (200bp)
    DYNAMIC_ELEVATED = "dynamic_elevated"  # 3c - elevated regime (300bp)
    DYNAMIC_VIOLENT = "dynamic_violent"  # 5c - violent regime (500bp)


@dataclass
class SpreadScenario:
    """Definition of a spread trading scenario to simulate."""
    name: str
    description: str
    asset: str  # BTC, ETH, SOL, XRP, DOGE
    spread_cents: float
    bid_cents: int
    ask_cents: int
    depth_yes: int
    depth_no: int
    edge_pct: float
    volatility_regime: VolatilityRegime
    expected_outcome: str  # "ACCEPT", "REJECT", "WARNING"
    expected_reason: str
    threshold_type: SpreadThresholdType


@dataclass
class SpreadSimulationResult:
    """Result of simulating a spread scenario."""
    scenario: SpreadScenario
    actual_outcome: str
    actual_reason: str
    passed: bool
    threshold_check: Dict[str, Any]
    quality_metrics: Dict[str, float]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SpreadTradingScenarioSimulator:
    """
    Spread-focused trading scenario simulator for MERID 15M stack.
    
    Tests spread configuration across:
    - Coarse filtering (75c threshold)
    - Edge-dependent limits (25c)
    - Quality assessment (15c)
    - Dynamic volatility regimes (2-5c)
    """

    def __init__(self, profile_name: str = "kalshi_crypto_15m_v2"):
        """
        Initialize the spread simulator.
        
        Args:
            profile_name: Name of the profile to load
        """
        self.profile_name = profile_name
        self.profile_config = None
        self.results: List[SpreadSimulationResult] = []
        
        # Load profile configuration
        self._load_profile()
        
        # Initialize spread thresholds from profile
        self._initialize_thresholds()
    
    def _load_profile(self):
        """Load the profile configuration from YAML."""
        try:
            import yaml
            profile_path = repo_root / "config" / "profiles" / f"{self.profile_name}.yaml"
            
            with open(profile_path, 'r', encoding='utf-8') as f:
                self.profile_config = yaml.safe_load(f)
            
            logger.info(f"[SPREAD-SIMULATOR] Loaded profile: {self.profile_name}")
        except Exception as e:
            logger.error(f"[SPREAD-SIMULATOR] Failed to load profile: {e}")
            raise
    
    def _initialize_thresholds(self):
        """Initialize spread thresholds from profile configuration."""
        # Coarse filter threshold (75c)
        guardrails = self.profile_config.get('guardrails', {})
        self.coarse_filter_threshold = guardrails.get('max_spread_cents', 40)
        
        # Edge-dependent threshold (25c)
        self.edge_dependent_threshold = guardrails.get('max_spread_for_edge', {}).get('default', 25)
        
        # Quality metric threshold (15c) - from spread_optimizer
        self.quality_metric_threshold = 15
        
        # Dynamic volatility regime thresholds (basis points -> cents)
        # calm: 200bp = 2c, elevated: 300bp = 3c, violent: 500bp = 5c
        self.dynamic_calm_threshold = 2.0  # 200bp
        self.dynamic_elevated_threshold = 3.0  # 300bp
        self.dynamic_violent_threshold = 5.0  # 500bp
        
        logger.info(
            f"[SPREAD-SIMULATOR] Thresholds initialized: "
            f"coarse={self.coarse_filter_threshold}c, "
            f"edge_dependent={self.edge_dependent_threshold}c, "
            f"quality={self.quality_metric_threshold}c, "
            f"dynamic_calm={self.dynamic_calm_threshold}c, "
            f"dynamic_elevated={self.dynamic_elevated_threshold}c, "
            f"dynamic_violent={self.dynamic_violent_threshold}c"
        )
    
    def _check_coarse_filter(self, spread_cents: float) -> Tuple[bool, str]:
        """
        Check against coarse filter threshold (75c).
        
        Args:
            spread_cents: Current spread in cents
            
        Returns:
            Tuple of (passed, reason)
        """
        if spread_cents > self.coarse_filter_threshold:
            return False, f"Spread {spread_cents}c exceeds coarse filter threshold {self.coarse_filter_threshold}c"
        return True, f"Spread {spread_cents}c within coarse filter threshold {self.coarse_filter_threshold}c"
    
    def _check_edge_dependent(self, spread_cents: float, edge_pct: float) -> Tuple[bool, str]:
        """
        Check against edge-dependent threshold (25c with edge multiplier).
        
        Args:
            spread_cents: Current spread in cents
            edge_pct: Edge percentage
            
        Returns:
            Tuple of (passed, reason)
        """
        # Require edge >= 1.1x spread (from profile spread_guard_edge_multiplier)
        spread_guard_edge_multiplier = self.profile_config.get('guardrails', {}).get('spread_guard_edge_multiplier', 1.1)
        min_edge_for_spread = (spread_cents / 100.0) * spread_guard_edge_multiplier
        
        if spread_cents > self.edge_dependent_threshold:
            return False, f"Spread {spread_cents}c exceeds edge-dependent threshold {self.edge_dependent_threshold}c"
        
        if edge_pct < min_edge_for_spread:
            return False, f"Edge {edge_pct:.2%} below required {min_edge_for_spread:.2%} for spread {spread_cents}c"
        
        return True, f"Spread {spread_cents}c and edge {edge_pct:.2%} pass edge-dependent check"
    
    def _check_quality_metric(self, spread_cents: float, total_depth: int) -> Tuple[bool, str, float]:
        """
        Check against quality metric threshold (15c with depth scoring).
        
        Args:
            spread_cents: Current spread in cents
            total_depth: Total book depth
            
        Returns:
            Tuple of (passed, reason, quality_score)
        """
        # Calculate liquidity score (from spread_optimizer logic)
        spread_score = max(0.0, 1.0 - (spread_cents / self.quality_metric_threshold))
        depth_score = min(1.0, total_depth / 50.0)  # Normalize to 50 levels
        liquidity_score = (spread_score * 0.7 + depth_score * 0.3)
        
        # Calculate quality score
        spread_quality = max(0.0, 1.0 - (spread_cents / self.quality_metric_threshold))
        depth_quality = min(1.0, total_depth / 5.0)  # Normalize to 5 levels
        quality_score = (spread_quality * 0.4 + depth_quality * 0.3 + liquidity_score * 0.3)
        
        if spread_cents > self.quality_metric_threshold:
            return False, f"Spread {spread_cents}c exceeds quality metric threshold {self.quality_metric_threshold}c", quality_score
        
        if quality_score < 0.5:
            return False, f"Quality score {quality_score:.3f} below minimum 0.5", quality_score
        
        return True, f"Quality score {quality_score:.3f} acceptable", quality_score
    
    def _check_dynamic_threshold(self, spread_cents: float, regime: VolatilityRegime) -> Tuple[bool, str]:
        """
        Check against dynamic volatility regime threshold.
        
        Args:
            spread_cents: Current spread in cents
            regime: Volatility regime
            
        Returns:
            Tuple of (passed, reason)
        """
        if regime == VolatilityRegime.CALM:
            threshold = self.dynamic_calm_threshold
        elif regime == VolatilityRegime.ELEVATED:
            threshold = self.dynamic_elevated_threshold
        else:  # VIOLENT
            threshold = self.dynamic_violent_threshold
        
        if spread_cents > threshold:
            return False, f"Spread {spread_cents}c exceeds {regime.value} regime threshold {threshold}c"
        return True, f"Spread {spread_cents}c within {regime.value} regime threshold {threshold}c"
    
    def simulate_scenario(self, scenario: SpreadScenario) -> SpreadSimulationResult:
        """
        Simulate a single spread scenario.
        
        Args:
            scenario: Spread scenario to simulate
            
        Returns:
            SpreadSimulationResult with validation outcomes
        """
        threshold_check = {}
        quality_metrics = {}
        
        # Check based on threshold type
        if scenario.threshold_type == SpreadThresholdType.COARSE_FILTER:
            passed, reason = self._check_coarse_filter(scenario.spread_cents)
            threshold_check['coarse_filter'] = {'passed': passed, 'reason': reason}
            actual_outcome = "ACCEPT" if passed else "REJECT"
            actual_reason = reason
        
        elif scenario.threshold_type == SpreadThresholdType.EDGE_DEPENDENT:
            passed, reason = self._check_edge_dependent(scenario.spread_cents, scenario.edge_pct)
            threshold_check['edge_dependent'] = {'passed': passed, 'reason': reason}
            actual_outcome = "ACCEPT" if passed else "REJECT"
            actual_reason = reason
        
        elif scenario.threshold_type == SpreadThresholdType.QUALITY_METRIC:
            total_depth = scenario.depth_yes + scenario.depth_no
            passed, reason, quality_score = self._check_quality_metric(scenario.spread_cents, total_depth)
            threshold_check['quality_metric'] = {'passed': passed, 'reason': reason}
            quality_metrics['quality_score'] = quality_score
            quality_metrics['liquidity_score'] = max(0.0, 1.0 - (scenario.spread_cents / self.quality_metric_threshold)) * 0.7 + min(1.0, total_depth / 50.0) * 0.3
            actual_outcome = "ACCEPT" if passed else "REJECT"
            actual_reason = reason
        
        elif scenario.threshold_type in [SpreadThresholdType.DYNAMIC_CALM, 
                                        SpreadThresholdType.DYNAMIC_ELEVATED,
                                        SpreadThresholdType.DYNAMIC_VIOLENT]:
            passed, reason = self._check_dynamic_threshold(scenario.spread_cents, scenario.volatility_regime)
            threshold_check['dynamic_regime'] = {'passed': passed, 'reason': reason, 'regime': scenario.volatility_regime.value}
            actual_outcome = "ACCEPT" if passed else "REJECT"
            actual_reason = reason
        
        # Determine if scenario passed
        scenario_passed = (actual_outcome == scenario.expected_outcome)
        
        return SpreadSimulationResult(
            scenario=scenario,
            actual_outcome=actual_outcome,
            actual_reason=actual_reason,
            passed=scenario_passed,
            threshold_check=threshold_check,
            quality_metrics=quality_metrics
        )
    
    def generate_scenarios(self) -> List[SpreadScenario]:
        """
        Generate comprehensive spread trading scenarios.
        
        Returns:
            List of SpreadScenario objects
        """
        scenarios = []
        
        # === Coarse Filter Scenarios (40c threshold) ===
        scenarios.append(SpreadScenario(
            name="coarse_filter_normal_spread",
            description="Normal spread within coarse filter (40c)",
            asset="BTC",
            spread_cents=10.0,
            bid_cents=45,
            ask_cents=55,
            depth_yes=10,
            depth_no=10,
            edge_pct=0.05,
            volatility_regime=VolatilityRegime.CALM,
            expected_outcome="ACCEPT",
            expected_reason="Spread within coarse filter threshold",
            threshold_type=SpreadThresholdType.COARSE_FILTER
        ))
        
        scenarios.append(SpreadScenario(
            name="coarse_filter_boundary",
            description="Spread at coarse filter boundary (40c)",
            asset="DOGE",
            spread_cents=40.0,
            bid_cents=20,
            ask_cents=95,
            depth_yes=5,
            depth_no=5,
            edge_pct=0.08,
            volatility_regime=VolatilityRegime.ELEVATED,
            expected_outcome="ACCEPT",
            expected_reason="Spread at coarse filter boundary",
            threshold_type=SpreadThresholdType.COARSE_FILTER
        ))
        
        scenarios.append(SpreadScenario(
            name="coarse_filter_exceeds",
            description="Spread exceeds coarse filter (45c > 40c)",
            asset="DOGE",
            spread_cents=45.0,
            bid_cents=10,
            ask_cents=90,
            depth_yes=3,
            depth_no=3,
            edge_pct=0.10,
            volatility_regime=VolatilityRegime.VIOLENT,
            expected_outcome="REJECT",
            expected_reason="Spread exceeds coarse filter threshold",
            threshold_type=SpreadThresholdType.COARSE_FILTER
        ))
        
        # === Edge-Dependent Scenarios (25c threshold) ===
        scenarios.append(SpreadScenario(
            name="edge_dependent_normal",
            description="Normal spread with sufficient edge (17% for 15c spread)",
            asset="ETH",
            spread_cents=15.0,
            bid_cents=40,
            ask_cents=55,
            depth_yes=8,
            depth_no=8,
            edge_pct=0.17,  # 17% edge meets 1.1x spread requirement (15c * 1.1 = 16.5c)
            volatility_regime=VolatilityRegime.CALM,
            expected_outcome="ACCEPT",
            expected_reason="Spread and edge pass edge-dependent check",
            threshold_type=SpreadThresholdType.EDGE_DEPENDENT
        ))
        
        scenarios.append(SpreadScenario(
            name="edge_dependent_insufficient_edge",
            description="Spread within threshold but insufficient edge",
            asset="SOL",
            spread_cents=20.0,
            bid_cents=35,
            ask_cents=55,
            depth_yes=6,
            depth_no=6,
            edge_pct=0.015,  # Below 1.1x spread requirement
            volatility_regime=VolatilityRegime.ELEVATED,
            expected_outcome="REJECT",
            expected_reason="Edge below required for spread",
            threshold_type=SpreadThresholdType.EDGE_DEPENDENT
        ))
        
        scenarios.append(SpreadScenario(
            name="edge_dependent_exceeds_threshold",
            description="Spread exceeds edge-dependent threshold (30c > 25c)",
            asset="XRP",
            spread_cents=30.0,
            bid_cents=30,
            ask_cents=60,
            depth_yes=4,
            depth_no=4,
            edge_pct=0.06,
            volatility_regime=VolatilityRegime.VIOLENT,
            expected_outcome="REJECT",
            expected_reason="Spread exceeds edge-dependent threshold",
            threshold_type=SpreadThresholdType.EDGE_DEPENDENT
        ))
        
        # === Quality Metric Scenarios (15c threshold) ===
        scenarios.append(SpreadScenario(
            name="quality_metric_high_quality",
            description="High quality spread with good depth",
            asset="BTC",
            spread_cents=5.0,
            bid_cents=47,
            ask_cents=52,
            depth_yes=20,
            depth_no=20,
            edge_pct=0.03,
            volatility_regime=VolatilityRegime.CALM,
            expected_outcome="ACCEPT",
            expected_reason="Quality score acceptable",
            threshold_type=SpreadThresholdType.QUALITY_METRIC
        ))
        
        scenarios.append(SpreadScenario(
            name="quality_metric_low_quality",
            description="Low quality spread with poor depth",
            asset="DOGE",
            spread_cents=20.0,
            bid_cents=30,
            ask_cents=50,
            depth_yes=2,
            depth_no=2,
            edge_pct=0.04,
            volatility_regime=VolatilityRegime.ELEVATED,
            expected_outcome="REJECT",
            expected_reason="Quality score below minimum",
            threshold_type=SpreadThresholdType.QUALITY_METRIC
        ))
        
        scenarios.append(SpreadScenario(
            name="quality_metric_exceeds_threshold",
            description="Spread exceeds quality metric threshold (20c > 15c)",
            asset="SOL",
            spread_cents=20.0,
            bid_cents=35,
            ask_cents=55,
            depth_yes=10,
            depth_no=10,
            edge_pct=0.05,
            volatility_regime=VolatilityRegime.VIOLENT,
            expected_outcome="REJECT",
            expected_reason="Spread exceeds quality metric threshold",
            threshold_type=SpreadThresholdType.QUALITY_METRIC
        ))
        
        # === Dynamic Volatility Regime Scenarios ===
        scenarios.append(SpreadScenario(
            name="dynamic_calm_regime",
            description="Calm regime with tight spread",
            asset="BTC",
            spread_cents=1.5,
            bid_cents=49,
            ask_cents=50.5,
            depth_yes=15,
            depth_no=15,
            edge_pct=0.02,
            volatility_regime=VolatilityRegime.CALM,
            expected_outcome="ACCEPT",
            expected_reason="Spread within calm regime threshold",
            threshold_type=SpreadThresholdType.DYNAMIC_CALM
        ))
        
        scenarios.append(SpreadScenario(
            name="dynamic_calm_exceeds",
            description="Calm regime but spread exceeds threshold (3c > 2c)",
            asset="ETH",
            spread_cents=3.0,
            bid_cents=48,
            ask_cents=51,
            depth_yes=12,
            depth_no=12,
            edge_pct=0.03,
            volatility_regime=VolatilityRegime.CALM,
            expected_outcome="REJECT",
            expected_reason="Spread exceeds calm regime threshold",
            threshold_type=SpreadThresholdType.DYNAMIC_CALM
        ))
        
        scenarios.append(SpreadScenario(
            name="dynamic_elevated_regime",
            description="Elevated regime with acceptable spread",
            asset="SOL",
            spread_cents=2.5,
            bid_cents=46,
            ask_cents=48.5,
            depth_yes=8,
            depth_no=8,
            edge_pct=0.025,
            volatility_regime=VolatilityRegime.ELEVATED,
            expected_outcome="ACCEPT",
            expected_reason="Spread within elevated regime threshold",
            threshold_type=SpreadThresholdType.DYNAMIC_ELEVATED
        ))
        
        scenarios.append(SpreadScenario(
            name="dynamic_violent_regime",
            description="Violent regime with wide but acceptable spread",
            asset="DOGE",
            spread_cents=4.5,
            bid_cents=42,
            ask_cents=46.5,
            depth_yes=5,
            depth_no=5,
            edge_pct=0.04,
            volatility_regime=VolatilityRegime.VIOLENT,
            expected_outcome="ACCEPT",
            expected_reason="Spread within violent regime threshold",
            threshold_type=SpreadThresholdType.DYNAMIC_VIOLENT
        ))
        
        scenarios.append(SpreadScenario(
            name="dynamic_violent_exceeds",
            description="Violent regime but spread exceeds threshold (6c > 5c)",
            asset="XRP",
            spread_cents=6.0,
            bid_cents=40,
            ask_cents=46,
            depth_yes=4,
            depth_no=4,
            edge_pct=0.05,
            volatility_regime=VolatilityRegime.VIOLENT,
            expected_outcome="REJECT",
            expected_reason="Spread exceeds violent regime threshold",
            threshold_type=SpreadThresholdType.DYNAMIC_VIOLENT
        ))
        
        # === Multi-Asset Spread Scenarios ===
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            scenarios.append(SpreadScenario(
                name=f"multi_asset_{asset.lower()}_coarse_filter",
                description=f"Coarse filter test for {asset}",
                asset=asset,
                spread_cents=35.0,  # Within 40c coarse filter threshold
                bid_cents=25,
                ask_cents=60,
                depth_yes=8,
                depth_no=8,
                edge_pct=0.05,
                volatility_regime=VolatilityRegime.ELEVATED,
                expected_outcome="ACCEPT",
                expected_reason="Spread within coarse filter for all assets",
                threshold_type=SpreadThresholdType.COARSE_FILTER
            ))
        
        return scenarios
    
    def run_simulation(self) -> Dict[str, Any]:
        """
        Run the complete spread scenario simulation.
        
        Returns:
            Dictionary with simulation results and summary
        """
        logger.info("[SPREAD-SIMULATOR] Starting spread scenario simulation")
        
        # Generate scenarios
        scenarios = self.generate_scenarios()
        logger.info(f"[SPREAD-SIMULATOR] Generated {len(scenarios)} scenarios")
        
        # Simulate each scenario
        for scenario in scenarios:
            result = self.simulate_scenario(scenario)
            self.results.append(result)
        
        # Calculate summary statistics
        total_scenarios = len(self.results)
        passed_scenarios = sum(1 for r in self.results if r.passed)
        failed_scenarios = total_scenarios - passed_scenarios
        
        # Group by threshold type
        by_threshold_type = {}
        for result in self.results:
            threshold_type = result.scenario.threshold_type.value
            if threshold_type not in by_threshold_type:
                by_threshold_type[threshold_type] = {'total': 0, 'passed': 0, 'failed': 0}
            by_threshold_type[threshold_type]['total'] += 1
            if result.passed:
                by_threshold_type[threshold_type]['passed'] += 1
            else:
                by_threshold_type[threshold_type]['failed'] += 1
        
        # Group by asset
        by_asset = {}
        for result in self.results:
            asset = result.scenario.asset
            if asset not in by_asset:
                by_asset[asset] = {'total': 0, 'passed': 0, 'failed': 0}
            by_asset[asset]['total'] += 1
            if result.passed:
                by_asset[asset]['passed'] += 1
            else:
                by_asset[asset]['failed'] += 1
        
        summary = {
            'profile': self.profile_name,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'total_scenarios': total_scenarios,
            'passed_scenarios': passed_scenarios,
            'failed_scenarios': failed_scenarios,
            'pass_rate': passed_scenarios / total_scenarios if total_scenarios > 0 else 0.0,
            'by_threshold_type': by_threshold_type,
            'by_asset': by_asset,
            'thresholds': {
                'coarse_filter_cents': self.coarse_filter_threshold,
                'edge_dependent_cents': self.edge_dependent_threshold,
                'quality_metric_cents': self.quality_metric_threshold,
                'dynamic_calm_cents': self.dynamic_calm_threshold,
                'dynamic_elevated_cents': self.dynamic_elevated_threshold,
                'dynamic_violent_cents': self.dynamic_violent_threshold,
            }
        }
        
        logger.info(
            f"[SPREAD-SIMULATOR] Simulation complete: "
            f"{passed_scenarios}/{total_scenarios} passed ({summary['pass_rate']:.1%})"
        )
        
        return {
            'summary': summary,
            'results': [
                {
                    'scenario': r.scenario.name,
                    'asset': r.scenario.asset,
                    'spread_cents': r.scenario.spread_cents,
                    'threshold_type': r.scenario.threshold_type.value,
                    'expected_outcome': r.scenario.expected_outcome,
                    'actual_outcome': r.actual_outcome,
                    'passed': r.passed,
                    'reason': r.actual_reason,
                    'quality_metrics': r.quality_metrics,
                }
                for r in self.results
            ]
        }
    
    def print_results(self, results: Dict[str, Any]):
        """Print simulation results in a readable format."""
        print("\n" + "="*80)
        print("SPREAD TRADING SCENARIO SIMULATION RESULTS")
        print("="*80)
        
        summary = results['summary']
        print(f"\nProfile: {summary['profile']}")
        print(f"Timestamp: {summary['timestamp']}")
        print(f"\nTotal Scenarios: {summary['total_scenarios']}")
        print(f"Passed: {summary['passed_scenarios']}")
        print(f"Failed: {summary['failed_scenarios']}")
        print(f"Pass Rate: {summary['pass_rate']:.1%}")
        
        print("\n" + "-"*80)
        print("THRESHOLDS TESTED:")
        print("-"*80)
        thresholds = summary['thresholds']
        print(f"  Coarse Filter: {thresholds['coarse_filter_cents']}c")
        print(f"  Edge-Dependent: {thresholds['edge_dependent_cents']}c")
        print(f"  Quality Metric: {thresholds['quality_metric_cents']}c")
        print(f"  Dynamic Calm: {thresholds['dynamic_calm_cents']}c")
        print(f"  Dynamic Elevated: {thresholds['dynamic_elevated_cents']}c")
        print(f"  Dynamic Violent: {thresholds['dynamic_violent_cents']}c")
        
        print("\n" + "-"*80)
        print("RESULTS BY THRESHOLD TYPE:")
        print("-"*80)
        for threshold_type, stats in summary['by_threshold_type'].items():
            print(f"  {threshold_type}: {stats['passed']}/{stats['total']} passed ({stats['passed']/stats['total']:.1%})")
        
        print("\n" + "-"*80)
        print("RESULTS BY ASSET:")
        print("-"*80)
        for asset, stats in summary['by_asset'].items():
            print(f"  {asset}: {stats['passed']}/{stats['total']} passed ({stats['passed']/stats['total']:.1%})")
        
        print("\n" + "-"*80)
        print("DETAILED RESULTS:")
        print("-"*80)
        for result in results['results']:
            status = "✓ PASS" if result['passed'] else "✗ FAIL"
            print(f"\n{status} - {result['scenario']}")
            print(f"  Asset: {result['asset']}")
            print(f"  Spread: {result['spread_cents']}c")
            print(f"  Threshold Type: {result['threshold_type']}")
            print(f"  Expected: {result['expected_outcome']}")
            print(f"  Actual: {result['actual_outcome']}")
            print(f"  Reason: {result['reason']}")
            if result['quality_metrics']:
                print(f"  Quality Score: {result['quality_metrics'].get('quality_score', 'N/A'):.3f}")
                print(f"  Liquidity Score: {result['quality_metrics'].get('liquidity_score', 'N/A'):.3f}")
        
        print("\n" + "="*80)


def main():
    """Main entry point for the spread trading scenario simulator."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Spread Trading Scenario Simulator for MERID 15M Stack"
    )
    parser.add_argument(
        '--profile',
        default='kalshi_crypto_15m_v2',
        help='Profile name to use (default: kalshi_crypto_15m_v2)'
    )
    parser.add_argument(
        '--output',
        help='Output file path for JSON results (optional)'
    )
    
    args = parser.parse_args()
    
    # Create simulator
    simulator = SpreadTradingScenarioSimulator(profile_name=args.profile)
    
    # Run simulation
    results = simulator.run_simulation()
    
    # Print results
    simulator.print_results(results)
    
    # Save to file if specified
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        logger.info(f"[SPREAD-SIMULATOR] Results saved to {args.output}")
    
    # Exit with error code if any scenarios failed
    if results['summary']['failed_scenarios'] > 0:
        sys.exit(1)
    
    sys.exit(0)


if __name__ == "__main__":
    main()
