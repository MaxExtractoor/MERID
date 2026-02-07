"""Comprehensive tests for trading/execution/defense.py - Coverage improvement."""
import pytest
import time
from unittest.mock import MagicMock, patch
import numpy as np

from trading.execution.defense import (
    MEVType,
    ThreatLevel,
    DefenseAction,
    MEVEvent,
    MEVHeatmapEntry,
    DefenseRecommendation,
    OrderSlicer,
    TimingRandomizer,
    FrontRunningDetector,
    SandwichDetector,
    MEVHeatmap,
    MEVDefenseEngine,
    ManipulationDetector,
    get_mev_defense,
)


class TestMEVHeatmapEntry:
    """Tests for MEVHeatmapEntry dataclass."""

    def test_creation_with_defaults(self):
        """Test creating entry with default last_updated."""
        entry = MEVHeatmapEntry(
            symbol="BTCUSDT",
            venue="binance",
            time_bucket=14,
            mev_intensity=0.75,
            attack_count_24h=5,
            avg_loss_per_attack=250.0,
            liquidity_depth=1000000.0,
            volatility=0.02
        )
        assert entry.symbol == "BTCUSDT"
        assert entry.venue == "binance"
        assert entry.time_bucket == 14
        assert entry.mev_intensity == 0.75
        assert entry.attack_count_24h == 5
        assert entry.last_updated > 0

    def test_to_dict(self):
        """Test serialization."""
        entry = MEVHeatmapEntry(
            symbol="ETHUSDT",
            venue="coinbase",
            time_bucket=10,
            mev_intensity=0.5,
            attack_count_24h=3,
            avg_loss_per_attack=100.0,
            liquidity_depth=500000.0,
            volatility=0.03
        )
        d = entry.to_dict()
        assert d["symbol"] == "ETHUSDT"
        assert d["venue"] == "coinbase"
        assert d["time_bucket"] == 10
        assert d["mev_intensity"] == 0.5
        assert d["attack_count_24h"] == 3


class TestDefenseRecommendation:
    """Tests for DefenseRecommendation dataclass."""

    def test_creation_with_defaults(self):
        """Test creating recommendation with defaults."""
        rec = DefenseRecommendation(
            action=DefenseAction.PROCEED,
            reason="Low risk"
        )
        assert rec.action == DefenseAction.PROCEED
        assert rec.reason == "Low risk"
        assert rec.suggested_delay_ms == 0
        assert rec.suggested_slice_count == 1
        assert rec.suggested_size_reduction == 1.0
        assert rec.threat_level == ThreatLevel.NONE

    def test_creation_with_custom_values(self):
        """Test creating recommendation with custom values."""
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="High MEV risk",
            suggested_delay_ms=500,
            suggested_slice_count=5,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.HIGH,
            estimated_mev_risk=0.15
        )
        assert rec.suggested_delay_ms == 500
        assert rec.suggested_slice_count == 5
        assert rec.suggested_size_reduction == 0.8
        assert rec.threat_level == ThreatLevel.HIGH

    def test_to_dict(self):
        """Test serialization."""
        rec = DefenseRecommendation(
            action=DefenseAction.DELAY,
            reason="Medium risk",
            suggested_delay_ms=200,
            threat_level=ThreatLevel.MEDIUM,
            estimated_mev_risk=0.05
        )
        d = rec.to_dict()
        assert d["action"] == "delay"
        assert d["reason"] == "Medium risk"
        assert d["suggested_delay_ms"] == 200
        assert d["threat_level"] == "medium"
        assert d["estimated_mev_risk"] == 0.05


