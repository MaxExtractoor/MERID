"""Test suite for paper fill ID determinism and idempotency contract.

Validates the v1 hash schema: hash(intent_id:ticker:side:action:count:price) mod 2^32
"""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from typing import Any, Dict

import pytest

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    simulate_paper_fill,
    TradingMode,
)
from merid.event_venues.kalshi.fills_ledger import (
    KalshiFill,
    KalshiFillsLedger,
    get_fills_ledger,
)


# ═══════════════════════════════════════════════════════════════════════════
# Upstream: simulate_paper_fill contract tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPaperFillDeterminism:
    """Validate hash_preimage construction and fill_id determinism."""

    def test_hash_preimage_format(self):
        """Assert exact format: intent_id:ticker:side:action:count:price"""
        intent = OrderIntent(
            ticker="KXBTC-25DEC-ABOVE-100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
        )
        fill = simulate_paper_fill(intent)

        preimage = fill["hash_preimage"]
        parts = preimage.split(":")

        # Exactly 6 colon-separated parts
        assert len(parts) == 6, f"Expected 6 parts, got {len(parts)}: {preimage}"

        # No spaces anywhere
        assert " " not in preimage, f"Spaces found in preimage: {preimage}"

        # Count and price are integers (no decimals, no floats)
        count_str, price_str = parts[4], parts[5]
        assert count_str.isdigit(), f"Count not integer: {count_str}"
        assert price_str.isdigit(), f"Price not integer: {price_str}"

        # Verify structure matches intent
        assert parts[0] == intent.intent_id
        assert parts[1] == intent.ticker
        assert parts[2] == intent.side
        assert parts[3] == intent.action
        assert int(count_str) == fill["count"]
        assert int(price_str) == fill["price_cents"]

    def test_fill_id_determinism_with_seeded_rng(self):
        """Same intent with seeded RNG must yield identical fill_id and hash_preimage."""
        import random

        intent = OrderIntent(
            ticker="KXBTC-25DEC-ABOVE-100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
        )

        rng1 = random.Random(12345)
        rng2 = random.Random(12345)

        fill1 = simulate_paper_fill(intent, _rng=rng1)
        fill2 = simulate_paper_fill(intent, _rng=rng2)

        assert fill1["fill_id"] == fill2["fill_id"]
        assert fill1["hash_preimage"] == fill2["hash_preimage"]
        assert fill1["idempotency_key"] == fill2["idempotency_key"]

    def test_fill_id_discriminates_by_intent_id(self):
        """Two intents with identical economics must have different fill_ids."""
        base = {
            "ticker": "KXBTC-25DEC-ABOVE-100000",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "count": 10,
        }

        intent1 = OrderIntent(**base)
        intent2 = OrderIntent(**base)  # Different intent_id auto-generated

        fill1 = simulate_paper_fill(intent1)
        fill2 = simulate_paper_fill(intent2)

        assert intent1.intent_id != intent2.intent_id
        assert fill1["fill_id"] != fill2["fill_id"]

    def test_no_op_fields_do_not_affect_hash(self):
        """Minor metadata changes on intent must not change fill_id (with same RNG)."""
        import random
        intent = OrderIntent(
            ticker="KXBTC-25DEC-ABOVE-100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            edge_pct=5.0,
            source="test",
            rationale="Test rationale",
        )

        # Use same RNG seed for both calls so partial fill behavior is identical
        rng1 = random.Random(99999)
        rng2 = random.Random(99999)
        fill1 = simulate_paper_fill(intent, _rng=rng1)

        # Modify no-op fields
        intent2 = replace(
            intent,
            edge_pct=10.0,
            source="different",
            rationale="Different rationale",
            confidence=0.95,
        )
        fill2 = simulate_paper_fill(intent2, _rng=rng2)

        # Core economics + intent_id unchanged → same fill_id
        assert fill1["fill_id"] == fill2["fill_id"]

    def test_idempotency_key_prefers_client_tag(self):
        """idempotency_key should use client_tag when present."""
        intent = OrderIntent(
            ticker="KXBTC-25DEC-ABOVE-100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
            client_tag="my-stable-tag-123",
        )
        fill = simulate_paper_fill(intent)

        assert fill["idempotency_key"] == "my-stable-tag-123"
        assert fill["idempotency_key"] != intent.intent_id

    def test_idempotency_key_falls_back_to_intent_id(self):
        """idempotency_key should use intent_id when client_tag is None."""
        intent = OrderIntent(
            ticker="KXBTC-25DEC-ABOVE-100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=10,
        )
        assert intent.client_tag is None

        fill = simulate_paper_fill(intent)

        assert fill["idempotency_key"] == intent.intent_id
        assert fill["idempotency_key"] is not None

    def test_source_and_version_always_present(self):
        """Every paper fill must have source='paper' and canonical_hash_version='v1'."""
        intent = OrderIntent(ticker="KXBTC", side="yes", action="buy", price_cents=50, count=5)
        fill = simulate_paper_fill(intent)

        assert fill["source"] == "paper"
        assert fill["canonical_hash_version"] == "v1"
        assert "hash_preimage" in fill
        assert fill["hash_preimage"] is not None
        assert fill["hash_preimage"] != ""

    def test_fill_id_starts_with_paper_prefix(self):
        """All paper fills must have fill_id starting with 'paper_'."""
        intent = OrderIntent(ticker="KXBTC", side="yes", action="buy", price_cents=50, count=5)
        fill = simulate_paper_fill(intent)

        assert fill["fill_id"].startswith("paper_"), f"Bad fill_id: {fill['fill_id']}"


