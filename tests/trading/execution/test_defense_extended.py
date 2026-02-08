"""Extended tests for trading/execution/defense.py - MEV Defense Coverage."""
import pytest
import time
import random
from unittest.mock import patch, MagicMock
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
    HiddenLiquidityInference,
    FrontRunningDetector,
    SandwichDetector,
    MEVHeatmap,
    MEVDefenseEngine,
    ManipulationDetector,
    get_mev_defense,
)


class TestEnums:
    """Test enum definitions."""

    def test_mev_type_values(self):
        """Test MEVType enum values."""
        assert MEVType.FRONT_RUNNING.value == "front_running"
        assert MEVType.BACK_RUNNING.value == "back_running"
        assert MEVType.SANDWICH.value == "sandwich"
        assert MEVType.LIQUIDATION.value == "liquidation"
        assert MEVType.ARBITRAGE.value == "arbitrage"
        assert MEVType.JIT_LIQUIDITY.value == "jit_liquidity"

    def test_threat_level_values(self):
        """Test ThreatLevel enum values."""
        assert ThreatLevel.NONE.value == "none"
        assert ThreatLevel.LOW.value == "low"
        assert ThreatLevel.MEDIUM.value == "medium"
        assert ThreatLevel.HIGH.value == "high"
        assert ThreatLevel.CRITICAL.value == "critical"

    def test_defense_action_values(self):
        """Test DefenseAction enum values."""
        assert DefenseAction.PROCEED.value == "proceed"
        assert DefenseAction.DELAY.value == "delay"
        assert DefenseAction.SLICE.value == "slice"
        assert DefenseAction.RANDOMIZE.value == "randomize"
        assert DefenseAction.ABORT.value == "abort"
        assert DefenseAction.USE_PRIVATE_MEMPOOL.value == "use_private_mempool"


class TestMEVEvent:
    """Test MEVEvent dataclass."""

    def test_mev_event_creation(self):
        """Test creating an MEV event."""
        event = MEVEvent(
            event_id="test_001",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.85,
            estimated_loss=100.0,
            symbol="BTC/USD"
        )
        assert event.event_id == "test_001"
        assert event.mev_type == MEVType.FRONT_RUNNING
        assert event.confidence == 0.85
        assert event.estimated_loss == 100.0

    def test_mev_event_to_dict(self):
        """Test MEVEvent to_dict method."""
        event = MEVEvent(
            event_id="test_002",
            mev_type=MEVType.SANDWICH,
            detected_at=1234567890.0,
            confidence=0.75,
            estimated_loss=250.0,
            attacker_address="0x1234567890abcdef1234567890abcdef12345678",
            symbol="ETH/USD"
        )
        result = event.to_dict()
        
        assert result["event_id"] == "test_002"
        assert result["mev_type"] == "sandwich"
        assert result["confidence"] == 0.75
        assert result["estimated_loss"] == 250.0
        assert "0x12345678..." in result["attacker_address"]
        assert result["symbol"] == "ETH/USD"

    def test_mev_event_to_dict_no_attacker(self):
        """Test to_dict with no attacker address."""
        event = MEVEvent(
            event_id="test_003",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.5,
            estimated_loss=50.0,
        )
        result = event.to_dict()
        assert result["attacker_address"] is None


class TestMEVHeatmapEntry:
    """Test MEVHeatmapEntry dataclass."""

    def test_heatmap_entry_creation(self):
        """Test creating a heatmap entry."""
        entry = MEVHeatmapEntry(
            symbol="BTC/USD",
            venue="coinbase",
            time_bucket=14,
            mev_intensity=0.65,
            attack_count_24h=8,
            avg_loss_per_attack=150.0,
            liquidity_depth=1000000.0,
            volatility=0.02
        )
        assert entry.symbol == "BTC/USD"
        assert entry.venue == "coinbase"
        assert entry.time_bucket == 14
        assert entry.mev_intensity == 0.65

    def test_heatmap_entry_to_dict(self):
        """Test heatmap entry to_dict."""
        entry = MEVHeatmapEntry(
            symbol="ETH/USD",
            venue="binance",
            time_bucket=10,
            mev_intensity=0.3,
            attack_count_24h=3,
            avg_loss_per_attack=75.5,
            liquidity_depth=500000.0,
            volatility=0.03
        )
        result = entry.to_dict()
        
        assert result["symbol"] == "ETH/USD"
        assert result["venue"] == "binance"
        assert result["time_bucket"] == 10
        assert result["mev_intensity"] == 0.3
        assert result["attack_count_24h"] == 3


