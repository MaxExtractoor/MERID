"""End-to-end integration tests for the promotion pipeline.

Exercises the full chain:
  report change → _diff_and_log → PromotionLog event → governance notify
  manual override → log event → governance notify
  log rotation under cap
  guard sync from report
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from merid.promotion_report import (
    PromotionEvent,
    PromotionLog,
    PromotionReport,
    DomainEligibility,
    AgentPromotion,
    RingResult,
    _diff_and_log,
    get_promotion_log,
    manual_promote,
    manual_demote,
)
from merid.governance_notifier import (
    GovernanceNotifier,
    LogChannel,
    reset_notifier,
)
from merid.execution_guard import ExecutionGuard


def _make_report(domains, agents):
    report = PromotionReport(timestamp=time.time())
    for name, eligible in domains:
        report.domains.append(DomainEligibility(
            domain=name, eligible=eligible, mode="paper",
        ))
    for aid, promoted in agents:
        report.agents.append(AgentPromotion(
            agent_id=aid, category="test", promoted=promoted,
        ))
    return report


# ═══════════════════════════════════════════════════════════════════════
# 1. Full pipeline: report diff → log → notify
# ═══════════════════════════════════════════════════════════════════════

class TestReportDiffToNotify:
    """Verify the complete automated pipeline end-to-end."""

    def test_first_report_creates_baseline_no_notify(self, tmp_path):
        """First report creates baseline events but does NOT notify (unknown→X)."""
        log = PromotionLog(log_file=tmp_path / "e2e1.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            r1 = _make_report([("crypto", True), ("equity", False)], [("agent_1", True)])
            events = _diff_and_log(None, r1)

        assert len(events) == 3
        assert all(e.source == "automation" for e in events)
        # Baseline events (unknown→X) should NOT trigger notifications
        mock_notifier.notify.assert_not_called()

    def test_status_change_triggers_notify(self, tmp_path):
        """When a domain flips status, the notification fires."""
        log = PromotionLog(log_file=tmp_path / "e2e2.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            r1 = _make_report([("crypto", True)], [])
            _diff_and_log(None, r1)  # baseline, no notify
            mock_notifier.notify.reset_mock()

            r2 = _make_report([("crypto", False)], [])
            events = _diff_and_log(r1, r2)

        assert len(events) == 1
        assert events[0].new_status == "blocked"
        mock_notifier.notify.assert_called_once()
        payload = mock_notifier.notify.call_args[0][0]
        assert payload["entity_id"] == "crypto"
        assert payload["source"] == "automation"

    def test_no_change_no_events_no_notify(self, tmp_path):
        """Identical reports produce zero events and zero notifications."""
        log = PromotionLog(log_file=tmp_path / "e2e3.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            r1 = _make_report([("crypto", True)], [("agent_1", True)])
            _diff_and_log(None, r1)
            mock_notifier.notify.reset_mock()

            r2 = _make_report([("crypto", True)], [("agent_1", True)])
            events = _diff_and_log(r1, r2)

        assert len(events) == 0
        mock_notifier.notify.assert_not_called()

    def test_multiple_transitions_multiple_notifies(self, tmp_path):
        """Multiple entities changing should fire one notify per change."""
        log = PromotionLog(log_file=tmp_path / "e2e4.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            r1 = _make_report([("crypto", True), ("equity", False)], [("a1", True)])
            _diff_and_log(None, r1)
            mock_notifier.notify.reset_mock()

            r2 = _make_report([("crypto", False), ("equity", True)], [("a1", False)])
            events = _diff_and_log(r1, r2)

        assert len(events) == 3
        assert mock_notifier.notify.call_count == 3


# ═══════════════════════════════════════════════════════════════════════
# 2. Manual override pipeline
# ═══════════════════════════════════════════════════════════════════════

class TestManualOverridePipeline:
    """Verify manual promote/demote flows through log and notify."""

    def test_manual_promote_full_chain(self, tmp_path):
        log = PromotionLog(log_file=tmp_path / "e2e5.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            event = manual_promote("domain", "crypto", reason="manual review", operator="alice")

        # Event in log
        assert len(log) == 1
        assert log.events()[0].source == "operator"
        assert log.events()[0].new_status == "eligible"

        # Notification fired
        mock_notifier.notify.assert_called_once()
        payload = mock_notifier.notify.call_args[0][0]
        assert payload["source"] == "operator"

        # Persisted to disk
        log2 = PromotionLog(log_file=tmp_path / "e2e5.json")
        assert len(log2) == 1

    def test_manual_after_automation_tracks_history(self, tmp_path):
        """Manual override after automated events should track full history."""
        log = PromotionLog(log_file=tmp_path / "e2e6.json")
        mock_notifier = MagicMock()
        mock_notifier.notify = MagicMock()

        with patch("merid.promotion_report.get_promotion_log", return_value=log), \
             patch("merid.governance_notifier.get_governance_notifier", return_value=mock_notifier):
            # Automated baseline
            r1 = _make_report([("crypto", False)], [])
            _diff_and_log(None, r1)

            # Operator override
            event = manual_promote("domain", "crypto", operator="bob")

        assert len(log) == 2
        assert log.events()[0].source == "automation"
        assert log.events()[1].source == "operator"
        assert log.events()[1].previous_status == "blocked"
        assert log.events()[1].new_status == "eligible"


# ═══════════════════════════════════════════════════════════════════════
# 3. Log rotation
# ═══════════════════════════════════════════════════════════════════════

class TestLogRotation:
    """Verify PromotionLog caps and rotates events."""

    def test_rotation_at_cap(self, tmp_path):
        log = PromotionLog(log_file=tmp_path / "rot1.json", max_events=5)
        for i in range(8):
            log.append(PromotionEvent(
                time.time(), "domain", f"d{i}", "unknown", "eligible", source="system",
            ))
        assert len(log) == 5
        # Oldest events trimmed, newest kept
        ids = [e.entity_id for e in log.events()]
        assert ids == ["d3", "d4", "d5", "d6", "d7"]

    def test_rotation_persists(self, tmp_path):
        log = PromotionLog(log_file=tmp_path / "rot2.json", max_events=3)
        for i in range(6):
            log.append(PromotionEvent(
                time.time(), "domain", f"d{i}", "unknown", "eligible", source="system",
            ))
        # Reload from disk
        log2 = PromotionLog(log_file=tmp_path / "rot2.json", max_events=3)
        assert len(log2) == 3
        ids = [e.entity_id for e in log2.events()]
        assert ids == ["d3", "d4", "d5"]

    def test_rotation_preserves_recent(self, tmp_path):
        """After rotation, the most recent events should be queryable."""
        log = PromotionLog(log_file=tmp_path / "rot3.json", max_events=10)
        for i in range(15):
            log.append(PromotionEvent(
                time.time(), "domain", f"d{i}", "unknown", "eligible", source="automation",
            ))
        latest = log.latest_for("domain", "d14")
        assert latest is not None
        assert latest.entity_id == "d14"

        # Old events should be gone
        old = log.latest_for("domain", "d0")
        assert old is None


# ═══════════════════════════════════════════════════════════════════════
# 4. Guard sync from report
# ═══════════════════════════════════════════════════════════════════════

class TestGuardSyncIntegration:
    """Verify ExecutionGuard syncs promotion state from the report."""

    def test_sync_populates_eligible_domains(self):
        guard = ExecutionGuard()
        report = _make_report([("crypto", True), ("equity", False)], [("a1", True), ("a2", False)])

        with patch("merid.promotion_report.get_cached_promotion_report", return_value=report):
            guard.sync_promotion_report()

        assert guard.is_domain_promoted("crypto") is True
        assert guard.is_domain_promoted("equity") is False
        assert guard._promotion_report_ts == report.timestamp

    def test_sync_updates_on_change(self):
        guard = ExecutionGuard()
        r1 = _make_report([("crypto", True)], [])
        r2 = _make_report([("crypto", False)], [])

        with patch("merid.promotion_report.get_cached_promotion_report", return_value=r1):
            guard.sync_promotion_report()
        assert guard.is_domain_promoted("crypto") is True

        with patch("merid.promotion_report.get_cached_promotion_report", return_value=r2):
            guard.sync_promotion_report()
        assert guard.is_domain_promoted("crypto") is False

    def test_summary_includes_freshness(self):
        guard = ExecutionGuard()
        report = _make_report([("crypto", True)], [])

        with patch("merid.promotion_report.get_cached_promotion_report", return_value=report):
            guard.sync_promotion_report()

        s = guard.summary()
        promo = s["promotion_enforcement"]
        assert promo["sync_age_s"] is not None
        assert promo["sync_age_s"] < 5  # just synced
        assert promo["stale"] is False

    def test_summary_stale_when_never_synced(self):
        guard = ExecutionGuard()
        s = guard.summary()
        promo = s["promotion_enforcement"]
        assert promo["stale"] is True
        assert promo["sync_age_s"] is None


# ═══════════════════════════════════════════════════════════════════════
# 5. Governance notifier real dispatch (log channel)
# ═══════════════════════════════════════════════════════════════════════

class TestGovernanceRealDispatch:
    """Verify the real LogChannel receives formatted payloads."""

    def test_log_channel_receives_formatted_event(self):
        notifier = GovernanceNotifier()
        notifier.add_channel(LogChannel())

        event_dict = PromotionEvent(
            time.time(), "domain", "crypto", "blocked", "eligible",
            source="operator", reason="manual override",
        ).to_dict()

        results = notifier.notify(event_dict, blocking=True)
        assert len(results) == 1
        assert results[0].success is True

        # History recorded
        assert len(notifier.history) == 1
        record = notifier.history[0]
        assert "DOMAIN" in record["payload"]["title"]
        assert "crypto" in record["payload"]["title"]
        assert record["payload"]["source"] == "operator"
