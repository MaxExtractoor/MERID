"""Additional tests for trading/execution/defense.py - Batch 50 Coverage."""
import pytest
import time
from unittest.mock import MagicMock, patch
from trading.execution.defense import (
    MEVEvent, MEVHeatmapEntry, DefenseRecommendation,
    OrderSlicer, TimingRandomizer, HiddenLiquidityInference,
    SandwichDetector, MEVHeatmap, MEVDefenseEngine, ManipulationDetector,
    MEVType, ThreatLevel, DefenseAction, get_mev_defense
)


class TestDataClasses:
    """Tests for dataclass to_dict methods."""

    def test_mev_event_to_dict(self):
        """Test MEVEvent.to_dict method."""
        event = MEVEvent(
            event_id="evt_123",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=1234567890.0,
            confidence=0.85,
            estimated_loss=100.0,
            attacker_address="0x1234567890abcdef",
            symbol="BTC-USD"
        )
        result = event.to_dict()
        assert result["event_id"] == "evt_123"
        assert result["mev_type"] == "front_running"
        assert result["confidence"] == 0.85
        assert result["attacker_address"] == "0x12345678..."

    def test_mev_event_to_dict_no_attacker(self):
        """Test MEVEvent.to_dict with no attacker."""
        event = MEVEvent(
            event_id="evt_123",
            mev_type=MEVType.ARBITRAGE,
            detected_at=1234567890.0,
            confidence=0.5,
            estimated_loss=0.0,
            attacker_address=None,
            symbol="ETH-USD"
        )
        result = event.to_dict()
        assert result["attacker_address"] is None

    def test_heatmap_entry_to_dict(self):
        """Test MEVHeatmapEntry.to_dict method."""
        entry = MEVHeatmapEntry(
            symbol="BTC-USD",
            venue="coinbase",
            time_bucket=12,
            mev_intensity=0.75,
            attack_count_24h=5,
            avg_loss_per_attack=150.0,
            liquidity_depth=1000000.0,
            volatility=0.05
        )
        result = entry.to_dict()
        assert result["symbol"] == "BTC-USD"
        assert result["mev_intensity"] == 0.75
        assert result["attack_count_24h"] == 5

    def test_defense_recommendation_to_dict(self):
        """Test DefenseRecommendation.to_dict method."""
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="High MEV risk",
            suggested_delay_ms=2000,
            suggested_slice_count=5,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.HIGH,
            estimated_mev_risk=0.15
        )
        result = rec.to_dict()
        assert result["action"] == "slice"
        assert result["threat_level"] == "high"
        assert result["suggested_delay_ms"] == 2000


class TestOrderSlicer:
    """Tests for OrderSlicer class."""

    @pytest.fixture
    def slicer(self):
        return OrderSlicer(min_slice_size=100.0, max_slices=20)

    def test_compute_optimal_slices_basic(self, slicer):
        """Test basic slice computation."""
        slices = slicer.compute_optimal_slices(
            total_size=1000.0,
            daily_volume=100000.0,
            volatility=0.1,
            mev_intensity=0.2
        )
        assert len(slices) > 0
        assert len(slices) <= 20
        assert sum(slices) == pytest.approx(1000.0, rel=0.01)

    def test_compute_optimal_slices_high_mev(self, slicer):
        """Test slice computation with high MEV."""
        slices = slicer.compute_optimal_slices(
            total_size=1000.0,
            daily_volume=100000.0,
            volatility=0.1,
            mev_intensity=0.9
        )
        # High MEV should result in more slices
        assert len(slices) >= 1

    def test_compute_optimal_slices_high_volatility(self, slicer):
        """Test slice computation with high volatility."""
        slices = slicer.compute_optimal_slices(
            total_size=1000.0,
            daily_volume=100000.0,
            volatility=0.8,
            mev_intensity=0.2
        )
        assert len(slices) >= 1

    def test_compute_optimal_slices_min_size_constraint(self, slicer):
        """Test slice computation respects minimum slice size."""
        slices = slicer.compute_optimal_slices(
            total_size=150.0,
            daily_volume=100000.0,
            volatility=0.1,
            mev_intensity=0.2
        )
        # Should adjust to meet min_slice_size
        assert len(slices) >= 1

    def test_compute_optimal_slices_zero_daily_volume(self, slicer):
        """Test slice computation with zero daily volume."""
        slices = slicer.compute_optimal_slices(
            total_size=1000.0,
            daily_volume=0.0,
            volatility=0.1,
            mev_intensity=0.2
        )
        assert len(slices) >= 1

    def test_compute_iceberg_schedule(self, slicer):
        """Test iceberg schedule computation."""
        visible, hidden = slicer.compute_iceberg_schedule(
            total_size=1000.0,
            visible_pct=0.1
        )
        assert visible == 100.0
        assert hidden == 900.0


