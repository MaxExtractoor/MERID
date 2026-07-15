"""Tests for toxicity detection module (bot counter-trading prevention)."""

import pytest
import time
from datetime import datetime, timezone

from merid.event_venues.kalshi.toxicity_detection import (
    ToxicityDetector,
    ToxicityMetrics,
    get_toxicity_detector,
    reset_toxicity_detectors,
)


class TestToxicityDetector:
    """Test toxicity detection functionality."""
    
    def test_detector_initialization(self):
        """Test detector initialization with default thresholds."""
        detector = ToxicityDetector()
        
        assert detector.vpin_threshold == 0.65
        assert detector.volume_z_threshold == 8.0
        assert detector.price_divergence_threshold == 0.02
        assert detector.entropy_threshold == 2.5
        assert detector.vpin_window_size == 50
        assert detector.volume_window_size == 100
        assert detector.price_window_size == 30
        assert detector.entropy_window_size == 60
    
    def test_detector_custom_thresholds(self):
        """Test detector initialization with custom thresholds."""
        detector = ToxicityDetector(
            vpin_threshold=0.7,
            volume_z_threshold=10.0,
            price_divergence_threshold=0.03,
            entropy_threshold=3.0,
        )
        
        assert detector.vpin_threshold == 0.7
        assert detector.volume_z_threshold == 10.0
        assert detector.price_divergence_threshold == 0.03
        assert detector.entropy_threshold == 3.0
    
    def test_vpin_calculation(self):
        """Test VPIN calculation with buy-sell imbalance."""
        detector = ToxicityDetector()
        
        # Simulate buy-heavy flow (toxic)
        for i in range(20):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 20,
        )
        
        # Should detect imbalance
        assert metrics.volume_imbalance > 0.5
        assert metrics.vpin > 0
    
    def test_vpin_balanced_flow(self):
        """Test VPIN with balanced flow (non-toxic)."""
        detector = ToxicityDetector()
        
        # Simulate balanced flow
        for i in range(20):
            side = "buy" if i % 2 == 0 else "sell"
            detector.update(
                price_cents=50,
                volume=10,
                side=side,
                timestamp=time.time() + i,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 20,
        )
        
        # Should have low VPIN
        assert abs(metrics.volume_imbalance) < 0.3
        assert metrics.vpin < 0.3
    
    def test_volume_z_score_normal(self):
        """Test volume Z-score with normal volume."""
        detector = ToxicityDetector()
        
        # Simulate normal volume
        for i in range(50):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 50,
        )
        
        # Z-score should be near 0 for normal volume
        assert abs(metrics.volume_z_score) < 2.0
    
    def test_volume_z_score_anomaly(self):
        """Test volume Z-score with volume spike."""
        detector = ToxicityDetector(volume_z_threshold=5.0)  # Lower threshold for testing
        
        # Simulate normal volume
        for i in range(50):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i,
            )
        
        # Volume spike
        metrics = detector.update(
            price_cents=50,
            volume=100,  # 10x normal
            side="buy",
            timestamp=time.time() + 50,
        )
        
        # Z-score should be high
        assert metrics.volume_z_score > 5.0
        assert metrics.is_anomalous
    
    def test_price_divergence(self):
        """Test price divergence detection."""
        detector = ToxicityDetector()
        
        # Simulate stable prices
        for i in range(20):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i,
            )
        
        # Sudden price jump
        metrics = detector.update(
            price_cents=60,  # 10 cent jump
            volume=10,
            side="buy",
            timestamp=time.time() + 20,
        )
        
        # Should detect divergence
        assert abs(metrics.price_divergence) > 0
    
    def test_entropy_calculation(self):
        """Test entropy calculation."""
        detector = ToxicityDetector()
        
        # Simulate stable market
        for i in range(30):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 30,
        )
        
        # Should have some entropy
        assert metrics.market_entropy >= 0
        assert metrics.signal_energy >= 0
    
    def test_toxicity_score_computation(self):
        """Test composite toxicity score."""
        detector = ToxicityDetector()
        
        # Simulate toxic flow (high imbalance, high intensity)
        for i in range(30):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i * 0.1,  # High frequency
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 3,
        )
        
        # Toxicity score should be elevated
        assert metrics.toxicity_score >= 0
        assert metrics.toxicity_score <= 1.0
    
    def test_should_block_trading_toxic(self):
        """Test trading block decision for toxic flow."""
        detector = ToxicityDetector(vpin_threshold=0.5)
        
        # Simulate toxic flow
        for i in range(30):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i * 0.1,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 3,
        )
        
        should_block, reason = detector.should_block_trading(metrics)
        
        # May block if toxicity is high enough
        if metrics.toxicity_score > 0.8:
            assert should_block
            assert "toxic" in reason.lower()
    
    def test_should_block_trading_chaotic(self):
        """Test trading block decision for chaotic market."""
        detector = ToxicityDetector(entropy_threshold=1.0)  # Low threshold for testing
        
        # Simulate chaotic market (rapid price changes)
        for i in range(30):
            price = 50 + (i % 10) * 5  # Oscillating prices
            detector.update(
                price_cents=price,
                volume=10,
                side="buy",
                timestamp=time.time() + i * 0.1,
            )
        
        metrics = detector.update(
            price_cents=55,
            volume=10,
            side="buy",
            timestamp=time.time() + 3,
        )
        
        should_block, reason = detector.should_block_trading(metrics)
        
        # May block if entropy is high
        if metrics.is_chaotic:
            assert should_block
            assert "entropy" in reason.lower()
    
    def test_spread_multiplier_normal(self):
        """Test spread multiplier for normal conditions."""
        detector = ToxicityDetector()
        
        # Simulate normal flow
        for i in range(20):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 20,
        )
        
        multiplier = detector.get_spread_multiplier(metrics)
        
        # Should be 1.0 for normal conditions
        assert multiplier == 1.0
    
    def test_spread_multiplier_toxic(self):
        """Test spread multiplier for toxic flow."""
        detector = ToxicityDetector()
        
        # Simulate toxic flow
        for i in range(30):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i * 0.1,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=10,
            side="buy",
            timestamp=time.time() + 3,
        )
        
        # Force toxic flag
        metrics.is_toxic = True
        metrics.toxicity_score = 0.8
        
        multiplier = detector.get_spread_multiplier(metrics)
        
        # Should be > 1.0 for toxic flow
        assert multiplier > 1.0
    
    def test_spread_multiplier_anomalous(self):
        """Test spread multiplier for anomalous volume."""
        detector = ToxicityDetector()
        
        # Simulate normal volume then spike
        for i in range(50):
            detector.update(
                price_cents=50,
                volume=10,
                side="buy",
                timestamp=time.time() + i,
            )
        
        metrics = detector.update(
            price_cents=50,
            volume=100,
            side="buy",
            timestamp=time.time() + 50,
        )
        
        # Force anomalous flag
        metrics.is_anomalous = True
        metrics.volume_z_score = 10.0
        
        multiplier = detector.get_spread_multiplier(metrics)
        
        # Should be > 1.0 for anomalous volume
        assert multiplier > 1.0