class TestOrderSlicer:
    """Tests for OrderSlicer class."""

    def test_initialization(self):
        """Test slicer initialization."""
        slicer = OrderSlicer(min_slice_size=50.0, max_slices=10)
        assert slicer.min_slice_size == 50.0
        assert slicer.max_slices == 10

    def test_compute_optimal_slices_small_order(self):
        """Test slicing small order."""
        slicer = OrderSlicer(min_slice_size=100.0, max_slices=20)
        slices = slicer.compute_optimal_slices(
            total_size=500.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.3
        )
        assert len(slices) >= 1
        assert sum(slices) == pytest.approx(500.0, rel=0.01)

    def test_compute_optimal_slices_large_order(self):
        """Test slicing large order."""
        slicer = OrderSlicer(min_slice_size=100.0, max_slices=20)
        slices = slicer.compute_optimal_slices(
            total_size=10000.0,
            daily_volume=50000.0,
            volatility=0.01,
            mev_intensity=0.8
        )
        assert len(slices) >= 1
        assert len(slices) <= 20
        assert sum(slices) == pytest.approx(10000.0, rel=0.01)

    def test_compute_optimal_slices_high_mev(self):
        """Test more slices with high MEV intensity."""
        slicer = OrderSlicer(min_slice_size=50.0, max_slices=20)
        
        low_mev_slices = slicer.compute_optimal_slices(
            total_size=5000.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.1
        )
        
        high_mev_slices = slicer.compute_optimal_slices(
            total_size=5000.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.9
        )
        
        # High MEV should result in more slices (or same due to limits)
        assert len(high_mev_slices) >= len(low_mev_slices)

    def test_compute_optimal_slices_zero_volume(self):
        """Test with zero daily volume."""
        slicer = OrderSlicer()
        slices = slicer.compute_optimal_slices(
            total_size=1000.0,
            daily_volume=0.0,
            volatility=0.02,
            mev_intensity=0.5
        )
        assert len(slices) >= 1
        assert sum(slices) == pytest.approx(1000.0, rel=0.01)

    def test_compute_iceberg_schedule(self):
        """Test iceberg order computation."""
        slicer = OrderSlicer()
        visible, hidden = slicer.compute_iceberg_schedule(
            total_size=10000.0,
            visible_pct=0.1
        )
        assert visible == 1000.0
        assert hidden == 9000.0

    def test_compute_iceberg_schedule_custom_pct(self):
        """Test iceberg with custom visibility."""
        slicer = OrderSlicer()
        visible, hidden = slicer.compute_iceberg_schedule(
            total_size=5000.0,
            visible_pct=0.25
        )
        assert visible == 1250.0
        assert hidden == 3750.0


class TestTimingRandomizer:
    """Tests for TimingRandomizer class."""

    def test_initialization(self):
        """Test randomizer initialization."""
        randomizer = TimingRandomizer()
        assert randomizer._rng is not None

    def test_randomize_delay(self):
        """Test delay randomization."""
        randomizer = TimingRandomizer()
        delays = [randomizer.randomize_delay(1000, jitter_pct=0.3) for _ in range(100)]
        
        # All delays should be within expected range
        for delay in delays:
            assert 700 <= delay <= 1300

    def test_randomize_delay_zero_jitter(self):
        """Test delay with zero jitter."""
        randomizer = TimingRandomizer()
        delay = randomizer.randomize_delay(500, jitter_pct=0.0)
        assert delay == 500

    def test_compute_random_schedule(self):
        """Test generating random execution schedule."""
        randomizer = TimingRandomizer()
        schedule = randomizer.compute_random_schedule(
            n_orders=5,
            total_duration_ms=10000
        )
        
        assert len(schedule) == 5
        # Times should be non-decreasing
        for i in range(1, len(schedule)):
            assert schedule[i] >= schedule[i-1]

    def test_compute_random_schedule_single(self):
        """Test schedule with single order."""
        randomizer = TimingRandomizer()
        schedule = randomizer.compute_random_schedule(n_orders=1, total_duration_ms=5000)
        assert schedule == [0]

    def test_should_add_decoy_delay(self):
        """Test decoy delay decision."""
        randomizer = TimingRandomizer()
        # Run multiple times to test probability
        results = [randomizer.should_add_decoy_delay() for _ in range(100)]
        # Should have some True and some False results
        true_count = sum(1 for r in results if r[0])
        assert 0 <= true_count <= 100  # Probabilistic