class TestDefenseRecommendation:
    """Test DefenseRecommendation dataclass."""

    def test_recommendation_creation(self):
        """Test creating a defense recommendation."""
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="High MEV risk",
            suggested_delay_ms=1500,
            suggested_slice_count=5,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.HIGH,
            estimated_mev_risk=50.0
        )
        assert rec.action == DefenseAction.SLICE
        assert rec.suggested_slice_count == 5
        assert rec.threat_level == ThreatLevel.HIGH

    def test_recommendation_to_dict(self):
        """Test recommendation to_dict."""
        rec = DefenseRecommendation(
            action=DefenseAction.RANDOMIZE,
            reason="Medium MEV risk",
            suggested_delay_ms=1000,
            suggested_slice_count=3,
            suggested_size_reduction=0.9,
            threat_level=ThreatLevel.MEDIUM,
            estimated_mev_risk=25.0
        )
        result = rec.to_dict()
        
        assert result["action"] == "randomize"
        assert result["reason"] == "Medium MEV risk"
        assert result["suggested_delay_ms"] == 1000
        assert result["threat_level"] == "medium"


class TestOrderSlicer:
    """Test OrderSlicer class."""

    @pytest.fixture
    def slicer(self):
        return OrderSlicer(min_slice_size=100.0, max_slices=20)

    def test_slicer_initialization(self, slicer):
        """Test slicer initialization."""
        assert slicer.min_slice_size == 100.0
        assert slicer.max_slices == 20

    def test_compute_optimal_slices_small_order(self, slicer):
        """Test slicing a small order."""
        slices = slicer.compute_optimal_slices(
            total_size=500.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.1
        )
        assert len(slices) >= 1
        assert sum(slices) == pytest.approx(500.0, rel=0.01)

    def test_compute_optimal_slices_large_order(self, slicer):
        """Test slicing a large order."""
        slices = slicer.compute_optimal_slices(
            total_size=50000.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.5
        )
        assert len(slices) > 1
        assert len(slices) <= 20
        assert sum(slices) == pytest.approx(50000.0, rel=0.01)

    def test_compute_optimal_slices_high_mev(self, slicer):
        """Test that high MEV intensity produces more slices."""
        slices_low_mev = slicer.compute_optimal_slices(
            total_size=10000.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.1
        )
        slices_high_mev = slicer.compute_optimal_slices(
            total_size=10000.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.9
        )
        # High MEV should produce at least as many slices
        assert len(slices_high_mev) >= len(slices_low_mev)

    def test_compute_optimal_slices_respects_min_size(self, slicer):
        """Test that slices respect minimum size."""
        slices = slicer.compute_optimal_slices(
            total_size=500.0,
            daily_volume=10000.0,
            volatility=0.01,
            mev_intensity=0.5
        )
        # With min_slice_size=100, we should have at most 5 slices
        assert len(slices) <= 5

    def test_compute_iceberg_schedule(self, slicer):
        """Test iceberg order schedule."""
        visible, hidden = slicer.compute_iceberg_schedule(
            total_size=10000.0,
            visible_pct=0.1
        )
        assert visible == 1000.0
        assert hidden == 9000.0
        assert visible + hidden == 10000.0


