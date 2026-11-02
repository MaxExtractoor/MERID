"""Failure provenance must survive the client/port/router boundary."""

from unittest.mock import AsyncMock

import pytest

from merid.event_venues.kalshi.order_router import (
    _create_order_outcome_needs_reconciliation,
)
from merid.event_venues.kalshi.port import CreateOrderRequest, CreateOrderResponse
from merid.event_venues.kalshi.venue_client_port import KalshiVenueClientExecutionPort
from merid.resilience.result import OperationResult


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("metadata", "retries", "certainty", "needs_reconciliation"),
    [
        ({}, 0, "pre_submit", False),
        ({"submission_may_have_been_sent": True, "status_code": 400}, 0, "rejected", False),
        ({"submission_may_have_been_sent": True, "status_code": 400}, 1, "unknown", True),
        ({"submission_may_have_been_sent": True, "status_code": 500}, 0, "unknown", True),
        ({"submission_may_have_been_sent": True, "status_code": 503}, 2, "unknown", True),
        ({"submission_may_have_been_sent": True, "status_code": 429}, 0, "unknown", True),
        ({"submission_may_have_been_sent": True}, 0, "unknown", True),
        ({"submission_may_have_been_sent": True, "status_code": 409}, 0, "unknown", False),
    ],
)
async def test_failure_provenance_survives_adapter(
    monkeypatch, metadata, retries, certainty, needs_reconciliation
):
    from decimal import Decimal
    from types import SimpleNamespace

    import merid.monitoring.bankroll_reconciler as bankroll
    import merid.monitoring.trade_attribution_fact_table as attribution

    monkeypatch.setattr(bankroll, "get_bankroll_reconciler", lambda: None)
    monkeypatch.setattr(attribution, "get_trade_attribution_table", lambda: None)
    failure = OperationResult.fail(Exception("test failure"), retries=retries, **metadata)
    client = SimpleNamespace(place_order_result=AsyncMock(return_value=failure))
    port = KalshiVenueClientExecutionPort(client)
    response = await port.create_order(
        CreateOrderRequest(ticker="KXTEST", side="buy", outcome="yes", size=Decimal("1"))
    )
    assert response.status_code == metadata.get("status_code")
    assert response.submission_certainty == certainty
    assert _create_order_outcome_needs_reconciliation(response) is needs_reconciliation


@pytest.mark.asyncio
async def test_empty_success_is_ambiguous(monkeypatch):
    from decimal import Decimal
    from types import SimpleNamespace

    import merid.monitoring.bankroll_reconciler as bankroll
    import merid.monitoring.trade_attribution_fact_table as attribution

    monkeypatch.setattr(bankroll, "get_bankroll_reconciler", lambda: None)
    monkeypatch.setattr(attribution, "get_trade_attribution_table", lambda: None)
    client = SimpleNamespace(place_order_result=AsyncMock(return_value=OperationResult.ok(None)))
    response = await KalshiVenueClientExecutionPort(client).create_order(
        CreateOrderRequest(ticker="KXTEST", side="buy", outcome="yes", size=Decimal("1"))
    )
    assert response.submission_certainty == "unknown"
    assert _create_order_outcome_needs_reconciliation(response)
    assert _create_order_outcome_needs_reconciliation(None)


@pytest.mark.parametrize(
    ("response", "needs_reconciliation"),
    [
        (CreateOrderResponse(success=True), True),
        (CreateOrderResponse(success=True, order_id="order-1"), False),
        (CreateOrderResponse(success=True, status="accepted"), False),
        (CreateOrderResponse(success=True, status="resting"), False),
    ],
)
def test_success_requires_venue_acceptance_evidence(response, needs_reconciliation):
    assert _create_order_outcome_needs_reconciliation(response) is needs_reconciliation