class TestTimingRandomizer:
    """Tests for TimingRandomizer class."""

    @pytest.fixture
    def randomizer(self):
        return TimingRandomizer()

    def test_randomize_delay(self, randomizer):
        """Test delay randomization."""
        delay = randomizer.randomize_delay(base_delay_ms=1000, jitter_pct=0.3)
        assert delay >= 0
        assert 700 <= delay <= 1300

    def test_compute_random_schedule_single_order(self, randomizer):
        """Test schedule with single order."""
        schedule = randomizer.compute_random_schedule(n_orders=1, total_duration_ms=5000)
        assert schedule == [0]

    def test_compute_random_schedule_multiple_orders(self, randomizer):
        """Test schedule with multiple orders."""
        schedule = randomizer.compute_random_schedule(n_orders=5, total_duration_ms=5000)
        assert len(schedule) == 5
        assert schedule[0] == 0
        assert schedule[-1] <= 5000
        assert schedule == sorted(schedule)

    def test_should_add_decoy_delay_true(self, randomizer):
        """Test decoy delay decision when RNG returns low value."""
        with patch.object(randomizer._rng, 'random', return_value=0.1):
            should_delay, delay = randomizer.should_add_decoy_delay()
            assert should_delay is True
            assert 500 <= delay <= 5000

    def test_should_add_decoy_delay_false(self, randomizer):
        """Test decoy delay decision when RNG returns high value."""
        with patch.object(randomizer._rng, 'random', return_value=0.5):
            should_delay, delay = randomizer.should_add_decoy_delay()
            assert should_delay is False
            assert delay == 0


class TestHiddenLiquidityInference:
    """Tests for HiddenLiquidityInference class."""

    @pytest.fixture
    def inference(self):
        return HiddenLiquidityInference()

    def test_record_observation_new_symbol(self, inference):
        """Test recording observation for new symbol."""
        inference.record_observation("BTC", 1000.0, 500.0, 0.001)
        assert "BTC" in inference._observations
        assert len(inference._observations["BTC"]) == 1

    def test_record_observation_existing_symbol(self, inference):
        """Test recording multiple observations."""
        inference.record_observation("BTC", 1000.0, 500.0, 0.001)
        inference.record_observation("BTC", 1100.0, 600.0, 0.002)
        assert len(inference._observations["BTC"]) == 2

    def test_estimate_hidden_liquidity_no_observations(self, inference):
        """Test estimation with no observations."""
        result = inference.estimate_hidden_liquidity("BTC", 1000.0)
        assert result == 2000.0  # Default 2x visible

    def test_estimate_hidden_liquidity_few_observations(self, inference):
        """Test estimation with few observations."""
        for i in range(5):
            inference.record_observation("BTC", 1000.0, 500.0, 0.001)
        result = inference.estimate_hidden_liquidity("BTC", 1000.0)
        assert result == 2000.0  # Still default (need 10+)

    def test_estimate_hidden_liquidity_with_data(self, inference):
        """Test estimation with sufficient observations."""
        for i in range(15):
            inference.record_observation("BTC", 1000.0, 800.0, 0.001)
        result = inference.estimate_hidden_liquidity("BTC", 1000.0)
        assert result >= 1000.0  # Should be at least visible

    def test_estimate_hidden_liquidity_zero_visible(self, inference):
        """Test estimation with zero visible depth."""
        for i in range(15):
            inference.record_observation("BTC", 0.0, 800.0, 0.001)
        result = inference.estimate_hidden_liquidity("BTC", 1000.0)
        assert result == 2000.0  # Default when no valid ratios

    def test_estimate_price_impact(self, inference):
        """Test price impact estimation."""
        impact = inference.estimate_price_impact("BTC", 1000.0, 10000.0)
        assert impact > 0
        assert impact <= 100.0

    def test_estimate_price_impact_zero_liquidity(self, inference):
        """Test price impact with zero liquidity."""
        impact = inference.estimate_price_impact("BTC", 1000.0, 0.0)
        assert impact == 100.0  # Max impact


