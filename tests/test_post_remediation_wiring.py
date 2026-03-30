"""
Tests for the post-remediation wiring audit components:
  - config/crypto_universe.py
  - agents/governance_event_bus.py
  - agents/alert_manager.py
  - agents/quorum_failure_tracker.py
  - agents/unified_decision_layer.py (QUORUM_FAILED routing)
"""
from __future__ import annotations

import time
from typing import Any, List
from unittest.mock import MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# §1  config/crypto_universe.py
# ══════════════════════════════════════════════════════════════════════════════

class TestCryptoUniverse:

    def setup_method(self):
        from config.crypto_universe import (
            CRYPTO_ASSETS,
            CRYPTO_ASSETS_ORDERED,
            CRYPTO_TIMEFRAMES,
            CRYPTO_TIMEFRAMES_ORDERED,
        )
        self.ASSETS = CRYPTO_ASSETS
        self.ASSETS_ORD = CRYPTO_ASSETS_ORDERED
        self.TIMEFRAMES = CRYPTO_TIMEFRAMES
        self.TIMEFRAMES_ORD = CRYPTO_TIMEFRAMES_ORDERED

    # ── Asset coverage ────────────────────────────────────────────────────────

    def test_all_five_assets_present(self):
        for asset in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            assert asset in self.ASSETS, f"{asset!r} missing from CRYPTO_ASSETS"

    def test_ordered_list_matches_frozenset(self):
        assert set(self.ASSETS_ORD) == set(self.ASSETS)

    # ── Timeframe coverage ────────────────────────────────────────────────────

    def test_all_five_timeframes_present(self):
        for tf in ("15m", "1h", "daily", "weekly", "monthly"):
            assert tf in self.TIMEFRAMES, f"{tf!r} missing from CRYPTO_TIMEFRAMES"

    def test_ordered_timeframes_match_frozenset(self):
        assert set(self.TIMEFRAMES_ORD) == set(self.TIMEFRAMES)

    # ── Full grid ─────────────────────────────────────────────────────────────

    def test_full_grid_has_25_pairs(self):
        from config.crypto_universe import get_full_grid
        grid = get_full_grid()
        assert len(grid) == 25

    def test_full_grid_contains_every_combination(self):
        from config.crypto_universe import get_full_grid, CRYPTO_ASSETS, CRYPTO_TIMEFRAMES
        grid = get_full_grid()
        grid_set = set(grid)
        for asset in CRYPTO_ASSETS:
            for tf in CRYPTO_TIMEFRAMES:
                assert (asset, tf) in grid_set, f"({asset}, {tf}) missing from grid"

    # ── Validation helpers ────────────────────────────────────────────────────

    def test_is_valid_pair_true(self):
        from config.crypto_universe import is_valid_pair
        assert is_valid_pair("BTC", "15m")
        assert is_valid_pair("DOGE", "monthly")

    def test_is_valid_pair_false_unknown_asset(self):
        from config.crypto_universe import is_valid_pair
        assert not is_valid_pair("SHIB", "daily")

    def test_is_valid_pair_false_unknown_timeframe(self):
        from config.crypto_universe import is_valid_pair
        assert not is_valid_pair("BTC", "4h")

    def test_assert_valid_pair_raises_on_bad_input(self):
        from config.crypto_universe import assert_valid_pair
        with pytest.raises(ValueError):
            assert_valid_pair("BTC", "4h")

    # ── Legacy normalisation ──────────────────────────────────────────────────

    def test_normalise_legacy_btc_15m(self):
        from config.crypto_universe import normalise_legacy_symbol
        assert normalise_legacy_symbol("BTC_15M") == ("BTC", "15m")

    def test_normalise_legacy_doge_daily(self):
        from config.crypto_universe import normalise_legacy_symbol
        assert normalise_legacy_symbol("DOGE_DAILY") == ("DOGE", "daily")

    def test_normalise_legacy_scalp(self):
        from config.crypto_universe import normalise_legacy_symbol
        assert normalise_legacy_symbol("ETH_SCALP") == ("ETH", "15m")

    def test_normalise_legacy_case_insensitive(self):
        from config.crypto_universe import normalise_legacy_symbol
        assert normalise_legacy_symbol("btc_15m") == ("BTC", "15m")

    def test_normalise_legacy_unknown_raises(self):
        from config.crypto_universe import normalise_legacy_symbol
        with pytest.raises(KeyError):
            normalise_legacy_symbol("UNKNOWN_SYMBOL")

    # ── get_assets/timeframes ─────────────────────────────────────────────────

    def test_get_timeframes_for_asset_returns_all(self):
        from config.crypto_universe import get_timeframes_for_asset, CRYPTO_TIMEFRAMES
        tfs = get_timeframes_for_asset("BTC")
        assert set(tfs) == set(CRYPTO_TIMEFRAMES)

    def test_get_assets_for_timeframe_returns_all(self):
        from config.crypto_universe import get_assets_for_timeframe, CRYPTO_ASSETS
        assets = get_assets_for_timeframe("daily")
        assert set(assets) == set(CRYPTO_ASSETS)

    def test_get_timeframes_for_unknown_asset_raises(self):
        from config.crypto_universe import get_timeframes_for_asset
        with pytest.raises(ValueError):
            get_timeframes_for_asset("FAKE")

    def test_get_assets_for_unknown_timeframe_raises(self):
        from config.crypto_universe import get_assets_for_timeframe
        with pytest.raises(ValueError):
            get_assets_for_timeframe("4h")


