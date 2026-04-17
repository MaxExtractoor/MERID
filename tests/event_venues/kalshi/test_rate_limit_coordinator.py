"""Tests for the global rate limit coordinator.

The coordinator now uses async-wait semantics: when the window is full,
``acquire_request_permit`` waits until the window resets and then grants
the permit (always returns True).  The old return-False design was never
enforced by callers, making it purely decorative.
"""
import asyncio
import time
import pytest
from merid.event_venues.kalshi.rate_limit_coordinator import (
    RateLimitBudget,
    get_rate_limit_coordinator,
)


@pytest.mark.asyncio
async def test_rest_rate_limit_allows_up_to_max():
    budget = RateLimitBudget(max_requests_per_second=10)
    for _ in range(10):
        assert await budget.acquire_request_permit("rest") is True


@pytest.mark.asyncio
async def test_rest_rate_limit_waits_and_succeeds_over_max():
    """Over-max calls wait for the next window and then return True (never False)."""
    budget = RateLimitBudget(max_requests_per_second=3)
    for _ in range(3):
        await budget.acquire_request_permit("rest")

    # Deny counter should be 0 so far (window not yet full)
    assert budget.get_utilization()["rest_denials"] == 0

    # Backdate window to simulate time passing — next call should proceed instantly
    budget._window_start -= 1.1
    assert await budget.acquire_request_permit("rest") is True


@pytest.mark.asyncio
async def test_ws_rate_limit_allows_up_to_max():
    budget = RateLimitBudget(max_ws_subscriptions_per_second=5)
    for _ in range(5):
        assert await budget.acquire_request_permit("ws") is True


@pytest.mark.asyncio
async def test_ws_rate_limit_waits_and_succeeds_over_max():
    """Over-max WS sub calls wait for the next window and then return True."""
    budget = RateLimitBudget(max_ws_subscriptions_per_second=3)
    for _ in range(3):
        await budget.acquire_request_permit("ws")

    # Backdate window to force immediate reset on next call
    budget._window_start -= 1.1
    assert await budget.acquire_request_permit("ws") is True


@pytest.mark.asyncio
async def test_rest_and_ws_limits_independent():
    """REST and WS counts should not interfere with each other."""
    budget = RateLimitBudget(max_requests_per_second=2, max_ws_subscriptions_per_second=2)
    # Fill REST budget
    await budget.acquire_request_permit("rest")
    await budget.acquire_request_permit("rest")
    # WS budget is separate — still available immediately
    assert await budget.acquire_request_permit("ws") is True
    # REST budget is full — a direct call would wait; check via denial counter instead
    # Backdate to force an immediate grant
    budget._window_start -= 1.1
    assert await budget.acquire_request_permit("rest") is True


@pytest.mark.asyncio
async def test_utilization_metrics():
    budget = RateLimitBudget(max_requests_per_second=10)
    for _ in range(5):
        await budget.acquire_request_permit("rest")
    util = budget.get_utilization()
    assert util["rest_utilization"] == 0.5
    assert util["total_rest_acquires"] == 5
    assert util["rest_denials"] == 0


@pytest.mark.asyncio
async def test_denial_counter_increments_on_window_full():
    """_rest_denials increments when the window is full (even though call eventually succeeds)."""
    budget = RateLimitBudget(max_requests_per_second=1)
    await budget.acquire_request_permit("rest")  # fills the window

    # Manually check: window is full, so next attempt would normally wait.
    # Test the counter path without actually waiting by running a concurrent task
    # that backdates the window after a short delay.
    async def _backdate():
        await asyncio.sleep(0.05)
        budget._window_start -= 1.1

    backdate_task = asyncio.create_task(_backdate())
    result = await budget.acquire_request_permit("rest")  # waits ~50ms then proceeds
    await backdate_task

    assert result is True
    assert budget.get_utilization()["rest_denials"] >= 1


@pytest.mark.asyncio
async def test_window_resets_after_backdating():
    """After backdating _window_start the coordinator immediately grants the next permit."""
    budget = RateLimitBudget(max_requests_per_second=1)
    await budget.acquire_request_permit("rest")  # fills window

    # Simulate 1.1 seconds elapsing
    budget._window_start -= 1.1
    result = await budget.acquire_request_permit("rest")
    assert result is True
    assert budget.get_utilization()["total_rest_acquires"] == 2


def test_singleton():
    c1 = get_rate_limit_coordinator()
    c2 = get_rate_limit_coordinator()
    assert c1 is c2