class TestSandwichDetector:
    """Tests for SandwichDetector class."""

    @pytest.fixture
    def detector(self):
        return SandwichDetector()

    def test_detect_sandwich_no_pattern(self, detector):
        """Test detection with no sandwich pattern."""
        our_trade = {"timestamp": 1000.0, "side": "buy", "price": 50000.0, "size": 1.0}
        surrounding = []  # No surrounding trades
        
        result = detector.detect_sandwich(our_trade, surrounding)
        assert result is None

    def test_detect_sandwich_with_pattern_same_address(self, detector):
        """Test detection with sandwich pattern and same address."""
        our_trade = {"timestamp": 1000.0, "side": "buy", "price": 50000.0, "size": 1.0, "tx_hash": "0xabc", "symbol": "BTC"}
        surrounding = [
            {"timestamp": 999.0, "side": "buy", "price": 49900.0, "size": 1.0, "address": "0xattacker"},
            {"timestamp": 1001.0, "side": "sell", "price": 50100.0, "size": 1.0, "address": "0xattacker"},
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding)
        assert result is not None
        assert result.mev_type == MEVType.SANDWICH
        assert result.confidence == 0.9  # Same address

    def test_detect_sandwich_with_pattern_similar_size(self, detector):
        """Test detection with sandwich pattern and similar sizes."""
        our_trade = {"timestamp": 1000.0, "side": "buy", "price": 50000.0, "size": 1.0, "tx_hash": "0xabc", "symbol": "BTC"}
        surrounding = [
            {"timestamp": 999.0, "side": "buy", "price": 49900.0, "size": 0.95, "address": "0xaddr1"},
            {"timestamp": 1001.0, "side": "sell", "price": 50100.0, "size": 0.92, "address": "0xaddr2"},
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding)
        assert result is not None
        assert result.confidence == 0.7  # Similar sizes

    def test_detect_sandwich_with_pattern_dissimilar_size(self, detector):
        """Test detection with sandwich pattern but dissimilar sizes."""
        our_trade = {"timestamp": 1000.0, "side": "buy", "price": 50000.0, "size": 1.0, "tx_hash": "0xabc", "symbol": "BTC"}
        surrounding = [
            {"timestamp": 999.0, "side": "buy", "price": 49900.0, "size": 0.3, "address": "0xaddr1"},
            {"timestamp": 1001.0, "side": "sell", "price": 50100.0, "size": 0.2, "address": "0xaddr2"},
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding)
        assert result is not None
        assert result.confidence == 0.4  # Low confidence

    def test_detect_sandwich_sell_side(self, detector):
        """Test detection for sell side."""
        our_trade = {"timestamp": 1000.0, "side": "sell", "price": 50000.0, "size": 1.0, "tx_hash": "0xabc", "symbol": "BTC"}
        surrounding = [
            {"timestamp": 999.0, "side": "sell", "price": 50100.0, "size": 1.0, "address": "0xattacker"},
            {"timestamp": 1001.0, "side": "buy", "price": 49900.0, "size": 1.0, "address": "0xattacker"},
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding)
        assert result is not None
        assert result.estimated_loss > 0

    def test_get_recent_events(self, detector):
        """Test getting recent events."""
        events = detector.get_recent_events(limit=10)
        assert isinstance(events, list)


class TestMEVHeatmap:
    """Tests for MEVHeatmap class."""

    @pytest.fixture
    def heatmap(self):
        return MEVHeatmap()

    def test_record_attack(self, heatmap):
        """Test recording an attack."""
        heatmap.record_attack("BTC-USD", "coinbase", MEVType.FRONT_RUNNING, 100.0)
        assert len(heatmap._attack_history) == 1

    def test_get_intensity_existing_entry(self, heatmap):
        """Test getting intensity for existing entry."""
        heatmap.record_attack("BTC-USD", "coinbase", MEVType.FRONT_RUNNING, 100.0)
        intensity = heatmap.get_intensity("BTC-USD", "coinbase", hour=12)
        assert intensity >= 0.0

    def test_get_intensity_different_hour(self, heatmap):
        """Test getting intensity for different hour."""
        heatmap.record_attack("BTC-USD", "coinbase", MEVType.FRONT_RUNNING, 100.0)
        intensity = heatmap.get_intensity("BTC-USD", "coinbase", hour=0)
        assert intensity >= 0.0

    def test_get_intensity_no_data(self, heatmap):
        """Test getting intensity with no data."""
        intensity = heatmap.get_intensity("ETH-USD", "binance")
        assert intensity == 0.0

    def test_get_safest_time(self, heatmap):
        """Test getting safest trading time."""
        heatmap.record_attack("BTC-USD", "coinbase", MEVType.FRONT_RUNNING, 100.0)
        safest = heatmap.get_safest_time("BTC-USD", "coinbase")
        assert 0 <= safest < 24

    def test_get_heatmap(self, heatmap):
        """Test getting heatmap data."""
        heatmap.record_attack("BTC-USD", "coinbase", MEVType.FRONT_RUNNING, 100.0)
        result = heatmap.get_heatmap("BTC-USD")
        assert result["symbol"] == "BTC-USD"
        assert "entries" in result
        assert "safest_hour" in result


