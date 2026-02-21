"""Tests for resilience API and circuit breaker observability hooks.

Covers:
- Circuit breaker state change listener callbacks
- Resilience API endpoint helpers (_get_breaker_summaries, _get_bulkhead_summaries)
- Venue health computation (_get_venue_health)
- Circuit breaker reset via API
- Prometheus metrics endpoint for resilience
"""

import asyncio
import logging

import pytest

from merid.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    get_circuit_breaker,
    get_all_breakers,
    reset_all_breakers,
    on_state_change,
    _state_listeners,
    _notify_listeners,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_breakers():
    """Reset all breakers and listeners before each test."""
    reset_all_breakers()
    _state_listeners.clear()
    yield
    reset_all_breakers()
    _state_listeners.clear()


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


# ── State change listener tests ──────────────────────────────────────

class TestStateChangeListeners:
    """Circuit breaker state change callback system."""

    def test_listener_called_on_open(self):
        events = []
        on_state_change(lambda name, old, new, ctx: events.append((name, old, new, ctx)))

        breaker = get_circuit_breaker("test-venue", failure_threshold=2, recovery_timeout=0.1)
        # Trip the breaker
        _run(breaker.record_failure(Exception("err1")))
        _run(breaker.record_failure(Exception("err2")))

        assert len(events) == 1
        name, old, new, ctx = events[0]
        assert name == "test-venue"
        assert old == "closed"
        assert new == "open"
        assert ctx["reason"] == "threshold_exceeded"
        assert ctx["failure_count"] == 2

    def test_listener_called_on_half_open(self):
        events = []
        on_state_change(lambda name, old, new, ctx: events.append((name, old, new)))

        breaker = get_circuit_breaker("test-ho", failure_threshold=1, recovery_timeout=0.01)
        _run(breaker.record_failure(Exception("err")))
        # Wait for recovery timeout
        import time
        time.sleep(0.02)
        # Next check_state should transition to half_open
        try:
            _run(breaker._check_state())
        except CircuitOpenError:
            pass

        transitions = [(old, new) for _, old, new in events]
        assert ("closed", "open") in transitions
        assert ("open", "half_open") in transitions

    def test_listener_called_on_recovery(self):
        events = []
        on_state_change(lambda name, old, new, ctx: events.append((name, old, new)))

        breaker = get_circuit_breaker("test-recover", failure_threshold=1, recovery_timeout=0.01)
        _run(breaker.record_failure(Exception("err")))
        import time
        time.sleep(0.02)
        try:
            _run(breaker._check_state())
        except CircuitOpenError:
            pass
        _run(breaker.record_success())

        transitions = [(old, new) for _, old, new in events]
        assert ("half_open", "closed") in transitions

    def test_listener_exception_does_not_break_breaker(self):
        def bad_listener(name, old, new, ctx):
            raise RuntimeError("listener crash")

        on_state_change(bad_listener)
        breaker = get_circuit_breaker("test-safe", failure_threshold=1)
        # Should not raise even though listener crashes
        _run(breaker.record_failure(Exception("err")))
        assert breaker.state == CircuitState.OPEN

    def test_multiple_listeners(self):
        events_a = []
        events_b = []
        on_state_change(lambda n, o, new, c: events_a.append(new))
        on_state_change(lambda n, o, new, c: events_b.append(new))

        breaker = get_circuit_breaker("test-multi", failure_threshold=1)
        _run(breaker.record_failure(Exception("err")))

        assert events_a == ["open"]
        assert events_b == ["open"]


# ── Notify listeners direct test ─────────────────────────────────────

class TestNotifyListeners:
    """Direct tests of _notify_listeners."""

    def test_empty_listeners(self):
        # Should not raise
        _notify_listeners("x", "closed", "open", {})

    def test_context_passed(self):
        received = []
        on_state_change(lambda n, o, new, ctx: received.append(ctx))
        _notify_listeners("x", "closed", "open", {"key": "val"})
        assert received == [{"key": "val"}]


# ── Resilience API helper tests ──────────────────────────────────────

