"""Tests for the promotion change log system.

Covers:
  1. PromotionEvent data model
  2. PromotionLog append-only storage + persistence
  3. Diff detection between consecutive reports
  4. Filtering and querying
  5. Integration with get_cached_promotion_report
"""

from __future__ import annotations

import json
import tempfile
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


# ═══════════════════════════════════════════════════════════════════════
# 1. PromotionEvent data model
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionEvent:
    """Verify PromotionEvent data structure and serialization."""

    def test_create_event(self):
        evt = PromotionEvent(
            timestamp=1000.0,
            entity_type="domain",
            entity_id="crypto",
            previous_status="blocked",
            new_status="eligible",
            reason="all rings passing",
            report_timestamp=999.0,
        )
        assert evt.entity_type == "domain"
        assert evt.entity_id == "crypto"
        assert evt.previous_status == "blocked"
        assert evt.new_status == "eligible"

    def test_default_source(self):
        evt = PromotionEvent(
            timestamp=1000.0,
            entity_type="domain",
            entity_id="crypto",
            previous_status="blocked",
            new_status="eligible",
        )
        assert evt.source == "system"

    def test_custom_source(self):
        evt = PromotionEvent(
            timestamp=1000.0,
            entity_type="domain",
            entity_id="crypto",
            previous_status="blocked",
            new_status="eligible",
            source="operator",
        )
        assert evt.source == "operator"

    def test_to_dict(self):
        evt = PromotionEvent(
            timestamp=1000.0,
            entity_type="agent",
            entity_id="agent_1",
            previous_status="unknown",
            new_status="blocked",
            reason="failed SLOs: latency",
            report_timestamp=999.0,
            source="automation",
        )
        d = evt.to_dict()
        assert d["entity_type"] == "agent"
        assert d["entity_id"] == "agent_1"
        assert d["previous_status"] == "unknown"
        assert d["new_status"] == "blocked"
        assert d["reason"] == "failed SLOs: latency"
        assert d["runbook_version"] == "1.0"
        assert d["source"] == "automation"

    def test_from_dict_roundtrip(self):
        evt = PromotionEvent(
            timestamp=1234.5,
            entity_type="domain",
            entity_id="equity",
            previous_status="eligible",
            new_status="blocked",
            reason="ring failed",
            report_timestamp=1234.0,
            runbook_version="1.0",
        )
        d = evt.to_dict()
        restored = PromotionEvent.from_dict(d)
        assert restored.timestamp == evt.timestamp
        assert restored.entity_type == evt.entity_type
        assert restored.entity_id == evt.entity_id
        assert restored.previous_status == evt.previous_status
        assert restored.new_status == evt.new_status
        assert restored.reason == evt.reason

    def test_from_dict_missing_optional_fields(self):
        d = {
            "timestamp": 100.0,
            "entity_type": "domain",
            "entity_id": "crypto",
            "previous_status": "unknown",
            "new_status": "eligible",
        }
        evt = PromotionEvent.from_dict(d)
        assert evt.reason == ""
        assert evt.report_timestamp == 0.0
        assert evt.runbook_version == "1.0"
        assert evt.source == "system"

    def test_from_dict_with_source(self):
        d = {
            "timestamp": 100.0,
            "entity_type": "domain",
            "entity_id": "crypto",
            "previous_status": "unknown",
            "new_status": "eligible",
            "source": "operator",
        }
        evt = PromotionEvent.from_dict(d)
        assert evt.source == "operator"

    def test_json_serializable(self):
        evt = PromotionEvent(
            timestamp=time.time(),
            entity_type="domain",
            entity_id="crypto",
            previous_status="blocked",
            new_status="eligible",
        )
        serialized = json.dumps(evt.to_dict())
        assert len(serialized) > 20


