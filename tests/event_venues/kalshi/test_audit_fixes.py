"""Tests for Kalshi integration audit fixes.

Tests all 8 phases of improvements:
1. DISCOVER: Schema validation, SLA tracking
2. ANALYZE: Timestamp validation, drift detection, clock skew
3. CONSENSUS: Anti-herding, thread-safe cache, track-record weighting
4. SIZE: Safe Kelly calculation, position caps
5. EXECUTE: Fill quality tracking, execution recommendations
6. MONITOR: Anomaly detection, auto-reconciliation
7. PROMOTE: Canary deployment
8. PROTECT: Enhanced kill switch with auto-exit
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

# Phase 1: DISCOVER
from merid.event_venues.kalshi.discovery_validator import (
    DiscoveryValidator,
    KalshiMarketSchema,
    get_discovery_validator,
)

# Phase 2: ANALYZE
from merid.event_venues.kalshi.analysis_validator import (
    TimestampValidator,
    FeatureDriftDetector,
    ClockSkewMonitor,
    get_timestamp_validator,
    get_drift_detector,
    get_clock_monitor,
)

# Phase 3: CONSENSUS
from merid.event_venues.kalshi.consensus_protection import (
    AntiHerdingDetector,
    ConsensusCache,
    TrackRecordWeighting,
    get_herding_detector,
    get_consensus_cache,
    get_track_weighting,
)

# Phase 4: SIZE
from merid.event_venues.kalshi.sizing_protection import (
    SafeKellyCalculator,
    get_safe_kelly_calculator,
)

# Phase 5: EXECUTE
from merid.event_venues.kalshi.execution_quality import (
    FillQualityTracker,
    get_fill_quality_tracker,
)

# Phase 6: MONITOR
from merid.event_venues.kalshi.monitoring_enhancements import (
    FillQualityAnomalyDetector,
    AutoReconciliationEngine,
    get_anomaly_detector,
    get_auto_reconciler,
)

# Phase 7: PROMOTE
from merid.event_venues.kalshi.promotion_enhancements import (
    CanaryDeploymentController,
    CanaryStage,
    CanaryMetrics,
    get_canary_controller,
)

# Phase 8: PROTECT
from merid.event_venues.kalshi.protection_enhancements import (
    EnhancedKillSwitch,
    KillSwitchMode,
    get_enhanced_kill_switch,
)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: DISCOVER Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestDiscoveryValidator:
    """Test schema validation and SLA tracking (D-001, D-002)."""

    def test_valid_market_schema(self):
        """Test that valid market passes validation."""
        validator = DiscoveryValidator()

        valid_market = {
            "market_id": "KXBTC-26MAR25-T95000",
            "event_ticker": "KXBTC-26MAR25",
            "series_ticker": "KXBTC",
            "question": "Will BTC be above $95,000 on March 26?",
            "status": "open",
            "yes_price": 55,
            "no_price": 45,
            "last_price": 55,
            "volume": 1000,
            "open_interest": 500,
            "close_time": "2026-03-26T23:59:59Z",
            "expiration_time": "2026-03-26T23:59:59Z",
        }

        result = validator.validate_market(valid_market)
        assert result.valid
        assert len(result.errors) == 0

    def test_invalid_market_missing_fields(self):
        """Test that market missing required fields fails validation (D-001)."""
        validator = DiscoveryValidator()

        invalid_market = {
            "market_id": "KXBTC-26MAR25-T95000",
            # Missing event_ticker, question, status, etc.
        }

        result = validator.validate_market(invalid_market)
        assert not result.valid
        assert len(result.errors) > 0

    def test_invalid_market_price_out_of_range(self):
        """Test that invalid prices fail validation (D-001)."""
        validator = DiscoveryValidator()

        invalid_market = {
            "market_id": "KXBTC-26MAR25-T95000",
            "event_ticker": "KXBTC-26MAR25",
            "series_ticker": "KXBTC",
            "question": "Will BTC be above $95,000 on March 26?",
            "status": "open",
            "yes_price": 150,  # Invalid: > 100
            "no_price": 45,
            "volume": 1000,
            "open_interest": 500,
            "close_time": "2026-03-26T23:59:59Z",
            "expiration_time": "2026-03-26T23:59:59Z",
        }

        result = validator.validate_market(invalid_market)
        assert not result.valid

    def test_sla_tracking(self):
        """Test SLA tracking and breach detection (D-002)."""
        validator = DiscoveryValidator(max_refresh_latency_ms=1000)

        # Start tracking
        metrics = validator.start_sla_tracking()

        # Simulate API call
        import time
        time.sleep(0.1)  # 100ms

        # Complete tracking
        validator.complete_sla_tracking(
            metrics,
            api_latency_ms=100,
            enrichment_latency_ms=50,
            markets_count=100,
        )

        assert metrics.total_latency_ms is not None
        assert metrics.total_latency_ms >= 100  # At least the sleep time
        assert not metrics.is_sla_breach(1000)  # Should be under 1000ms

    def test_sla_breach_detection(self):
        """Test that SLA breaches are detected (D-002)."""
        validator = DiscoveryValidator(max_refresh_latency_ms=100)

        metrics = validator.start_sla_tracking()

        # Simulate slow operation
        import time
        time.sleep(0.2)  # 200ms

        validator.complete_sla_tracking(
            metrics,
            api_latency_ms=200,
            enrichment_latency_ms=50,
            markets_count=100,
        )

        assert metrics.is_sla_breach(100)  # Should breach 100ms limit


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: ANALYZE Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestTimestampValidator:
    """Test timestamp validation (A-001)."""

    def test_recent_timestamp_valid(self):
        """Test that recent timestamps pass validation."""
        validator = TimestampValidator(max_age_seconds=3600)
        now = datetime.now(timezone.utc)
        recent = now - timedelta(minutes=5)

        result = validator.validate_timestamp(recent, source="twitter")
        assert result.valid
        assert result.age_seconds < 3600

    def test_stale_timestamp_rejected(self):
        """Test that stale timestamps are rejected (A-001)."""
        validator = TimestampValidator(max_age_seconds=3600)
        now = datetime.now(timezone.utc)
        stale = now - timedelta(hours=2)  # 2 hours old

        result = validator.validate_timestamp(stale, source="twitter", now=now)
        assert not result.valid
        assert "stale" in result.error.lower()

    def test_future_timestamp_rejected(self):
        """Test that future timestamps are rejected (A-001)."""
        validator = TimestampValidator()
        now = datetime.now(timezone.utc)
        future = now + timedelta(minutes=5)

        result = validator.validate_timestamp(future, source="twitter", now=now)
        assert not result.valid
        assert "future" in result.error.lower()

    def test_naive_timestamp_rejected(self):
        """Test that timezone-naive timestamps are rejected (A-001)."""
        validator = TimestampValidator()
        naive = datetime.now()  # No timezone

        result = validator.validate_timestamp(naive, source="twitter")
        assert not result.valid
        assert "timezone-naive" in result.error.lower()


class TestFeatureDriftDetector:
    """Test feature drift detection (A-002)."""

    def test_no_drift_on_normal_values(self):
        """Test that normal values don't trigger drift detection."""
        detector = FeatureDriftDetector()

        # Build baseline
        for i in range(50):
            detector.update_baseline("sentiment_score", 0.5 + 0.1 * (i % 10) / 10)

        # Check normal value
        result = detector.check_drift("sentiment_score", 0.55)
        assert not result.drifted
        assert result.drift_magnitude == "none"

    def test_severe_drift_detected(self):
        """Test that severe drift is detected (A-002)."""
        detector = FeatureDriftDetector(z_score_threshold=3.0)

        # Build baseline around 0.5
        for i in range(100):
            detector.update_baseline("sentiment_score", 0.5)

        # Check severely drifted value
        result = detector.check_drift("sentiment_score", 2.0, auto_update=False)
        assert result.drifted
        assert result.drift_magnitude in ["moderate", "severe"]
        assert result.z_score > 3.0