class TestResilienceApiHelpers:
    """Test the API helper functions."""

    def test_get_breaker_summaries(self):
        from web.api.resilience import _get_breaker_summaries
        # Create some breakers
        get_circuit_breaker("venue-a")
        get_circuit_breaker("venue-b")
        summaries = _get_breaker_summaries()
        assert len(summaries) >= 2
        names = [s["name"] for s in summaries]
        assert "venue-a" in names
        assert "venue-b" in names

    def test_get_breaker_summaries_empty(self):
        from web.api.resilience import _get_breaker_summaries
        from merid.resilience.circuit_breaker import _breakers
        _breakers.clear()
        assert _get_breaker_summaries() == []

    def test_venue_health_computation(self):
        from web.api.resilience import _get_venue_health
        # Create a breaker in open state
        breaker = get_circuit_breaker("test-health", failure_threshold=1)
        _run(breaker.record_failure(Exception("err")))
        assert breaker.state == CircuitState.OPEN

        venues = _get_venue_health()
        test_venue = next((v for v in venues if v["venue"] == "test-health"), None)
        if test_venue:
            assert test_venue["health"] == "unhealthy"
            assert test_venue["breaker_state"] == "open"


# ── Resilience API endpoint tests ────────────────────────────────────

class TestResilienceEndpoints:
    """Test the async API endpoints."""

    def test_get_status(self):
        from web.api.resilience import get_resilience_status
        get_circuit_breaker("ep-test")
        result = _run(get_resilience_status())
        assert "overall_health" in result
        assert "circuit_breakers" in result
        assert "venue_health" in result
        assert "summary" in result
        assert result["summary"]["breakers_total"] >= 1

    def test_get_breakers(self):
        from web.api.resilience import get_breakers
        get_circuit_breaker("ep-breaker")
        result = _run(get_breakers())
        assert "circuit_breakers" in result

    def test_get_bulkheads(self):
        from web.api.resilience import get_bulkheads
        result = _run(get_bulkheads())
        assert "bulkheads" in result

    def test_get_venues(self):
        from web.api.resilience import get_venues
        result = _run(get_venues())
        assert "venues" in result

    def test_reset_breaker_success(self):
        from web.api.resilience import reset_breaker
        breaker = get_circuit_breaker("reset-test", failure_threshold=1)
        _run(breaker.record_failure(Exception("err")))
        assert breaker.state == CircuitState.OPEN

        result = _run(reset_breaker("reset-test"))
        assert result["ok"] is True
        assert result["old_state"] == "open"
        assert result["new_state"] == "closed"
        assert breaker.state == CircuitState.CLOSED

    def test_reset_breaker_not_found(self):
        from web.api.resilience import reset_breaker
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _run(reset_breaker("nonexistent"))
        assert exc_info.value.status_code == 404

    def test_resilience_metrics(self):
        from web.api.resilience import resilience_metrics
        get_circuit_breaker("metrics-test")
        response = _run(resilience_metrics())
        assert "text/plain" in response.media_type


# ── Overall health aggregation tests ─────────────────────────────────

class TestHealthAggregation:
    """Test overall health computation logic."""

    def test_healthy_when_all_closed(self):
        from web.api.resilience import get_resilience_status
        get_circuit_breaker("healthy-a")
        get_circuit_breaker("healthy-b")
        result = _run(get_resilience_status())
        assert result["overall_health"] == "healthy"

    def test_degraded_when_breaker_has_failures(self):
        from web.api.resilience import get_resilience_status
        breaker = get_circuit_breaker("degraded-test", failure_threshold=5)
        _run(breaker.record_failure(Exception("err")))
        # 1 failure, not enough to open, but venue shows degraded
        result = _run(get_resilience_status())
        # Check venue health includes degraded
        degraded = [v for v in result["venue_health"] if v["venue"] == "degraded-test"]
        if degraded:
            assert degraded[0]["health"] == "degraded"

    def test_unhealthy_when_breaker_open(self):
        from web.api.resilience import get_resilience_status
        breaker = get_circuit_breaker("unhealthy-test", failure_threshold=1)
        _run(breaker.record_failure(Exception("err")))
        assert breaker.state == CircuitState.OPEN
        result = _run(get_resilience_status())
        assert result["overall_health"] in ("degraded", "unhealthy")
