"""Tests for ExecutionSubscriber circuit breaker integration."""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from merid.circuit_breaker import _breakers, CircuitState


@pytest.fixture(autouse=True)
def clean_breakers():
    """Remove subscriber CB between tests."""
    _breakers.pop("kalshi:execution_subscriber", None)
    yield
    _breakers.pop("kalshi:execution_subscriber", None)


@pytest.mark.asyncio
async def test_consecutive_failures_trip_circuit_breaker():
    """After FAILURE_THRESHOLD consecutive routing failures, CB must be OPEN."""
    from merid.swarm.execution_subscriber import ExecutionSubscriber
    from merid.circuit_breaker import get_circuit_breaker

    sub = ExecutionSubscriber()

    with patch.object(sub, "_route_to_execution", side_effect=RuntimeError("no route")):
        for _ in range(5):
            await sub._handle_decision({
                "decision_id": "d1",
                "market_id": "KXBTCD",
                "action": "buy",
                "side": "yes",
                "size_contracts": 1,
                "risk_approved": True,
            })

    cb = get_circuit_breaker("kalshi:execution_subscriber")
    assert cb.state == CircuitState.OPEN, f"Expected OPEN, got {cb.state}"


@pytest.mark.asyncio
async def test_open_cb_skips_routing():
    """When CB is OPEN, _handle_decision must skip routing without calling _route_to_execution."""
    from merid.swarm.execution_subscriber import ExecutionSubscriber
    from merid.circuit_breaker import get_circuit_breaker

    sub = ExecutionSubscriber()
    cb = get_circuit_breaker("kalshi:execution_subscriber", failure_threshold=1, recovery_timeout=3600.0)
    cb._on_failure()  # Force OPEN

    called = []

    async def fake_route(data):
        called.append(data)

    with patch.object(sub, "_route_to_execution", side_effect=fake_route):
        await sub._handle_decision({
            "decision_id": "d2",
            "market_id": "KXBTCD",
            "action": "buy",
            "side": "yes",
            "size_contracts": 1,
            "risk_approved": True,
        })

    assert called == [], "Route must not be called when CB is OPEN"


@pytest.mark.asyncio
async def test_success_resets_failure_counter():
    """A successful route after failures does not leave the CB in OPEN state."""
    from merid.swarm.execution_subscriber import ExecutionSubscriber
    from merid.circuit_breaker import get_circuit_breaker

    sub = ExecutionSubscriber()
    call_count = [0]

    async def sometimes_fail(data):
        call_count[0] += 1
        if call_count[0] < 3:
            raise RuntimeError("transient")

    with patch.object(sub, "_route_to_execution", side_effect=sometimes_fail):
        for _ in range(4):
            await sub._handle_decision({
                "decision_id": "d3",
                "market_id": "KXBTCD",
                "action": "buy",
                "side": "yes",
                "size_contracts": 1,
                "risk_approved": True,
            })

    # 2 failures (below threshold=5) + 2 successes — CB should be CLOSED
    cb = get_circuit_breaker("kalshi:execution_subscriber")
    assert cb.state == CircuitState.CLOSED, f"CB should be CLOSED after recovery, got {cb.state}"


@pytest.mark.asyncio
async def test_stale_decision_gets_price_stale_flag():
    """Decisions older than MAX_DECISION_AGE_S must be flagged _price_stale=True."""
    import time as _time
    from merid.swarm.execution_subscriber import ExecutionSubscriber

    sub = ExecutionSubscriber()
    routed_data = []

    async def capture(data):
        routed_data.append(data.copy())

    with patch.object(sub, "_route_to_execution", side_effect=capture):
        stale_decision = {
            "decision_id": "stale-1",
            "market_id": "KXBTCD",
            "action": "buy",
            "side": "yes",
            "size_contracts": 2,
            "limit_price_cents": 55,
            "risk_approved": True,
            "_created_at": _time.time() - 30.0,  # 30 seconds old — beyond MAX_DECISION_AGE_S
        }
        await sub._handle_decision(stale_decision)

    assert len(routed_data) == 1
    assert routed_data[0].get("_price_stale") is True, \
        f"Expected _price_stale=True, got: {routed_data[0]}"


@pytest.mark.asyncio
async def test_fresh_decision_no_stale_flag():
    """Fresh decisions (just created) must NOT have _price_stale set."""
    import time as _time
    from merid.swarm.execution_subscriber import ExecutionSubscriber

    sub = ExecutionSubscriber()
    routed_data = []

    async def capture(data):
        routed_data.append(data.copy())

    with patch.object(sub, "_route_to_execution", side_effect=capture):
        fresh_decision = {
            "decision_id": "fresh-1",
            "market_id": "KXBTCD",
            "action": "buy",
            "side": "yes",
            "size_contracts": 2,
            "limit_price_cents": 55,
            "risk_approved": True,
            "_created_at": _time.time(),  # just now
        }
        await sub._handle_decision(fresh_decision)

    assert len(routed_data) == 1
    assert not routed_data[0].get("_price_stale"), \
        f"Fresh decision must not be stale: {routed_data[0]}"


@pytest.mark.asyncio
async def test_decision_without_created_at_not_flagged():
    """Decisions with no _created_at (legacy) must route normally without _price_stale."""
    from merid.swarm.execution_subscriber import ExecutionSubscriber

    sub = ExecutionSubscriber()
    routed_data = []

    async def capture(data):
        routed_data.append(data.copy())

    with patch.object(sub, "_route_to_execution", side_effect=capture):
        await sub._handle_decision({
            "decision_id": "legacy-1",
            "market_id": "KXBTCD",
            "action": "buy",
            "side": "yes",
            "size_contracts": 1,
            "risk_approved": True,
            # no _created_at
        })

    assert len(routed_data) == 1
    assert not routed_data[0].get("_price_stale"), \
        "Decision without _created_at must not be flagged stale"
