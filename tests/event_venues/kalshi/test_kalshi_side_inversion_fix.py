"""Tests for Kalshi side inversion fix.

Tests the critical fix for Kalshi's side field inversion issue:
- Kalshi quotes everything from YES side
- Their WebSocket and HTTP fill messages always report side="yes"
- We must derive the correct side from the original intent using client_order_id

This test ensures:
1. WebSocket fill ingestion derives side from intent correctly
2. HTTP fill ingestion derives side from intent correctly
3. Fallback to Kalshi's reported side when intent not found
4. All Kalshi format sides (BUY_YES, SELL_YES, BUY_NO, SELL_NO) are handled
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator, Generator

import pytest

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
    OrderIntent,
)


@pytest.fixture
async def ledger(monkeypatch) -> AsyncGenerator[KalshiFillsLedger, None]:
    """Provide a fresh fills ledger for each test."""
    # Reset all singleton state
    KalshiFillsLedger._initialized = False
    KalshiFillsLedger._instance = None
    
    l = KalshiFillsLedger()
    
    # Clear all internal state to ensure isolation
    l._fills = {}
    l._intents = {}
    l._fills_by_order = {}
    l._fills_by_market = {}
    l._http_ingested = 0
    l._ws_ingested = 0
    l._duplicates_dropped = 0
    
    yield l
    
    # Clean up: shutdown writer task properly
    await l.shutdown()
    
    # Clean up after test
    KalshiFillsLedger._initialized = False
    KalshiFillsLedger._instance = None


class TestKalshiSideInversionFix:
    """Test Kalshi side inversion fix for WebSocket and HTTP fill ingestion."""

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_intent_sell_no(self, ledger: KalshiFillsLedger) -> None:
        """Test that SELL_NO intent results in side='no' in fill, not Kalshi's reported 'yes'."""
        # Record intent with SELL_NO (long YES)
        intent = OrderIntent(
            intent_id="client-001",  # intent_id is used as key in _intents dict
            ticker="KXBTC-15M",
            side="SELL_NO",  # Kalshi format
            action="sell",
            price_cents=50,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent
        
        # Simulate Kalshi WebSocket fill (always reports side="yes")
        ws_fill = {
            "fill_id": "fill-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",  # Kalshi reports YES (incorrect for SELL_NO)
            "action": "sell",
            "count": 1,
            "price": 50,
            "client_order_id": "client-001",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True
        
        # Verify side was derived from intent, not Kalshi's reported side
        fill = ledger.get_fill_by_id("fill-001")
        assert fill is not None
        assert fill.side == "no", f"Expected side='no' (from SELL_NO intent), got '{fill.side}'"
        assert fill.action == "sell"

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_intent_buy_no(self, ledger: KalshiFillsLedger) -> None:
        """Test that BUY_NO intent results in side='no' in fill."""
        intent = OrderIntent(
            intent_id="client-002",
            ticker="KXETH-15M",
            side="BUY_NO",
            action="buy",
            price_cents=50,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent
        
        ws_fill = {
            "fill_id": "fill-002",
            "market_ticker": "KXETH-15M",
            "side": "yes",  # Kalshi reports YES (incorrect for BUY_NO)
            "action": "buy",
            "count": 1,
            "price": 50,
            "client_order_id": "client-002",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True
        
        fill = ledger.get_fill_by_id("fill-002")
        assert fill is not None
        assert fill.side == "no", f"Expected side='no' (from BUY_NO intent), got '{fill.side}'"
        assert fill.action == "buy"

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_intent_sell_yes(self, ledger: KalshiFillsLedger) -> None:
        """Test that SELL_YES intent results in side='yes' in fill."""
        intent = OrderIntent(
            intent_id="client-003",
            ticker="KXSOL-15M",
            side="SELL_YES",
            action="sell",
            price_cents=50,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent
        
        ws_fill = {
            "fill_id": "fill-003",
            "market_ticker": "KXSOL-15M",
            "side": "yes",  # Kalshi reports YES (correct for SELL_YES)
            "action": "sell",
            "count": 1,
            "price": 50,
            "client_order_id": "client-003",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True
        
        fill = ledger.get_fill_by_id("fill-003")
        assert fill is not None
        assert fill.side == "yes", f"Expected side='yes' (from SELL_YES intent), got '{fill.side}'"
        assert fill.action == "sell"

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_intent_buy_yes(self, ledger: KalshiFillsLedger) -> None:
        """Test that BUY_YES intent results in side='yes' in fill."""
        intent = OrderIntent(
            intent_id="client-004",
            ticker="KXXRP-15M",
            side="BUY_YES",
            action="buy",
            price_cents=50,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent
        
        ws_fill = {
            "fill_id": "fill-004",
            "market_ticker": "KXXRP-15M",
            "side": "yes",  # Kalshi reports YES (correct for BUY_YES)
            "action": "buy",
            "count": 1,
            "price": 50,
            "client_order_id": "client-004",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True
        
        fill = ledger.get_fill_by_id("fill-004")
        assert fill is not None
        assert fill.side == "yes", f"Expected side='yes' (from BUY_YES intent), got '{fill.side}'"
        assert fill.action == "buy"

    @pytest.mark.asyncio
    async def test_ws_fill_side_fallback_when_no_intent(self, ledger: KalshiFillsLedger) -> None:
        """Test that side falls back to Kalshi's reported side when intent not found."""
        # No intent recorded
        ws_fill = {
            "fill_id": "fill-005",
            "market_ticker": "KXDOGE-15M",
            "side": "yes",  # Kalshi reports YES
            "action": "buy",
            "count": 1,
            "price": 50,
            "client_order_id": "client-005",  # No matching intent
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True
        
        fill = ledger.get_fill_by_id("fill-005")
        assert fill is not None
        assert fill.side == "yes", f"Expected side='yes' (fallback to Kalshi), got '{fill.side}'"

    @pytest.mark.asyncio
    async def test_http_fill_side_derived_from_intent_sell_no(self, ledger: KalshiFillsLedger) -> None:
        """Test that HTTP fill ingestion also derives side from intent."""
        intent = OrderIntent(
            intent_id="client-006",
            ticker="KXBTC-15M",
            side="SELL_NO",
            action="sell",
            price_cents=50,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent
        
        # Test the _parse_fill logic directly for HTTP fills
        http_fill = {
            "fill_id": "fill-006",
            "market_ticker": "KXBTC-15M",
            "side": "yes",  # Kalshi reports YES (incorrect for SELL_NO)
            "action": "sell",
            "count": 1,
            "price": 50,
            "fee": 0,
            "created_time": "2024-01-01T12:00:00Z",
            "order_id": "order-006",
            "client_order_id": "client-006",
        }
        
        # Parse the fill directly to test side derivation
        fill = ledger._parse_fill(http_fill, "http_poller")
        assert fill is not None
        assert fill.side == "no", f"Expected side='no' (from SELL_NO intent), got '{fill.side}'"
        assert fill.action == "sell"

    @pytest.mark.asyncio
    async def test_http_fill_side_derived_from_intent_buy_no(self, ledger: KalshiFillsLedger) -> None:
        """Test that HTTP fill ingestion derives side from BUY_NO intent."""
        intent = OrderIntent(
            intent_id="client-007",
            ticker="KXETH-15M",
            side="BUY_NO",
            action="buy",
            price_cents=50,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent
        
        http_fill = {
            "fill_id": "fill-007",
            "market_ticker": "KXETH-15M",
            "side": "yes",  # Kalshi reports YES (incorrect for BUY_NO)
            "action": "buy",
            "count": 1,
            "price": 50,
            "fee": 0,
            "created_time": "2024-01-01T12:00:00Z",
            "order_id": "order-007",
            "client_order_id": "client-007",
        }
        
        fill = ledger._parse_fill(http_fill, "http_poller")
        assert fill is not None
        assert fill.side == "no", f"Expected side='no' (from BUY_NO intent), got '{fill.side}'"
        assert fill.action == "buy"

    @pytest.mark.asyncio
    async def test_http_fill_side_fallback_when_no_intent(self, ledger: KalshiFillsLedger) -> None:
        """Test that HTTP fill ingestion falls back to Kalshi's reported side."""
        # No intent recorded
        http_fill = {
            "fill_id": "fill-008",
            "market_ticker": "KXSOL-15M",
            "side": "yes",
            "action": "buy",
            "count": 1,
            "price": 50,
            "fee": 0,
            "created_time": "2024-01-01T12:00:00Z",
            "order_id": "order-008",
            "client_order_id": "client-008",  # No matching intent
        }
        
        fill = ledger._parse_fill(http_fill, "http_poller")
        assert fill is not None
        assert fill.side == "yes", f"Expected side='yes' (fallback to Kalshi), got '{fill.side}'"

    @pytest.mark.asyncio
    async def test_intent_side_lowercase_fallback(self, ledger: KalshiFillsLedger) -> None:
        """Test that lowercase intent.side is handled correctly."""
        intent = OrderIntent(
            intent_id="client-009",
            ticker="KXXRP-15M",
            side="no",  # Lowercase (not Kalshi format)
            action="sell",
            price_cents=50,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent
        
        ws_fill = {
            "fill_id": "fill-009",
            "market_ticker": "KXXRP-15M",
            "side": "yes",
            "action": "sell",
            "count": 1,
            "price": 50,
            "client_order_id": "client-009",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        
        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True
        
        fill = ledger.get_fill_by_id("fill-009")
        assert fill is not None
        assert fill.side == "no", f"Expected side='no' (from lowercase intent.side), got '{fill.side}'"