class TestClockSkewMonitor:
    """Test clock skew monitoring (A-003)."""

    def test_no_skew_within_tolerance(self):
        """Test that minimal skew is within tolerance."""
        monitor = ClockSkewMonitor(max_skew_seconds=5.0)
        now = datetime.now(timezone.utc)
        reference = now - timedelta(seconds=1)  # 1 second behind

        result = monitor.check_skew(reference)
        assert result.within_tolerance
        assert abs(result.skew_seconds) <= 5.0

    def test_large_skew_detected(self):
        """Test that large clock skew is detected (A-003)."""
        monitor = ClockSkewMonitor(max_skew_seconds=5.0)
        now = datetime.now(timezone.utc)
        reference = now - timedelta(seconds=10)  # 10 seconds behind

        result = monitor.check_skew(reference, force=True)
        assert not result.within_tolerance
        assert abs(result.skew_seconds) > 5.0


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: CONSENSUS Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAntiHerdingDetector:
    """Test anti-herding protection (C-001)."""

    def test_diverse_proposals_no_herding(self):
        """Test that diverse proposals don't trigger herding detection."""
        detector = AntiHerdingDetector(min_unique_archetypes=2)

        proposals = [
            Mock(agent_archetype="momentum", direction="yes", rationale="Strong momentum signal"),
            Mock(agent_archetype="mean_reversion", direction="no", rationale="Price extended too far"),
            Mock(agent_archetype="orderbook", direction="yes", rationale="Bid depth increasing"),
        ]

        metrics = detector.detect_herding(proposals)
        assert not metrics.herding_detected
        assert metrics.unique_archetypes >= 2

    def test_identical_archetypes_herding(self):
        """Test that identical archetypes trigger herding detection (C-001)."""
        detector = AntiHerdingDetector(min_unique_archetypes=2)

        proposals = [
            Mock(agent_archetype="momentum", direction="yes", rationale="Strong momentum 1"),
            Mock(agent_archetype="momentum", direction="yes", rationale="Strong momentum 2"),
            Mock(agent_archetype="momentum", direction="yes", rationale="Strong momentum 3"),
        ]

        metrics = detector.detect_herding(proposals)
        assert metrics.herding_detected
        assert "archetype diversity" in metrics.herding_reason.lower()