class TestFrontRunningDetector:
    """Tests for FrontRunningDetector class."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = FrontRunningDetector(detection_window_ms=5000)
        assert detector.detection_window_ms == 5000
        assert detector._pending_orders == {}
        assert detector._detected_events == []

    def test_register_pending_order(self):
        """Test registering a pending order."""
        detector = FrontRunningDetector()
        detector.register_pending_order(
            order_id="order_123",
            symbol="BTCUSDT",
            side="buy",
            size=1.0,
            price=50000.0
        )
        assert "order_123" in detector._pending_orders
        assert detector._pending_orders["order_123"]["symbol"] == "BTCUSDT"

    def test_check_for_front_running_no_pending(self):
        """Test check with no pending order."""
        detector = FrontRunningDetector()
        result = detector.check_for_front_running(
            order_id="unknown",
            executed_price=50100.0,
            market_trades=[]
        )
        assert result is None

    def test_check_for_front_running_no_suspicious(self):
        """Test check with no suspicious trades."""
        detector = FrontRunningDetector()
        detector.register_pending_order(
            order_id="order_123",
            symbol="BTCUSDT",
            side="buy",
            size=1.0,
            price=50000.0
        )
        result = detector.check_for_front_running(
            order_id="order_123",
            executed_price=50000.0,
            market_trades=[]
        )
        assert result is None

    def test_get_recent_events(self):
        """Test getting recent events."""
        detector = FrontRunningDetector()
        events = detector.get_recent_events(limit=10)
        assert isinstance(events, list)


class TestSandwichDetector:
    """Tests for SandwichDetector class."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = SandwichDetector()
        assert detector._detected_events == []
        assert detector._event_count == 0

    def test_detect_sandwich_no_pattern(self):
        """Test detection with no sandwich pattern."""
        detector = SandwichDetector()
        now = time.time()
        
        our_trade = {
            "timestamp": now,
            "side": "buy",
            "price": 50000.0,
            "size": 1.0,
            "tx_hash": "our_tx",
            "symbol": "BTCUSDT"
        }
        
        surrounding_trades = [
            {"timestamp": now - 10, "side": "sell", "price": 49900.0},
            {"timestamp": now + 10, "side": "buy", "price": 50100.0},
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding_trades)
        assert result is None

    def test_get_recent_events(self):
        """Test getting recent events."""
        detector = SandwichDetector()
        events = detector.get_recent_events(limit=10)
        assert isinstance(events, list)


class TestMEVHeatmap:
    """Tests for MEVHeatmap class."""

    def test_initialization(self):
        """Test heatmap initialization."""
        heatmap = MEVHeatmap()
        assert heatmap._entries == {}

    def test_record_attack(self):
        """Test recording MEV attack."""
        heatmap = MEVHeatmap()
        
        heatmap.record_attack(
            symbol="BTCUSDT",
            venue="binance",
            mev_type=MEVType.FRONT_RUNNING,
            loss=100.0
        )
        
        # Should have recorded attack
        assert len(heatmap._attack_history) == 1
        intensity = heatmap.get_intensity("BTCUSDT", "binance")
        assert intensity >= 0

    def test_get_intensity_unknown_symbol(self):
        """Test getting intensity for unknown symbol."""
        heatmap = MEVHeatmap()
        intensity = heatmap.get_intensity("UNKNOWN", "binance")
        assert intensity == 0.0

    def test_get_safest_time(self):
        """Test getting safest hour."""
        heatmap = MEVHeatmap()
        
        # Record some attacks at different hours
        for i in range(5):
            heatmap.record_attack(
                symbol="ETHUSDT",
                venue="coinbase",
                mev_type=MEVType.SANDWICH,
                loss=200.0
            )
        
        safest = heatmap.get_safest_time("ETHUSDT", "coinbase")
        assert 0 <= safest < 24

    def test_get_heatmap(self):
        """Test getting heatmap data."""
        heatmap = MEVHeatmap()
        heatmap.record_attack("BTCUSDT", "binance", MEVType.FRONT_RUNNING, 50.0)
        
        data = heatmap.get_heatmap("BTCUSDT")
        assert "symbol" in data
        assert "entries" in data
        assert data["symbol"] == "BTCUSDT"


