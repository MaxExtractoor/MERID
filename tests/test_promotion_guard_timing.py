"""Timing-robustness tests for ExecutionGuard promotion gate.

Exercises the four scenarios described in the problem statement:
  1. Delayed report — guard within grace window → fail-open.
  2. Missing report past grace window → still fail-open (warn, don't block).
  3. Stale report within grace window → fail-open.
  4. Stale report outside grace window → still fail-open (warn).
  5. Concurrent refresh calls → lock prevents head-of-line blocking.
  6. Successful sync → domain membership is enforced after grace expires.
  7. Partial failure recovery — sync fails, previous state preserved.
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from merid.execution_guard import ExecutionGuard


# ── Helpers ───────────────────────────────────────────────────────────────────

def _guard_at_age(age_s: float, *, domains: set | None = None, report_ts: float = 0.0) -> ExecutionGuard:
    """Return a guard whose _init_ts is `age_s` seconds in the past."""
    g = ExecutionGuard()
    g._init_ts = time.time() - age_s
    g._promotion_eligible_domains = domains
    g._promotion_blocked_agents = set()
    g._promotion_report_ts = report_ts
    return g


# ── Scenario 1: Delayed first report within grace window ─────────────────────

class TestGraceWindowNoReport:
    """Guard within grace window with no report ever loaded → always allow."""

    def test_allows_any_domain_within_grace(self):
        guard = _guard_at_age(0.0, domains=None)
        assert guard.is_domain_promoted("crypto") is True
        assert guard.is_domain_promoted("prediction") is True
        assert guard.is_domain_promoted("equity") is True

    def test_allows_near_end_of_grace(self):
        """Still allows at 299s (grace=300s)."""
        guard = _guard_at_age(299.0, domains=None)
        assert guard.is_domain_promoted("prediction") is True

    def test_allows_after_grace_too_when_no_report(self):
        """No report loaded at all — always fail-open regardless of age."""
        guard = _guard_at_age(3600.0, domains=None)  # 1 hour old
        assert guard.is_domain_promoted("prediction") is True

    def test_agent_check_also_fails_open_within_grace(self):
        guard = _guard_at_age(10.0)
        guard._promotion_blocked_agents = None
        assert guard.is_agent_promoted("agent-x") is True

    def test_agent_check_fails_open_within_grace_even_if_blocked_set_exists(self):
        guard = _guard_at_age(10.0)
        guard._promotion_blocked_agents = {"agent-x"}  # blocked set loaded
        # Still within grace → fail-open
        assert guard.is_agent_promoted("agent-x") is True


# ── Scenario 2: Stale report within grace window ──────────────────────────────

class TestStaleReportInGrace:
    """Report loaded but stale; guard still within grace → fail-open."""

    def test_stale_report_within_grace_allows(self):
        stale_ts = time.time() - 700.0  # report 700s old (>600s threshold)
        guard = _guard_at_age(
            100.0,  # guard 100s old, within 300s grace
            domains={"prediction"},
            report_ts=stale_ts,
        )
        # Even though report doesn't list "crypto", stale+grace → allow
        assert guard.is_domain_promoted("crypto") is True
        assert guard.is_domain_promoted("prediction") is True

    def test_fresh_report_within_grace_uses_domain_membership(self):
        """Fresh report is loaded and guard is within grace → enforce domain list."""
        fresh_ts = time.time() - 60.0  # report 60s old (fresh)
        guard = _guard_at_age(
            100.0,
            domains={"prediction"},
            report_ts=fresh_ts,
        )
        # Report is fresh → domain list is enforced
        assert guard.is_domain_promoted("prediction") is True
        assert guard.is_domain_promoted("equity") is False


# ── Scenario 3: Stale report outside grace window ─────────────────────────────

class TestStaleReportOutsideGrace:
    """Report stale; guard has lived longer than grace window → fail-open with warning."""

    def test_stale_report_outside_grace_still_allows(self):
        """Stale report outside grace → fail-open (don't hard-block)."""
        stale_ts = time.time() - 700.0
        guard = _guard_at_age(
            3600.0,  # guard 1h old, well outside 300s grace
            domains={"prediction"},
            report_ts=stale_ts,
        )
        # Stale → fail-open regardless of domain list
        assert guard.is_domain_promoted("crypto") is True

    def test_fresh_report_outside_grace_enforces_membership(self):
        """Fresh report, guard past grace → domain list IS enforced."""
        fresh_ts = time.time() - 30.0
        guard = _guard_at_age(
            3600.0,
            domains={"prediction"},
            report_ts=fresh_ts,
        )
        assert guard.is_domain_promoted("prediction") is True
        assert guard.is_domain_promoted("equity") is False
        assert guard.is_domain_promoted("crypto") is False


# ── Scenario 4: Concurrent refresh — lock prevents head-of-line blocking ─────

class TestPromotionRefreshLock:
    """sync_promotion_report is non-blocking when a refresh is already running."""

    def test_concurrent_sync_skips_gracefully(self):
        """Second sync call while first holds the lock returns immediately."""
        guard = ExecutionGuard()

        # Simulate a long-running sync by holding the lock externally.
        guard._promotion_refresh_lock.acquire()
        try:
            start = time.monotonic()
            guard.sync_promotion_report()  # Should return immediately (non-blocking)
            elapsed = time.monotonic() - start
            assert elapsed < 0.5, (
                f"sync_promotion_report blocked for {elapsed:.2f}s — "
                "should have skipped immediately when lock is held"
            )
        finally:
            guard._promotion_refresh_lock.release()

    def test_lock_released_after_successful_sync(self):
        """Lock must be released after a successful sync so the next call can proceed."""
        guard = ExecutionGuard()
        fake_report = MagicMock()
        fake_report.eligible_domains = ["prediction"]
        fake_report.blocked_agents = []
        fake_report.timestamp = time.time()

        with patch(
            "merid.execution_guard.ExecutionGuard.sync_promotion_report",
            wraps=guard.sync_promotion_report,
        ):
            with patch(
                "merid.promotion_report.get_cached_promotion_report",
                return_value=fake_report,
            ):
                guard.sync_promotion_report()

        # Lock must be available after sync
        acquired = guard._promotion_refresh_lock.acquire(blocking=False)
        assert acquired, "Lock not released after sync_promotion_report()"
        guard._promotion_refresh_lock.release()

    def test_lock_released_after_failed_sync(self):
        """Lock must be released even when the sync raises an exception."""
        guard = ExecutionGuard()

        with patch(
            "merid.promotion_report.get_cached_promotion_report",
            side_effect=RuntimeError("pipeline down"),
        ):
            guard.sync_promotion_report()  # Should swallow the error

        # Lock must still be available
        acquired = guard._promotion_refresh_lock.acquire(blocking=False)
        assert acquired, "Lock not released after failed sync_promotion_report()"
        guard._promotion_refresh_lock.release()

    def test_parallel_threads_dont_deadlock(self):
        """Many concurrent threads calling sync_promotion_report don't deadlock."""
        guard = ExecutionGuard()
        fake_report = MagicMock()
        fake_report.eligible_domains = ["prediction"]
        fake_report.blocked_agents = []
        fake_report.timestamp = time.time()

        errors = []

        def _do_sync():
            try:
                with patch(
                    "merid.promotion_report.get_cached_promotion_report",
                    return_value=fake_report,
                ):
                    guard.sync_promotion_report()
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_do_sync) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert not errors, f"Thread errors: {errors}"
        # Lock must be free after all threads complete
        acquired = guard._promotion_refresh_lock.acquire(blocking=False)
        assert acquired
        guard._promotion_refresh_lock.release()


