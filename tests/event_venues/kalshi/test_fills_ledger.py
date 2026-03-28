"""Tests for KalshiFillsLedger — canonical fill store.

Validates:
  - Fills require a non-empty fill_id (ghost-trade guard).
  - Duplicate WS/REST deliveries are idempotently merged (not double-counted).
  - Position reconstruction from fills is correct.
  - PnL contribution is calculated correctly.
  - Ledger provides source-of-truth for UI, position, and PnL.
"""

from __future__ import annotations

import pytest

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger


@pytest.fixture
def ledger() -> KalshiFillsLedger:
    return KalshiFillsLedger()


# ── fill_id enforcement ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fill_requires_fill_id(ledger: KalshiFillsLedger) -> None:
    """Fills without a fill_id are rejected — no ghost-trade corruption."""
    with pytest.raises(ValueError, match="fill_id"):
        await ledger.upsert(
            fill_id="",
            ticker="KXBTC-15M-T95000",
            side="yes",
            action="buy",
            count=5,
            price_cents=60,
        )


@pytest.mark.asyncio
async def test_fill_requires_fill_id_none_rejected(ledger: KalshiFillsLedger) -> None:
    """None is treated as empty and rejected."""
    with pytest.raises((ValueError, TypeError)):
        await ledger.upsert(
            fill_id=None,  # type: ignore[arg-type]
            ticker="KXBTC-15M-T95000",
            side="yes",
            action="buy",
            count=5,
            price_cents=60,
        )


# ── Basic store / retrieve ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_new_fill_stored(ledger: KalshiFillsLedger) -> None:
    new = await ledger.upsert("f-001", "KXBTC-15M-T95000", "yes", "buy", 10, 55)
    assert new is True
    assert ledger.size() == 1


@pytest.mark.asyncio
async def test_fill_is_retrievable(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-002", "KXBTC-15M-T95000", "yes", "buy", 10, 55, source="ws")
    fills = ledger.all_fills()
    assert len(fills) == 1
    assert fills[0].fill_id == "f-002"
    assert fills[0].source == "ws"


# ── Idempotent deduplication ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_fill_id_ignored(ledger: KalshiFillsLedger) -> None:
    """Second upsert with the same fill_id returns False; count stays 1."""
    r1 = await ledger.upsert("f-dup", "KXBTC-15M-T95000", "yes", "buy", 10, 55, source="rest")
    r2 = await ledger.upsert("f-dup", "KXBTC-15M-T95000", "yes", "buy", 10, 55, source="ws")
    assert r1 is True
    assert r2 is False
    assert ledger.size() == 1


@pytest.mark.asyncio
async def test_duplicate_across_rest_and_ws_paths(ledger: KalshiFillsLedger) -> None:
    """WS and REST can both deliver the same fill; only one is stored."""
    await ledger.upsert("f-x", "KXETH-T3500", "no", "sell", 3, 40, source="rest")
    await ledger.upsert("f-x", "KXETH-T3500", "no", "sell", 3, 40, source="ws")
    assert ledger.size() == 1
    # The original (rest) record wins
    assert ledger.all_fills()[0].source == "rest"


@pytest.mark.asyncio
async def test_different_fills_both_stored(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-a", "KXBTC-15M-T95000", "yes", "buy", 5, 60)
    await ledger.upsert("f-b", "KXBTC-15M-T95000", "yes", "sell", 3, 65)
    assert ledger.size() == 2


# ── Position reconstruction ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_buy_yes_adds_position(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-1", "KXBTC-T95000", "yes", "buy", 10, 55)
    positions = ledger.positions()
    assert positions.get("KXBTC-T95000") == 10


@pytest.mark.asyncio
async def test_sell_yes_reduces_position(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-1", "KXBTC-T95000", "yes", "buy", 10, 55)
    await ledger.upsert("f-2", "KXBTC-T95000", "yes", "sell", 4, 60)
    assert ledger.positions().get("KXBTC-T95000") == 6


@pytest.mark.asyncio
async def test_buy_no_is_net_short_yes(ledger: KalshiFillsLedger) -> None:
    """Buying 'no' contracts is equivalent to shorting 'yes'."""
    await ledger.upsert("f-3", "KXETH-T3500", "no", "buy", 5, 40)
    positions = ledger.positions()
    assert positions.get("KXETH-T3500") == -5


@pytest.mark.asyncio
async def test_flat_position_after_close(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-open", "KXBTC-T95000", "yes", "buy", 8, 55)
    await ledger.upsert("f-close", "KXBTC-T95000", "yes", "sell", 8, 65)
    assert ledger.positions().get("KXBTC-T95000", 0) == 0


# ── PnL ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pnl_buy_is_negative_cost(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-b", "KXBTC-T95000", "yes", "buy", 10, 60)
    # Buying 10 contracts @ 60c = -$6.00
    assert abs(ledger.realized_pnl() - (-6.0)) < 1e-9


@pytest.mark.asyncio
async def test_pnl_sell_is_positive_proceeds(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-s", "KXBTC-T95000", "yes", "sell", 5, 80)
    # Selling 5 contracts @ 80c = +$4.00
    assert abs(ledger.realized_pnl() - 4.0) < 1e-9


# ── has_fill / fills_for_ticker ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_has_fill_true(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-h", "KXBTC-T95000", "yes", "buy", 1, 50)
    assert ledger.has_fill("f-h") is True


@pytest.mark.asyncio
async def test_has_fill_false(ledger: KalshiFillsLedger) -> None:
    assert ledger.has_fill("f-missing") is False


@pytest.mark.asyncio
async def test_fills_for_ticker(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-1", "KXBTC-T95000", "yes", "buy", 5, 55)
    await ledger.upsert("f-2", "KXETH-T3500", "yes", "buy", 3, 60)
    await ledger.upsert("f-3", "KXBTC-T95000", "yes", "sell", 2, 65)
    btc_fills = ledger.fills_for_ticker("KXBTC-T95000")
    assert len(btc_fills) == 2
    assert all(f.ticker == "KXBTC-T95000" for f in btc_fills)


# ── Summary ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_summary_structure(ledger: KalshiFillsLedger) -> None:
    await ledger.upsert("f-s1", "KXBTC-T95000", "yes", "buy", 5, 55)
    s = ledger.summary()
    assert "fill_count" in s
    assert "realized_pnl" in s
    assert "positions" in s
    assert s["fill_count"] == 1
