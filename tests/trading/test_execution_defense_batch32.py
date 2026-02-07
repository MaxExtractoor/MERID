"""Tests for trading execution defense module - Batch 32 Coverage."""
import pytest
from unittest.mock import MagicMock, patch
import time
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
    """Tests for defense enums."""

    def test_mev_type_values(self):
        assert MEVType.FRONT_RUNNING.value == "front_running"
        assert MEVType.BACK_RUNNING.value == "back_running"
        assert MEVType.SANDWICH.value == "sandwich"
        assert MEVType.LIQUIDATION.value == "liquidation"
        assert MEVType.ARBITRAGE.value == "arbitrage"
        assert MEVType.JIT_LIQUIDITY.value == "jit_liquidity"

    def test_threat_level_values(self):
        assert ThreatLevel.NONE.value == "none"
        assert ThreatLevel.LOW.value == "low"
        assert ThreatLevel.MEDIUM.value == "medium"
        assert ThreatLevel.HIGH.value == "high"
        assert ThreatLevel.CRITICAL.value == "critical"

    def test_defense_action_values(self):
        assert DefenseAction.PROCEED.value == "proceed"
        assert DefenseAction.DELAY.value == "delay"
        assert DefenseAction.SLICE.value == "slice"
        assert DefenseAction.RANDOMIZE.value == "randomize"
        assert DefenseAction.ABORT.value == "abort"
        assert DefenseAction.USE_PRIVATE_MEMPOOL.value == "use_private_mempool"


class TestMEVEvent:
    """Tests for MEVEvent dataclass."""

    @pytest.fixture
    def mev_event(self):
        return MEVEvent(
            event_id="event_123",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.85,
            estimated_loss=100.0,
            attacker_address="0x1234567890abcdef",
            symbol="BTC/USD",
            block_number=12345,
        )

    def test_event_creation(self, mev_event):
        assert mev_event.event_id == "event_123"
        assert mev_event.mev_type == MEVType.FRONT_RUNNING
        assert mev_event.confidence == 0.85
        assert mev_event.estimated_loss == 100.0

    def test_event_to_dict(self, mev_event):
        d = mev_event.to_dict()
        assert d["event_id"] == "event_123"
        assert d["mev_type"] == "front_running"
        assert d["confidence"] == 0.85


class TestDefenseRecommendation:
    """Tests for DefenseRecommendation dataclass."""

    @pytest.fixture
    def recommendation(self):
        return DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="High MEV risk",
            suggested_delay_ms=1000,
            suggested_slice_count=5,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.HIGH,
            estimated_mev_risk=50.0,
        )

    def test_recommendation_creation(self, recommendation):
        assert recommendation.action == DefenseAction.SLICE
        assert recommendation.threat_level == ThreatLevel.HIGH
        assert recommendation.estimated_mev_risk == 50.0

    def test_recommendation_to_dict(self, recommendation):
        d = recommendation.to_dict()
        assert d["action"] == "slice"
        assert d["threat_level"] == "high"


class TestOrderSlicer:
    """Tests for OrderSlicer."""

    @pytest.fixture
    def slicer(self):
        return OrderSlicer(min_slice_size=100.0, max_slices=20)

    def test_initialization(self, slicer):
        assert slicer.min_slice_size == 100.0
        assert slicer.max_slices == 20

    def test_compute_optimal_slices_basic(self, slicer):
        slices = slicer.compute_optimal_slices(
            total_size=1000.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.3,
        )
        assert len(slices) >= 1
        assert len(slices) <= 20
        assert sum(slices) > 990 and sum(slices) < 1010

    def test_compute_optimal_slices_respects_min_size(self, slicer):
        slices = slicer.compute_optimal_slices(
            total_size=150.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.1,
        )
        assert all(s >= 100.0 for s in slices)

    def test_compute_iceberg_schedule(self, slicer):
        visible, hidden = slicer.compute_iceberg_schedule(1000.0, visible_pct=0.1)
        assert visible == 100.0
        assert hidden == 900.0


class TestTimingRandomizer:
    """Tests for TimingRandomizer."""

    @pytest.fixture
    def randomizer(self):
        return TimingRandomizer()

    def test_randomize_delay(self, randomizer):
        delay = randomizer.randomize_delay(1000, jitter_pct=0.3)
        assert delay >= 700 and delay <= 1300

    def test_compute_random_schedule(self, randomizer):
        schedule = randomizer.compute_random_schedule(5, 10000)
        assert len(schedule) == 5
        assert schedule[0] == 0
        assert all(d >= 0 for d in schedule)

    def test_compute_random_schedule_single(self, randomizer):
        schedule = randomizer.compute_random_schedule(1, 10000)
        assert schedule == [0]

    def test_should_add_decoy_delay(self, randomizer):
        # Test multiple times since it's random
        results = [randomizer.should_add_decoy_delay() for _ in range(100)]
        delays = [d for should, d in results if should]
        assert all(d >= 500 and d <= 5000 for d in delays)


class TestHiddenLiquidityInference:
    """Tests for HiddenLiquidityInference."""

    @pytest.fixture
    def inference(self):
        return HiddenLiquidityInference()

    def test_estimate_hidden_liquidity_no_data(self, inference):
        liquidity = inference.estimate_hidden_liquidity("BTC", 1000.0)
        assert liquidity == 2000.0  # Default 2x

    def test_record_and_estimate(self, inference):
        # Add observations showing high execution relative to visible depth
        for _ in range(15):
            inference.record_observation("BTC", 1000.0, 3000.0, 0.01)
        liquidity = inference.estimate_hidden_liquidity("BTC", 1000.0)
        # Should be greater than visible depth due to high execution ratio
        assert liquidity > 1000.0

    def test_estimate_price_impact(self, inference):
        impact = inference.estimate_price_impact("BTC", 100.0, 1000.0)
        assert isinstance(impact, float)
        assert impact > 0