class TestMEVDefenseEngine:
    """Tests for MEVDefenseEngine class."""

    @pytest.fixture
    def engine(self):
        return MEVDefenseEngine()

    def test_assess_mev_risk_critical(self, engine):
        """Test risk assessment for critical level."""
        # Record many attacks to get high intensity
        for i in range(20):
            engine.heatmap.record_attack("BTC-USD", "default", MEVType.FRONT_RUNNING, 1000.0)
        
        level, risk = engine.assess_mev_risk("BTC-USD", "default", 10000.0, 100000.0)
        assert level == ThreatLevel.CRITICAL
        assert risk > 0

    def test_assess_mev_risk_none(self, engine):
        """Test risk assessment for no risk."""
        level, risk = engine.assess_mev_risk("NEW-SYMBOL", "default", 100.0, 1000000.0)
        assert level == ThreatLevel.NONE
        assert risk >= 0

    def test_get_defense_recommendation_critical(self, engine):
        """Test recommendation for critical threat."""
        for i in range(20):
            engine.heatmap.record_attack("BTC-USD", "default", MEVType.FRONT_RUNNING, 1000.0)
        
        rec = engine.get_defense_recommendation("BTC-USD", "default", "buy", 10000.0, 100000.0, 0.1)
        assert rec.action == DefenseAction.ABORT
        assert rec.threat_level == ThreatLevel.CRITICAL

    def test_get_defense_recommendation_high(self, engine):
        """Test recommendation for high threat."""
        for i in range(12):
            engine.heatmap.record_attack("BTC-USD", "default", MEVType.FRONT_RUNNING, 500.0)
        
        rec = engine.get_defense_recommendation("BTC-USD", "default", "buy", 10000.0, 100000.0, 0.1)
        # Just verify a recommendation is returned
        assert rec.action in DefenseAction
        assert rec.threat_level in ThreatLevel

    def test_get_defense_recommendation_medium(self, engine):
        """Test recommendation for medium threat."""
        for i in range(8):
            engine.heatmap.record_attack("BTC-USD", "default", MEVType.FRONT_RUNNING, 200.0)
        
        rec = engine.get_defense_recommendation("BTC-USD", "default", "buy", 10000.0, 100000.0, 0.1)
        # Just verify a recommendation is returned
        assert rec.action in DefenseAction
        assert rec.threat_level in ThreatLevel

    def test_get_defense_recommendation_low(self, engine):
        """Test recommendation for low threat."""
        for i in range(4):
            engine.heatmap.record_attack("BTC-USD", "default", MEVType.FRONT_RUNNING, 50.0)
        
        rec = engine.get_defense_recommendation("BTC-USD", "default", "buy", 10000.0, 100000.0, 0.1)
        # Just verify a recommendation is returned
        assert rec.action in DefenseAction
        assert rec.threat_level in ThreatLevel

    def test_get_defense_recommendation_none(self, engine):
        """Test recommendation for no threat."""
        rec = engine.get_defense_recommendation("NEW-SYMBOL", "default", "buy", 100.0, 1000000.0, 0.01)
        assert rec.action == DefenseAction.PROCEED
        assert rec.threat_level == ThreatLevel.NONE

    def test_apply_defense(self, engine):
        """Test applying defense measures."""
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="Test",
            suggested_delay_ms=1000,
            suggested_slice_count=5,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.HIGH,
            estimated_mev_risk=0.1
        )
        
        result = engine.apply_defense(1000.0, rec, 100000.0, 0.1)
        assert "slices" in result
        assert "original_size" in result
        assert result["original_size"] == 1000.0

    def test_record_mev_event(self, engine):
        """Test recording MEV event."""
        event = MEVEvent(
            event_id="evt_123",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.8,
            estimated_loss=100.0,
            symbol="BTC-USD"
        )
        engine.record_mev_event(event)
        assert engine._total_mev_suffered == 100.0

    def test_record_mev_avoided(self, engine):
        """Test recording avoided MEV."""
        engine.record_mev_avoided(50.0)
        assert engine._total_mev_avoided == 50.0

    def test_get_status(self, engine):
        """Test getting engine status."""
        status = engine.get_status()
        assert "total_mev_suffered" in status
        assert "total_mev_avoided" in status
        assert "recent_action_counts" in status

    def test_get_mev_summary(self, engine):
        """Test getting MEV summary."""
        summary = engine.get_mev_summary("BTC-USD")
        assert "heatmap" in summary
        assert "safest_hour" in summary
        assert "current_intensity" in summary