# ═══════════════════════════════════════════════════════════════════════
# 2. PromotionLog storage and persistence
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionLog:
    """Verify append-only log with file persistence."""

    def _make_log(self, tmp_path: Path) -> PromotionLog:
        return PromotionLog(log_file=tmp_path / "test_log.json")

    def _make_event(self, entity_id="crypto", new_status="eligible") -> PromotionEvent:
        return PromotionEvent(
            timestamp=time.time(),
            entity_type="domain",
            entity_id=entity_id,
            previous_status="blocked",
            new_status=new_status,
        )

    def test_empty_log(self, tmp_path):
        log = self._make_log(tmp_path)
        assert len(log) == 0
        assert log.events() == []

    def test_append_and_retrieve(self, tmp_path):
        log = self._make_log(tmp_path)
        evt = self._make_event()
        log.append(evt)
        assert len(log) == 1
        assert log.events()[0].entity_id == "crypto"

    def test_append_multiple(self, tmp_path):
        log = self._make_log(tmp_path)
        log.append(self._make_event("crypto"))
        log.append(self._make_event("equity"))
        log.append(self._make_event("prediction"))
        assert len(log) == 3

    def test_persistence_across_instances(self, tmp_path):
        log_file = tmp_path / "persist_test.json"

        log1 = PromotionLog(log_file=log_file)
        log1.append(self._make_event("crypto"))
        log1.append(self._make_event("equity"))

        # New instance reads from same file
        log2 = PromotionLog(log_file=log_file)
        assert len(log2) == 2
        assert log2.events()[0].entity_id == "crypto"
        assert log2.events()[1].entity_id == "equity"

    def test_file_created_on_append(self, tmp_path):
        log_file = tmp_path / "subdir" / "new_log.json"
        assert not log_file.exists()

        log = PromotionLog(log_file=log_file)
        log.append(self._make_event())
        assert log_file.exists()

    def test_clear(self, tmp_path):
        log = self._make_log(tmp_path)
        log.append(self._make_event("crypto"))
        log.append(self._make_event("equity"))
        assert len(log) == 2

        log.clear()
        assert len(log) == 0
        assert log.events() == []

    def test_latest_for(self, tmp_path):
        log = self._make_log(tmp_path)
        log.append(self._make_event("crypto", "blocked"))
        log.append(self._make_event("crypto", "eligible"))
        log.append(self._make_event("equity", "blocked"))

        latest_crypto = log.latest_for("domain", "crypto")
        assert latest_crypto is not None
        assert latest_crypto.new_status == "eligible"

        latest_equity = log.latest_for("domain", "equity")
        assert latest_equity is not None
        assert latest_equity.new_status == "blocked"

        latest_missing = log.latest_for("domain", "sports")
        assert latest_missing is None

    def test_corrupt_file_handled(self, tmp_path):
        log_file = tmp_path / "corrupt.json"
        log_file.write_text("not valid json {{{")

        log = PromotionLog(log_file=log_file)
        assert len(log) == 0  # graceful fallback

    def test_limit_parameter(self, tmp_path):
        log = self._make_log(tmp_path)
        for i in range(20):
            log.append(self._make_event(f"domain_{i}"))

        assert len(log.events(limit=5)) == 5
        assert len(log.events(limit=100)) == 20

    def test_limit_returns_most_recent(self, tmp_path):
        log = self._make_log(tmp_path)
        for i in range(10):
            log.append(self._make_event(f"domain_{i}"))

        recent = log.events(limit=3)
        assert recent[0].entity_id == "domain_7"
        assert recent[1].entity_id == "domain_8"
        assert recent[2].entity_id == "domain_9"


# ═══════════════════════════════════════════════════════════════════════
# 3. Filtering
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionLogFiltering:
    """Verify entity_type and entity_id filtering."""

    def _make_log_with_events(self, tmp_path: Path) -> PromotionLog:
        log = PromotionLog(log_file=tmp_path / "filter_test.json")
        now = time.time()
        events = [
            PromotionEvent(now, "domain", "crypto", "unknown", "eligible"),
            PromotionEvent(now, "domain", "equity", "unknown", "blocked"),
            PromotionEvent(now, "agent", "agent_alpha", "unknown", "eligible"),
            PromotionEvent(now, "agent", "agent_beta", "unknown", "blocked"),
            PromotionEvent(now, "domain", "crypto", "eligible", "blocked"),
        ]
        for e in events:
            log.append(e)
        return log

    def test_filter_by_entity_type_domain(self, tmp_path):
        log = self._make_log_with_events(tmp_path)
        domains = log.events(entity_type="domain")
        assert len(domains) == 3
        assert all(e.entity_type == "domain" for e in domains)

    def test_filter_by_entity_type_agent(self, tmp_path):
        log = self._make_log_with_events(tmp_path)
        agents = log.events(entity_type="agent")
        assert len(agents) == 2
        assert all(e.entity_type == "agent" for e in agents)

    def test_filter_by_entity_id(self, tmp_path):
        log = self._make_log_with_events(tmp_path)
        crypto = log.events(entity_id="crypto")
        assert len(crypto) == 2
        assert all(e.entity_id == "crypto" for e in crypto)

    def test_filter_combined(self, tmp_path):
        log = self._make_log_with_events(tmp_path)
        result = log.events(entity_type="agent", entity_id="agent_alpha")
        assert len(result) == 1
        assert result[0].entity_id == "agent_alpha"

    def test_filter_no_match(self, tmp_path):
        log = self._make_log_with_events(tmp_path)
        result = log.events(entity_type="domain", entity_id="nonexistent")
        assert len(result) == 0