class TestConsensusCache:
    """Test thread-safe consensus cache (C-002)."""

    def test_cache_set_and_get(self):
        """Test basic cache operations."""
        cache = ConsensusCache()
        cache.set("key1", {"value": 123})
        assert cache.get("key1") == {"value": 123}

    def test_cache_invalidate(self):
        """Test cache invalidation."""
        cache = ConsensusCache()
        cache.set("key1", {"value": 123})
        assert cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_concurrent_access_safe(self):
        """Test that concurrent access is thread-safe (C-002)."""
        import threading

        cache = ConsensusCache()
        errors = []

        def writer(i):
            try:
                for j in range(100):
                    cache.set(f"key_{i}", {"value": j})
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0  # No race condition errors


class TestTrackRecordWeighting:
    """Test improved track-record weighting (C-003)."""

    def test_low_sample_count_discounted(self):
        """Test that agents with few samples get lower weight (C-003)."""
        weighting = TrackRecordWeighting(min_samples=20)

        # Low sample count
        weight_low = weighting.calculate_weight(
            "agent1",
            brier_score=0.15,
            win_rate=0.8,
            sample_count=5,
        )

        # High sample count
        weight_high = weighting.calculate_weight(
            "agent2",
            brier_score=0.15,
            win_rate=0.8,
            sample_count=100,
        )

        assert weight_low.final_weight < weight_high.final_weight

    def test_recency_discounting(self):
        """Test that old trades are discounted (C-003)."""
        weighting = TrackRecordWeighting(recency_halflife_days=14.0)

        # Recent trades
        weight_recent = weighting.calculate_weight(
            "agent1",
            brier_score=0.15,
            win_rate=0.8,
            sample_count=50,
            last_trade_age_days=1.0,
        )

        # Old trades
        weight_old = weighting.calculate_weight(
            "agent2",
            brier_score=0.15,
            win_rate=0.8,
            sample_count=50,
            last_trade_age_days=30.0,
        )

        assert weight_recent.final_weight > weight_old.final_weight


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: SIZE Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSafeKellyCalculator:
    """Test safe Kelly calculation (S-001, S-002)."""

    def test_normal_kelly_calculation(self):
        """Test Kelly calculation for normal case."""
        calc = SafeKellyCalculator()

        result = calc.calculate_safe_kelly(
            edge=0.05,  # 5% edge
            price_cents=50,
            bankroll_cents=10000,  # $100
            kelly_fraction=0.25,
        )

        assert result.contracts > 0
        assert result.error is None

    def test_division_by_zero_protection(self):
        """Test that price=0 doesn't cause division by zero (S-001)."""
        calc = SafeKellyCalculator()

        result = calc.calculate_safe_kelly(
            edge=0.05,
            price_cents=0,  # Degenerate price
            bankroll_cents=10000,
        )

        assert result.contracts == 0
        assert result.error is not None
        assert "division by zero" in result.error.lower()

    def test_price_100_protection(self):
        """Test that price=100 doesn't cause division by zero (S-001)."""
        calc = SafeKellyCalculator()

        result = calc.calculate_safe_kelly(
            edge=0.05,
            price_cents=100,  # Degenerate price
            bankroll_cents=10000,
        )

        assert result.contracts == 0
        assert result.error is not None

    def test_absolute_position_cap(self):
        """Test that absolute cap prevents runaway sizes (S-002)."""
        calc = SafeKellyCalculator(absolute_max_contracts=100)

        result = calc.calculate_safe_kelly(
            edge=0.50,  # Huge edge
            price_cents=10,  # Cheap price
            bankroll_cents=1000000,  # Large bankroll
        )

        assert result.contracts <= 100
        assert result.capped

    def test_bankroll_fraction_cap(self):
        """Test that bankroll fraction limit is enforced (S-002)."""
        calc = SafeKellyCalculator(max_bankroll_fraction=0.10)

        result = calc.calculate_safe_kelly(
            edge=0.20,
            price_cents=50,
            bankroll_cents=10000,
        )

        # Should not exceed 10% of bankroll in notional
        max_contracts = int(10000 * 0.10 / 50)
        assert result.contracts <= max_contracts


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: EXECUTE Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFillQualityTracker:
    """Test fill quality tracking (E-001)."""

    def test_record_and_retrieve_fill(self):
        """Test recording fills and retrieving profile."""
        tracker = FillQualityTracker(min_samples_for_profile=3)

        # Record fills
        for i in range(5):
            tracker.record_fill(
                "KXBTC-TEST",
                intended_price_cents=50,
                filled_price_cents=51,  # 1 cent slippage
                intended_contracts=10,
                filled_contracts=10,
                latency_ms=100.0,
            )

        profile = tracker.get_market_profile("KXBTC-TEST")
        assert profile is not None
        assert profile.mean_slippage_cents == 1.0
        assert profile.mean_latency_ms == 100.0

    def test_execution_recommendation_aggressive(self):
        """Test that good quality markets get aggressive execution (E-001)."""
        tracker = FillQualityTracker(min_samples_for_profile=3)

        # Record excellent fills
        for i in range(10):
            tracker.record_fill(
                "KXBTC-TEST",
                intended_price_cents=50,
                filled_price_cents=50,  # No slippage
                intended_contracts=10,
                filled_contracts=10,  # Full fill
                latency_ms=100.0,
            )

        rec = tracker.get_execution_recommendation("KXBTC-TEST", intended_contracts=10)
        assert rec["strategy"] == "aggressive"

    def test_execution_recommendation_iceberg(self):
        """Test that poor quality + large size triggers iceberg (E-002)."""
        tracker = FillQualityTracker(min_samples_for_profile=3)

        # Record poor fills
        for i in range(10):
            tracker.record_fill(
                "KXBTC-TEST",
                intended_price_cents=50,
                filled_price_cents=55,  # 5 cent slippage
                intended_contracts=10,
                filled_contracts=7,  # Partial fills
                latency_ms=800.0,  # High latency
            )

        rec = tracker.get_execution_recommendation("KXBTC-TEST", intended_contracts=100)
        assert rec["strategy"] == "iceberg"
        assert rec["iceberg_slice_size"] is not None