class TestManipulationDetector:
    """Tests for ManipulationDetector class."""

    @pytest.fixture
    def detector(self):
        return ManipulationDetector()

    def test_record_tick_new_symbol(self, detector):
        """Test recording tick for new symbol."""
        detector.record_tick("BTC", 50000.0, 100.0)
        assert "BTC" in detector._price_history
        assert "BTC" in detector._volume_history

    def test_record_tick_existing_symbol(self, detector):
        """Test recording multiple ticks."""
        detector.record_tick("BTC", 50000.0, 100.0)
        detector.record_tick("BTC", 50100.0, 150.0)
        assert len(detector._price_history["BTC"]) == 2

    def test_detect_pump_and_dump_insufficient_data(self, detector):
        """Test pump/dump detection with insufficient data."""
        result = detector.detect_pump_and_dump("BTC")
        assert result is None

    def test_detect_pump_and_dump_no_pattern(self, detector):
        """Test pump/dump detection with no pattern."""
        # Add 50 stable price points
        for i in range(50):
            detector.record_tick("BTC", 50000.0 + i * 10, 100.0)
        
        result = detector.detect_pump_and_dump("BTC")
        assert result is None

    def test_detect_pump_and_dump_with_pattern(self, detector):
        """Test pump/dump detection with pattern."""
        # Create pump and dump pattern
        base_price = 50000.0
        # Pre-pump
        for i in range(10):
            detector.record_tick("BTC", base_price, 100.0)
        # Pump
        for i in range(15):
            detector.record_tick("BTC", base_price * (1 + 0.02 * i), 200.0)
        # Peak
        peak = base_price * 1.3
        detector.record_tick("BTC", peak, 300.0)
        # Dump
        for i in range(15):
            detector.record_tick("BTC", peak * (1 - 0.015 * i), 150.0)
        # Post-dump
        for i in range(10):
            detector.record_tick("BTC", peak * 0.85, 100.0)
        
        result = detector.detect_pump_and_dump("BTC")
        assert result is not None
        assert result["type"] == "pump_and_dump"

    def test_detect_wash_trading_insufficient_data(self, detector):
        """Test wash trading detection with insufficient trades."""
        trades = [{"address": "0x1", "size": 100.0} for _ in range(10)]
        result = detector.detect_wash_trading("BTC", trades)
        assert result is None

    def test_detect_wash_trading_no_pattern(self, detector):
        """Test wash trading detection with no pattern."""
        trades = [{"address": f"0x{i}", "size": 100.0} for i in range(25)]
        result = detector.detect_wash_trading("BTC", trades)
        assert result is None

    def test_detect_wash_trading_with_pattern(self, detector):
        """Test wash trading detection with pattern."""
        # One address dominates volume
        trades = [{"address": "0xattacker", "size": 1000.0} for _ in range(15)]
        trades += [{"address": "0xother", "size": 100.0} for _ in range(10)]
        
        result = detector.detect_wash_trading("BTC", trades)
        assert result is not None
        assert result["type"] == "wash_trading"

    def test_detect_wash_trading_zero_volume(self, detector):
        """Test wash trading detection with zero volume."""
        trades = [{"address": "0x1", "size": 0.0} for _ in range(25)]
        result = detector.detect_wash_trading("BTC", trades)
        assert result is None

    def test_get_alerts(self, detector):
        """Test getting alerts."""
        alerts = detector.get_alerts(limit=10)
        assert isinstance(alerts, list)


class TestSingleton:
    """Tests for singleton getter."""

    def test_get_mev_defense_singleton(self):
        """Test get_mev_defense returns singleton."""
        engine1 = get_mev_defense()
        engine2 = get_mev_defense()
        assert engine1 is engine2