class TestPaperFillSerialization:
    """Validate JSON round-tripping preserves types."""

    def test_numeric_types_preserved_after_json_roundtrip(self):
        """price_cents and count must remain ints after JSON round-trip."""
        intent = OrderIntent(ticker="KXBTC", side="yes", action="buy", price_cents=55, count=10)
        fill = simulate_paper_fill(intent)

        # Simulate serialization (event bus, then deserialization)
        json_str = json.dumps(fill)
        reconstructed = json.loads(json_str)

        # Types preserved
        assert isinstance(reconstructed["price_cents"], int)
        assert isinstance(reconstructed["count"], int)
        assert isinstance(reconstructed["requested_price_cents"], int)
        assert isinstance(reconstructed["requested_count"], int)

        # Values match
        assert reconstructed["price_cents"] == fill["price_cents"]
        assert reconstructed["count"] == fill["count"]


# ═══════════════════════════════════════════════════════════════════════════
# Downstream: fills_ledger parsing tests
# ═══════════════════════════════════════════════════════════════════════════

class TestLedgerParseFill:
    """Validate _parse_fill correctly extracts paper fill metadata."""

    @pytest.fixture
    def ledger(self):
        return KalshiFillsLedger()

    def test_parse_fill_extracts_paper_metadata(self, ledger):
        """_parse_fill must populate idempotency_key, canonical_hash_version, hash_preimage."""
        paper_payload = {
            "fill_id": "paper_1234567890",
            "hash_preimage": "intent_abc:KXBTC:yes:buy:10:55",
            "source": "paper",
            "idempotency_key": "my-idempotency-key",
            "canonical_hash_version": "v1",
            "ticker": "KXBTC",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "count": 10,
            "ts": "2026-03-27T20:00:00+00:00",
        }

        fill = ledger._parse_fill(paper_payload, "http_poller")

        assert fill.fill_id == "paper_1234567890"
        assert fill.idempotency_key == "my-idempotency-key"
        assert fill.canonical_hash_version == "v1"
        assert fill.hash_preimage == "intent_abc:KXBTC:yes:buy:10:55"
        assert fill.ingestion_source == "http_poller"

    def test_parse_fill_handles_missing_paper_fields(self, ledger):
        """Legacy/live fills without paper fields should have None for new fields."""
        live_payload = {
            "fill_id": "live_abc123",
            "trade_id": "trade_123",
            "ticker": "KXBTC",
            "side": "yes",
            "action": "buy",
            "price": 0.55,
            "count": 10,
            "created_at": "2026-03-27T20:00:00+00:00",
        }

        fill = ledger._parse_fill(live_payload, "http_poller")

        assert fill.fill_id == "live_abc123"
        assert fill.idempotency_key is None
        assert fill.canonical_hash_version is None
        assert fill.hash_preimage is None


# ═══════════════════════════════════════════════════════════════════════════
# Integration: End-to-end idempotency tests
# ═══════════════════════════════════════════════════════════════════════════

