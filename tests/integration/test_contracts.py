"""Contract tests for MERID broker integrations using Pact.

TODO: Pact contract harness not yet wired in MERID
These tests are currently skipped until Pact is properly configured.
See: https://docs.pact.io/implementation_guides/python for setup instructions.
"""

import pytest


@pytest.mark.skip(reason="Pact contract harness not yet wired in MERID")
@pytest.mark.contract
class TestKalshiContract:
    """Consumer-driven contract tests for Kalshi API."""
    
    @pytest.mark.asyncio
    async def test_get_markets(self):
        """Contract test for Kalshi markets endpoint."""
        # TODO: Implement when Pact is configured
        pass
    
    @pytest.mark.asyncio
    async def test_place_order(self):
        """Contract test for Kalshi order placement."""
        # TODO: Implement when Pact is configured
        pass
    
    @pytest.mark.asyncio
    async def test_websocket_event_stream(self):
        """Contract test for Kalshi WebSocket events."""
        # TODO: Implement when Pact is configured
        pass


@pytest.mark.skip(reason="Pact contract harness not yet wired in MERID")
@pytest.mark.contract
class TestAlpacaContract:
    """Consumer-driven contract tests for Alpaca API."""
    
    @pytest.mark.asyncio
    async def test_get_account(self):
        """Contract test for Alpaca account endpoint."""
        # TODO: Implement when Pact is configured
        pass
    
    @pytest.mark.asyncio
    async def test_submit_order(self):
        """Contract test for Alpaca order submission."""
        # TODO: Implement when Pact is configured
        pass


@pytest.mark.skip(reason="Pact contract harness not yet wired in MERID")
@pytest.mark.contract
class TestPolymarketContract:
    """Consumer-driven contract tests for Polymarket CLOB."""
    
    @pytest.mark.asyncio
    async def test_get_orderbook(self):
        """Contract test for Polymarket orderbook."""
        # TODO: Implement when Pact is configured
        pass