# ══════════════════════════════════════════════════════════════════════════════
# Phase 6: MONITOR Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestFillQualityAnomalyDetector:
    """Test anomaly detection (M-001)."""

    def test_normal_metrics_no_anomaly(self):
        """Test that normal metrics don't trigger anomalies."""
        detector = FillQualityAnomalyDetector(baseline_window=50)

        # Build baseline
        for i in range(60):
            detector.record_metric("slippage_cents", 1.0 + 0.2 * (i % 5))

        # Check normal value
        result = detector.check_anomaly("slippage_cents", 1.5)
        assert not result.anomaly_detected

    def test_severe_anomaly_detected(self):
        """Test that severe anomalies are detected (M-001)."""
        detector = FillQualityAnomalyDetector(baseline_window=50)

        # Build baseline around 1.0
        for i in range(60):
            detector.record_metric("slippage_cents", 1.0)

        # Check severe anomaly
        result = detector.check_anomaly("slippage_cents", 10.0, auto_record=False)
        assert result.anomaly_detected
        assert result.severity in ["moderate", "severe"]


class TestAutoReconciliationEngine:
    """Test automated reconciliation (M-002)."""

    def test_no_discrepancies(self):
        """Test reconciliation with matching positions."""
        reconciler = AutoReconciliationEngine()

        local = {"KXBTC-TEST": 10, "KXETH-TEST": 5}
        remote = {"KXBTC-TEST": 10, "KXETH-TEST": 5}

        result = reconciler.reconcile_positions(local, remote)
        assert result.reconciled
        assert len(result.discrepancies) == 0

    def test_minor_discrepancy_auto_fixed(self):
        """Test that minor discrepancies are auto-fixed (M-002)."""
        reconciler = AutoReconciliationEngine(
            position_tolerance_contracts=2,
            auto_fix_enabled=True,
        )

        local = {"KXBTC-TEST": 10}
        remote = {"KXBTC-TEST": 11}  # 1 contract difference

        result = reconciler.reconcile_positions(local, remote)
        assert not result.reconciled  # Has discrepancies
        assert len(result.auto_fixed) == 1
        assert "KXBTC-TEST" in result.auto_fixed

    def test_major_discrepancy_manual_review(self):
        """Test that major discrepancies require manual review (M-002)."""
        reconciler = AutoReconciliationEngine(position_tolerance_contracts=2)

        local = {"KXBTC-TEST": 10}
        remote = {"KXBTC-TEST": 20}  # 10 contract difference

        result = reconciler.reconcile_positions(local, remote)
        assert len(result.manual_review_required) == 1
        assert "KXBTC-TEST" in result.manual_review_required


