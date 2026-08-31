"""Tests for the 2026-08-13 canonicalization split and migration.

Verifies that:
- KalshiFill records carry schema and canonicalization provenance.
- Legacy SQLite rows without canonical fields are backfilled from raw execution facts.
- Legacy rows without usable execution facts are marked UNTRUSTED_LEGACY and
  quarantined (unmatched=True).
- Untrusted legacy fills are excluded from live position replay and trigger a
  REST-reconciliation requirement for the ticker.
- The `_parse_fill` canonicalization uses exchange execution facts, not intent,
  and logs but does not apply side conflicts.
"""

import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import AsyncGenerator

import aiosqlite
import pytest

from merid.event_venues.kalshi.fills_ledger import (
    KalshiFill,
    KalshiFillsLedger,
    OrderIntent,
    derive_position_effect,
)
from merid.event_venues.kalshi.position_cache import get_position_cache


@pytest.fixture
async def fresh_ledger(monkeypatch, tmp_path) -> AsyncGenerator[KalshiFillsLedger, None]:
    """Provide an isolated fills ledger with a temp SQLite DB."""
    db_path = tmp_path / "kalshi_fills.db"
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(db_path))
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    # Reset singleton state
    KalshiFillsLedger._initialized = False
    KalshiFillsLedger._instance = None

    ledger = KalshiFillsLedger()
    ledger._fills = {}
    ledger._intents = {}
    ledger._fills_by_order = {}
    ledger._fills_by_market = {}

    yield ledger

    await ledger.shutdown()
    KalshiFillsLedger._initialized = False
    KalshiFillsLedger._instance = None


class TestDerivePositionEffect:
    """Unit tests for the pure execution-derived canonicalizer."""

    def test_buy_yes_long_yes(self):
        effect = derive_position_effect(
            execution_outcome_side="yes",
            execution_action="buy",
            execution_price_cents=55,
            quantity_cc=100,
        )
        assert effect["canonical_position_side"] == "yes"
        assert effect["canonical_position_action"] == "buy"
        assert effect["canonical_leg_price_cents"] == 55
        assert effect["canonical_yes_delta_cc"] == 100
        assert effect["canonicalization_state"] == "TRUSTED_LIVE_V1"

    def test_sell_no_long_yes(self):
        # Raw user execution: SELL NO -> canonical position side/action are the
        # user's order side/action, yes_delta is positive (long YES).
        effect = derive_position_effect(
            execution_outcome_side="no",
            execution_action="sell",
            execution_price_cents=40,
            yes_price_cents=60,
            no_price_cents=40,
            quantity_cc=100,
            is_exit=False,
        )
        assert effect["canonical_position_side"] == "no"
        assert effect["canonical_position_action"] == "sell"
        assert effect["canonical_leg_price_cents"] == 40
        assert effect["canonical_yes_delta_cc"] == 100
        assert effect["canonicalization_state"] == "TRUSTED_LIVE_V1"

    def test_buy_no_long_no(self):
        effect = derive_position_effect(
            execution_outcome_side="no",
            execution_action="buy",
            execution_price_cents=32,
            yes_price_cents=68,
            no_price_cents=32,
            quantity_cc=100,
            is_exit=False,
        )
        assert effect["canonical_position_side"] == "no"
        assert effect["canonical_position_action"] == "buy"
        assert effect["canonical_leg_price_cents"] == 32
        assert effect["canonical_yes_delta_cc"] == -100
        assert effect["canonicalization_state"] == "TRUSTED_LIVE_V1"

    def test_sell_yes_long_no(self):
        # Raw user execution: SELL YES -> canonical position side/action are the
        # user's order side/action, yes_delta is negative (long NO).
        effect = derive_position_effect(
            execution_outcome_side="yes",
            execution_action="sell",
            execution_price_cents=70,
            yes_price_cents=70,
            no_price_cents=30,
            quantity_cc=100,
            is_exit=False,
        )
        assert effect["canonical_position_side"] == "yes"
        assert effect["canonical_position_action"] == "sell"
        assert effect["canonical_leg_price_cents"] == 70
        assert effect["canonical_yes_delta_cc"] == -100
        assert effect["canonicalization_state"] == "TRUSTED_LIVE_V1"

    def test_untrusted_raw_missing_side(self):
        effect = derive_position_effect(
            execution_outcome_side=None,
            execution_action="buy",
            execution_price_cents=50,
            quantity_cc=100,
        )
        assert effect["canonicalization_state"] == "UNTRUSTED_RAW"
        assert effect["canonical_position_side"] is None