# ══════════════════════════════════════════════════════════════════════════════
# §2  agents/governance_event_bus.py
# ══════════════════════════════════════════════════════════════════════════════

class TestGovernanceEventBus:

    def _make_bus(self):
        from agents.governance_event_bus import GovernanceEventBus
        return GovernanceEventBus()

    def _make_event(self, event_type=None, asset="BTC", timeframe="15m"):
        from agents.governance_event_bus import GovernanceEvent, GovernanceEventType
        return GovernanceEvent(
            event_type=event_type or GovernanceEventType.QUORUM_FAILED,
            asset=asset,
            timeframe=timeframe,
            source="test",
            payload={"reason": "unit test"},
        )

    # ── Basic pub/sub ─────────────────────────────────────────────────────────

    def test_subscribe_and_receive(self):
        from agents.governance_event_bus import GovernanceEventType
        bus = self._make_bus()
        received: List[Any] = []
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, received.append)
        bus.publish(self._make_event())
        assert len(received) == 1

    def test_no_subscriber_logs_warning(self):
        import logging
        from agents.governance_event_bus import GovernanceEventType
        bus = self._make_bus()
        bus_logger = logging.getLogger("agents.governance_event_bus")
        with patch.object(bus_logger, "warning") as mock_warn:
            bus.publish(self._make_event(GovernanceEventType.KILL_SWITCH_ACTIVATED))
        assert mock_warn.called
        msg = " ".join(str(a) for a in mock_warn.call_args_list[0][0])
        assert "no subscribers" in msg.lower()

    def test_unsubscribe_removes_handler(self):
        from agents.governance_event_bus import GovernanceEventType
        bus = self._make_bus()
        received: List[Any] = []
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, received.append)
        bus.unsubscribe(GovernanceEventType.QUORUM_FAILED, received.append)
        bus.publish(self._make_event())
        assert received == []

    # ── DLQ behaviour ─────────────────────────────────────────────────────────

    def test_failed_handler_moves_to_dlq_after_retries(self):
        from agents.governance_event_bus import GovernanceEventBus, GovernanceEventType

        bus = GovernanceEventBus()
        # Override retry knobs to speed up the test.
        bus.MAX_RETRIES = 1
        bus.INITIAL_RETRY_DELAY_S = 0.0

        def bad_handler(_evt):
            raise RuntimeError("boom")

        bus.subscribe(GovernanceEventType.QUORUM_FAILED, bad_handler)
        bus.publish(self._make_event())

        assert bus.get_dlq_depth() == 1

    def test_dlq_entries_accessible(self):
        from agents.governance_event_bus import GovernanceEventBus, GovernanceEventType

        bus = GovernanceEventBus()
        bus.MAX_RETRIES = 0
        bus.INITIAL_RETRY_DELAY_S = 0.0

        bus.subscribe(GovernanceEventType.QUORUM_FAILED, lambda _: (_ for _ in ()).throw(ValueError("oops")))
        bus.publish(self._make_event())

        entries = bus.get_dlq_entries()
        assert len(entries) == 1
        assert "oops" in entries[0].last_error

    def test_replay_dlq_redelivers_and_clears(self):
        from agents.governance_event_bus import GovernanceEventBus, GovernanceEventType

        bus = GovernanceEventBus()
        bus.MAX_RETRIES = 0
        bus.INITIAL_RETRY_DELAY_S = 0.0

        calls: List[Any] = []

        def first_fail_then_ok(evt):
            if evt._attempt == 0 and not calls:
                raise RuntimeError("fail on first real call")
            calls.append(evt)

        # First subscription: always fail → goes to DLQ
        def always_fail(_evt):
            raise RuntimeError("always fail")

        bus.subscribe(GovernanceEventType.QUORUM_FAILED, always_fail)
        bus.publish(self._make_event())
        assert bus.get_dlq_depth() == 1

        # Replace subscriber with a working one before replay.
        bus.unsubscribe(GovernanceEventType.QUORUM_FAILED, always_fail)
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, calls.append)
        replayed = bus.replay_dlq()
        assert replayed == 1
        assert bus.get_dlq_depth() == 0
        assert len(calls) == 1

    def test_clear_dlq_discards_entries(self):
        from agents.governance_event_bus import GovernanceEventBus, GovernanceEventType

        bus = GovernanceEventBus()
        bus.MAX_RETRIES = 0
        bus.INITIAL_RETRY_DELAY_S = 0.0

        bus.subscribe(GovernanceEventType.QUORUM_FAILED, lambda _: (_ for _ in ()).throw(RuntimeError("x")))
        bus.publish(self._make_event())
        assert bus.get_dlq_depth() == 1

        cleared = bus.clear_dlq()
        assert cleared == 1
        assert bus.get_dlq_depth() == 0

    # ── Event validation ──────────────────────────────────────────────────────

    def test_invalid_asset_logs_warning(self):
        import logging
        from agents.governance_event_bus import GovernanceEventType
        bus = self._make_bus()
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, lambda _: None)
        bus_logger = logging.getLogger("agents.governance_event_bus")
        with patch.object(bus_logger, "warning") as mock_warn:
            bus.publish(self._make_event(asset="SHIB", timeframe="daily"))
        assert mock_warn.called
        msg = " ".join(str(a) for a in mock_warn.call_args_list[0][0])
        assert "unknown" in msg.lower() or "invalid" in msg.lower()

    # ── Metrics ───────────────────────────────────────────────────────────────

    def test_get_metrics_tracks_event_counts(self):
        from agents.governance_event_bus import GovernanceEventType
        bus = self._make_bus()
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, lambda _: None)
        bus.publish(self._make_event())
        bus.publish(self._make_event())
        m = bus.get_metrics()
        assert m["event_counts"].get("quorum.failed", 0) == 2

    def test_get_metrics_tracks_dlq_counts(self):
        from agents.governance_event_bus import GovernanceEventBus, GovernanceEventType

        bus = GovernanceEventBus()
        bus.MAX_RETRIES = 0
        bus.INITIAL_RETRY_DELAY_S = 0.0

        bus.subscribe(GovernanceEventType.QUORUM_FAILED, lambda _: (_ for _ in ()).throw(RuntimeError("z")))
        bus.publish(self._make_event())
        m = bus.get_metrics()
        assert m["dlq_counts"].get("quorum.failed", 0) == 1

    # ── Singleton ─────────────────────────────────────────────────────────────

    def test_singleton_returns_same_instance(self):
        from agents.governance_event_bus import get_governance_event_bus
        import agents.governance_event_bus as geb_module
        # Reset singleton for isolation.
        geb_module._governance_event_bus = None
        bus1 = get_governance_event_bus()
        bus2 = get_governance_event_bus()
        assert bus1 is bus2


