"""Filtered position snapshots must not claim partial pages are complete."""

from unittest.mock import AsyncMock

import pytest

from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.resilience.result import OperationResult


@pytest.mark.asyncio
async def test_second_page_failure_is_not_empty_success():
    client = object.__new__(KalshiVenueClient)
    client._request_with_resilience = AsyncMock(side_effect=[
        OperationResult.ok({"market_positions": [{"ticker": "KXTEST"}], "cursor": "next"}),
        OperationResult.fail(RuntimeError("unavailable")),
    ])
    result = await client.get_positions_with_filters({"market_ticker": "KXTEST"})
    assert not result.success
    assert result.metadata["truncated"] is True


@pytest.mark.asyncio
async def test_page_limit_is_not_success():
    client = object.__new__(KalshiVenueClient)
    client._request_with_resilience = AsyncMock(return_value=OperationResult.ok({
        "market_positions": [], "cursor": "still-more",
    }))
    result = await client.get_positions_with_filters()
    assert not result.success
    assert result.metadata["truncated"] is True
    assert client._request_with_resilience.await_count == 50


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, {}, {"market_positions": None}])
async def test_malformed_position_page_is_not_success(data):
    client = object.__new__(KalshiVenueClient)
    client._request_with_resilience = AsyncMock(return_value=OperationResult.ok(data))
    result = await client.get_positions_with_filters()
    assert not result.success


@pytest.mark.asyncio
async def test_complete_pages_are_combined():
    client = object.__new__(KalshiVenueClient)
    client._request_with_resilience = AsyncMock(side_effect=[
        OperationResult.ok({"market_positions": [{"ticker": "KX1"}], "cursor": "next"}),
        OperationResult.ok({"market_positions": [{"ticker": "KX2"}], "cursor": ""}),
    ])
    result = await client.get_positions_with_filters()
    assert result.success
    assert [row["ticker"] for row in result.data["market_positions"]] == ["KX1", "KX2"]