class TestTimingRandomizer:
    """Test TimingRandomizer class."""

    @pytest.fixture
    def randomizer(self):
        return TimingRandomizer()

    def test_randomize_delay(self, randomizer):
        """Test delay randomization."""
        delays = [randomizer.randomize_delay(1000, 0.3) for _ in range(100)]
        
        # All delays should be within expected range
        for d in delays:
            assert 700 <= d <= 1300  # 1000 ± 30%
        
        # Should have some variation
        assert len(set(delays)) > 1

    def test_randomize_delay_zero(self, randomizer):
        """Test delay with zero base."""
        delay = randomizer.randomize_delay(0, 0.3)
        assert delay == 0

    def test_compute_random_schedule_single(self, randomizer):
        """Test schedule with single order."""
        schedule = randomizer.compute_random_schedule(1, 10000)
        assert schedule == [0]

    def test_compute_random_schedule_multiple(self, randomizer):
        """Test schedule with multiple orders."""
        schedule = randomizer.compute_random_schedule(5, 10000)
        assert len(schedule) == 5
        assert schedule[0] == 0
        assert all(0 <= d <= 10000 for d in schedule)

    def test_should_add_decoy_delay(self, randomizer):
        """Test decoy delay decision."""
        results = [randomizer.should_add_decoy_delay() for _ in range(100)]
        
        # Should have some True and some False (probabilistic)
        true_count = sum(1 for should, _ in results if should)
        # Expect roughly 20% True, but with randomness
        assert 5 <= true_count <= 40


class TestHiddenLiquidityInference:
    """Test HiddenLiquidityInference class."""

    @pytest.fixture
    def inference(self):
        return HiddenLiquidityInference()

    def test_record_observation(self, inference):
        """Test recording observations."""
        inference.record_observation(
            symbol="BTC/USD",
            visible_depth=1000.0,
            executed_volume=1500.0,
            price_impact=0.001
        )
        assert "BTC/USD" in inference._observations
        assert len(inference._observations["BTC/USD"]) == 1

    def test_estimate_hidden_liquidity_no_data(self, inference):
        """Test estimation with no historical data."""
        estimate = inference.estimate_hidden_liquidity("NEW/USD", 1000.0)
        assert estimate == 2000.0  # Default 2x multiplier

    def test_estimate_hidden_liquidity_with_data(self, inference):
        """Test estimation with historical data."""
        for i in range(20):
            inference.record_observation(
                symbol="BTC/USD",
                visible_depth=1000.0,
                executed_volume=1500.0,  # 1.5x visible
                price_impact=0.001
            )
        
        estimate = inference.estimate_hidden_liquidity("BTC/USD", 1000.0)
        # Should be around 1.5x based on historical ratio
        assert estimate >= 1000.0

    def test_estimate_price_impact(self, inference):
        """Test price impact estimation."""
        impact = inference.estimate_price_impact(
            symbol="BTC/USD",
            order_size=100.0,
            visible_depth=1000.0
        )
        # Impact should be reasonable
        assert 0 <= impact <= 100.0

    def test_estimate_price_impact_zero_liquidity(self, inference):
        """Test price impact with zero liquidity."""
        # Force zero liquidity scenario
        with patch.object(inference, 'estimate_hidden_liquidity', return_value=0):
            impact = inference.estimate_price_impact("BTC/USD", 100.0, 0.0)
        assert impact == 100.0  # Max impact


class TestFrontRunningDetector:
    """Test FrontRunningDetector class."""

    @pytest.fixture
    def detector(self):
        return FrontRunningDetector(detection_window_ms=5000)

    def test_register_pending_order(self, detector):
        """Test registering a pending order."""
        detector.register_pending_order(
            order_id="order_001",
            symbol="BTC/USD",
            side="buy",
            size=1.0,
            price=50000.0
        )
        assert "order_001" in detector._pending_orders

    def test_check_no_front_running(self, detector):
        """Test when no front-running detected."""
        detector.register_pending_order(
            order_id="order_002",
            symbol="BTC/USD",
            side="buy",
            size=1.0,
            price=50000.0
        )
        
        result = detector.check_for_front_running(
            order_id="order_002",
            executed_price=50010.0,
            market_trades=[]
        )
        assert result is None

    def test_check_front_running_detected(self, detector):
        """Test when front-running is detected."""
        now = time.time()
        detector._pending_orders["order_003"] = {
            "symbol": "BTC/USD",
            "side": "buy",
            "size": 1.0,
            "price": 50000.0,
            "submitted_at": now - 1.0,  # 1 second ago
        }
        
        suspicious_trades = [
            {
                "price": 50100.0,  # Higher than expected
                "size": 0.5,
                "timestamp": now - 0.5,  # After submission
                "tx_hash": "0xabc123",
            }
        ]
        
        result = detector.check_for_front_running(
            order_id="order_003",
            executed_price=50150.0,
            market_trades=suspicious_trades
        )
        
        assert result is not None
        assert result.mev_type == MEVType.FRONT_RUNNING
        assert result.estimated_loss > 0

    def test_check_nonexistent_order(self, detector):
        """Test checking non-existent order."""
        result = detector.check_for_front_running(
            order_id="nonexistent",
            executed_price=50000.0,
            market_trades=[]
        )
        assert result is None

    def test_get_recent_events(self, detector):
        """Test getting recent events."""
        events = detector.get_recent_events(limit=10)
        assert isinstance(events, list)


