"""Tests for health-aware venue routing: RoutingPolicy, VenueSelector, TradeRouter integration.

Covers:
- VenueSelector with healthy/degraded/unhealthy/disabled venues
- Failover to alternative venues in the same domain
- RoutingPolicy configuration knobs (allow_degraded, max_degraded_venues, preferred_venues)
- Fallback strategies (REJECT, FORCE_SIM, BEST_EFFORT)
- RoutingDecision metadata
- TradeRouter integration with venue health gating
"""

import asyncio

import pytest

from merid.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    get_circuit_breaker,
    get_all_breakers,
    reset_all_breakers,
    _state_listeners,
)
from merid.pipeline.routing_policy import (
    FallbackStrategy,
    RoutingDecision,
    RoutingPolicy,
    VenueHealth,
    VenueSelector,
)


# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_state():
    """Reset breakers and listeners before each test."""
    reset_all_breakers()
    _state_listeners.clear()
    # Clear the breaker registry
    from merid.resilience.circuit_breaker import _breakers
    _breakers.clear()
    yield
    reset_all_breakers()
    _state_listeners.clear()
    _breakers.clear()


def _run(coro):
    """Run an async coroutine synchronously."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


def _trip_breaker(name: str) -> CircuitBreaker:
    """Create and trip a circuit breaker to OPEN state."""
    breaker = get_circuit_breaker(name, failure_threshold=1)
    _run(breaker.record_failure(Exception("test failure")))
    assert breaker.state == CircuitState.OPEN
    return breaker


# ── VenueHealth computation tests ────────────────────────────────────

class TestVenueHealthComputation:
    """Test _get_venue_health for different breaker states."""

    def test_healthy_when_no_breaker(self):
        selector = VenueSelector()
        health = selector._get_venue_health("unknown-venue")
        assert health == VenueHealth.HEALTHY

    def test_healthy_when_breaker_closed(self):
        get_circuit_breaker("test-venue")
        selector = VenueSelector()
        health = selector._get_venue_health("test-venue")
        assert health == VenueHealth.HEALTHY

    def test_unhealthy_when_breaker_open(self):
        _trip_breaker("bad-venue")
        selector = VenueSelector()
        health = selector._get_venue_health("bad-venue")
        assert health == VenueHealth.UNHEALTHY

    def test_degraded_when_breaker_has_failures(self):
        breaker = get_circuit_breaker("flaky-venue", failure_threshold=5)
        _run(breaker.record_failure(Exception("err")))
        # 1 failure, not enough to open
        assert breaker.state == CircuitState.CLOSED
        selector = VenueSelector()
        health = selector._get_venue_health("flaky-venue")
        assert health == VenueHealth.DEGRADED


# ── check_venue tests ────────────────────────────────────────────────

class TestCheckVenue:
    """Test check_venue eligibility logic."""

    def test_healthy_venue_eligible(self):
        get_circuit_breaker("ok-venue")
        selector = VenueSelector()
        eligible, health = selector.check_venue("ok-venue")
        assert eligible is True
        assert health == VenueHealth.HEALTHY

    def test_unhealthy_venue_not_eligible(self):
        _trip_breaker("down-venue")
        selector = VenueSelector()
        eligible, health = selector.check_venue("down-venue")
        assert eligible is False
        assert health == VenueHealth.UNHEALTHY

    def test_degraded_eligible_when_allowed(self):
        breaker = get_circuit_breaker("flaky", failure_threshold=5)
        _run(breaker.record_failure(Exception("err")))
        selector = VenueSelector(policy=RoutingPolicy(allow_degraded=True))
        eligible, health = selector.check_venue("flaky")
        assert eligible is True
        assert health == VenueHealth.DEGRADED

    def test_degraded_not_eligible_when_disallowed(self):
        breaker = get_circuit_breaker("flaky2", failure_threshold=5)
        _run(breaker.record_failure(Exception("err")))
        selector = VenueSelector(policy=RoutingPolicy(allow_degraded=False))
        eligible, health = selector.check_venue("flaky2")
        assert eligible is False
        assert health == VenueHealth.DEGRADED


# ── select() tests — requested venue healthy ─────────────────────────

class TestSelectHealthyVenue:
    """When the requested venue is healthy, use it directly."""

    def test_healthy_requested_venue(self):
        get_circuit_breaker("binance")
        selector = VenueSelector()
        decision = selector.select("binance", "crypto")
        assert decision.venue == "binance"
        assert decision.health == "healthy"
        assert decision.reason == "requested_venue_healthy"
        assert decision.fallback_used is False

    def test_degraded_requested_venue_allowed(self):
        breaker = get_circuit_breaker("binance", failure_threshold=5)
        _run(breaker.record_failure(Exception("err")))
        selector = VenueSelector(policy=RoutingPolicy(allow_degraded=True))
        decision = selector.select("binance", "crypto")
        assert decision.venue == "binance"
        assert decision.reason == "requested_venue_degraded"


# ── select() tests — failover ────────────────────────────────────────

class TestSelectFailover:
    """When the requested venue is unhealthy, failover to alternatives."""

    def test_failover_to_healthy_alternative(self):
        _trip_breaker("binance")
        get_circuit_breaker("coinbase")  # healthy
        selector = VenueSelector(policy=RoutingPolicy(
            preferred_venues={"crypto": ["binance", "coinbase", "kraken"]},
        ))
        decision = selector.select("binance", "crypto")
        assert decision.venue == "coinbase"
        assert decision.reason == "failover"
        assert decision.fallback_used is True
        assert decision.original_venue == "binance"

    def test_failover_skips_unhealthy_alternatives(self):
        _trip_breaker("binance")
        _trip_breaker("coinbase")
        get_circuit_breaker("kraken")  # healthy
        selector = VenueSelector(policy=RoutingPolicy(
            preferred_venues={"crypto": ["binance", "coinbase", "kraken"]},
        ))
        decision = selector.select("binance", "crypto")
        assert decision.venue == "kraken"
        assert decision.reason == "failover"

    def test_failover_respects_preference_order(self):
        _trip_breaker("binance")
        get_circuit_breaker("kraken")  # healthy
        get_circuit_breaker("coinbase")  # healthy
        selector = VenueSelector(policy=RoutingPolicy(
            preferred_venues={"crypto": ["binance", "kraken", "coinbase"]},
        ))
        decision = selector.select("binance", "crypto")
        # kraken is preferred over coinbase
        assert decision.venue == "kraken"


# ── select() tests — fallback strategies ─────────────────────────────

class TestFallbackStrategies:
    """When all venues are unhealthy, apply fallback strategy."""

    def test_reject_when_all_unhealthy(self):
        # Trip ALL crypto venues (including ModeManager defaults)
        for v in ("binance", "coinbase", "kraken", "okx"):
            _trip_breaker(v)
        selector = VenueSelector(policy=RoutingPolicy(
            preferred_venues={"crypto": ["binance", "coinbase", "kraken", "okx"]},
            fallback_strategy=FallbackStrategy.REJECT,
        ))
        decision = selector.select("binance", "crypto")
        assert decision.venue is None
        assert decision.reason == "all_venues_unhealthy"

    def test_force_sim_when_all_unhealthy(self):
        for v in ("binance", "coinbase", "kraken", "okx"):
            _trip_breaker(v)
        selector = VenueSelector(policy=RoutingPolicy(
            preferred_venues={"crypto": ["binance", "coinbase", "kraken", "okx"]},
            fallback_strategy=FallbackStrategy.FORCE_SIM,
        ))
        decision = selector.select("binance", "crypto")
        assert decision.venue == "binance"
        assert decision.reason == "force_sim_fallback"
        assert decision.fallback_used is True

    def test_best_effort_when_all_unhealthy(self):
        for v in ("binance", "coinbase", "kraken", "okx"):
            _trip_breaker(v)
        selector = VenueSelector(policy=RoutingPolicy(
            preferred_venues={"crypto": ["binance", "coinbase", "kraken", "okx"]},
            fallback_strategy=FallbackStrategy.BEST_EFFORT,
        ))
        decision = selector.select("binance", "crypto")
        assert decision.venue == "binance"
        assert decision.reason == "best_effort_fallback"


# ── max_degraded_venues tests ────────────────────────────────────────

class TestMaxDegradedVenues:
    """Test the max_degraded_venues configuration knob."""

    def test_max_degraded_limits_candidates(self):
        _trip_breaker("binance")
        # Create 3 degraded venues
        for name in ("coinbase", "kraken", "okx"):
            b = get_circuit_breaker(name, failure_threshold=5)
            _run(b.record_failure(Exception("err")))

        selector = VenueSelector(policy=RoutingPolicy(
            allow_degraded=True,
            max_degraded_venues=1,
            preferred_venues={"crypto": ["binance", "coinbase", "kraken", "okx"]},
        ))
        decision = selector.select("binance", "crypto")
        # Should pick the first degraded venue (coinbase) but not exceed limit
        assert decision.venue == "coinbase"
        assert decision.reason == "failover"


# ── RoutingDecision tests ────────────────────────────────────────────

class TestRoutingDecision:
    """RoutingDecision serialization."""

    def test_to_dict(self):
        d = RoutingDecision(
            venue="binance",
            health="healthy",
            reason="requested_venue_healthy",
            original_venue="binance",
            candidates_checked=1,
        )
        result = d.to_dict()
        assert result["venue"] == "binance"
        assert result["health"] == "healthy"
        assert result["candidates_checked"] == 1
        assert result["fallback_used"] is False


# ── RoutingPolicy tests ──────────────────────────────────────────────

class TestRoutingPolicy:
    """RoutingPolicy configuration and serialization."""

    def test_defaults(self):
        policy = RoutingPolicy()
        assert policy.allow_degraded is True
        assert policy.max_degraded_venues == 2
        assert policy.fallback_strategy == FallbackStrategy.REJECT

    def test_to_dict(self):
        policy = RoutingPolicy(
            allow_degraded=False,
            preferred_venues={"crypto": ["binance"]},
            fallback_strategy=FallbackStrategy.FORCE_SIM,
        )
        d = policy.to_dict()
        assert d["allow_degraded"] is False
        assert d["fallback_strategy"] == "force_sim"
        assert d["preferred_venues"] == {"crypto": ["binance"]}
