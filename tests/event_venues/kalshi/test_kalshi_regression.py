"""Regression tests for Kalshi client NoneType.request bug."""

import pytest
import respx
from httpx import Response
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.models import KalshiConfig

@respx.mock
@pytest.mark.asyncio
async def test_ensure_client_initialization_regression():
    """Verify that _ensure_client always returns a valid client even if initially None."""
    config = KalshiConfig(
        email="test@example.com",
        password="test_password",
        use_demo=True
    )
    client = KalshiVenueClient(config)
    
    # Force client to None (simulate uninitialized state)
    client._http_client = None
    
    # Mock login
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    
    # This should not raise AttributeError: 'NoneType' object has no attribute 'request'
    # because _ensure_client should initialize it
    http_client = await client._ensure_client()
    assert http_client is not None
    assert not http_client.is_closed

@respx.mock
@pytest.mark.asyncio
async def test_request_with_resilience_initializes_client():
    """Verify that _request_with_resilience initializes the client if it's None."""
    config = KalshiConfig(
        email="test@example.com",
        password="test_password",
        use_demo=True
    )
    client = KalshiVenueClient(config)
    client._http_client = None
    
    # Mock login and markets
    respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
        return_value=Response(200, json={"token": "test", "member_id": "123"})
    )
    respx.get("https://demo-api.kalshi.co/trade-api/v2/markets").mock(
        return_value=Response(200, json={"markets": []})
    )
    
    # This call uses _request_with_resilience internally
    result = await client.list_markets_result()
    assert result.success
    assert client._http_client is not None