class TestEndToEndIdempotency:
    """Validate duplicate detection and replay behavior."""

    @pytest.fixture
    def fresh_ledger(self):
        """Fresh ledger instance that bypasses singleton and DB loading."""
        led = object.__new__(KalshiFillsLedger)
        led._initialized = False
        led.__init__()
        # Don't call start() to avoid loading from DB
        return led

    @pytest.mark.asyncio
    async def test_duplicate_fill_id_dropped(self, fresh_ledger):
        """Sending same paper fill twice should result in single ledger entry."""
        import random
        intent = OrderIntent(ticker="KXBTC", side="yes", action="buy", price_cents=50, count=5)
        # Use seeded RNG for determinism
        rng = random.Random(12345)
        fill_payload = simulate_paper_fill(intent, _rng=rng)

        # First ingest
        count1, _ = await fresh_ledger.ingest_http_fills([fill_payload])
        assert count1 == 1

        # Second ingest (duplicate)
        count2, _ = await fresh_ledger.ingest_http_fills([fill_payload])
        assert count2 == 0  # Dropped as duplicate

        # Verify only one fill in ledger
        fills = fresh_ledger.get_fills()
        assert len(fills) == 1
        assert fills[0].fill_id == fill_payload["fill_id"]

    @pytest.mark.asyncio
    async def test_different_intents_same_economics_both_stored(self, fresh_ledger):
        """Two different intents with same ticker/side/price/count should both be stored."""
        import random
        base = {"ticker": "KXBTC", "side": "yes", "action": "buy", "price_cents": 50, "count": 5}

        intent1 = OrderIntent(**base)
        intent2 = OrderIntent(**base)

        # Use same RNG seed but different intents → different fill_ids
        rng1 = random.Random(12345)
        rng2 = random.Random(12345)

        fill1 = simulate_paper_fill(intent1, _rng=rng1)
        fill2 = simulate_paper_fill(intent2, _rng=rng2)

        # Different intent_ids → different fill_ids
        assert fill1["fill_id"] != fill2["fill_id"]

        count1, _ = await fresh_ledger.ingest_http_fills([fill1])
        count2, _ = await fresh_ledger.ingest_http_fills([fill2])

        assert count1 == 1
        assert count2 == 1

        fills = fresh_ledger.get_fills()
        assert len(fills) == 2


# ═══════════════════════════════════════════════════════════════════════════
# Invariant enforcement
# ═══════════════════════════════════════════════════════════════════════════

class TestPaperFillInvariants:
    """Hard assertions about paper fill structure."""

    def test_paper_fill_invariants(self):
        """Paper fills must satisfy: source='paper', fill_id starts with 'paper_', hash_preimage non-empty."""
        intent = OrderIntent(ticker="KXBTC", side="yes", action="buy", price_cents=50, count=5)
        fill = simulate_paper_fill(intent)

        # Invariant assertions
        assert fill["source"] == "paper", f"Paper fill missing source='paper': {fill}"
        assert fill["fill_id"].startswith("paper_"), f"Paper fill_id missing prefix: {fill['fill_id']}"
        assert fill["hash_preimage"], f"Paper fill missing hash_preimage: {fill}"
        assert fill["canonical_hash_version"] == "v1", f"Paper fill wrong version: {fill}"
        assert fill["idempotency_key"], f"Paper fill missing idempotency_key: {fill}"


# ═══════════════════════════════════════════════════════════════════════════
# Multi-ticker coverage (BTC/ETH/SOL/XRP/DOGE)
# ═══════════════════════════════════════════════════════════════════════════

class TestMultiTickerCoverage:
    """Validate contract holds across all crypto tickers."""

    @pytest.mark.parametrize("ticker", [
        "KXBTC-25DEC-ABOVE-100000",
        "KXETH-25DEC-ABOVE-3000",
        "KXSOL-25DEC-ABOVE-200",
        "KXXRP-25DEC-ABOVE-1",
        "KXDOGE-25DEC-ABOVE-0.1",
    ])
    def test_paper_fill_contract_for_ticker(self, ticker):
        """Paper fill contract valid for all crypto tickers."""
        intent = OrderIntent(ticker=ticker, side="yes", action="buy", price_cents=55, count=10)
        fill = simulate_paper_fill(intent)

        # All invariants hold
        assert fill["source"] == "paper"
        assert fill["fill_id"].startswith("paper_")
        assert fill["canonical_hash_version"] == "v1"
        assert fill["hash_preimage"]
        assert ticker in fill["hash_preimage"]
