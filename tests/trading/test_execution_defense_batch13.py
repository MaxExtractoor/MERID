"""Tests for execution defense module - Batch 13 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time
from decimal import Decimal

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
    get_mev_defense
)


class TestMEVType:
    """Tests for MEVType enum."""

    def test_all_types_exist(self):
        """Test all MEV types defined."""
        assert MEVType.FRONT_RUNNING.value == "front_running"
        assert MEVType.BACK_RUNNING.value == "back_running"
        assert MEVType.SANDWICH.value == "sandwich"
        assert MEVType.LIQUIDATION.value == "liquidation"
        assert MEVType.ARBITRAGE.value == "arbitrage"
        assert MEVType.JIT_LIQUIDITY.value == "jit_liquidity"


class TestThreatLevel:
    """Tests for ThreatLevel enum."""

    def test_all_levels_exist(self):
        """Test all threat levels defined."""
        assert ThreatLevel.NONE.value == "none"
        assert ThreatLevel.LOW.value == "low"
        assert ThreatLevel.MEDIUM.value == "medium"
        assert ThreatLevel.HIGH.value == "high"
        assert ThreatLevel.CRITICAL.value == "critical"


class TestDefenseAction:
    """Tests for DefenseAction enum."""

    def test_all_actions_exist(self):
        """Test all defense actions defined."""
        assert DefenseAction.PROCEED.value == "proceed"
        assert DefenseAction.DELAY.value == "delay"
        assert DefenseAction.SLICE.value == "slice"
        assert DefenseAction.RANDOMIZE.value == "randomize"
        assert DefenseAction.ABORT.value == "abort"
        assert DefenseAction.USE_PRIVATE_MEMPOOL.value == "use_private_mempool"


class TestMEVEvent:
    """Tests for MEVEvent dataclass."""

    def test_event_creation(self):
        """Test creating MEV event."""
        event = MEVEvent(
            event_id="evt_123",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.85,
            estimated_loss=150.50,
            attacker_address="0x123...",
            victim_tx="tx_456",
            symbol="BTCUSDT",
            block_number=12345
        )
        assert event.event_id == "evt_123"
        assert event.mev_type == MEVType.FRONT_RUNNING
        assert event.confidence == 0.85
        assert event.estimated_loss == 150.50

    def test_event_to_dict(self):
        """Test event serialization."""
        event = MEVEvent(
            event_id="evt_123",
            mev_type=MEVType.SANDWICH,
            detected_at=time.time(),
            confidence=0.75,
            estimated_loss=200.0,
            attacker_address="0xabcdef123456",
            symbol="ETHUSDT"
        )
        d = event.to_dict()
        assert d["event_id"] == "evt_123"
        assert d["mev_type"] == "sandwich"
        assert d["confidence"] == 0.75


class TestDefenseRecommendation:
    """Tests for DefenseRecommendation dataclass."""

    def test_recommendation_creation(self):
        """Test creating defense recommendation."""
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="High MEV risk",
            suggested_delay_ms=1000,
            suggested_slice_count=5,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.HIGH,
            estimated_mev_risk=50.0
        )
        assert rec.action == DefenseAction.SLICE
        assert rec.suggested_slice_count == 5
        assert rec.threat_level == ThreatLevel.HIGH

    def test_recommendation_to_dict(self):
        """Test recommendation serialization."""
        rec = DefenseRecommendation(
            action=DefenseAction.DELAY,
            reason="Medium risk",
            threat_level=ThreatLevel.MEDIUM,
            estimated_mev_risk=25.0
        )
        d = rec.to_dict()
        assert d["action"] == "delay"
        assert d["threat_level"] == "medium"


class TestOrderSlicer:
    """Tests for OrderSlicer."""

    @pytest.fixture
    def slicer(self):
        """Create order slicer."""
        return OrderSlicer(min_slice_size=100.0, max_slices=20)

    def test_initialization(self, slicer):
        """Test slicer initialization."""
        assert slicer.min_slice_size == 100.0
        assert slicer.max_slices == 20

    def test_compute_optimal_slices(self, slicer):
        """Test slice computation."""
        slices = slicer.compute_optimal_slices(
            total_size=10000.0,
            daily_volume=1000000.0,
            volatility=0.1,
            mev_intensity=0.5
        )
        assert len(slices) >= 1
        assert len(slices) <= 20
        assert sum(slices) == pytest.approx(10000.0, rel=0.01)

    def test_compute_iceberg_schedule(self, slicer):
        """Test iceberg schedule computation."""
        visible, hidden = slicer.compute_iceberg_schedule(
            total_size=10000.0,
            visible_pct=0.1
        )
        assert visible == 1000.0
        assert hidden == 9000.0


class TestTimingRandomizer:
    """Tests for TimingRandomizer."""

    @pytest.fixture
    def randomizer(self):
        """Create timing randomizer."""
        return TimingRandomizer()

    def test_randomize_delay(self, randomizer):
        """Test delay randomization."""
        base_delay = 1000
        randomized = randomizer.randomize_delay(base_delay, jitter_pct=0.3)
        # Should be within 30% of base
        assert 700 <= randomized <= 1300

    def test_compute_random_schedule(self, randomizer):
        """Test random schedule computation."""
        delays = randomizer.compute_random_schedule(
            n_orders=5,
            total_duration_ms=10000
        )
        assert len(delays) == 5
        assert delays[0] == 0  # First order starts immediately
        assert all(d >= 0 for d in delays)

    def test_should_add_decoy_delay(self, randomizer):
        """Test decoy delay decision."""
        # Run multiple times to check probability
        delays_added = 0
        for _ in range(100):
            should_add, delay = randomizer.should_add_decoy_delay()
            if should_add:
                delays_added += 1
                assert 500 <= delay <= 5000
        # Should add roughly 20% of the time
        assert 10 <= delays_added <= 35


class TestFrontRunningDetector:
    """Tests for FrontRunningDetector."""

    @pytest.fixture
    def detector(self):
        """Create front-running detector."""
        return FrontRunningDetector(detection_window_ms=5000)

    def test_initialization(self, detector):
        """Test detector initialization."""
        assert detector.detection_window_ms == 5000

    def test_register_pending_order(self, detector):
        """Test registering pending order."""
        detector.register_pending_order(
            order_id="order_123",
            symbol="BTCUSDT",
            side="buy",
            size=1.0,
            price=45000.0
        )
        assert "order_123" in detector._pending_orders

    def test_check_no_front_running(self, detector):
        """Test detection with no front-running."""
        detector.register_pending_order(
            order_id="order_123",
            symbol="BTCUSDT",
            side="buy",
            size=1.0,
            price=45000.0
        )
        
        market_trades = []  # No suspicious trades
        event = detector.check_for_front_running("order_123", 45000.0, market_trades)
        
        assert event is None


class TestSandwichDetector:
    """Tests for SandwichDetector."""

    @pytest.fixture
    def detector(self):
        """Create sandwich detector."""
        return SandwichDetector()

    def test_detect_no_sandwich(self, detector):
        """Test detection with no sandwich."""
        our_trade = {
            "timestamp": time.time(),
            "side": "buy",
            "price": 45000.0,
            "size": 1.0
        }
        surrounding_trades = []  # No sandwich pattern
        
        event = detector.detect_sandwich(our_trade, surrounding_trades)
        assert event is None


class TestMEVHeatmap:
    """Tests for MEVHeatmap."""

    @pytest.fixture
    def heatmap(self):
        """Create MEV heatmap."""
        return MEVHeatmap()

    def test_initialization(self, heatmap):
        """Test heatmap initialization."""
        assert len(heatmap._entries) == 0

    def test_record_attack(self, heatmap):
        """Test recording attack."""
        heatmap.record_attack(
            symbol="BTCUSDT",
            venue="binance",
            mev_type=MEVType.FRONT_RUNNING,
            loss=100.0
        )
        assert len(heatmap._attack_history) == 1

    def test_get_intensity_no_data(self, heatmap):
        """Test getting intensity with no data."""
        intensity = heatmap.get_intensity("BTCUSDT", "binance")
        assert intensity == 0.0

    def test_get_safest_time_no_data(self, heatmap):
        """Test getting safest time with no data."""
        safest = heatmap.get_safest_time("BTCUSDT", "binance")
        assert 0 <= safest <= 23  # Should return an hour


class TestMEVDefenseEngine:
    """Tests for MEVDefenseEngine."""

    @pytest.fixture
    def engine(self):
        """Create MEV defense engine."""
        return MEVDefenseEngine()

    def test_initialization(self, engine):
        """Test engine initialization."""
        assert engine.slicer is not None
        assert engine.timing is not None
        assert engine.heatmap is not None

    def test_assess_mev_risk_no_history(self, engine):
        """Test risk assessment with no history."""
        threat, risk = engine.assess_mev_risk(
            symbol="BTCUSDT",
            venue="binance",
            order_size=1000.0,
            daily_volume=1000000.0
        )
        assert threat == ThreatLevel.NONE
        assert risk >= 0.0

    def test_get_defense_recommendation_low_risk(self, engine):
        """Test recommendation for low risk."""
        rec = engine.get_defense_recommendation(
            symbol="BTCUSDT",
            venue="binance",
            side="buy",
            order_size=1000.0,
            daily_volume=1000000.0,
            volatility=0.1
        )
        assert rec.action in [DefenseAction.PROCEED, DefenseAction.DELAY]
        assert rec.threat_level in [ThreatLevel.NONE, ThreatLevel.LOW]

    def test_record_mev_avoided(self, engine):
        """Test recording avoided MEV."""
        engine.record_mev_avoided(100.0)
        assert engine._total_mev_avoided == 100.0

    def test_get_status(self, engine):
        """Test getting engine status."""
        status = engine.get_status()
        assert "total_mev_suffered" in status
        assert "total_mev_avoided" in status
        assert "net_mev_impact" in status

    def test_get_mev_summary(self, engine):
        """Test getting MEV summary."""
        summary = engine.get_mev_summary("BTCUSDT")
        assert "heatmap" in summary
        assert "safest_hour" in summary
        assert "current_intensity" in summary


class TestManipulationDetector:
    """Tests for ManipulationDetector."""

    @pytest.fixture
    def detector(self):
        """Create manipulation detector."""
        return ManipulationDetector()

    def test_initialization(self, detector):
        """Test detector initialization."""
        assert len(detector._alerts) == 0

    def test_record_tick(self, detector):
        """Test recording price/volume tick."""
        detector.record_tick("BTCUSDT", price=45000.0, volume=100.0)
        assert "BTCUSDT" in detector._price_history
        assert "BTCUSDT" in detector._volume_history

    def test_detect_pump_and_dump_insufficient_data(self, detector):
        """Test pump/dump detection with insufficient data."""
        result = detector.detect_pump_and_dump("BTCUSDT")
        assert result is None  # Not enough data points

    def test_get_alerts_empty(self, detector):
        """Test getting alerts when empty."""
        alerts = detector.get_alerts()
        assert len(alerts) == 0


class TestGetMEVDefense:
    """Tests for get_mev_defense singleton."""

    def test_singleton_creation(self):
        """Test singleton is created."""
        engine1 = get_mev_defense()
        engine2 = get_mev_defense()
        
        assert engine1 is engine2
        assert isinstance(engine1, MEVDefenseEngine)