# ── Scenario 5: Partial failure recovery ─────────────────────────────────────

class TestPartialFailureRecovery:
    """sync_promotion_report failure leaves previous state intact."""

    def test_sync_failure_preserves_previous_state(self):
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = {"prediction", "crypto"}
        guard._promotion_blocked_agents = set()
        guard._promotion_report_ts = time.time() - 60.0

        with patch(
            "merid.promotion_report.get_cached_promotion_report",
            side_effect=RuntimeError("pipeline down"),
        ):
            guard.sync_promotion_report()

        # Previous state must be unchanged
        assert guard._promotion_eligible_domains == {"prediction", "crypto"}

    def test_sync_failure_does_not_set_domains_to_none(self):
        """After a successful sync, a failing sync does not reset to None."""
        guard = ExecutionGuard()
        guard._promotion_eligible_domains = {"prediction"}
        guard._promotion_report_ts = time.time() - 30.0

        with patch(
            "merid.promotion_report.get_cached_promotion_report",
            side_effect=ConnectionError("timeout"),
        ):
            guard.sync_promotion_report()

        assert guard._promotion_eligible_domains is not None

    def test_grace_helper_method(self):
        """_promotion_within_grace() boundary conditions."""
        guard = ExecutionGuard()
        guard._promotion_report_grace_s = 60.0
        guard._init_ts = time.time() - 30.0
        assert guard._promotion_within_grace() is True

        guard._init_ts = time.time() - 120.0
        assert guard._promotion_within_grace() is False

    def test_stale_helper_method(self):
        """_promotion_report_stale() boundary conditions."""
        guard = ExecutionGuard()
        guard._promotion_report_ts = time.time() - 50.0
        assert guard._promotion_report_stale(max_age_s=60.0) is False

        guard._promotion_report_ts = time.time() - 700.0
        assert guard._promotion_report_stale(max_age_s=600.0) is True

        guard._promotion_report_ts = 0.0
        assert guard._promotion_report_stale() is True
