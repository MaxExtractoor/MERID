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
async def ledger(monkeypatch, tmp_path) -> AsyncGenerator[KalshiFillsLedger, None]:
    """Provide a fresh fills ledger for each test."""
    # TEST-ISOLATION FIX (2026-07-19): Redirect DB writes away from production.
    # Without this, test fills are persisted to data/kalshi_fills.db (or
    # PostgreSQL) and pollute real position tracking.
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(tmp_path / "test_fills.db"))
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)
    
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
                # Trusted fills carry both legs explicitly (real Kalshi V2
                # payloads); a single-leg sell is quarantined as
                # UNTRUSTED_RAW and cannot close a position.
                "yes_price": 0.52,
                "no_price": 0.48,
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
                # Both leg prices required for a trusted closing fill.
                "yes_price": 0.55,
                "no_price": 0.45,
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


class TestCounterpartyFormAccounting:
    """Signed-YES replay accounting for Kalshi complement-form fills.

    Kalshi reports one economic position under different canonical forms: a
    BUY_NO entry arrives as ``yes/sell`` and its SELL_NO exit arrives as
    ``yes/buy``.  Positions are tracked per ticker by signed-YES exposure —
    the old ``ticker:side`` keys split one position across keys, dropped
    entries as naked sells, and minted phantom opposite-side positions
    (2026-09-21 audit).
    """

    @staticmethod
    def _fill(**kw) -> "KalshiFill":
        from merid.event_venues.kalshi.fills_ledger import KalshiFill

        defaults = dict(
            fill_id="fill-x",
            order_id="ord-x",
            market_ticker="KXBTC15M-TEST",
            side="yes",
            action="sell",
            count_fp=Decimal("1"),
            quantity_cc=100,
            yes_price_dollars=Decimal("0.64"),
            no_price_dollars=Decimal("0.36"),
            fee_cost=Decimal("0.01"),
            proceeds_dollars=Decimal("-0.37"),
            canonical_position_side="yes",
            canonical_position_action="sell",
            canonical_leg_price_cents=64,
            canonical_yes_delta_cc=-100,
            canonicalization_state="TRUSTED_LIVE_V1",
            canonicalization_version=3,
            unmatched=False,
            ingestion_source="http_poller",
            created_time=datetime.now(timezone.utc),
        )
        defaults.update(kw)
        return KalshiFill(**defaults)

    def test_counterparty_entry_creates_no_position(self, ledger: KalshiFillsLedger) -> None:
        # BUY_NO reported in book form: yes/sell at YES 64c -> NO costs 36c.
        entry = self._fill(fill_id="fill-entry-1", order_id="ord-entry-1")
        ledger.on_fill(entry)

        pos = ledger._open_positions.get("KXBTC15M-TEST")
        assert pos is not None, "counterparty-form entry must open a position"
        assert pos["side"] == "no"
        assert pos["signed_yes_cc"] == -100
        assert pos["total_contracts"] == Decimal("1")
        assert pos["avg_price_cents"] == 36  # held-side leg, not the YES leg

    def test_complement_exit_closes_and_realizes_pnl(self, ledger: KalshiFillsLedger) -> None:
        t0 = datetime.now(timezone.utc)
        entry = self._fill(
            fill_id="fill-entry-2", order_id="ord-entry-2", created_time=t0,
        )
        # SELL_NO reported as a complement YES buy at 29c: pays 29c to lock a
        # YES+NO pair that settles at $1.
        exit_fill = self._fill(
            fill_id="fill-exit-2",
            order_id="ord-exit-2",
            side="yes",
            action="buy",
            yes_price_dollars=Decimal("0.29"),
            no_price_dollars=Decimal("0.71"),
            fee_cost=Decimal("0.0145"),
            proceeds_dollars=Decimal("-0.3045"),
            canonical_position_side="yes",
            canonical_position_action="buy",
            canonical_leg_price_cents=29,
            canonical_yes_delta_cc=100,
            is_exit=True,
            entry_or_exit="exit",
            created_time=t0 + timedelta(seconds=30),
        )
        ledger.on_fill(entry)
        ledger.on_fill(exit_fill)

        assert "KXBTC15M-TEST" not in ledger._open_positions, "position must close"
        # Net segment cash: -0.37 entry + -0.3045 exit + $1.00 pair lock = +0.3255
        assert abs(ledger._session_realized_pnl - Decimal("0.3255")) < Decimal("0.001"), (
            f"realized={ledger._session_realized_pnl}"
        )

    def test_live_router_promotion_single_mutation(self, ledger: KalshiFillsLedger) -> None:
        t0 = datetime.now(timezone.utc)
        # Provisional fill created by the router in intent form (BUY_NO).
        prov = self._fill(
            fill_id="live_router_ord-3_0",
            order_id="ord-3",
            side="no",
            action="buy",
            yes_price_dollars=Decimal("0.64"),
            no_price_dollars=Decimal("0.36"),
            proceeds_dollars=Decimal("-0.37"),
            canonical_position_side="no",
            canonical_position_action="buy",
            canonical_leg_price_cents=36,
            canonical_yes_delta_cc=-100,
            ingestion_source="order_router",
            created_time=t0,
        )
        ledger.on_fill(prov)
        assert len([f for f in ledger._fills.values() if f.order_id == "ord-3"]) == 1

        # Authoritative exchange fill in book form for the same order.
        auth = self._fill(
            fill_id="fill-auth-3",
            order_id="ord-3",
            side="yes",
            action="sell",
            yes_price_dollars=Decimal("0.64"),
            no_price_dollars=Decimal("0.36"),
            proceeds_dollars=Decimal("-0.37"),
            canonical_position_side="yes",
            canonical_position_action="sell",
            canonical_leg_price_cents=64,
            canonical_yes_delta_cc=-100,
            created_time=t0 + timedelta(milliseconds=200),
        )
        ledger.on_fill(auth)

        fills_for_order = [f for f in ledger._fills.values() if f.order_id == "ord-3"]
        assert len(fills_for_order) == 1, "promotion must not duplicate the fill"
        assert fills_for_order[0].fill_id == "fill-auth-3"
        assert "live_router_ord-3_0" in ledger._stale_live_router_db_ids

        pos = ledger._open_positions.get("KXBTC15M-TEST")
        assert pos is not None and pos["side"] == "no"
        assert pos["total_contracts"] == Decimal("1"), "no double-apply after promotion"
        assert pos["avg_price_cents"] == 36

    def test_partial_exit_credited_once(self, ledger: KalshiFillsLedger) -> None:
        t0 = datetime.now(timezone.utc)
        entry = self._fill(
            fill_id="fill-entry-4",
            order_id="ord-entry-4",
            count_fp=Decimal("2"),
            quantity_cc=200,
            fee_cost=Decimal("0.02"),
            proceeds_dollars=Decimal("-0.74"),
            canonical_yes_delta_cc=-200,
            created_time=t0,
        )

        def _exit(fid: str, oid: str, ts) -> "KalshiFill":
            return self._fill(
                fill_id=fid,
                order_id=oid,
                side="yes",
                action="buy",
                yes_price_dollars=Decimal("0.29"),
                no_price_dollars=Decimal("0.71"),
                fee_cost=Decimal("0.0145"),
                proceeds_dollars=Decimal("-0.3045"),
                canonical_position_side="yes",
                canonical_position_action="buy",
                canonical_leg_price_cents=29,
                canonical_yes_delta_cc=100,
                is_exit=True,
                entry_or_exit="exit",
                created_time=ts,
            )

        ledger.on_fill(entry)
        ledger.on_fill(_exit("fill-exit-4a", "ord-exit-4a", t0 + timedelta(seconds=10)))
        # After the partial: one contract remains, partial PnL credited once.
        pos = ledger._open_positions.get("KXBTC15M-TEST")
        assert pos is not None and pos["total_contracts"] == Decimal("1")
        partial_expected = Decimal("-0.3045") + Decimal("1.0") - Decimal("0.36")
        assert abs(ledger._session_realized_pnl - partial_expected) < Decimal("0.001")

        ledger.on_fill(_exit("fill-exit-4b", "ord-exit-4b", t0 + timedelta(seconds=20)))
        assert "KXBTC15M-TEST" not in ledger._open_positions
        # Total realized = full segment net cash, credited exactly once:
        # -0.74 entry + 2 * (-0.3045 + $1 pair) = +0.651
        assert abs(ledger._session_realized_pnl - Decimal("0.651")) < Decimal("0.001"), (
            f"session_realized={ledger._session_realized_pnl}"
        )

    @pytest.mark.asyncio
    async def test_promoted_provisional_row_deleted_from_db(
        self, ledger: KalshiFillsLedger
    ) -> None:
        """A flushed live_router_ row must be deleted after promotion.

        Restart replay must see only the authoritative fill — a stale
        provisional row would re-apply the mirrored economics.
        """
        import aiosqlite

        t0 = datetime.now(timezone.utc)
        prov = self._fill(
            fill_id="live_router_ord-p1_0",
            order_id="ord-p1",
            market_ticker="KXBTC15M-26SEP220000-00",
            side="no",
            action="buy",
            yes_price_dollars=Decimal("0.64"),
            no_price_dollars=Decimal("0.36"),
            proceeds_dollars=Decimal("-0.37"),
            canonical_position_side="no",
            canonical_position_action="buy",
            canonical_leg_price_cents=36,
            canonical_yes_delta_cc=-100,
            ingestion_source="order_router",
            created_time=t0,
        )
        ledger.on_fill(prov)
        await ledger._flush_to_db()

        async with aiosqlite.connect(ledger._db_path) as db:
            async with db.execute("SELECT fill_id FROM kalshi_fills") as cur:
                rows = [r[0] for r in await cur.fetchall()]
        assert rows == ["live_router_ord-p1_0"], f"provisional row must flush first: {rows}"

        auth = self._fill(
            fill_id="9f8e7d6c-0000-4000-8000-0000000000a1",
            order_id="ord-p1",
            market_ticker="KXBTC15M-26SEP220000-00",
            side="yes",
            action="sell",
            yes_price_dollars=Decimal("0.64"),
            no_price_dollars=Decimal("0.36"),
            proceeds_dollars=Decimal("-0.37"),
            canonical_position_side="yes",
            canonical_position_action="sell",
            canonical_leg_price_cents=64,
            canonical_yes_delta_cc=-100,
            created_time=t0 + timedelta(milliseconds=200),
        )
        ledger.on_fill(auth)
        await ledger._flush_to_db()

        async with aiosqlite.connect(ledger._db_path) as db:
            async with db.execute("SELECT fill_id FROM kalshi_fills") as cur:
                rows = sorted(r[0] for r in await cur.fetchall())
        assert rows == ["9f8e7d6c-0000-4000-8000-0000000000a1"], (
            f"stale provisional row must be deleted after promotion: {rows}"
        )

        # Reload from disk: only the authoritative fill may come back.
        KalshiFillsLedger._initialized = False
        KalshiFillsLedger._instance = None
        ledger2 = KalshiFillsLedger()
        try:
            loaded = await ledger2.load_from_db()
            assert loaded == 1, f"expected 1 authoritative fill, loaded {loaded}"
            reloaded = [f for f in ledger2._fills.values() if f.order_id == "ord-p1"]
            assert len(reloaded) == 1
            assert reloaded[0].fill_id == "9f8e7d6c-0000-4000-8000-0000000000a1"
            pos = ledger2._replay_market_position("KXBTC15M-26SEP220000-00")
            assert pos is not None and pos["side"] == "no"
            assert pos["total_contracts"] == Decimal("1")
            assert pos["avg_price_cents"] == 36
        finally:
            await ledger2.shutdown()
            KalshiFillsLedger._initialized = False
            KalshiFillsLedger._instance = None

    def test_failed_promotion_superseded_by_authoritative_fill(
        self, ledger: KalshiFillsLedger
    ) -> None:
        """If promotion matching fails (price moved >1c), the provisional row
        survives — but replay must still count only the authoritative fill.
        """
        t0 = datetime.now(timezone.utc)
        prov = self._fill(
            fill_id="live_router_ord-6_0",
            order_id="ord-6",
            side="no",
            action="buy",
            yes_price_dollars=Decimal("0.64"),
            no_price_dollars=Decimal("0.36"),
            proceeds_dollars=Decimal("-0.37"),
            canonical_position_side="no",
            canonical_position_action="buy",
            canonical_leg_price_cents=36,
            canonical_yes_delta_cc=-100,
            ingestion_source="order_router",
            created_time=t0,
        )
        ledger.on_fill(prov)
        pos = ledger._open_positions.get("KXBTC15M-TEST")
        assert pos is not None and pos["total_contracts"] == Decimal("1")

        # Authoritative fill for the same order at a different price — too far
        # for _is_same_economic_fill, so promotion does not merge the rows.
        auth = self._fill(
            fill_id="fill-auth-6",
            order_id="ord-6",
            side="yes",
            action="sell",
            yes_price_dollars=Decimal("0.60"),
            no_price_dollars=Decimal("0.40"),
            proceeds_dollars=Decimal("-0.41"),
            canonical_position_side="yes",
            canonical_position_action="sell",
            canonical_leg_price_cents=60,
            canonical_yes_delta_cc=-100,
            created_time=t0 + timedelta(milliseconds=200),
        )
        ledger.on_fill(auth)

        pos = ledger._open_positions.get("KXBTC15M-TEST")
        assert pos is not None, "authoritative fill must still open the position"
        assert pos["side"] == "no"
        assert pos["total_contracts"] == Decimal("1"), (
            f"superseded provisional double-applied: {pos['total_contracts']}"
        )
        assert pos["avg_price_cents"] == 40  # authoritative held-side basis