class TestFrontRunningDetector:
    """Tests for FrontRunningDetector."""

    @pytest.fixture
    def detector(self):
        return FrontRunningDetector(detection_window_ms=5000)

    def test_register_pending_order(self, detector):
        detector.register_pending_order("order_123", "BTC/USD", "buy", 1.0, 50000.0)
        assert "order_123" in detector._pending_orders

    def test_check_for_front_running_no_pending(self, detector):
        event = detector.check_for_front_running("order_123", 50000.0, [])
        assert event is None

    def test_get_recent_events_empty(self, detector):
        events = detector.get_recent_events()
        assert events == []


class TestSandwichDetector:
    """Tests for SandwichDetector."""

    @pytest.fixture
    def detector(self):
        return SandwichDetector()

    def test_detect_sandwich_no_pattern(self, detector):
        our_trade = {"timestamp": time.time(), "side": "buy", "price": 50000.0, "size": 1.0}
        surrounding = []
        event = detector.detect_sandwich(our_trade, surrounding)
        assert event is None

    def test_get_recent_events_empty(self, detector):
        events = detector.get_recent_events()
        assert events == []


class TestMEVHeatmap:
    """Tests for MEVHeatmap."""

    @pytest.fixture
    def heatmap(self):
        return MEVHeatmap()

    def test_record_attack(self, heatmap):
        heatmap.record_attack("BTC/USD", "binance", MEVType.FRONT_RUNNING, 100.0)
        assert len(heatmap._attack_history) == 1

    def test_get_intensity_no_data(self, heatmap):
        intensity = heatmap.get_intensity("BTC/USD", "binance")
        assert intensity == 0.0

    def test_get_safest_time_no_data(self, heatmap):
        safest = heatmap.get_safest_time("BTC/USD", "binance")
        assert 0 <= safest < 24

    def test_get_heatmap_empty(self, heatmap):
        data = heatmap.get_heatmap("BTC/USD")
        assert data["symbol"] == "BTC/USD"
        assert data["entries"] == []


class TestMEVDefenseEngine:
    """Tests for MEVDefenseEngine."""

    @pytest.fixture
    def engine(self):
        return MEVDefenseEngine()

    def test_initialization(self, engine):
        assert engine.slicer is not None
        assert engine.timing is not None
        assert engine.liquidity is not None
        assert engine.front_running_detector is not None
        assert engine.sandwich_detector is not None
        assert engine.heatmap is not None

    def test_assess_mev_risk_low(self, engine):
        level, risk = engine.assess_mev_risk("BTC/USD", "binance", 1000.0, 1000000.0)
        assert level in ThreatLevel
        assert risk >= 0.0

    def test_get_defense_recommendation(self, engine):
        rec = engine.get_defense_recommendation(
            "BTC/USD", "binance", "buy", 1000.0, 1000000.0, 0.02
        )
        assert rec.action in DefenseAction
        assert rec.threat_level in ThreatLevel
        assert rec.suggested_slice_count >= 1

    def test_apply_defense(self, engine):
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="Test",
            suggested_delay_ms=1000,
            suggested_slice_count=5,
            suggested_size_reduction=1.0,
            threat_level=ThreatLevel.MEDIUM,
            estimated_mev_risk=10.0,
        )
        result = engine.apply_defense(1000.0, rec, 1000000.0, 0.02)
        assert "slices" in result
        assert "total_duration_ms" in result
        assert len(result["slices"]) > 0

    def test_record_mev_event(self, engine):
        event = MEVEvent(
            event_id="evt_123",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.8,
            estimated_loss=50.0,
            symbol="BTC/USD",
        )
        engine.record_mev_event(event)
        assert engine._total_mev_suffered == 50.0

    def test_record_mev_avoided(self, engine):
        engine.record_mev_avoided(100.0)
        assert engine._total_mev_avoided == 100.0

    def test_get_status(self, engine):
        status = engine.get_status()
        assert "total_mev_suffered" in status
        assert "total_mev_avoided" in status
        assert "recent_action_counts" in status

    def test_get_mev_summary(self, engine):
        summary = engine.get_mev_summary("BTC/USD")
        assert "heatmap" in summary
        assert "safest_hour" in summary
        assert "current_intensity" in summary


class TestManipulationDetector:
    """Tests for ManipulationDetector."""

    @pytest.fixture
    def detector(self):
        return ManipulationDetector()

    def test_record_tick(self, detector):
        detector.record_tick("BTC/USD", 50000.0, 100.0)
        assert "BTC/USD" in detector._price_history

    def test_detect_pump_and_dump_insufficient_data(self, detector):
        result = detector.detect_pump_and_dump("BTC/USD")
        assert result is None

    def test_detect_wash_trading_insufficient_trades(self, detector):
        result = detector.detect_wash_trading("BTC/USD", [])
        assert result is None

    def test_get_alerts_empty(self, detector):
        alerts = detector.get_alerts()
        assert alerts == []


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_mev_defense(self):
        # Reset singleton
        import trading.execution.defense as defense_module
        defense_module._mev_defense = None

        defense1 = get_mev_defense()
        defense2 = get_mev_defense()
        assert defense1 is defense2