# ══════════════════════════════════════════════════════════════════════════════
# §3  agents/alert_manager.py
# ══════════════════════════════════════════════════════════════════════════════

class TestAlertManager:

    def _make_manager(self, **kwargs):
        from agents.alert_manager import AlertManager
        return AlertManager(**kwargs)

    # ── Firing alerts ─────────────────────────────────────────────────────────

    def test_fire_delivers_to_sink(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        captured: List[Any] = []
        mgr.add_sink(captured.append)
        mgr.fire(AlertSeverity.CRITICAL, "test", "msg", "src")
        assert len(captured) == 1

    def test_fire_first_occurrence_not_suppressed(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        captured: List[Any] = []
        mgr.add_sink(captured.append)
        mgr.fire(AlertSeverity.WARNING, "quorum_fail", "BTC down", "watchdog", asset="BTC", timeframe="15m")
        assert len(captured) == 1

    def test_fire_duplicate_within_window_suppressed(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        captured: List[Any] = []
        mgr.add_sink(captured.append)
        for _ in range(5):
            mgr.fire(AlertSeverity.WARNING, "same_alert", "msg", "src", asset="BTC", timeframe="15m")
        # Only the first one should fire; the rest are suppressed as duplicates.
        assert len(captured) == 1

    # ── Escalation ────────────────────────────────────────────────────────────

    def test_escalation_fires_on_repeated_critical_alerts(self):
        from agents.alert_manager import AlertManager, AlertSeverity, EscalationPolicy
        policy = EscalationPolicy(
            critical_repeat_threshold=3,
            escalation_window_s=60.0,
            max_suppression_s=3600.0,   # long — don't re-surface during this test
        )
        mgr = AlertManager(policy=policy)
        captured: List[Any] = []
        mgr.add_sink(captured.append)

        # Fire enough CRITICAL alerts on the same key to cross the threshold.
        # Fire 1: opens incident (not suppressed).
        # Fires 2-3: suppressed but count accumulates.
        # Fire 4 (= threshold+1): escalation check crosses threshold → escalate & emit.
        for _ in range(4):
            mgr.fire(AlertSeverity.CRITICAL, "crisis", "BTC failed", "src",
                     asset="BTC", timeframe="daily")

        escalated = any(
            inc.state.value == "escalated"
            for inc in mgr._incidents.values()
        )
        assert escalated, "Expected at least one incident to be escalated"

    # ── Incident report ───────────────────────────────────────────────────────

    def test_get_incident_report_structure(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        captured: List[Any] = []
        mgr.add_sink(captured.append)
        mgr.fire(AlertSeverity.HIGH, "quorum", "msg", "src", asset="ETH", timeframe="1h")
        report = mgr.get_incident_report()
        assert "generated_at" in report
        assert "open_incident_count" in report
        assert "by_asset" in report
        assert "by_timeframe" in report
        assert "coverage_gaps" in report

    def test_get_incident_report_by_asset(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        mgr.add_sink(lambda _: None)
        mgr.fire(AlertSeverity.HIGH, "q", "m", "s", asset="SOL", timeframe="daily")
        report = mgr.get_incident_report()
        assert "SOL" in report["by_asset"]

    def test_get_incident_report_coverage_gaps(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        report = mgr.get_incident_report()
        # With no incidents, all 25 pairs are gaps.
        assert len(report["coverage_gaps"]) == 25

    # ── Incident resolution ───────────────────────────────────────────────────

    def test_resolve_incident(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        mgr.add_sink(lambda _: None)
        mgr.fire(AlertSeverity.CRITICAL, "x", "y", "z", asset="XRP", timeframe="weekly")
        incident_ids = list(mgr._incidents.keys())
        assert incident_ids
        result = mgr.resolve_incident(incident_ids[0])
        assert result is True
        report = mgr.get_incident_report()
        assert report["open_incident_count"] == 0

    def test_resolve_nonexistent_incident_returns_false(self):
        mgr = self._make_manager()
        assert mgr.resolve_incident("bad-id") is False

    # ── Meta-errors ───────────────────────────────────────────────────────────

    def test_sink_failure_recorded_as_meta_error(self):
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()

        def bad_sink(_alert):
            raise RuntimeError("sink down")

        mgr.add_sink(bad_sink)
        mgr.fire(AlertSeverity.INFO, "t", "m", "s")
        errors = mgr.get_meta_errors()
        assert len(errors) == 1
        assert "sink down" in errors[0]["error"]

    # ── Universe validation ───────────────────────────────────────────────────

    def test_unknown_asset_logs_warning(self):
        import logging
        from agents.alert_manager import AlertSeverity
        mgr = self._make_manager()
        mgr.add_sink(lambda _: None)
        am_logger = logging.getLogger("agents.alert_manager")
        with patch.object(am_logger, "warning") as mock_warn:
            mgr.fire(AlertSeverity.INFO, "t", "m", "s", asset="SHIB")
        assert mock_warn.called
        msg = " ".join(str(a) for a in mock_warn.call_args_list[0][0])
        assert "unknown asset" in msg.lower()

    # ── Singleton ─────────────────────────────────────────────────────────────

    def test_singleton(self):
        import agents.alert_manager as am_module
        am_module._alert_manager = None
        from agents.alert_manager import get_alert_manager
        m1 = get_alert_manager()
        m2 = get_alert_manager()
        assert m1 is m2


# ══════════════════════════════════════════════════════════════════════════════
# §4  agents/quorum_failure_tracker.py
# ══════════════════════════════════════════════════════════════════════════════

class TestQuorumFailureTracker:

    def _make_tracker(self, window_s=60.0, threshold=3, cooldown_s=10.0):
        from agents.quorum_failure_tracker import QuorumFailureTracker
        return QuorumFailureTracker(
            window_s=window_s,
            threshold=threshold,
            cooldown_s=cooldown_s,
        )

    # ── Emission logic ────────────────────────────────────────────────────────

    def test_first_failure_always_emits(self):
        tracker = self._make_tracker()
        assert tracker.record_failure("BTC", "15m") is True

    def test_failures_below_threshold_all_emit(self):
        tracker = self._make_tracker(threshold=3, cooldown_s=0.0)
        for i in range(3):
            result = tracker.record_failure("BTC", "15m")
            assert result is True, f"Call {i+1} should emit"

    def test_throttled_after_threshold_exceeded(self):
        tracker = self._make_tracker(threshold=2, cooldown_s=9999.0)
        for _ in range(3):
            tracker.record_failure("BTC", "15m")
        # Now over threshold and within cooldown → should suppress.
        suppressed = tracker.record_failure("BTC", "15m")
        assert suppressed is False

    def test_different_keys_tracked_independently(self):
        tracker = self._make_tracker(threshold=2, cooldown_s=9999.0)
        # Flood BTC/15m.
        for _ in range(5):
            tracker.record_failure("BTC", "15m")
        # ETH/daily should still emit.
        assert tracker.record_failure("ETH", "daily") is True

    def test_suppressed_count_increments(self):
        tracker = self._make_tracker(threshold=1, cooldown_s=9999.0)
        tracker.record_failure("SOL", "1h")  # emits (count=1)
        tracker.record_failure("SOL", "1h")  # emits (count=2, threshold crossed)
        tracker.record_failure("SOL", "1h")  # suppressed
        tracker.record_failure("SOL", "1h")  # suppressed
        status = tracker.get_status("SOL", "1h")
        assert status.suppressed_count >= 1

    # ── get_status ────────────────────────────────────────────────────────────

    def test_get_status_returns_correct_counts(self):
        tracker = self._make_tracker()
        tracker.record_failure("DOGE", "weekly")
        tracker.record_failure("DOGE", "weekly")
        status = tracker.get_status("DOGE", "weekly")
        assert status.failure_count_in_window == 2
        assert status.asset == "DOGE"
        assert status.timeframe == "weekly"

    def test_get_status_unknown_key_returns_zeros(self):
        tracker = self._make_tracker()
        status = tracker.get_status("XRP", "monthly")
        assert status.failure_count_in_window == 0
        assert status.suppressed_count == 0
        assert status.throttled is False

    # ── get_metrics ───────────────────────────────────────────────────────────

    def test_get_metrics_structure(self):
        tracker = self._make_tracker()
        m = tracker.get_metrics()
        assert "window_s" in m
        assert "threshold" in m
        assert "cooldown_s" in m
        assert "per_key" in m

    # ── reset ─────────────────────────────────────────────────────────────────

    def test_reset_clears_suppression(self):
        tracker = self._make_tracker(threshold=1, cooldown_s=9999.0)
        for _ in range(5):
            tracker.record_failure("BTC", "monthly")
        tracker.reset("BTC", "monthly")
        # After reset, next failure should emit again.
        assert tracker.record_failure("BTC", "monthly") is True

    # ── Singleton ─────────────────────────────────────────────────────────────

    def test_singleton(self):
        import agents.quorum_failure_tracker as qft_module
        qft_module._quorum_failure_tracker = None
        from agents.quorum_failure_tracker import get_quorum_failure_tracker
        t1 = get_quorum_failure_tracker()
        t2 = get_quorum_failure_tracker()
        assert t1 is t2


# ══════════════════════════════════════════════════════════════════════════════
# §5  agents/unified_decision_layer.py — QUORUM_FAILED routing
# ══════════════════════════════════════════════════════════════════════════════

class TestUnifiedDecisionLayerQuorumRouting:
    """
    Test that QUORUM_FAILED decisions are routed through the tracker and bus.
    We stub out the heavy framework dependencies so these are pure unit tests.
    """

    def _make_decision(self, final_decision: str, asset=None, timeframe=None):
        """Build a minimal UnifiedDecision-like object."""
        from agents.unified_decision_layer import UnifiedDecision, DecisionPriority
        return UnifiedDecision(
            decision_id="d-test",
            decision_type="crypto_signal",
            final_decision=final_decision,
            confidence=0.3,
            priority=DecisionPriority.HIGH,
            contributions=[],
            aggregation_method="weighted_voting",
            reasoning_summary="not enough agents",
            timestamp=time.time(),
            metadata={"asset": asset, "timeframe": timeframe},
        )

    def test_quorum_failed_calls_tracker(self):
        from agents.unified_decision_layer import UnifiedDecisionLayer
        from agents.quorum_failure_tracker import QuorumFailureTracker

        tracker = QuorumFailureTracker()
        layer = UnifiedDecisionLayer.__new__(UnifiedDecisionLayer)

        with patch("agents.quorum_failure_tracker.get_quorum_failure_tracker",
                   return_value=tracker):
            decision = self._make_decision("QUORUM_FAILED", "BTC", "15m")
            layer._handle_quorum_failed(
                "crypto_signal",
                {"asset": "BTC", "timeframe": "15m"},
                decision,
            )

        status = tracker.get_status("BTC", "15m")
        assert status.failure_count_in_window == 1

    def test_quorum_failed_publishes_governance_event(self):
        from agents.unified_decision_layer import UnifiedDecisionLayer
        from agents.governance_event_bus import GovernanceEventBus, GovernanceEventType
        from agents.quorum_failure_tracker import QuorumFailureTracker

        bus = GovernanceEventBus()
        received: List[Any] = []
        bus.subscribe(GovernanceEventType.QUORUM_FAILED, received.append)

        tracker = QuorumFailureTracker()
        layer = UnifiedDecisionLayer.__new__(UnifiedDecisionLayer)

        with (
            patch("agents.quorum_failure_tracker.get_quorum_failure_tracker",
                  return_value=tracker),
            patch("agents.governance_event_bus.get_governance_event_bus",
                  return_value=bus),
        ):
            decision = self._make_decision("QUORUM_FAILED", "ETH", "1h")
            layer._handle_quorum_failed(
                "crypto_signal",
                {"asset": "ETH", "timeframe": "1h"},
                decision,
            )

        assert len(received) == 1
        assert received[0].asset == "ETH"
        assert received[0].timeframe == "1h"

    def test_quorum_failed_fires_alert_manager(self):
        from agents.unified_decision_layer import UnifiedDecisionLayer
        from agents.alert_manager import AlertManager
        from agents.quorum_failure_tracker import QuorumFailureTracker

        am = AlertManager()
        fired: List[Any] = []
        am.add_sink(fired.append)

        tracker = QuorumFailureTracker()
        layer = UnifiedDecisionLayer.__new__(UnifiedDecisionLayer)

        with (
            patch("agents.quorum_failure_tracker.get_quorum_failure_tracker",
                  return_value=tracker),
            patch("agents.alert_manager.get_alert_manager",
                  return_value=am),
        ):
            decision = self._make_decision("QUORUM_FAILED", "SOL", "daily")
            layer._handle_quorum_failed(
                "crypto_signal",
                {"asset": "SOL", "timeframe": "daily"},
                decision,
            )

        assert len(fired) == 1
        assert fired[0].asset == "SOL"

    def test_suppressed_quorum_failure_does_not_alert(self):
        """After throttle threshold, further failures should NOT re-fire alerts."""
        from agents.unified_decision_layer import UnifiedDecisionLayer
        from agents.alert_manager import AlertManager
        from agents.quorum_failure_tracker import QuorumFailureTracker

        am = AlertManager()
        fired: List[Any] = []
        am.add_sink(fired.append)

        tracker = QuorumFailureTracker(threshold=1, cooldown_s=9999.0)
        layer = UnifiedDecisionLayer.__new__(UnifiedDecisionLayer)

        # Pre-load: flood tracker so it immediately throttles.
        for _ in range(5):
            tracker.record_failure("XRP", "weekly")

        with (
            patch("agents.quorum_failure_tracker.get_quorum_failure_tracker",
                  return_value=tracker),
            patch("agents.alert_manager.get_alert_manager",
                  return_value=am),
        ):
            decision = self._make_decision("QUORUM_FAILED", "XRP", "weekly")
            layer._handle_quorum_failed(
                "crypto_signal",
                {"asset": "XRP", "timeframe": "weekly"},
                decision,
            )

        assert len(fired) == 0, "Alert should be suppressed after throttle threshold"

    def test_validate_asset_timeframe_warns_on_invalid(self):
        import logging
        from agents.unified_decision_layer import UnifiedDecisionLayer

        layer = UnifiedDecisionLayer.__new__(UnifiedDecisionLayer)
        udl_logger = logging.getLogger("agents.unified_decision")
        with patch.object(udl_logger, "warning") as mock_warn:
            layer._validate_asset_timeframe("SHIB", "4h")
        assert mock_warn.called

    def test_get_crypto_grid_returns_25_pairs(self):
        from agents.unified_decision_layer import UnifiedDecisionLayer
        grid = UnifiedDecisionLayer._get_crypto_grid()
        assert len(grid) == 25
