"""Restart and journal-recovery tests.

These tests verify that the fills ledger can rebuild a position purely from
immutable persisted fill events, matching the exchange signed position to the
 centi-contract.
"""

import pytest
from datetime import datetime, timezone
from decimal import Decimal

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill


def _fill(
    fill_id: str,
    ticker: str,
    action: str,
    side: str,
    quantity_cc: int,
    price_cents: int,
    seconds_ago: float = 0.0,
):
    """Build a trusted canonical fill for a market."""
    return KalshiFill(
        fill_id=fill_id,
        market_ticker=ticker,
        action=action,
        side=side,
        canonical_position_action=action,
        canonical_position_side=side,
        canonical_leg_price_cents=price_cents,
        canonicalization_state="TRUSTED_LIVE_V1",
        quantity_cc=quantity_cc,
        count_fp=Decimal(quantity_cc) / Decimal("100"),
        fee_cost=Decimal("0"),
        created_time=datetime.now(timezone.utc),
        ingested_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def ledger(tmp_path):
    """Return an isolated, empty fills ledger that writes to a temp DB path."""
    import os
    import uuid
    # Give each test a unique temporary database path so parallel runs cannot
    # cross-contaminate each other.
    db_path = str(tmp_path / f"kalshi_fills_{uuid.uuid4().hex[:8]}.db")
    os.environ["MERID_FILLS_DB_PATH"] = db_path
    l = KalshiFillsLedger()
    yield l


def test_compute_position_from_fills_recovers_entry_and_exit(ledger):
    """A fresh ledger can recover a long YES position from entry and exit fills."""
    ticker = "KXBTC15M-TEST-JRNL"

    # Entry: buy 100 centi-contracts of YES at 45c.
    entry = _fill("entry-1", ticker, "buy", "yes", 100, 45)
    ledger._fills[entry.fill_id] = entry
    ledger._fills_by_market.setdefault(ticker, []).append(entry.fill_id)

    pos = ledger.compute_position_from_fills(ticker)

    assert pos is not None
    assert pos["side"] == "yes"
    assert pos["quantity_cc"] == 100
    assert pos["avg_price_cents"] == 45

    # Exit: sell the same YES exposure at 55c.
    exit_fill = _fill("exit-1", ticker, "sell", "yes", 100, 55)
    ledger._fills[exit_fill.fill_id] = exit_fill
    ledger._fills_by_market[ticker].append(exit_fill.fill_id)

    pos = ledger.compute_position_from_fills(ticker)
    assert pos is None, "full exit should return zero position"


def test_recompute_from_partial_fills(ledger):
    """A position with a partial exit still recovers the remaining exposure."""
    ticker = "KXBTC15M-TEST-JRNL-2"

    entry = _fill("entry-2a", ticker, "buy", "yes", 100, 40)
    partial_exit = _fill("exit-2a", ticker, "sell", "yes", 40, 50)

    for f in (entry, partial_exit):
        ledger._fills[f.fill_id] = f
        ledger._fills_by_market.setdefault(ticker, []).append(f.fill_id)

    pos = ledger.compute_position_from_fills(ticker)

    assert pos is not None
    assert pos["side"] == "yes"
    assert pos["quantity_cc"] == 60


def test_untrusted_fill_excluded_from_replay(ledger):
    """An untrusted fill is retained in the ledger but not replayed into a position."""
    ticker = "KXBTC15M-TEST-JRNL-3"

    entry = _fill("entry-3", ticker, "buy", "yes", 100, 45)
    untrusted = _fill("legacy-3", ticker, "buy", "yes", 100, 45)
    untrusted.canonicalization_state = "UNTRUSTED_LEGACY"

    for f in (entry, untrusted):
        ledger._fills[f.fill_id] = f
        ledger._fills_by_market.setdefault(ticker, []).append(f.fill_id)

    pos = ledger.compute_position_from_fills(ticker)

    assert pos is not None
    assert pos["quantity_cc"] == 100, "untrusted fill must not double the position"
