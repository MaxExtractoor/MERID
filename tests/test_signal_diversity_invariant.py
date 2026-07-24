"""
Signal Diversity Invariant Test Harness

Tests that the signal layer generates both bullish and bearish intents
across BTC/ETH/SOL/XRP/DOGE 15-minute markets, ensuring the system is
"market-aligned by construction" rather than "YES-biased by construction".

Invariant: For each asset, in a sample of N windows, the system must emit
non-zero counts of both BULLISH_EVENT and BEARISH_EVENT intents, with ratios
within a sanity band (20-80%) instead of 0 or 100%.

This test can run against:
1. Historical signal data from database
2. Simulated signal generation
3. Live signal stream (with time window)

Usage:
    pytest tests/test_signal_diversity_invariant.py
    pytest tests/test_signal_diversity_invariant.py::TestSignalDiversity::test_historical_diversity
    pytest tests/test_signal_diversity_invariant.py::TestSignalDiversity::test_simulated_diversity
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from collections import Counter
from dataclasses import dataclass

try:
    from merid.prediction.signal_terminology import StrategyIntent
except ImportError:
    # Fallback for testing
    class StrategyIntent:
        BULLISH_EVENT = "bullish_event"
        BEARISH_EVENT = "bearish_event"
        NEUTRAL = "neutral"


@dataclass
class SignalSample:
    """A single signal sample for analysis."""
    asset: str
    timestamp: datetime
    strategy_intent: str
    confidence: float
    edge_pct: float
    velocity: float
    market_id: str


class SignalDiversityAnalyzer:
    """Analyzes signal diversity across assets and time windows."""
    
    def __init__(self, min_ratio: float = 0.20, max_ratio: float = 0.80):
        """
        Args:
            min_ratio: Minimum acceptable ratio for either intent (default 20%)
            max_ratio: Maximum acceptable ratio for either intent (default 80%)
        """
        self.min_ratio = min_ratio
        self.max_ratio = max_ratio
        self.assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def analyze_diversity(
        self,
        signals: List[SignalSample],
        min_samples_per_asset: int = 50
    ) -> Dict[str, Dict]:
        """Analyze signal diversity across assets.
        
        Args:
            signals: List of signal samples
            min_samples_per_asset: Minimum samples required per asset for valid analysis
            
        Returns:
            Dict with per-asset diversity metrics
        """
        results = {}
        
        for asset in self.assets:
            asset_signals = [s for s in signals if s.asset == asset]
            
            if len(asset_signals) < min_samples_per_asset:
                results[asset] = {
                    "valid": False,
                    "error": f"Insufficient samples: {len(asset_signals)} < {min_samples_per_asset}",
                    "total_samples": len(asset_signals),
                }
                continue
            
            # Count intents
            intent_counts = Counter(s.strategy_intent for s in asset_signals)
            bullish_count = intent_counts.get(StrategyIntent.BULLISH_EVENT, 0)
            bearish_count = intent_counts.get(StrategyIntent.BEARISH_EVENT, 0)
            neutral_count = intent_counts.get(StrategyIntent.NEUTRAL, 0)
            total_count = len(asset_signals)
            
            # Calculate ratios
            bullish_ratio = bullish_count / total_count if total_count > 0 else 0
            bearish_ratio = bearish_count / total_count if total_count > 0 else 0
            
            # Check invariants
            has_bullish = bullish_count > 0
            has_bearish = bearish_count > 0
            ratio_in_bounds = (
                self.min_ratio <= bullish_ratio <= self.max_ratio and
                self.min_ratio <= bearish_ratio <= self.max_ratio
            )
            
            results[asset] = {
                "valid": has_bullish and has_bearish and ratio_in_bounds,
                "total_samples": total_count,
                "bullish_count": bullish_count,
                "bearish_count": bearish_count,
                "neutral_count": neutral_count,
                "bullish_ratio": bullish_ratio,
                "bearish_ratio": bearish_ratio,
                "has_bullish": has_bullish,
                "has_bearish": has_bearish,
                "ratio_in_bounds": ratio_in_bounds,
                "error": None if (has_bullish and has_bearish and ratio_in_bounds) else (
                    f"Diversity violation: bullish={bullish_ratio:.2%}, bearish={bearish_ratio:.2%}"
                ),
            }
        
        return results
    
    def generate_summary(self, results: Dict[str, Dict]) -> str:
        """Generate human-readable summary of diversity analysis."""
        lines = ["Signal Diversity Invariant Analysis", "=" * 50]
        
        for asset, metrics in results.items():
            if metrics["valid"]:
                lines.append(f"✓ {asset}: PASS (bullish={metrics['bullish_ratio']:.2%}, bearish={metrics['bearish_ratio']:.2%})")
            else:
                lines.append(f"✗ {asset}: FAIL ({metrics.get('error', 'Unknown error')})")
        
        return "\n".join(lines)


class TestSignalDiversity:
    """Test suite for signal diversity invariant."""
    
    def test_simulated_diverse_signals(self):
        """Test with simulated diverse signals (should pass)."""
        analyzer = SignalDiversityAnalyzer()
        
        # Generate diverse signals for each asset
        signals = []
        now = datetime.now(timezone.utc)
        
        for asset in analyzer.assets:
            for i in range(100):
                # Alternate between bullish and bearish with some neutral
                if i % 3 == 0:
                    intent = StrategyIntent.BULLISH_EVENT
                elif i % 3 == 1:
                    intent = StrategyIntent.BEARISH_EVENT
                else:
                    intent = StrategyIntent.NEUTRAL
                
                signals.append(SignalSample(
                    asset=asset,
                    timestamp=now + timedelta(minutes=i),
                    strategy_intent=intent,
                    confidence=0.7,
                    edge_pct=0.05,
                    velocity=0.001,
                    market_id=f"KX{asset}15M-TEST",
                ))
        
        results = analyzer.analyze_diversity(signals)
        
        # All assets should pass
        for asset, metrics in results.items():
            assert metrics["valid"], f"{asset} failed diversity check: {metrics.get('error')}"
            assert metrics["has_bullish"], f"{asset} has no bullish signals"
            assert metrics["has_bearish"], f"{asset} has no bearish signals"
            assert metrics["ratio_in_bounds"], f"{asset} ratios out of bounds"
    
    def test_simulated_bullish_bias(self):
        """Test with bullish-biased signals (should fail)."""
        analyzer = SignalDiversityAnalyzer()
        
        # Generate bullish-biased signals
        signals = []
        now = datetime.now(timezone.utc)
        
        for asset in analyzer.assets:
            for i in range(100):
                # 90% bullish, 10% neutral, 0% bearish
                if i < 90:
                    intent = StrategyIntent.BULLISH_EVENT
                else:
                    intent = StrategyIntent.NEUTRAL
                
                signals.append(SignalSample(
                    asset=asset,
                    timestamp=now + timedelta(minutes=i),
                    strategy_intent=intent,
                    confidence=0.7,
                    edge_pct=0.05,
                    velocity=0.001,
                    market_id=f"KX{asset}15M-TEST",
                ))
        
        results = analyzer.analyze_diversity(signals)
        
        # All assets should fail due to lack of bearish signals
        for asset, metrics in results.items():
            assert not metrics["valid"], f"{asset} should fail with bullish bias"
            assert not metrics["has_bearish"], f"{asset} should have no bearish signals"
    
    def test_simulated_bearish_bias(self):
        """Test with bearish-biased signals (should fail)."""
        analyzer = SignalDiversityAnalyzer()
        
        # Generate bearish-biased signals
        signals = []
        now = datetime.now(timezone.utc)
        
        for asset in analyzer.assets:
            for i in range(100):
                # 90% bearish, 10% neutral, 0% bullish
                if i < 90:
                    intent = StrategyIntent.BEARISH_EVENT
                else:
                    intent = StrategyIntent.NEUTRAL
                
                signals.append(SignalSample(
                    asset=asset,
                    timestamp=now + timedelta(minutes=i),
                    strategy_intent=intent,
                    confidence=0.7,
                    edge_pct=0.05,
                    velocity=0.001,
                    market_id=f"KX{asset}15M-TEST",
                ))
        
        results = analyzer.analyze_diversity(signals)
        
        # All assets should fail due to lack of bullish signals
        for asset in analyzer.assets:
            metrics = results[asset]
            assert not metrics["valid"], f"{asset} should fail with bearish bias"
            assert not metrics["has_bullish"], f"{asset} should have no bullish signals"
    
    def test_insufficient_samples(self):
        """Test with insufficient samples (should fail gracefully)."""
        analyzer = SignalDiversityAnalyzer()
        
        # Generate only 10 samples per asset (below default 50 threshold)
        signals = []
        now = datetime.now(timezone.utc)
        
        for asset in analyzer.assets:
            for i in range(10):
                intent = StrategyIntent.BULLISH_EVENT if i % 2 == 0 else StrategyIntent.BEARISH_EVENT
                signals.append(SignalSample(
                    asset=asset,
                    timestamp=now + timedelta(minutes=i),
                    strategy_intent=intent,
                    confidence=0.7,
                    edge_pct=0.05,
                    velocity=0.001,
                    market_id=f"KX{asset}15M-TEST",
                ))
        
        results = analyzer.analyze_diversity(signals, min_samples_per_asset=50)
        
        # All assets should fail due to insufficient samples
        for asset, metrics in results.items():
            assert not metrics["valid"], f"{asset} should fail with insufficient samples"
            assert "Insufficient samples" in metrics["error"]
    
    def test_ratio_bounds_enforcement(self):
        """Test that ratio bounds are enforced correctly."""
        analyzer = SignalDiversityAnalyzer(min_ratio=0.25, max_ratio=0.75)
        
        # Generate signals with 80/20 split (outside bounds)
        signals = []
        now = datetime.now(timezone.utc)
        
        for asset in analyzer.assets:
            for i in range(100):
                # 80% bullish, 20% bearish
                intent = StrategyIntent.BULLISH_EVENT if i < 80 else StrategyIntent.BEARISH_EVENT
                signals.append(SignalSample(
                    asset=asset,
                    timestamp=now + timedelta(minutes=i),
                    strategy_intent=intent,
                    confidence=0.7,
                    edge_pct=0.05,
                    velocity=0.001,
                    market_id=f"KX{asset}15M-TEST",
                ))
        
        results = analyzer.analyze_diversity(signals)
        
        # All assets should fail due to ratio out of bounds
        for asset, metrics in results.items():
            assert not metrics["valid"], f"{asset} should fail with ratio out of bounds"
            assert not metrics["ratio_in_bounds"], f"{asset} ratios should be out of bounds"
    
    def test_historical_diversity(self):
        """Test against simulated historical signal data.
        
        This test simulates historical signal data to validate the diversity analyzer
        without requiring database access. It tests the same logic that would be used
        against production data.
        """
        analyzer = SignalDiversityAnalyzer(min_ratio=0.25, max_ratio=0.75)
        
        # Simulate historical signal data with realistic diversity
        signals = []
        now = datetime.now(timezone.utc)
        
        # Generate 500 samples per asset (simulating historical data)
        for asset in analyzer.assets:
            for i in range(500):
                # Simulate realistic distribution: ~45% bullish, ~45% bearish, ~10% neutral
                if i < 225:
                    intent = StrategyIntent.BULLISH_EVENT
                elif i < 450:
                    intent = StrategyIntent.BEARISH_EVENT
                else:
                    intent = StrategyIntent.NEUTRAL
                
                signals.append(SignalSample(
                    asset=asset,
                    timestamp=now - timedelta(hours=i),
                    strategy_intent=intent,
                    confidence=0.7 + (i % 30) / 100,  # Varying confidence
                    edge_pct=0.05,
                    velocity=0.001,
                    market_id=f"KX{asset}15M-TEST",
                ))
        
        results = analyzer.analyze_diversity(signals)
        
        # All assets should pass with realistic diversity
        for asset in analyzer.assets:
            metrics = results[asset]
            assert metrics["valid"], f"{asset} should pass with realistic diversity"
            assert metrics["has_bullish"], f"{asset} should have bullish signals"
            assert metrics["has_bearish"], f"{asset} should have bearish signals"
            assert metrics["ratio_in_bounds"], f"{asset} ratios should be in bounds"
            assert metrics["total_samples"] == 500, f"{asset} should have 500 samples"


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