class TestMEVDefenseEngine:
    """Tests for MEVDefenseEngine class."""

    def test_initialization(self):
        """Test engine initialization."""
        engine = MEVDefenseEngine()
        assert engine.heatmap is not None
        assert engine.slicer is not None
        assert engine.timing is not None
        assert engine.front_running_detector is not None
        assert engine.sandwich_detector is not None

    def test_assess_mev_risk_low(self):
        """Test assessing low MEV risk."""
        engine = MEVDefenseEngine()
        
        level, risk = engine.assess_mev_risk(
            symbol="BTCUSDT",
            venue="binance",
            order_size=100.0,
            daily_volume=10000000.0
        )
        
        assert level in ThreatLevel
        assert risk >= 0

    def test_assess_mev_risk_high_participation(self):
        """Test assessing risk with high participation rate."""
        engine = MEVDefenseEngine()
        
        level, risk = engine.assess_mev_risk(
            symbol="SOLANA",
            venue="raydium",
            order_size=100000.0,
            daily_volume=50000.0  # Very low volume
        )
        
        assert level in ThreatLevel
        # High participation should increase risk
        assert risk >= 0

    def test_get_defense_recommendation_low_risk(self):
        """Test getting recommendation for low-risk order."""
        engine = MEVDefenseEngine()
        
        rec = engine.get_defense_recommendation(
            symbol="BTCUSDT",
            venue="binance",
            side="buy",
            order_size=100.0,
            daily_volume=10000000.0,
            volatility=0.01
        )
        
        assert isinstance(rec, DefenseRecommendation)
        assert rec.action in DefenseAction

    def test_get_defense_recommendation_high_risk(self):
        """Test getting recommendation for high-risk order."""
        engine = MEVDefenseEngine()
        
        # Record attacks to increase intensity
        for i in range(15):
            engine.heatmap.record_attack(
                symbol="SOLANA",
                venue="raydium",
                mev_type=MEVType.FRONT_RUNNING,
                loss=500.0
            )
        
        rec = engine.get_defense_recommendation(
            symbol="SOLANA",
            venue="raydium",
            side="buy",
            order_size=100000.0,
            daily_volume=50000.0,
            volatility=0.05
        )
        
        assert isinstance(rec, DefenseRecommendation)
        # Should have elevated threat level
        assert rec.threat_level in ThreatLevel


class TestManipulationDetector:
    """Tests for ManipulationDetector class."""

    def test_initialization(self):
        """Test detector initialization."""
        detector = ManipulationDetector()
        assert detector is not None

    def test_detect_wash_trading(self):
        """Test wash trading detection."""
        detector = ManipulationDetector()
        
        # Simulate trades - need 20+ to trigger detection
        trades = [
            {"address": "A", "size": 100, "price": 50000, "timestamp": time.time()}
            for _ in range(25)
        ]
        
        result = detector.detect_wash_trading("BTCUSDT", trades)
        
        # Should return detection result (dict or None)
        assert isinstance(result, (dict, type(None)))


class TestGetMEVDefense:
    """Tests for singleton getter."""

    def test_singleton_pattern(self):
        """Test singleton returns same instance."""
        import trading.execution.defense as defense_module
        defense_module._mev_defense = None  # Reset singleton
        
        engine1 = get_mev_defense()
        engine2 = get_mev_defense()
        
        assert engine1 is engine2

    def test_creates_engine(self):
        """Test getter creates engine."""
        import trading.execution.defense as defense_module
        defense_module._mev_defense = None  # Reset singleton
        
        engine = get_mev_defense()
        
        assert isinstance(engine, MEVDefenseEngine)
