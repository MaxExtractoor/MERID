"""Comprehensive tests for trading/execution/defense.py - MEV Defense module.

Coverage targets: enums, dataclasses, OrderSlicer, TimingRandomizer,
HiddenLiquidityInference, FrontRunningDetector, SandwichDetector,
MEVHeatmap, MEVDefenseEngine, ManipulationDetector.
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from trading.execution.defense import (
    MEVType, ThreatLevel, DefenseAction,
    MEVEvent, MEVHeatmapEntry, DefenseRecommendation,
    OrderSlicer, TimingRandomizer, HiddenLiquidityInference,
    FrontRunningDetector, SandwichDetector, MEVHeatmap,
    MEVDefenseEngine, ManipulationDetector,
    get_mev_defense,
)


# =============================================================================
# Enum Tests
# =============================================================================

class TestMEVType:
    """Test MEVType enum."""

    def test_all_values(self):
        assert MEVType.FRONT_RUNNING.value == "front_running"
        assert MEVType.BACK_RUNNING.value == "back_running"
        assert MEVType.SANDWICH.value == "sandwich"
        assert MEVType.LIQUIDATION.value == "liquidation"
        assert MEVType.ARBITRAGE.value == "arbitrage"
        assert MEVType.JIT_LIQUIDITY.value == "jit_liquidity"

    def test_enum_count(self):
        assert len(MEVType) == 6


class TestThreatLevel:
    """Test ThreatLevel enum."""

    def test_all_values(self):
        assert ThreatLevel.NONE.value == "none"
        assert ThreatLevel.LOW.value == "low"
        assert ThreatLevel.MEDIUM.value == "medium"
        assert ThreatLevel.HIGH.value == "high"
        assert ThreatLevel.CRITICAL.value == "critical"

    def test_enum_count(self):
        assert len(ThreatLevel) == 5


class TestDefenseAction:
    """Test DefenseAction enum."""

    def test_all_values(self):
        assert DefenseAction.PROCEED.value == "proceed"
        assert DefenseAction.DELAY.value == "delay"
        assert DefenseAction.SLICE.value == "slice"
        assert DefenseAction.RANDOMIZE.value == "randomize"
        assert DefenseAction.ABORT.value == "abort"
        assert DefenseAction.USE_PRIVATE_MEMPOOL.value == "use_private_mempool"


# =============================================================================
# Dataclass Tests
# =============================================================================

class TestMEVEvent:
    """Test MEVEvent dataclass."""

    def test_creation(self):
        event = MEVEvent(
            event_id="ev_001",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.85,
            estimated_loss=150.0,
            symbol="ETH/USDT"
        )
        assert event.event_id == "ev_001"
        assert event.mev_type == MEVType.FRONT_RUNNING
        assert event.confidence == 0.85

    def test_to_dict(self):
        event = MEVEvent(
            event_id="ev_002",
            mev_type=MEVType.SANDWICH,
            detected_at=1234567890.0,
            confidence=0.75,
            estimated_loss=200.0,
            attacker_address="0x1234567890abcdef1234567890abcdef12345678",
            symbol="BTC/USDT"
        )
        d = event.to_dict()
        assert d["event_id"] == "ev_002"
        assert d["mev_type"] == "sandwich"
        assert d["attacker_address"].startswith("0x12345678")
        assert d["attacker_address"].endswith("...")

    def test_to_dict_no_attacker(self):
        event = MEVEvent(
            event_id="ev_003",
            mev_type=MEVType.ARBITRAGE,
            detected_at=time.time(),
            confidence=0.5,
            estimated_loss=50.0
        )
        d = event.to_dict()
        assert d["attacker_address"] is None


class TestMEVHeatmapEntry:
    """Test MEVHeatmapEntry dataclass."""

    def test_creation(self):
        entry = MEVHeatmapEntry(
            symbol="ETH/USDT",
            venue="uniswap",
            time_bucket=14,
            mev_intensity=0.65,
            attack_count_24h=12,
            avg_loss_per_attack=75.5,
            liquidity_depth=1000000.0,
            volatility=0.05
        )
        assert entry.symbol == "ETH/USDT"
        assert entry.time_bucket == 14
        assert entry.mev_intensity == 0.65

    def test_to_dict(self):
        entry = MEVHeatmapEntry(
            symbol="SOL/USDT",
            venue="jupiter",
            time_bucket=8,
            mev_intensity=0.333333,
            attack_count_24h=5,
            avg_loss_per_attack=25.123456,
            liquidity_depth=500000.0,
            volatility=0.08
        )
        d = entry.to_dict()
        assert d["mev_intensity"] == 0.3333
        assert d["avg_loss_per_attack"] == 25.1235


class TestDefenseRecommendation:
    """Test DefenseRecommendation dataclass."""

    def test_creation(self):
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="High MEV risk",
            suggested_delay_ms=2000,
            suggested_slice_count=5,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.HIGH,
            estimated_mev_risk=150.0
        )
        assert rec.action == DefenseAction.SLICE
        assert rec.suggested_slice_count == 5

    def test_to_dict(self):
        rec = DefenseRecommendation(
            action=DefenseAction.ABORT,
            reason="Critical risk",
            threat_level=ThreatLevel.CRITICAL,
            estimated_mev_risk=500.123456
        )
        d = rec.to_dict()
        assert d["action"] == "abort"
        assert d["threat_level"] == "critical"
        assert d["estimated_mev_risk"] == 500.123456


# =============================================================================
# OrderSlicer Tests
# =============================================================================

class TestOrderSlicer:
    """Test OrderSlicer class."""

    def test_init(self):
        slicer = OrderSlicer(min_slice_size=50.0, max_slices=10)
        assert slicer.min_slice_size == 50.0
        assert slicer.max_slices == 10

    def test_compute_optimal_slices_small_order(self):
        slicer = OrderSlicer(min_slice_size=100.0)
        slices = slicer.compute_optimal_slices(
            total_size=500.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.1
        )
        assert len(slices) >= 1
        assert sum(slices) == pytest.approx(500.0)

    def test_compute_optimal_slices_large_order(self):
        slicer = OrderSlicer(min_slice_size=100.0, max_slices=10)
        slices = slicer.compute_optimal_slices(
            total_size=50000.0,
            daily_volume=100000.0,
            volatility=0.02,
            mev_intensity=0.5
        )
        assert len(slices) <= 10
        assert sum(slices) == pytest.approx(50000.0)

    def test_compute_optimal_slices_high_mev(self):
        slicer = OrderSlicer()
        slices_low = slicer.compute_optimal_slices(1000, 100000, 0.02, 0.1)
        slices_high = slicer.compute_optimal_slices(1000, 100000, 0.02, 0.9)
        # Higher MEV should result in more slices
        assert len(slices_high) >= len(slices_low)

    def test_compute_iceberg_schedule(self):
        slicer = OrderSlicer()
        visible, hidden = slicer.compute_iceberg_schedule(10000.0, 0.1)
        assert visible == 1000.0
        assert hidden == 9000.0

    def test_compute_iceberg_schedule_default(self):
        slicer = OrderSlicer()
        visible, hidden = slicer.compute_iceberg_schedule(5000.0)
        assert visible == 500.0
        assert hidden == 4500.0


# =============================================================================
# TimingRandomizer Tests
# =============================================================================

class TestTimingRandomizer:
    """Test TimingRandomizer class."""

    def test_init(self):
        randomizer = TimingRandomizer()
        assert randomizer._rng is not None

    def test_randomize_delay(self):
        randomizer = TimingRandomizer()
        delays = [randomizer.randomize_delay(1000, 0.3) for _ in range(100)]
        # All delays should be within jitter range
        assert all(700 <= d <= 1300 for d in delays)

    def test_randomize_delay_zero(self):
        randomizer = TimingRandomizer()
        delay = randomizer.randomize_delay(0, 0.5)
        assert delay >= 0

    def test_compute_random_schedule_single(self):
        randomizer = TimingRandomizer()
        schedule = randomizer.compute_random_schedule(1, 5000)
        assert schedule == [0]

    def test_compute_random_schedule_multiple(self):
        randomizer = TimingRandomizer()
        schedule = randomizer.compute_random_schedule(5, 10000)
        assert len(schedule) == 5
        assert schedule[0] == 0
        assert all(0 <= d <= 10000 for d in schedule)

    def test_should_add_decoy_delay(self):
        randomizer = TimingRandomizer()
        results = [randomizer.should_add_decoy_delay() for _ in range(1000)]
        decoys = [r for r in results if r[0]]
        # Should be roughly 20% decoys
        assert 100 <= len(decoys) <= 300


# =============================================================================
# HiddenLiquidityInference Tests
# =============================================================================

class TestHiddenLiquidityInference:
    """Test HiddenLiquidityInference class."""

    def test_init(self):
        inference = HiddenLiquidityInference()
        assert inference._observations == {}

    def test_record_observation(self):
        inference = HiddenLiquidityInference()
        inference.record_observation("ETH/USDT", 100000.0, 150000.0, 5.0)
        assert "ETH/USDT" in inference._observations
        assert len(inference._observations["ETH/USDT"]) == 1

    def test_estimate_hidden_liquidity_no_data(self):
        inference = HiddenLiquidityInference()
        estimate = inference.estimate_hidden_liquidity("BTC/USDT", 50000.0)
        # Default 2x visible
        assert estimate == 100000.0

    def test_estimate_hidden_liquidity_with_data(self):
        inference = HiddenLiquidityInference()
        for i in range(15):
            inference.record_observation("ETH/USDT", 1000.0, 1500.0, 2.0)
        estimate = inference.estimate_hidden_liquidity("ETH/USDT", 1000.0)
        # Should be > 1000 based on ratio
        assert estimate >= 1000.0

    def test_estimate_price_impact_no_data(self):
        inference = HiddenLiquidityInference()
        impact = inference.estimate_price_impact("SOL/USDT", 1000.0, 10000.0)
        # Impact should be reasonable
        assert 0 <= impact <= 100

    def test_estimate_price_impact_zero_liquidity(self):
        inference = HiddenLiquidityInference()
        impact = inference.estimate_price_impact("UNKNOWN", 1000.0, 0.0)
        assert impact == 100.0


# =============================================================================
# FrontRunningDetector Tests
# =============================================================================

class TestFrontRunningDetector:
    """Test FrontRunningDetector class."""

    def test_init(self):
        detector = FrontRunningDetector(detection_window_ms=3000)
        assert detector.detection_window_ms == 3000
        assert detector._pending_orders == {}

    def test_register_pending_order(self):
        detector = FrontRunningDetector()
        detector.register_pending_order("order_001", "ETH/USDT", "buy", 10.0, 3000.0)
        assert "order_001" in detector._pending_orders

    def test_check_no_pending_order(self):
        detector = FrontRunningDetector()
        result = detector.check_for_front_running("nonexistent", 100.0, [])
        assert result is None

    def test_check_no_suspicious_trades(self):
        detector = FrontRunningDetector()
        detector.register_pending_order("order_001", "ETH/USDT", "buy", 10.0, 3000.0)
        result = detector.check_for_front_running("order_001", 3000.0, [])
        assert result is None

    def test_check_front_running_detected(self):
        detector = FrontRunningDetector()
        now = time.time()
        detector._pending_orders["order_001"] = {
            "symbol": "ETH/USDT",
            "side": "buy",
            "size": 10.0,
            "price": 3000.0,
            "submitted_at": now - 1,
        }
        
        suspicious_trades = [
            {"timestamp": now - 0.5, "price": 3050.0, "tx_hash": "0xabc"}
        ]
        
        result = detector.check_for_front_running("order_001", 3100.0, suspicious_trades)
        assert result is not None
        assert result.mev_type == MEVType.FRONT_RUNNING

    def test_get_recent_events(self):
        detector = FrontRunningDetector()
        events = detector.get_recent_events(10)
        assert events == []


# =============================================================================
# SandwichDetector Tests
# =============================================================================

class TestSandwichDetector:
    """Test SandwichDetector class."""

    def test_init(self):
        detector = SandwichDetector()
        assert detector._detected_events == []

    def test_detect_no_sandwich(self):
        detector = SandwichDetector()
        our_trade = {"timestamp": time.time(), "side": "buy", "price": 100, "size": 10}
        result = detector.detect_sandwich(our_trade, [])
        assert result is None

    def test_detect_sandwich_pattern(self):
        detector = SandwichDetector()
        now = time.time()
        our_trade = {
            "timestamp": now,
            "side": "buy",
            "price": 105.0,
            "size": 10.0,
            "tx_hash": "0xvictim",
            "symbol": "ETH/USDT"
        }
        surrounding = [
            {"timestamp": now - 0.5, "side": "buy", "price": 100.0, "size": 50.0, "address": "0xattacker"},
            {"timestamp": now + 0.5, "side": "sell", "price": 107.0, "size": 50.0, "address": "0xattacker"},
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding)
        assert result is not None
        assert result.mev_type == MEVType.SANDWICH
        assert result.confidence == 0.9

    def test_detect_sandwich_different_addresses(self):
        detector = SandwichDetector()
        now = time.time()
        our_trade = {
            "timestamp": now,
            "side": "buy",
            "price": 105.0,
            "size": 10.0
        }
        surrounding = [
            {"timestamp": now - 0.5, "side": "buy", "price": 100.0, "size": 50.0, "address": "0xaddr1"},
            {"timestamp": now + 0.5, "side": "sell", "price": 107.0, "size": 50.0, "address": "0xaddr2"},
        ]
        
        result = detector.detect_sandwich(our_trade, surrounding)
        # Different addresses but similar size should still detect
        assert result is not None
        assert result.confidence < 0.9

    def test_get_recent_events(self):
        detector = SandwichDetector()
        events = detector.get_recent_events()
        assert events == []


# =============================================================================
# MEVHeatmap Tests
# =============================================================================

class TestMEVHeatmap:
    """Test MEVHeatmap class."""

    def test_init(self):
        heatmap = MEVHeatmap()
        assert heatmap._entries == {}

    def test_record_attack(self):
        heatmap = MEVHeatmap()
        heatmap.record_attack("ETH/USDT", "uniswap", MEVType.SANDWICH, 100.0)
        assert len(heatmap._attack_history) == 1

    def test_get_intensity_no_data(self):
        heatmap = MEVHeatmap()
        intensity = heatmap.get_intensity("BTC/USDT", "binance")
        assert intensity == 0.0

    def test_get_intensity_with_data(self):
        heatmap = MEVHeatmap()
        for _ in range(5):
            heatmap.record_attack("ETH/USDT", "uniswap", MEVType.FRONT_RUNNING, 50.0)
        intensity = heatmap.get_intensity("ETH/USDT", "uniswap")
        assert intensity > 0

    def test_get_safest_time(self):
        heatmap = MEVHeatmap()
        safest = heatmap.get_safest_time("ETH/USDT", "uniswap")
        assert 0 <= safest < 24

    def test_get_heatmap(self):
        heatmap = MEVHeatmap()
        heatmap.record_attack("BTC/USDT", "coinbase", MEVType.ARBITRAGE, 25.0)
        data = heatmap.get_heatmap("BTC/USDT")
        assert data["symbol"] == "BTC/USDT"
        assert "entries" in data
        assert "safest_hour" in data


# =============================================================================
# MEVDefenseEngine Tests
# =============================================================================

class TestMEVDefenseEngine:
    """Test MEVDefenseEngine class."""

    def test_init(self):
        engine = MEVDefenseEngine()
        assert engine.slicer is not None
        assert engine.timing is not None
        assert engine.heatmap is not None

    def test_assess_mev_risk_low(self):
        engine = MEVDefenseEngine()
        level, risk = engine.assess_mev_risk("BTC/USDT", "binance", 100.0, 1000000.0)
        assert level == ThreatLevel.NONE
        assert risk >= 0

    def test_assess_mev_risk_high_participation(self):
        engine = MEVDefenseEngine()
        level, risk = engine.assess_mev_risk("MICRO", "dex", 50000.0, 10000.0)
        assert level in [ThreatLevel.MEDIUM, ThreatLevel.HIGH, ThreatLevel.CRITICAL]

    def test_get_defense_recommendation_proceed(self):
        engine = MEVDefenseEngine()
        rec = engine.get_defense_recommendation(
            "BTC/USDT", "binance", "buy", 100.0, 1000000.0, 0.02
        )
        assert rec.action == DefenseAction.PROCEED
        assert rec.threat_level == ThreatLevel.NONE

    def test_get_defense_recommendation_high_risk(self):
        engine = MEVDefenseEngine()
        # Inject high intensity
        for _ in range(15):
            engine.heatmap.record_attack("SCAM", "dex", MEVType.SANDWICH, 1000.0)
        
        rec = engine.get_defense_recommendation(
            "SCAM", "dex", "buy", 10000.0, 5000.0, 0.1
        )
        assert rec.action in [DefenseAction.SLICE, DefenseAction.ABORT, DefenseAction.RANDOMIZE]

    def test_apply_defense(self):
        engine = MEVDefenseEngine()
        rec = DefenseRecommendation(
            action=DefenseAction.SLICE,
            reason="Test",
            suggested_delay_ms=1000,
            suggested_slice_count=3,
            suggested_size_reduction=0.8,
            threat_level=ThreatLevel.MEDIUM,
            estimated_mev_risk=50.0
        )
        
        result = engine.apply_defense(10000.0, rec, 100000.0, 0.03)
        assert "slices" in result
        assert result["original_size"] == 10000.0
        assert result["adjusted_size"] == 8000.0

    def test_record_mev_event(self):
        engine = MEVDefenseEngine()
        event = MEVEvent(
            event_id="ev_test",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=0.8,
            estimated_loss=100.0,
            symbol="ETH/USDT"
        )
        engine.record_mev_event(event)
        assert engine._total_mev_suffered == 100.0

    def test_record_mev_avoided(self):
        engine = MEVDefenseEngine()
        engine.record_mev_avoided(50.0)
        assert engine._total_mev_avoided == 50.0

    def test_get_status(self):
        engine = MEVDefenseEngine()
        status = engine.get_status()
        assert "total_mev_suffered" in status
        assert "total_mev_avoided" in status
        assert "net_mev_impact" in status

    def test_get_mev_summary(self):
        engine = MEVDefenseEngine()
        summary = engine.get_mev_summary("ETH/USDT")
        assert "heatmap" in summary
        assert "safest_hour" in summary
        assert "current_intensity" in summary


# =============================================================================
# ManipulationDetector Tests
# =============================================================================

class TestManipulationDetector:
    """Test ManipulationDetector class."""

    def test_init(self):
        detector = ManipulationDetector()
        assert detector._price_history == {}
        assert detector._alerts == []

    def test_record_tick(self):
        detector = ManipulationDetector()
        detector.record_tick("ETH/USDT", 3000.0, 100.0)
        assert "ETH/USDT" in detector._price_history

    def test_detect_pump_and_dump_no_data(self):
        detector = ManipulationDetector()
        result = detector.detect_pump_and_dump("BTC/USDT")
        assert result is None

    def test_detect_pump_and_dump_insufficient_data(self):
        detector = ManipulationDetector()
        for i in range(30):
            detector.record_tick("ETH/USDT", 100.0 + i, 10.0)
        result = detector.detect_pump_and_dump("ETH/USDT")
        assert result is None  # Not enough data points

    def test_detect_wash_trading_no_data(self):
        detector = ManipulationDetector()
        result = detector.detect_wash_trading("BTC/USDT", [])
        assert result is None

    def test_detect_wash_trading_insufficient_trades(self):
        detector = ManipulationDetector()
        trades = [{"address": "0x123", "size": 100}]
        result = detector.detect_wash_trading("BTC/USDT", trades)
        assert result is None

    def test_detect_wash_trading_concentrated(self):
        detector = ManipulationDetector()
        trades = [
            {"address": "0xwhale", "size": 1000} for _ in range(15)
        ] + [
            {"address": f"0xother{i}", "size": 10} for i in range(10)
        ]
        result = detector.detect_wash_trading("SCAM/USDT", trades)
        assert result is not None
        assert result["type"] == "wash_trading"

    def test_get_alerts(self):
        detector = ManipulationDetector()
        alerts = detector.get_alerts()
        assert alerts == []


# =============================================================================
# Singleton Tests
# =============================================================================

class TestGetMevDefense:
    """Test get_mev_defense singleton."""

    def test_returns_instance(self):
        import trading.execution.defense as module
        module._mev_defense = None
        
        engine = get_mev_defense()
        assert isinstance(engine, MEVDefenseEngine)

    def test_returns_same_instance(self):
        engine1 = get_mev_defense()
        engine2 = get_mev_defense()
        assert engine1 is engine2