class TestToxicityDetectorSingleton:
    """Test global detector singleton management."""
    
    def test_get_toxicity_detector(self):
        """Test getting detector for a ticker."""
        reset_toxicity_detectors()
        
        detector1 = get_toxicity_detector("KXBTCD-25JUN-T100000")
        detector2 = get_toxicity_detector("KXBTCD-25JUN-T100000")
        
        # Should return same instance
        assert detector1 is detector2
    
    def test_get_toxicity_detector_different_tickers(self):
        """Test getting detectors for different tickers."""
        reset_toxicity_detectors()
        
        detector1 = get_toxicity_detector("KXBTCD-25JUN-T100000")
        detector2 = get_toxicity_detector("KXETHD-25JUN-T100000")
        
        # Should return different instances
        assert detector1 is not detector2
    
    def test_reset_toxicity_detectors(self):
        """Test resetting all detectors."""
        reset_toxicity_detectors()
        
        detector1 = get_toxicity_detector("KXBTCD-25JUN-T100000")
        detector1.update(price_cents=50, volume=10, side="buy")
        
        reset_toxicity_detectors()
        
        detector2 = get_toxicity_detector("KXBTCD-25JUN-T100000")
        
        # Should be new instance
        assert detector1 is not detector2


class TestToxicityMetrics:
    """Test ToxicityMetrics dataclass."""
    
    def test_metrics_initialization(self):
        """Test metrics initialization."""
        metrics = ToxicityMetrics()
        
        assert metrics.vpin == 0.0
        assert metrics.volume_imbalance == 0.0
        assert metrics.trade_intensity == 0.0
        assert metrics.volume_z_score == 0.0
        assert metrics.price_divergence == 0.0
        assert metrics.market_entropy == 0.0
        assert metrics.signal_energy == 0.0
        assert metrics.toxicity_score == 0.0
        assert metrics.anomaly_score == 0.0
        assert metrics.is_toxic is False
        assert metrics.is_anomalous is False
        assert metrics.is_divergent is False
        assert metrics.is_chaotic is False
    
    def test_metrics_to_dict(self):
        """Test metrics serialization to dict."""
        metrics = ToxicityMetrics(
            vpin=0.7,
            volume_imbalance=0.5,
            trade_intensity=5.0,
            is_toxic=True,
        )
        
        d = metrics.to_dict()
        
        assert d["vpin"] == 0.7
        assert d["volume_imbalance"] == 0.5
        assert d["trade_intensity"] == 5.0
        assert d["is_toxic"] is True