class TestKalshiFillProvenance:
    """New fills must carry schema and canonicalization provenance."""

    @pytest.mark.asyncio
    async def test_new_fill_schema_version(self, fresh_ledger: KalshiFillsLedger) -> None:
        raw = {
            "fill_id": "fill-schema-001",
            "market_ticker": "KXETH15M-TEST",
            "outcome_side": "no",
            "side": "no",
            "action": "buy",
            "yes_price_dollars": "0.6800",
            "no_price_dollars": "0.3200",
            "count_fp": "1",
            "fee_cost": "0",
            "created_time": datetime.now(timezone.utc).isoformat(),
        }
        fill = fresh_ledger._parse_fill(raw, "http_poller")
        assert fill.ledger_schema_version == 3
        assert fill.canonicalization_version == 1
        assert fill.canonicalization_state == "TRUSTED_LIVE_V1"
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "buy"


class TestLegacyMigration:
    """SQLite rows written before the canonical columns must be migrated."""

    @pytest.mark.asyncio
    async def test_legacy_row_backfill_from_raw(self, fresh_ledger: KalshiFillsLedger, tmp_path) -> None:
        """A legacy row with side/action/price is backfilled to schema version 2."""
        db_path = tmp_path / "kalshi_fills.db"

        # Create a pre-canonical (v1) table and insert one legacy row.
        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS kalshi_fills (
                    fill_id TEXT PRIMARY KEY,
                    market_ticker TEXT NOT NULL,
                    side TEXT,
                    action TEXT,
                    count_fp TEXT,
                    quantity_cc INTEGER DEFAULT 0,
                    yes_price_dollars REAL,
                    no_price_dollars REAL,
                    fee_cost REAL,
                    created_time TEXT,
                    ingestion_source TEXT,
                    ingested_at TEXT,
                    agent_id TEXT,
                    intent_id TEXT,
                    reconciled INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                INSERT INTO kalshi_fills
                (fill_id, market_ticker, side, action, count_fp, quantity_cc,
                 yes_price_dollars, no_price_dollars, fee_cost, created_time,
                 ingestion_source, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "legacy-001",
                "KXBTC15M-TEST",
                "no",
                "buy",
                "1",
                100,
                0.68,
                0.32,
                0.0,
                datetime.now(timezone.utc).isoformat(),
                "http_poller",
                datetime.now(timezone.utc).isoformat(),
            ))
            await db.commit()

        # Loading from DB should migrate the table and backfill canonical fields.
        loaded = await fresh_ledger.load_from_db()
        assert loaded == 1

        fill = fresh_ledger.get_fill_by_id("legacy-001")
        assert fill is not None
        assert fill.ledger_schema_version == 2
        assert fill.canonicalization_version == 1
        assert fill.canonicalization_state == "TRUSTED_BACKFILLED_V1"
        assert fill.canonical_position_side == "no"
        assert fill.canonical_position_action == "buy"
        assert fill.canonical_yes_delta_cc == -100
        assert fill.canonical_leg_price_cents == 32
        assert fill.unmatched is False

        # The backfilled row contributes to live position math.
        pos = fresh_ledger.compute_position_from_fills("KXBTC15M-TEST")
        assert pos is not None
        assert pos["side"] == "no"
        assert pos["quantity_cc"] == 100
        assert pos["signed_yes_exposure"] == -100
        assert pos["excluded_from_live_replay"] == 0

        # Migration summary reflects a single trusted backfill.
        summary = fresh_ledger.get_migration_summary()
        assert summary["legacy_rows_total"] == 1
        assert summary["trusted_backfilled_rows"] == 1
        assert summary["untrusted_legacy_rows"] == 0
        assert summary["rows_excluded_from_live_replay"] == 0

    @pytest.mark.asyncio
    async def test_legacy_untrusted_row_quarantined(self, fresh_ledger: KalshiFillsLedger, tmp_path) -> None:
        """A legacy row with no usable execution facts is marked UNTRUSTED_LEGACY."""
        db_path = tmp_path / "kalshi_fills.db"

        async with aiosqlite.connect(str(db_path)) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS kalshi_fills (
                    fill_id TEXT PRIMARY KEY,
                    market_ticker TEXT NOT NULL,
                    side TEXT,
                    action TEXT,
                    count_fp TEXT,
                    quantity_cc INTEGER DEFAULT 0,
                    yes_price_dollars REAL,
                    no_price_dollars REAL,
                    fee_cost REAL,
                    created_time TEXT,
                    ingestion_source TEXT,
                    ingested_at TEXT,
                    agent_id TEXT,
                    intent_id TEXT,
                    reconciled INTEGER DEFAULT 0
                )
            """)
            await db.execute("""
                INSERT INTO kalshi_fills
                (fill_id, market_ticker, side, action, count_fp, quantity_cc,
                 yes_price_dollars, no_price_dollars, fee_cost, created_time,
                 ingestion_source, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "legacy-untrusted-001",
                "KXBTC15M-TEST",
                None,
                None,
                "1",
                100,
                0.50,
                0.50,
                0.0,
                datetime.now(timezone.utc).isoformat(),
                "http_poller",
                datetime.now(timezone.utc).isoformat(),
            ))
            await db.commit()

        loaded = await fresh_ledger.load_from_db()
        assert loaded == 1

        fill = fresh_ledger.get_fill_by_id("legacy-untrusted-001")
        assert fill is not None
        assert fill.ledger_schema_version == 2
        assert fill.canonicalization_version == 1
        assert fill.canonicalization_state == "UNTRUSTED_LEGACY"
        assert fill.unmatched is True
        assert fill.unmatched_reason == "untrusted_legacy"
        assert fill.canonical_position_side is None
        assert fill.canonical_position_action is None
        assert fill.canonical_yes_delta_cc is None

        # UNTRUSTED_LEGACY rows must not be used to construct a live position.
        pos = fresh_ledger.compute_position_from_fills("KXBTC15M-TEST")
        assert pos is None

        # The ticker is flagged for exchange REST reconciliation before entry.
        assert "KXBTC15M-TEST" in fresh_ledger.get_untrusted_legacy_tickers()
        cache = get_position_cache()
        assert cache._reconciliation_halted.get("KXBTC15M-TEST") is True

        # Migration summary records the quarantine.
        summary = fresh_ledger.get_migration_summary()
        assert summary["legacy_rows_total"] == 1
        assert summary["trusted_backfilled_rows"] == 0
        assert summary["untrusted_legacy_rows"] == 1
        assert summary["rows_excluded_from_live_replay"] == 1

    @pytest.mark.asyncio
    async def test_untrusted_fill_does_not_apply_to_position_cache(self, fresh_ledger: KalshiFillsLedger) -> None:
        """A UNTRUSTED_LEGACY fill must not mutate the position cache."""
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=50,
            fee_cents=0,
            side="yes",
            client_order_id="coid-untrusted",
            fill_id="fill-untrusted-cache",
            action="buy",
            canonicalization_state="UNTRUSTED_LEGACY",
        )
        assert "KXETH15M-TEST" not in cache._positions
        assert "fill-untrusted-cache" not in cache._applied_fill_ids

    @pytest.mark.asyncio
    async def test_none_canonicalization_state_fails_closed(self, fresh_ledger: KalshiFillsLedger) -> None:
        """A fill with canonicalization_state=None is treated as UNTRUSTED_RAW."""
        cache = get_position_cache()
        cache._positions = {}
        cache._applied_fill_ids.clear()
        cache._reconciliation_halted.clear()

        await cache.on_fill(
            market_id="KXETH15M-TEST",
            contracts=1,
            quantity_cc=100,
            price_cents=50,
            fee_cents=0,
            side="yes",
            client_order_id="coid-none",
            fill_id="fill-none-cache",
            action="buy",
            canonicalization_state=None,
        )
        assert "KXETH15M-TEST" not in cache._positions
        assert "fill-none-cache" not in cache._applied_fill_ids
        assert cache._reconciliation_halted.get("KXETH15M-TEST") is True

        # A manually constructed KalshiFill with no state must not build a position.
        fill = KalshiFill(
            fill_id="fill-none-ledger",
            market_ticker="KXETH15M-TEST",
            side="yes",
            action="buy",
            count_fp=1,
            quantity_cc=100,
            yes_price_dollars=Decimal("0.50"),
            fee_cost=Decimal("0"),
        )
        fresh_ledger._fills = {fill.fill_id: fill}
        fresh_ledger._fills_by_market = {fill.market_ticker: [fill.fill_id]}
        pos = fresh_ledger.compute_position_from_fills(fill.market_ticker)
        assert pos is None