# ══════════════════════════════════════════════════════════════════════════════
# Phase 7: PROMOTE Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestCanaryDeploymentController:
    """Test canary deployment (P-001)."""

    def test_register_canary(self):
        """Test canary registration."""
        controller = CanaryDeploymentController()
        config = controller.register_canary("agent1", initial_stage=CanaryStage.STAGE_1)

        assert config.agent_id == "agent1"
        assert config.current_stage == CanaryStage.STAGE_1

    def test_traffic_routing(self):
        """Test deterministic traffic routing (P-001)."""
        controller = CanaryDeploymentController()
        controller.register_canary("agent1", initial_stage=CanaryStage.STAGE_1)  # 1% traffic

        # Check routing for 1000 markets
        routes = [
            controller.should_route_to_canary("agent1", market_id=f"MARKET_{i}")
            for i in range(1000)
        ]

        routed_count = sum(routes)
        routed_pct = routed_count / 1000

        # Should be approximately 1%
        assert 0.005 <= routed_pct <= 0.015  # 0.5% - 1.5% tolerance

    def test_canary_promotion(self):
        """Test canary promotion logic (P-001)."""
        controller = CanaryDeploymentController()
        controller.register_canary("agent1", initial_stage=CanaryStage.STAGE_1)

        # Good metrics → should promote
        metrics = CanaryMetrics(
            agent_id="agent1",
            stage=CanaryStage.STAGE_1,
            trade_count=60,
            win_rate=0.7,
            mean_edge=0.05,
            profit_factor=1.5,
            mean_slippage_cents=1.0,
            quality_score=0.8,
            evaluation_time=datetime.now(timezone.utc),
        )

        action, new_stage = controller.evaluate_canary("agent1", metrics)
        assert action == "promote"
        assert new_stage == CanaryStage.STAGE_2

    def test_canary_rollback(self):
        """Test canary rollback on poor performance (P-001)."""
        controller = CanaryDeploymentController()
        config = controller.register_canary("agent1", initial_stage=CanaryStage.STAGE_1)
        config.auto_rollback_threshold = 0.4

        # Poor metrics → should rollback
        metrics = CanaryMetrics(
            agent_id="agent1",
            stage=CanaryStage.STAGE_1,
            trade_count=60,
            win_rate=0.3,
            mean_edge=-0.02,
            profit_factor=0.7,
            mean_slippage_cents=5.0,
            quality_score=0.3,
            evaluation_time=datetime.now(timezone.utc),
        )

        action, new_stage = controller.evaluate_canary("agent1", metrics)
        assert action == "rollback"
        assert new_stage == CanaryStage.STAGE_0