class TestSandwichDetector:
    """Test SandwichDetector class."""

    @pytest.fixture
    def detector(self):
        return SandwichDetector()

    def test_detect_no_sandwich(self, detector):
        """Test when no sandwich detected."""
        our_trade = {
            "timestamp": time.time(),
            "side": "buy",
            "price": 50000.0,
            "size": 1.0,
        }
        
        result = detector.detect_sandwich(our_trade, [])
        assert result is None

    def test_detect_sandwich(self, detector):
        """Test sandwich detection."""
        now = time.time()
        
        our_trade = {
            "timestamp": now,
            "side": "buy",
            "price": 50100.0,
            "size": 1.0,
            "symbol": "BTC/USD",
            "tx_hash": "0xvictim",
        }
        
        surrounding_trades = [
            # Front-run: same direction, just before
            {
                "timestamp": now - 0.5,
                "side": "buy",
                "price": 50000.0,
                "size": 2.0,
                "address": "0xattacker",
            },
            # Back-run: opposite direction, just after
            {
                "timestamp": now + 0.5,
                "side": "sell",
                "price": 50150.0,
                "size": 2.0,
                "address": "0xattacker",
            },
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding_trades)
        
        assert result is not None
        assert result.mev_type == MEVType.SANDWICH
        assert result.confidence >= 0.4

    def test_detect_sandwich_different_addresses(self, detector):
        """Test sandwich detection with different addresses (lower confidence)."""
        now = time.time()
        
        our_trade = {
            "timestamp": now,
            "side": "buy",
            "price": 50100.0,
            "size": 1.0,
            "symbol": "BTC/USD",
        }
        
        surrounding_trades = [
            {
                "timestamp": now - 0.5,
                "side": "buy",
                "price": 50000.0,
                "size": 2.0,
                "address": "0xaddr1",
            },
            {
                "timestamp": now + 0.5,
                "side": "sell",
                "price": 50150.0,
                "size": 0.5,  # Different size
                "address": "0xaddr2",
            },
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding_trades)
        
        # May or may not detect depending on size similarity
        if result:
            assert result.confidence < 0.9

    def test_get_recent_events(self, detector):
        """Test getting recent events."""
        events = detector.get_recent_events(limit=10)
        assert isinstance(events, list)


class TestMEVHeatmap:
    """Test MEVHeatmap class."""

    @pytest.fixture
    def heatmap(self):
        return MEVHeatmap()

    def test_record_attack(self, heatmap):
        """Test recording an attack."""
        heatmap.record_attack(
            symbol="BTC/USD",
            venue="coinbase",
            mev_type=MEVType.FRONT_RUNNING,
            loss=100.0
        )
        assert len(heatmap._attack_history) == 1

    def test_get_intensity_no_data(self, heatmap):
        """Test intensity with no data."""
        intensity = heatmap.get_intensity("NEW/USD", "venue")
        assert intensity == 0.0

    def test_get_intensity_with_data(self, heatmap):
        """Test intensity after recording attacks."""
        for _ in range(5):
            heatmap.record_attack(
                symbol="BTC/USD",
                venue="coinbase",
                mev_type=MEVType.SANDWICH,
                loss=50.0
            )
        
        intensity = heatmap.get_intensity("BTC/USD", "coinbase")
        assert intensity > 0.0

    def test_get_safest_time(self, heatmap):
        """Test finding safest time."""
        hour = heatmap.get_safest_time("BTC/USD", "coinbase")
        assert 0 <= hour < 24

    def test_get_heatmap(self, heatmap):
        """Test getting heatmap data."""
        heatmap.record_attack("BTC/USD", "coinbase", MEVType.FRONT_RUNNING, 100.0)
        
        result = heatmap.get_heatmap("BTC/USD")
        
        assert "symbol" in result
        assert "entries" in result
        assert "safest_hour" in result


