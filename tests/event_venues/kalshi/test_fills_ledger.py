"""Tests for Kalshi fills ledger — idempotent fill tracking.

This module tests the `KalshiFillsLedger` class:
- Idempotent fill recording (same ID = single entry)
- Position calculation from fills
- WS and REST fill parsing
- Thread safety
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import AsyncGenerator, Generator

import pytest

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
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


class TestFillsLedgerIdempotency:
    """Test idempotency guarantees."""

    @pytest.mark.asyncio
    async def test_duplicate_fill_id_rejected(self, ledger: KalshiFillsLedger) -> None:
        """Test that duplicate fill IDs are rejected."""
        fill1 = {
            "fill_id": "fill-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        
        result1 = await ledger.ingest_ws_fill(fill1)
        result2 = await ledger.ingest_ws_fill(fill1)
        
        assert result1 is True
        assert result2 is False

    @pytest.mark.asyncio
    async def test_different_fill_ids_accepted(self, ledger: KalshiFillsLedger) -> None:
        """Test that different fill IDs are both accepted."""
        fill1 = {
            "fill_id": "fill-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
        }
        fill2 = {
            "fill_id": "fill-002",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 50,
            "price": 51,
        }
        
        result1 = await ledger.ingest_ws_fill(fill1)
        result2 = await ledger.ingest_ws_fill(fill2)
        
        assert result1 is True
        assert result2 is True
        assert ledger.summary()["fills_total"] == 2


class TestFillsLedgerPositionCalculation:
    """Test position calculation from fill history."""

    def test_empty_position(self, ledger: KalshiFillsLedger) -> None:
        """Test position with no fills."""
        pos = ledger.compute_position_from_fills("KXBTC-15M")
        assert pos is None

    @pytest.mark.asyncio
    async def test_simple_long_position(self, ledger: KalshiFillsLedger) -> None:
        """Test long position calculation."""
        fill = {
            "fill_id": "fill-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
            "fee": 7,
        }
        
        await ledger.ingest_ws_fill(fill)
        pos = ledger.compute_position_from_fills("KXBTC-15M")
        
        assert pos is not None
        assert pos["side"] == "yes"
        assert pos["contracts"] == 100
        assert pos["computed_from_fills"] == 1

    @pytest.mark.asyncio
    async def test_long_with_multiple_buys(self, ledger: KalshiFillsLedger) -> None:
        """Test long position with multiple buy fills."""
        fills = [
            {
                "fill_id": "fill-001",
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "buy",
                "count": 100,
                "price": 50,
            },
            {
                "fill_id": "fill-002",
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "buy",
                "count": 100,
                "price": 51,
            },
        ]
        
        for f in fills:
            await ledger.ingest_ws_fill(f)
        
        pos = ledger.compute_position_from_fills("KXBTC-15M")
        assert pos is not None
        assert pos["contracts"] == 200

    @pytest.mark.asyncio
    async def test_partial_close_long(self, ledger: KalshiFillsLedger) -> None:
        """Test partial position close."""
        fills = [
            {
                "fill_id": "fill-001",
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "buy",
                "count": 100,
                "price": 50,
            },
            {
                "fill_id": "fill-002",
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "sell",
                "count": 60,
                "price": 52,
            },
        ]
        
        for f in fills:
            await ledger.ingest_ws_fill(f)
        
        pos = ledger.compute_position_from_fills("KXBTC-15M")
        assert pos is not None
        assert pos["contracts"] == 40

    @pytest.mark.asyncio
    async def test_full_close_long(self, ledger: KalshiFillsLedger) -> None:
        """Test full position close."""
        fills = [
            {
                "fill_id": "fill-001",
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "buy",
                "count": 100,
                "price": 50,
            },
            {
                "fill_id": "fill-002",
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "sell",
                "count": 100,
                "price": 55,
            },
        ]
        
        for f in fills:
            await ledger.ingest_ws_fill(f)
        
        pos = ledger.compute_position_from_fills("KXBTC-15M")
        assert pos is None  # Fully closed

    @pytest.mark.asyncio
    async def test_short_position_via_no_side(self, ledger: KalshiFillsLedger) -> None:
        """Test position with 'no' side."""
        fill = {
            "fill_id": "fill-001",
            "market_ticker": "KXBTC-15M",
            "side": "no",
            "action": "buy",
            "count": 100,
            "price": 50,
        }
        
        await ledger.ingest_ws_fill(fill)
        pos = ledger.compute_position_from_fills("KXBTC-15M")
        
        assert pos is not None
        assert pos["side"] == "no"
        assert pos["contracts"] == 100


class TestFillsLedgerWSAndREST:
    """Test WebSocket and REST fill parsing."""

    @pytest.mark.asyncio
    async def test_record_ws_fill_success(self, ledger: KalshiFillsLedger) -> None:
        """Test WebSocket fill parsing."""
        ws_data = {
            "fill_id": "ws-fill-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
            "fee": 7,
            "created_time": "2024-01-01T12:00:00Z",
            "order_id": "order-001",
        }
        
        result = await ledger.ingest_ws_fill(ws_data)
        
        assert result is True
        summary = ledger.summary()
        assert summary["fills_from_ws"] == 1

    @pytest.mark.asyncio
    async def test_record_ws_fill_duplicate(self, ledger: KalshiFillsLedger) -> None:
        """Test WebSocket fill duplicate handling."""
        ws_data = {
            "fill_id": "ws-fill-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
        }
        
        result1 = await ledger.ingest_ws_fill(ws_data)
        result2 = await ledger.ingest_ws_fill(ws_data)
        
        assert result1 is True
        assert result2 is False

    @pytest.mark.asyncio
    async def test_record_rest_fills_success(self, ledger: KalshiFillsLedger) -> None:
        """Test REST fill parsing."""
        rest_data = [
            {
                "fill_id": "rest-fill-001",
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "buy",
                "count": 100,
                "price": 50,
                "fee": 7,
                "created_time": "2024-01-01T12:00:00Z",
                "order_id": "order-001",
            }
        ]
        
        count, _ = await ledger.ingest_http_fills(rest_data)
        
        assert count == 1
        summary = ledger.summary()
        assert summary["fills_from_http"] == 1


class TestFillsLedgerQueries:
    """Test query methods."""

    @pytest.mark.asyncio
    async def test_get_fills_by_ticker(self, ledger: KalshiFillsLedger) -> None:
        """Test filtering fills by ticker."""
        await ledger.ingest_ws_fill({
            "fill_id": "f1", "market_ticker": "KXBTC-15M", "side": "yes", "action": "buy",
            "count": 100, "price": 50,
        })
        await ledger.ingest_ws_fill({
            "fill_id": "f2", "market_ticker": "KXETH-15M", "side": "yes", "action": "buy",
            "count": 100, "price": 50,
        })
        
        btc_fills = ledger.get_fills(market_ticker="KXBTC-15M")
        
        assert len(btc_fills) == 1
        assert btc_fills[0].market_ticker == "KXBTC-15M"

    @pytest.mark.asyncio
    async def test_get_fills_by_agent(self, ledger: KalshiFillsLedger) -> None:
        """Test filtering fills by agent."""
        await ledger.ingest_ws_fill({
            "fill_id": "f1", "market_ticker": "KXBTC-15M", "side": "yes", "action": "buy",
            "count": 100, "price": 50,
        }, agent_id="agent-1")
        await ledger.ingest_ws_fill({
            "fill_id": "f2", "market_ticker": "KXETH-15M", "side": "yes", "action": "buy",
            "count": 100, "price": 50,
        }, agent_id="agent-2")
        
        agent1_fills = ledger.get_fills(agent_id="agent-1")
        
        assert len(agent1_fills) == 1
        assert agent1_fills[0].agent_id == "agent-1"


class TestFillsLedgerOrphanDetection:
    """Test orphan fill detection."""

    @pytest.mark.asyncio
    async def test_orphan_fill_detection(self, ledger: KalshiFillsLedger) -> None:
        """Test detection of fills without linked intents."""
        await ledger.ingest_ws_fill({
            "fill_id": "f1",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
            # No client_order_id = orphan
        })
        
        orphans = ledger.get_orphan_fills()
        
        assert len(orphans) == 1
        assert orphans[0].fill_id == "f1"


class TestFillsLedgerSummary:
    """Test summary statistics."""

    @pytest.mark.asyncio
    async def test_summary_accuracy(self, ledger: KalshiFillsLedger) -> None:
        """Test that summary accurately reflects state."""
        await ledger.ingest_ws_fill({
            "fill_id": "f1", "market_ticker": "KXBTC-15M",
            "side": "yes", "action": "buy", "count": 100, "price": 50,
        })
        await ledger.ingest_ws_fill({
            "fill_id": "f2", "market_ticker": "KXETH-15M",
            "side": "yes", "action": "buy", "count": 100, "price": 50,
        })
        
        summary = ledger.summary()
        
        assert summary["fills_total"] == 2
        assert summary["fills_from_ws"] == 2
        assert summary["total_fills"] == 2

    def test_empty_ledger_summary(self, ledger: KalshiFillsLedger) -> None:
        """Test summary with no fills."""
        summary = ledger.summary()
        
        assert summary["fills_total"] == 0
        assert summary["total_realized_pnl_usd"] == 0.0
        assert summary["total_fees_usd"] == 0.0