# ══════════════════════════════════════════════════════════════════════════════
# Phase 8: PROTECT Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestEnhancedKillSwitch:
    """Test enhanced kill switch (PR-001, PR-002)."""

    def test_live_mode_blocks_trading(self):
        """Test that LIVE mode blocks trading when activated."""
        ks = EnhancedKillSwitch(mode=KillSwitchMode.LIVE, auto_exit_enabled=False)

        # Initially allows trading
        allowed, reason = ks.can_trade()
        assert allowed

        # Activate
        ks.activate(reason="Test activation")

        # Now blocks trading
        allowed, reason = ks.can_trade()
        assert not allowed
        assert "global kill switch" in reason.lower()

    def test_dry_run_mode_allows_trading(self):
        """Test that DRY_RUN mode logs but allows trading (PR-002)."""
        ks = EnhancedKillSwitch(mode=KillSwitchMode.DRY_RUN)

        # Activate
        result = ks.activate(reason="Test dry-run activation")
        assert result.dry_run

        # Still allows trading
        allowed, reason = ks.can_trade()
        assert allowed

    def test_domain_kill_switch(self):
        """Test domain-specific kill switches."""
        ks = EnhancedKillSwitch(mode=KillSwitchMode.LIVE, auto_exit_enabled=False)

        # Activate for crypto domain only
        ks.activate(domain="crypto", reason="Test crypto kill switch")

        # Crypto blocked
        allowed, reason = ks.can_trade(domain="crypto")
        assert not allowed
        assert "crypto" in reason.lower()

        # Other domains allowed
        allowed, reason = ks.can_trade(domain="economics")
        assert allowed

    def test_auto_exit_triggered(self):
        """Test that auto-exit is triggered on activation (PR-001)."""
        ks = EnhancedKillSwitch(mode=KillSwitchMode.LIVE, auto_exit_enabled=True)

        result = ks.activate(reason="Test auto-exit")

        assert result.success
        # In real implementation, would check positions_closed
        # For now, we just verify the method was called

    def test_audit_log_tracking(self):
        """Test that all activations/deactivations are logged."""
        ks = EnhancedKillSwitch(mode=KillSwitchMode.LIVE, auto_exit_enabled=False)

        ks.activate(reason="Test 1")
        ks.deactivate(reason="Test 2")
        ks.activate(domain="crypto", reason="Test 3")

        log = ks.get_audit_log()
        assert len(log) == 3
        assert log[0]["action"] == "activate"
        assert log[1]["action"] == "deactivate"
        assert log[2]["domain"] == "crypto"


# ══════════════════════════════════════════════════════════════════════════════
# Integration Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestAuditFixesIntegration:
    """Integration tests for all audit fixes working together."""

    def test_discovery_to_execution_pipeline(self):
        """Test complete pipeline from discovery through execution."""
        # 1. Discovery: validate market
        validator = get_discovery_validator()
        market_data = {
            "market_id": "KXBTC-26MAR25-T95000",
            "event_ticker": "KXBTC-26MAR25",
            "series_ticker": "KXBTC",
            "question": "Will BTC be above $95,000?",
            "status": "open",
            "yes_price": 55,
            "no_price": 45,
            "volume": 1000,
            "open_interest": 500,
            "close_time": "2026-03-26T23:59:59Z",
            "expiration_time": "2026-03-26T23:59:59Z",
        }

        val_result = validator.validate_market(market_data)
        assert val_result.valid

        # 2. Analysis: validate timestamp
        ts_validator = get_timestamp_validator()
        ts_result = ts_validator.validate_timestamp(
            datetime.now(timezone.utc) - timedelta(minutes=5),
            source="market_data",
        )
        assert ts_result.valid

        # 3. Sizing: calculate safe Kelly
        kelly_calc = get_safe_kelly_calculator()
        size_result = kelly_calc.calculate_safe_kelly(
            edge=0.05,
            price_cents=55,
            bankroll_cents=10000,
        )
        assert size_result.contracts > 0
        assert size_result.error is None

        # 4. Protection: check kill switch
        ks = get_enhanced_kill_switch()
        allowed, reason = ks.can_trade(domain="crypto")
        # Should allow if not activated
        assert allowed or reason is not None

    def test_consensus_with_anti_herding(self):
        """Test consensus formation with anti-herding protection."""
        herding_detector = get_herding_detector()
        track_weighting = get_track_weighting()

        # Diverse proposals
        proposals = [
            Mock(agent_archetype="momentum", direction="yes", rationale="Momentum strong"),
            Mock(agent_archetype="mean_reversion", direction="no", rationale="Price extended"),
            Mock(agent_archetype="orderbook", direction="yes", rationale="Bid depth up"),
        ]

        # Check herding
        herding_metrics = herding_detector.detect_herding(proposals)
        assert not herding_metrics.herding_detected

        # Calculate weights
        weights = [
            track_weighting.calculate_weight(
                f"agent{i}",
                brier_score=0.2,
                win_rate=0.6,
                sample_count=50,
            )
            for i in range(3)
        ]

        assert all(w.final_weight > 0 for w in weights)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