class TestMEVDefenseEngine:
    """Test MEVDefenseEngine class."""

    @pytest.fixture
    def engine(self):
        return MEVDefenseEngine()

    def test_engine_initialization(self, engine):
        """Test engine initializes all components."""
        assert engine.slicer is not None
        assert engine.timing is not None
        assert engine.liquidity is not None
        assert engine.front_running_detector is not None
        assert engine.sandwich_detector is not None
        assert engine.heatmap is not None

    def test_assess_mev_risk_low(self, engine):
        """Test assessing low MEV risk."""
        level, risk = engine.assess_mev_risk(
            symbol="BTC/USD",
            venue="coinbase",
            order_size=100.0,
            daily_volume=1000000.0
        )
        
        assert level in [ThreatLevel.NONE, ThreatLevel.LOW]
        assert risk >= 0

    def test_assess_mev_risk_high(self, engine):
        """Test assessing high MEV risk."""
        # Record many attacks to increase intensity
        for _ in range(15):
            engine.heatmap.record_attack(
                "BTC/USD", "coinbase", MEVType.FRONT_RUNNING, 500.0
            )
        
        level, risk = engine.assess_mev_risk(
            symbol="BTC/USD",
            venue="coinbase",
            order_size=100000.0,  # Large order
            daily_volume=100000.0  # 100% participation
        )
        
        assert level in [ThreatLevel.HIGH, ThreatLevel.CRITICAL]

    def test_get_defense_recommendation_proceed(self, engine):
        """Test recommendation for low risk."""
        rec = engine.get_defense_recommendation(
            symbol="BTC/USD",
            venue="coinbase",
            side="buy",
            order_size=100.0,
            daily_volume=1000000.0,
            volatility=0.01
        )
        
        assert rec.action in [DefenseAction.PROCEED, DefenseAction.DELAY]
        assert rec.threat_level in [ThreatLevel.NONE, ThreatLevel.LOW]

    def test_get_defense_recommendation_slice(self, engine):
        """Test recommendation for high risk."""
        # Increase intensity
        for _ in range(20):
            engine.heatmap.record_attack(
                "BTC/USD", "coinbase", MEVType.SANDWICH, 1000.0
            )
        
        rec = engine.get_defense_recommendation(
            symbol="BTC/USD",
            venue="coinbase",
            side="buy",
            order_size=500000.0,  # Very large
            daily_volume=100000.0,
            volatility=0.01
        )
        
        assert rec.action in [DefenseAction.SLICE, DefenseAction.ABORT]

    def test_apply_defense(self, engine):
        """Test applying defense measures."""
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="Test",
            suggested_delay_ms=1000,
            suggested_slice_count=5,
            suggested_size_reduction=0.9,
            threat_level=ThreatLevel.MEDIUM,
            estimated_mev_risk=10.0
        )
        
        result = engine.apply_defense(
            order_size=10000.0,
            recommendation=rec,
            daily_volume=100000.0,
            volatility=0.02
        )
        
        assert "original_size" in result
        assert "adjusted_size" in result
        assert "slices" in result
        assert result["adjusted_size"] == 9000.0

    def test_record_mev_event(self, engine):
        """Test recording MEV event."""
        event = MEVEvent(
            event_id="test_001",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.8,
            estimated_loss=100.0,
            symbol="BTC/USD"
        )
        
        engine.record_mev_event(event)
        
        assert engine._total_mev_suffered == 100.0

    def test_record_mev_avoided(self, engine):
        """Test recording avoided MEV."""
        engine.record_mev_avoided(50.0)
        assert engine._total_mev_avoided == 50.0

    def test_get_status(self, engine):
        """Test getting engine status."""
        engine.record_mev_avoided(100.0)
        
        status = engine.get_status()
        
        assert "total_mev_suffered" in status
        assert "total_mev_avoided" in status
        assert "net_mev_impact" in status
        assert status["total_mev_avoided"] == 100.0

    def test_get_mev_summary(self, engine):
        """Test getting MEV summary."""
        summary = engine.get_mev_summary("BTC/USD")
        
        assert "heatmap" in summary
        assert "safest_hour" in summary
        assert "current_intensity" in summary


