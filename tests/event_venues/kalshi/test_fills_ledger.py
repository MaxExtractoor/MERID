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


class TestOrderIntentSizingContext:
    """Test OrderIntent sizing context fields for TRADE-TRACE."""

    def test_order_intent_sizing_context_fields(self, ledger: KalshiFillsLedger) -> None:
        """Test OrderIntent includes sizing context fields."""
        intent = OrderIntent(
            intent_id="intent-001",
            ticker="KXBTC-15M",
            side="yes",
            action="buy",
            count=100,
            price_cents=50,
            agent_id="agent-1",
            # Sizing context fields
            edgepct=0.05,
            netedgecents=2.5,
            band="STANDARD",
            regime="NORMAL",
            size_contracts=100,
            notional_usd=50.0,
        )
        
        ledger.record_intent(intent)
        
        # Verify intent was stored
        retrieved = ledger._intents.get("intent-001")
        assert retrieved is not None
        assert retrieved.ticker == "KXBTC-15M"  # Field is now 'ticker', not 'market_ticker'
        assert retrieved.edgepct == 0.05
        assert retrieved.netedgecents == 2.5
        assert retrieved.band == "STANDARD"
        assert retrieved.regime == "NORMAL"
        assert retrieved.size_contracts == 100
        assert retrieved.notional_usd == 50.0

    def test_order_intent_default_sizing_context(self, ledger: KalshiFillsLedger) -> None:
        """Test OrderIntent sizing context defaults to zero/empty."""
        intent = OrderIntent(
            intent_id="intent-002",
            ticker="KXBTC-15M",
            side="yes",
            action="buy",
            count=100,
            price_cents=50,
            agent_id="agent-1",
        )
        
        ledger.record_intent(intent)
        
        # Verify defaults
        retrieved = ledger._intents.get("intent-002")
        assert retrieved is not None
        assert retrieved.ticker == "KXBTC-15M"  # Field is now 'ticker', not 'market_ticker'
        assert retrieved.edgepct == 0.0
        assert retrieved.netedgecents == 0.0
        assert retrieved.band == ""
        assert retrieved.regime == ""
        assert retrieved.size_contracts == 0
        assert retrieved.notional_usd == 0.0


class TestFillIngestWithTradeTrace:
    """Test FILL-INGEST log with TRADE-TRACE context."""

    @pytest.mark.asyncio
    async def test_fill_ingest_with_linked_intent(self, ledger: KalshiFillsLedger, caplog) -> None:
        """Test FILL-INGEST log includes sizing context from linked intent."""
        # Record intent with sizing context
        intent = OrderIntent(
            intent_id="intent-003",
            ticker="KXBTC-15M",
            side="yes",
            action="buy",
            count=100,
            price_cents=50,
            agent_id="agent-1",
            edgepct=0.05,
            netedgecents=2.5,
            band="STANDARD",
            regime="NORMAL",
            size_contracts=100,
            notional_usd=50.0,
        )
        ledger.record_intent(intent)
        
        # Ingest fill with client_order_id linking to intent
        fill = {
            "fill_id": "fill-003",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
            "client_order_id": "intent-003",
        }
        
        with caplog.at_level("INFO"):
            await ledger.ingest_ws_fill(fill)
        
        # Verify FILL-INGEST log was emitted with sizing context
        ingest_logs = [log for log in caplog.records if "FILL-INGEST" in log.message]
        assert len(ingest_logs) == 1
        log_message = ingest_logs[0].message
        assert "edgepct=0.0500" in log_message
        assert "netedgecents=2.50" in log_message
        assert "band=STANDARD" in log_message
        assert "regime=NORMAL" in log_message

    @pytest.mark.asyncio
    async def test_fill_ingest_without_linked_intent(self, ledger: KalshiFillsLedger, caplog) -> None:
        """Test FILL-INGEST log uses defaults when no linked intent."""
        # Ingest fill without client_order_id (orphan)
        fill = {
            "fill_id": "fill-004",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
        }
        
        with caplog.at_level("INFO"):
            await ledger.ingest_ws_fill(fill)
        
        # Verify FILL-INGEST log was emitted with defaults
        ingest_logs = [log for log in caplog.records if "FILL-INGEST" in log.message]
        assert len(ingest_logs) == 1
        log_message = ingest_logs[0].message
        assert "edgepct=0.0000" in log_message
        assert "netedgecents=0.00" in log_message
        assert "band=" in log_message  # Empty band
        assert "regime=" in log_message  # Empty regime


class TestFillsLedgerMutexInitialization:
    """Test mutex initialization fix for event loop safety."""

    @pytest.mark.asyncio
    async def test_mutex_initialization_on_first_access(self, ledger: KalshiFillsLedger) -> None:
        """Test that mutex is initialized on first access via _ensure_mutex()."""
        # Initially mutex should be None
        assert ledger._mutex is None
        
        # Access via _ensure_mutex should initialize it
        mutex = ledger._ensure_mutex()
        assert mutex is not None
        assert isinstance(mutex, asyncio.Lock)
        
        # Subsequent calls should return the same mutex
        mutex2 = ledger._ensure_mutex()
        assert mutex is mutex2

    @pytest.mark.asyncio
    async def test_mutex_initialized_before_ingest_ws_fill(self, ledger: KalshiFillsLedger) -> None:
        """Test that ingest_ws_fill properly initializes mutex via _ensure_mutex."""
        fill = {
            "fill_id": "fill-mutex-test-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
        }
        
        # Before ingest, mutex should be None
        assert ledger._mutex is None
        
        # Ingest should work without error (mutex initialized internally)
        result = await ledger.ingest_ws_fill(fill)
        assert result is True
        
        # After ingest, mutex should be initialized
        assert ledger._mutex is not None

    @pytest.mark.asyncio
    async def test_mutex_initialized_before_ingest_http_fills(self, ledger: KalshiFillsLedger) -> None:
        """Test that ingest_http_fills properly initializes mutex via _ensure_mutex."""
        fills = [
            {
                "fill_id": "KX-FILL-ABC123-XYZ789",  # Use realistic Kalshi fill ID format
                "market_ticker": "KXBTC-15M",
                "side": "yes",
                "action": "buy",
                "count": 100,
                "yes_price": 0.50,
                "created_time": datetime.now(timezone.utc).isoformat(),
            }
        ]
        
        # Before ingest, mutex should be None
        assert ledger._mutex is None
        
        # Ingest should work without error (mutex initialized internally)
        new_count, new_ids = await ledger.ingest_http_fills(fills, agent_map={})
        assert new_count == 1
        
        # After ingest, mutex should be initialized
        assert ledger._mutex is not None

    @pytest.mark.asyncio
    async def test_mutex_thread_safety_concurrent_access(self, ledger: KalshiFillsLedger) -> None:
        """Test that mutex handles concurrent access safely."""
        fill1 = {
            "fill_id": "fill-concurrent-001",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 100,
            "price": 50,
        }
        fill2 = {
            "fill_id": "fill-concurrent-002",
            "market_ticker": "KXBTC-15M",
            "side": "yes",
            "action": "buy",
            "count": 50,
            "price": 51,
        }
        
        # Ingest fills concurrently
        results = await asyncio.gather(
            ledger.ingest_ws_fill(fill1),
            ledger.ingest_ws_fill(fill2),
        )
        
        # Both should succeed
        assert all(results)
        assert ledger.summary()["fills_total"] == 2
