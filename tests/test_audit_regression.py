"""Audit regression tests for ExecutionGuard.

Bug-05: ExecutionGuard.is_domain_promoted() was failing CLOSED (returning False)
when the promotion report had not yet loaded, even in paper mode.  The correct
behaviour is to fail OPEN (return True) when ``_promotion_eligible_domains`` is
None — giving the first report time to populate within the grace period.

These tests also verify the three attributes added to close the gap:
  _init_ts                  — guard initialisation timestamp
  _promotion_report_grace_s — grace period before absent-report blocking
  _promotion_refresh_lock   — threading.Lock protecting concurrent refreshes
"""

from __future__ import annotations

import threading
import time

import pytest

from merid.execution_guard import ExecutionGuard


# ── Helper ───────────────────────────────────────────────────────────────────

def _fresh_guard() -> ExecutionGuard:
    """Create a fresh ExecutionGuard with promotion state reset to *no report*."""
    g = ExecutionGuard()
    g._promotion_eligible_domains = None
    g._promotion_blocked_agents = None
    g._promotion_report_ts = 0.0
    assert hasattr(g, "_init_ts"), "ExecutionGuard missing _init_ts"
    assert hasattr(g, "_promotion_refresh_lock"), "ExecutionGuard missing _promotion_refresh_lock"
    assert hasattr(g, "_promotion_report_grace_s"), "ExecutionGuard missing _promotion_report_grace_s"
    return g


# ── Bug-05 regression ────────────────────────────────────────────────────────

class TestBug5ExecutionGuardPromotionFailClosed:
    """Regression: guard must fail OPEN (allow) when promotion report is missing."""

    def test_fails_open_when_report_missing_and_paper_mode(self):
        """With no promotion report loaded, is_domain_promoted() must return True."""
        guard = _fresh_guard()
        assert guard._promotion_eligible_domains is None
        # Enforcement enabled; no report → fail-open (True)
        assert guard.is_domain_promoted("prediction") is True
        assert guard.is_domain_promoted("crypto") is True
        assert guard.is_domain_promoted("equity") is True

    def test_fails_open_for_agent_when_report_missing(self):
        """is_agent_promoted() must also fail-open when no report is loaded."""
        guard = _fresh_guard()
        assert guard._promotion_blocked_agents is None
        assert guard.is_agent_promoted("agent-01") is True
        assert guard.is_agent_promoted("agent-research") is True

    def test_blocks_domain_when_report_loaded_and_domain_absent(self):
        """Once a report is loaded, unlisted domains ARE blocked."""
        guard = _fresh_guard()
        guard._promotion_eligible_domains = {"prediction"}
        assert guard.is_domain_promoted("prediction") is True
        assert guard.is_domain_promoted("equity") is False

    def test_blocks_agent_when_report_loaded_and_agent_in_blocked_set(self):
        """Once a report is loaded, agents in the blocked set ARE blocked."""
        guard = _fresh_guard()
        guard._promotion_blocked_agents = {"bad-agent-01"}
        assert guard.is_agent_promoted("good-agent") is True
        assert guard.is_agent_promoted("bad-agent-01") is False


# ── New attribute presence tests ─────────────────────────────────────────────

class TestExecutionGuardNewAttributes:
    """Verify the three new attributes are present and have sensible defaults."""

    def test_init_ts_is_recent(self):
        before = time.time()
        guard = ExecutionGuard()
        after = time.time()
        assert hasattr(guard, "_init_ts")
        assert before <= guard._init_ts <= after

    def test_promotion_report_grace_s_is_positive(self):
        guard = ExecutionGuard()
        assert hasattr(guard, "_promotion_report_grace_s")
        assert guard._promotion_report_grace_s > 0

    def test_promotion_refresh_lock_is_threading_lock(self):
        guard = ExecutionGuard()
        assert hasattr(guard, "_promotion_refresh_lock")
        lock = guard._promotion_refresh_lock
        # Must be acquirable (i.e. it is a real lock)
        acquired = lock.acquire(blocking=False)
        assert acquired, "Lock should be acquirable (not already held)"
        lock.release()

    def test_fresh_guard_reset_attributes(self):
        guard = _fresh_guard()
        assert guard._promotion_eligible_domains is None
        assert guard._promotion_blocked_agents is None
        assert guard._promotion_report_ts == 0.0
