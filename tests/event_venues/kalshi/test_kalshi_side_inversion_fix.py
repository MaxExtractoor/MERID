"""Tests for Kalshi raw/canonical execution split.

Tests the architecture where:
- `KalshiFill.side` / `action` are the raw exchange execution report.
- `KalshiFill.canonical_position_*` are derived from those execution facts only.
- `KalshiFill.intent_target_side` / `intent_action` capture the expected side
  from the original OrderIntent for mismatch alerting.
- A side conflict between intent and execution triggers `side_conflict=True`.
- When the exchange-reported exposure direction diverges from the agent's
  recorded intent, the fill is quarantined as `UNTRUSTED_SIDE_CONFLICT` and
  is not applied to live positions until reconciled.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import AsyncGenerator

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
    """Test raw/canonical split for WebSocket and HTTP fill ingestion."""

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_execution_sell_no(self, ledger: KalshiFillsLedger) -> None:
        """SELL_NO intent with an execution report that matches the intent.

        The raw exchange report for a SELL_NO should carry side=no, action=sell.
        Canonical position effect is a long YES position (sell NO = buy YES).
        """
        intent = OrderIntent(
            intent_id="client-001",
            ticker="KXBTC-15M",
            side="SELL_NO",
            action="sell",
            price_cents=40,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent

        ws_fill = {
            "fill_id": "fill-001",
            "market_ticker": "KXBTC-15M",
            "outcome_side": "no",
            "side": "no",
            "action": "sell",
            "count": 1,
            "price": 40,
            "client_order_id": "client-001",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True

        fill = ledger.get_fill_by_id("fill-001")
        assert fill is not None
        # Raw exchange fields preserved exactly.
        assert fill.side == "no"
        assert fill.action == "sell"
        # Canonical outcome side equals raw exchange side.
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "sell"
        # Signed-YES delta is positive -> long YES.
        assert fill.canonical_yes_delta_cc == 100
        # Leg price is the NO-side price.
        assert fill.canonical_leg_price_cents == 40
        # Intent expected side matches execution.
        assert fill.intent_target_side == "no"
        assert fill.side_conflict is False

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_execution_buy_no(self, ledger: KalshiFillsLedger) -> None:
        """BUY_NO intent with an execution report that matches the intent."""
        intent = OrderIntent(
            intent_id="client-002",
            ticker="KXETH-15M",
            side="BUY_NO",
            action="buy",
            price_cents=60,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent

        ws_fill = {
            "fill_id": "fill-002",
            "market_ticker": "KXETH-15M",
            "outcome_side": "no",
            "side": "no",
            "action": "buy",
            "count": 1,
            "price": 60,
            "client_order_id": "client-002",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True

        fill = ledger.get_fill_by_id("fill-002")
        assert fill is not None
        assert fill.side == "no"
        assert fill.action == "buy"
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == -100
        assert fill.canonical_leg_price_cents == 60
        assert fill.intent_target_side == "no"
        assert fill.side_conflict is False

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_execution_sell_yes(self, ledger: KalshiFillsLedger) -> None:
        """SELL_YES intent with an execution report that matches the intent."""
        intent = OrderIntent(
            intent_id="client-003",
            ticker="KXSOL-15M",
            side="SELL_YES",
            action="sell",
            price_cents=70,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent

        ws_fill = {
            "fill_id": "fill-003",
            "market_ticker": "KXSOL-15M",
            "outcome_side": "yes",
            "side": "yes",
            "action": "sell",
            "count": 1,
            "price": 70,
            "client_order_id": "client-003",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True

        fill = ledger.get_fill_by_id("fill-003")
        assert fill is not None
        assert fill.side == "yes"
        assert fill.action == "sell"
        assert fill.canonical_position_side == "yes"
        assert fill.canonical_position_action == "sell"
        assert fill.canonical_yes_delta_cc == -100
        assert fill.canonical_leg_price_cents == 70
        assert fill.intent_target_side == "yes"
        assert fill.side_conflict is False

    @pytest.mark.asyncio
    async def test_ws_fill_side_derived_from_execution_buy_yes(self, ledger: KalshiFillsLedger) -> None:
        """BUY_YES intent with an execution report that matches the intent."""
        intent = OrderIntent(
            intent_id="client-004",
            ticker="KXXRP-15M",
            side="BUY_YES",
            action="buy",
            price_cents=55,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent

        ws_fill = {
            "fill_id": "fill-004",
            "market_ticker": "KXXRP-15M",
            "outcome_side": "yes",
            "side": "yes",
            "action": "buy",
            "count": 1,
            "price": 55,
            "client_order_id": "client-004",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True

        fill = ledger.get_fill_by_id("fill-004")
        assert fill is not None
        assert fill.side == "yes"
        assert fill.action == "buy"
        assert fill.canonical_position_side == "yes"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == 100
        assert fill.canonical_leg_price_cents == 55
        assert fill.intent_target_side == "yes"
        assert fill.side_conflict is False

    @pytest.mark.asyncio
    async def test_ws_fill_side_fallback_when_no_intent(self, ledger: KalshiFillsLedger) -> None:
        """Without an intent, canonical side/action are still derived from raw exchange facts."""
        ws_fill = {
            "fill_id": "fill-005",
            "market_ticker": "KXDOGE-15M",
            "outcome_side": "yes",
            "side": "yes",
            "action": "buy",
            "count": 1,
            "price": 50,
            "client_order_id": "client-005",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True

        fill = ledger.get_fill_by_id("fill-005")
        assert fill is not None
        assert fill.side == "yes"
        assert fill.action == "buy"
        assert fill.canonical_position_side == "yes"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == 100
        assert fill.canonical_leg_price_cents == 50
        # No intent, so no side_conflict and no intent_target_side.
        assert fill.intent_target_side is None
        assert fill.side_conflict is False

    @pytest.mark.asyncio
    async def test_http_fill_side_derived_from_execution_sell_no(self, ledger: KalshiFillsLedger) -> None:
        """HTTP SELL_NO fill: canonical derived from execution, not intent."""
        intent = OrderIntent(
            intent_id="client-006",
            ticker="KXBTC-15M",
            side="SELL_NO",
            action="sell",
            price_cents=40,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent

        http_fill = {
            "fill_id": "fill-006",
            "market_ticker": "KXBTC-15M",
            "outcome_side": "no",
            "side": "no",
            "action": "sell",
            "count": 1,
            "price": 40,
            "fee": 0,
            "created_time": "2024-01-01T12:00:00Z",
            "order_id": "order-006",
            "client_order_id": "client-006",
        }

        fill = ledger._parse_fill(http_fill, "http_poller")
        assert fill is not None
        assert fill.side == "no"
        assert fill.action == "sell"
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "sell"
        assert fill.canonical_yes_delta_cc == 100
        assert fill.canonical_leg_price_cents == 40
        assert fill.intent_target_side == "no"
        assert fill.side_conflict is False

    @pytest.mark.asyncio
    async def test_http_fill_side_derived_from_execution_buy_no(self, ledger: KalshiFillsLedger) -> None:
        """HTTP BUY_NO fill: canonical derived from execution, not intent."""
        intent = OrderIntent(
            intent_id="client-007",
            ticker="KXETH-15M",
            side="BUY_NO",
            action="buy",
            price_cents=60,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent

        http_fill = {
            "fill_id": "fill-007",
            "market_ticker": "KXETH-15M",
            "outcome_side": "no",
            "side": "no",
            "action": "buy",
            "count": 1,
            "price": 60,
            "fee": 0,
            "created_time": "2024-01-01T12:00:00Z",
            "order_id": "order-007",
            "client_order_id": "client-007",
        }

        fill = ledger._parse_fill(http_fill, "http_poller")
        assert fill is not None
        assert fill.side == "no"
        assert fill.action == "buy"
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == -100
        assert fill.canonical_leg_price_cents == 60
        assert fill.intent_target_side == "no"
        assert fill.side_conflict is False

    @pytest.mark.asyncio
    async def test_http_fill_side_fallback_when_no_intent(self, ledger: KalshiFillsLedger) -> None:
        """HTTP fill without an intent still canonicalizes from raw exchange fields."""
        http_fill = {
            "fill_id": "fill-008",
            "market_ticker": "KXSOL-15M",
            "outcome_side": "yes",
            "side": "yes",
            "action": "buy",
            "count": 1,
            "price": 50,
            "fee": 0,
            "created_time": "2024-01-01T12:00:00Z",
            "order_id": "order-008",
            "client_order_id": "client-008",
        }

        fill = ledger._parse_fill(http_fill, "http_poller")
        assert fill is not None
        assert fill.canonical_position_side == "yes"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == 100

    @pytest.mark.asyncio
    async def test_intent_exchange_side_conflict_quarantined(self, ledger: KalshiFillsLedger) -> None:
        """If the exchange reports an exposure-inverting side compared to the
        intent, the fill is quarantined rather than applied.

        The intent says BUY_YES (long YES, +100 signed-YES) but the exchange
        reports outcome_side=no, action=buy (BUY_NO, long NO, -100).  The
        exposure direction diverges, so the canonical position effect is
        cleared and the fill is stored as `UNTRUSTED_SIDE_CONFLICT`.
        """
        intent = OrderIntent(
            intent_id="client-009",
            ticker="KXXRP-15M",
            side="BUY_YES",
            action="buy",
            price_cents=40,
            count=1,
        )
        ledger._intents[intent.intent_id] = intent

        ws_fill = {
            "fill_id": "fill-009",
            "market_ticker": "KXXRP-15M",
            "outcome_side": "no",
            "side": "no",
            "action": "buy",
            "count": 1,
            "price": 40,
            "client_order_id": "client-009",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }

        result = await ledger.ingest_ws_fill(ws_fill)
        assert result is True

        fill = ledger.get_fill_by_id("fill-009")
        assert fill is not None
        # Raw exchange fields preserved.
        assert fill.side == "no"
        assert fill.action == "buy"
        # The exposure-inverting report is quarantined; canonical fields are None.
        assert fill.canonical_position_side is None
        assert fill.canonical_position_action is None
        assert fill.canonical_yes_delta_cc is None
        assert fill.canonicalization_state == "UNTRUSTED_SIDE_CONFLICT"
        assert fill.unmatched is True
        # Intent expected side recorded, conflict flagged.
        assert fill.intent_target_side == "yes"
        assert fill.side_conflict is True