# ═══════════════════════════════════════════════════════════════════════
# 4. Diff detection
# ═══════════════════════════════════════════════════════════════════════

class TestDiffAndLog:
    """Verify _diff_and_log detects status transitions correctly."""

    def _make_report(
        self,
        domains: list[tuple[str, bool]],
        agents: list[tuple[str, bool]],
    ) -> PromotionReport:
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

    def test_first_report_emits_events(self, tmp_path):
        """First report (no previous) should emit events for all entities."""
        log = PromotionLog(log_file=tmp_path / "diff1.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            current = self._make_report(
                [("crypto", True), ("equity", False)],
                [("agent_1", True)],
            )
            events = _diff_and_log(None, current)

        # All entities transition from "unknown"
        assert len(events) == 3
        assert all(e.previous_status == "unknown" for e in events)

    def test_no_change_no_events(self, tmp_path):
        """Identical reports should produce zero events."""
        log = PromotionLog(log_file=tmp_path / "diff2.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            r1 = self._make_report([("crypto", True)], [("agent_1", True)])
            r2 = self._make_report([("crypto", True)], [("agent_1", True)])
            events = _diff_and_log(r1, r2)

        assert len(events) == 0

    def test_domain_promotion(self, tmp_path):
        """Domain going from blocked to eligible should emit one event."""
        log = PromotionLog(log_file=tmp_path / "diff3.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report([("crypto", False)], [])
            curr = self._make_report([("crypto", True)], [])
            events = _diff_and_log(prev, curr)

        assert len(events) == 1
        assert events[0].entity_type == "domain"
        assert events[0].entity_id == "crypto"
        assert events[0].previous_status == "blocked"
        assert events[0].new_status == "eligible"

    def test_domain_demotion(self, tmp_path):
        """Domain going from eligible to blocked should emit one event."""
        log = PromotionLog(log_file=tmp_path / "diff4.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report([("crypto", True)], [])
            curr = self._make_report([("crypto", False)], [])
            events = _diff_and_log(prev, curr)

        assert len(events) == 1
        assert events[0].new_status == "blocked"

    def test_agent_promotion(self, tmp_path):
        """Agent going from blocked to promoted should emit one event."""
        log = PromotionLog(log_file=tmp_path / "diff5.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report([], [("agent_1", False)])
            curr = self._make_report([], [("agent_1", True)])
            events = _diff_and_log(prev, curr)

        assert len(events) == 1
        assert events[0].entity_type == "agent"
        assert events[0].new_status == "eligible"

    def test_agent_demotion(self, tmp_path):
        """Agent going from promoted to blocked should emit one event."""
        log = PromotionLog(log_file=tmp_path / "diff6.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report([], [("agent_1", True)])
            curr = self._make_report([], [("agent_1", False)])
            events = _diff_and_log(prev, curr)

        assert len(events) == 1
        assert events[0].new_status == "blocked"

    def test_mixed_transitions(self, tmp_path):
        """Multiple entities changing in different directions."""
        log = PromotionLog(log_file=tmp_path / "diff7.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report(
                [("crypto", True), ("equity", False)],
                [("agent_1", True), ("agent_2", False)],
            )
            curr = self._make_report(
                [("crypto", False), ("equity", True)],
                [("agent_1", False), ("agent_2", True)],
            )
            events = _diff_and_log(prev, curr)

        assert len(events) == 4
        ids = {(e.entity_type, e.entity_id, e.new_status) for e in events}
        assert ("domain", "crypto", "blocked") in ids
        assert ("domain", "equity", "eligible") in ids
        assert ("agent", "agent_1", "blocked") in ids
        assert ("agent", "agent_2", "eligible") in ids

    def test_new_entity_in_current(self, tmp_path):
        """Entity appearing for the first time should have previous_status=unknown."""
        log = PromotionLog(log_file=tmp_path / "diff8.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report([("crypto", True)], [])
            curr = self._make_report([("crypto", True), ("equity", True)], [])
            events = _diff_and_log(prev, curr)

        assert len(events) == 1
        assert events[0].entity_id == "equity"
        assert events[0].previous_status == "unknown"

    def test_events_have_report_timestamp(self, tmp_path):
        """Events should reference the report that triggered them."""
        log = PromotionLog(log_file=tmp_path / "diff9.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            curr = self._make_report([("crypto", True)], [])
            events = _diff_and_log(None, curr)

        assert len(events) == 1
        assert events[0].report_timestamp == curr.timestamp

    def test_reason_populated_for_blocked(self, tmp_path):
        """Blocked events should include blocker reasons."""
        log = PromotionLog(log_file=tmp_path / "diff10.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            curr = self._make_report([], [])
            curr.domains.append(DomainEligibility(
                domain="crypto", eligible=False, mode="paper",
                blockers=["ring failed", "mode wrong"],
            ))
            events = _diff_and_log(None, curr)

        assert len(events) == 1
        assert "ring failed" in events[0].reason
        assert "mode wrong" in events[0].reason


# ═══════════════════════════════════════════════════════════════════════
# 5. Singleton and module-level access
# ═══════════════════════════════════════════════════════════════════════

class TestPromotionLogSingleton:
    """Verify the module-level singleton accessor."""

    def test_get_promotion_log_returns_instance(self):
        log = get_promotion_log()
        assert isinstance(log, PromotionLog)

    def test_get_promotion_log_is_singleton(self):
        log1 = get_promotion_log()
        log2 = get_promotion_log()
        assert log1 is log2


# ═══════════════════════════════════════════════════════════════════════
# 6. Source tagging
# ═══════════════════════════════════════════════════════════════════════

class TestSourceTagging:
    """Verify that automated diff events are tagged with source='automation'."""

    def _make_report(self, domains, agents):
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

    def test_diff_events_tagged_automation(self, tmp_path):
        """Events from _diff_and_log should have source='automation'."""
        log = PromotionLog(log_file=tmp_path / "src1.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            curr = self._make_report([("crypto", True)], [("agent_1", False)])
            events = _diff_and_log(None, curr)

        assert len(events) == 2
        assert all(e.source == "automation" for e in events)

    def test_diff_domain_transition_tagged(self, tmp_path):
        """Domain transitions from diff should be automation-sourced."""
        log = PromotionLog(log_file=tmp_path / "src2.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report([("crypto", False)], [])
            curr = self._make_report([("crypto", True)], [])
            events = _diff_and_log(prev, curr)

        assert len(events) == 1
        assert events[0].source == "automation"

    def test_diff_agent_transition_tagged(self, tmp_path):
        """Agent transitions from diff should be automation-sourced."""
        log = PromotionLog(log_file=tmp_path / "src3.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            prev = self._make_report([], [("agent_1", True)])
            curr = self._make_report([], [("agent_1", False)])
            events = _diff_and_log(prev, curr)

        assert len(events) == 1
        assert events[0].source == "automation"


# ═══════════════════════════════════════════════════════════════════════
# 7. Source filtering
# ═══════════════════════════════════════════════════════════════════════

class TestSourceFiltering:
    """Verify filtering events by source."""

    def _make_mixed_log(self, tmp_path: Path) -> PromotionLog:
        log = PromotionLog(log_file=tmp_path / "srcfilter.json")
        now = time.time()
        log.append(PromotionEvent(now, "domain", "crypto", "unknown", "eligible", source="automation"))
        log.append(PromotionEvent(now, "domain", "equity", "unknown", "blocked", source="automation"))
        log.append(PromotionEvent(now, "domain", "crypto", "eligible", "blocked", source="operator"))
        log.append(PromotionEvent(now, "agent", "agent_1", "unknown", "eligible", source="system"))
        return log

    def test_filter_automation(self, tmp_path):
        log = self._make_mixed_log(tmp_path)
        events = log.events(source="automation")
        assert len(events) == 2
        assert all(e.source == "automation" for e in events)

    def test_filter_operator(self, tmp_path):
        log = self._make_mixed_log(tmp_path)
        events = log.events(source="operator")
        assert len(events) == 1
        assert events[0].entity_id == "crypto"
        assert events[0].source == "operator"

    def test_filter_system(self, tmp_path):
        log = self._make_mixed_log(tmp_path)
        events = log.events(source="system")
        assert len(events) == 1
        assert events[0].entity_id == "agent_1"

    def test_filter_source_combined_with_entity(self, tmp_path):
        log = self._make_mixed_log(tmp_path)
        events = log.events(entity_type="domain", source="automation")
        assert len(events) == 2

    def test_filter_source_no_match(self, tmp_path):
        log = self._make_mixed_log(tmp_path)
        events = log.events(source="nonexistent")
        assert len(events) == 0


# ═══════════════════════════════════════════════════════════════════════
# 8. Manual promote / demote
# ═══════════════════════════════════════════════════════════════════════

class TestManualPromoteDemote:
    """Verify operator-initiated promotion and demotion functions."""

    def test_manual_promote_creates_event(self, tmp_path):
        log = PromotionLog(log_file=tmp_path / "manual1.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            event = manual_promote("domain", "crypto", reason="testing", operator="alice")

        assert event.entity_type == "domain"
        assert event.entity_id == "crypto"
        assert event.new_status == "eligible"
        assert event.source == "operator"
        assert "alice" in event.reason or "testing" in event.reason

    def test_manual_demote_creates_event(self, tmp_path):
        log = PromotionLog(log_file=tmp_path / "manual2.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            event = manual_demote("agent", "agent_1", reason="SLO regression", operator="bob")

        assert event.entity_type == "agent"
        assert event.entity_id == "agent_1"
        assert event.new_status == "blocked"
        assert event.source == "operator"
        assert "SLO regression" in event.reason

    def test_manual_promote_default_reason(self, tmp_path):
        log = PromotionLog(log_file=tmp_path / "manual3.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            event = manual_promote("domain", "equity", operator="charlie")

        assert "charlie" in event.reason
        assert "manual promotion" in event.reason

    def test_manual_demote_default_reason(self, tmp_path):
        log = PromotionLog(log_file=tmp_path / "manual4.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            event = manual_demote("domain", "equity", operator="dave")

        assert "dave" in event.reason
        assert "manual demotion" in event.reason

    def test_manual_promote_tracks_previous_status(self, tmp_path):
        """Manual promote should look up the latest status for the entity."""
        log = PromotionLog(log_file=tmp_path / "manual5.json")
        # Pre-populate with a blocked event
        log.append(PromotionEvent(
            time.time(), "domain", "crypto", "unknown", "blocked", source="automation",
        ))
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            event = manual_promote("domain", "crypto", operator="eve")

        assert event.previous_status == "blocked"
        assert event.new_status == "eligible"

    def test_manual_demote_tracks_previous_status(self, tmp_path):
        """Manual demote should look up the latest status for the entity."""
        log = PromotionLog(log_file=tmp_path / "manual6.json")
        log.append(PromotionEvent(
            time.time(), "agent", "agent_1", "unknown", "eligible", source="automation",
        ))
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            event = manual_demote("agent", "agent_1", operator="frank")

        assert event.previous_status == "eligible"
        assert event.new_status == "blocked"

    def test_manual_promote_unknown_entity(self, tmp_path):
        """Manual promote on entity with no history should show previous_status=unknown."""
        log = PromotionLog(log_file=tmp_path / "manual7.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            event = manual_promote("domain", "new_domain", operator="grace")

        assert event.previous_status == "unknown"

    def test_manual_events_persisted(self, tmp_path):
        """Manual events should be persisted to the log file."""
        log = PromotionLog(log_file=tmp_path / "manual8.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            manual_promote("domain", "crypto", operator="heidi")
            manual_demote("agent", "agent_1", operator="ivan")

        assert len(log) == 2
        # Verify persistence
        log2 = PromotionLog(log_file=tmp_path / "manual8.json")
        assert len(log2) == 2
        assert log2.events()[0].source == "operator"
        assert log2.events()[1].source == "operator"

    def test_mixed_automation_and_operator_events(self, tmp_path):
        """Log should correctly interleave automation and operator events."""
        log = PromotionLog(log_file=tmp_path / "manual9.json")
        with patch("merid.promotion_report.get_promotion_log", return_value=log):
            # Simulate automation event
            log.append(PromotionEvent(
                time.time(), "domain", "crypto", "unknown", "blocked", source="automation",
            ))
            # Operator override
            manual_promote("domain", "crypto", reason="override", operator="judy")
            # Another automation event
            log.append(PromotionEvent(
                time.time(), "domain", "crypto", "eligible", "blocked", source="automation",
            ))

        assert len(log) == 3
        sources = [e.source for e in log.events()]
        assert sources == ["automation", "operator", "automation"]