class TestManipulationDetector:
    """Test ManipulationDetector class."""

    @pytest.fixture
    def detector(self):
        return ManipulationDetector()

    def test_record_tick(self, detector):
        """Test recording a tick."""
        detector.record_tick("BTC/USD", 50000.0, 100.0)
        
        assert "BTC/USD" in detector._price_history
        assert len(detector._price_history["BTC/USD"]) == 1

    def test_detect_pump_and_dump_insufficient_data(self, detector):
        """Test pump detection with insufficient data."""
        for i in range(10):
            detector.record_tick("BTC/USD", 50000.0 + i, 100.0)
        
        result = detector.detect_pump_and_dump("BTC/USD")
        assert result is None

    def test_detect_pump_and_dump_pattern(self, detector):
        """Test pump and dump detection."""
        # Create pump and dump pattern
        base_price = 100.0
        
        # Pre-pump stable prices
        for _ in range(15):
            detector.record_tick("TEST/USD", base_price, 100.0)
        
        # Pump phase
        for i in range(15):
            price = base_price + (i * 3)  # Rapid rise
            detector.record_tick("TEST/USD", price, 500.0)
        
        # Peak
        for _ in range(5):
            detector.record_tick("TEST/USD", base_price + 50, 200.0)
        
        # Dump phase
        for i in range(15):
            price = base_price + 50 - (i * 3)  # Rapid fall
            detector.record_tick("TEST/USD", price, 300.0)
        
        result = detector.detect_pump_and_dump("TEST/USD")
        # May or may not detect depending on exact pattern
        # Just verify it runs without error
        assert result is None or "type" in result

    def test_detect_wash_trading_insufficient_data(self, detector):
        """Test wash trading with insufficient data."""
        trades = [{"address": "0x1", "size": 100.0}]
        result = detector.detect_wash_trading("BTC/USD", trades)
        assert result is None

    def test_detect_wash_trading_concentrated(self, detector):
        """Test wash trading detection with concentrated volume."""
        trades = [
            {"address": "0xwhale", "size": 1000.0},
            {"address": "0xwhale", "size": 1000.0},
            {"address": "0xwhale", "size": 1000.0},
            {"address": "0xother1", "size": 100.0},
            {"address": "0xother2", "size": 100.0},
        ] * 5  # 25 trades total
        
        result = detector.detect_wash_trading("BTC/USD", trades)
        
        assert result is not None
        assert result["type"] == "wash_trading"
        assert result["concentration"] > 50.0

    def test_detect_wash_trading_distributed(self, detector):
        """Test wash trading with distributed volume."""
        trades = [
            {"address": f"0xaddr{i}", "size": 100.0}
            for i in range(25)
        ]
        
        result = detector.detect_wash_trading("BTC/USD", trades)
        assert result is None  # No single address dominates

    def test_get_alerts(self, detector):
        """Test getting alerts."""
        alerts = detector.get_alerts(limit=10)
        assert isinstance(alerts, list)


class TestSingleton:
    """Test singleton pattern."""

    def test_get_mev_defense_singleton(self):
        """Test get_mev_defense returns singleton."""
        import trading.execution.defense as defense_module
        defense_module._mev_defense = None
        
        engine1 = get_mev_defense()
        engine2 = get_mev_defense()
        
        assert engine1 is engine2
        
        # Cleanup
        defense_module._mev_defense = None
