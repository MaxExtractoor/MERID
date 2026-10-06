"""Regression tests for the 2026-10-06 XRP early-exit defect.

Live incident: KXXRP15M-26OCT061500-00 was opened long NO via a complement-form
SELL_YES fill (YES leg 16c == NO leg 84c).  The ledger recompute produced the
correct held-side basis (84c), but the reconstructed CachedPosition carried
``entry_price_state="unknown"`` and ``entry_fill_price_cents=16`` (raw YES
execution leg).  The REST-sync monitor handoff therefore substituted a YES-mid
fallback (~17-20c) for the entry basis.  The exit engine computed a phantom
+56c profit and trailed out at 76-77c — realizing roughly -8.2c (entry 84,
exit 77, ~1.24c fee) while logging a win.

These tests pin the held-side basis invariants:
  - complement-form entries (SELL_YES opening long NO) record the NO leg as
    the basis and entry anchor;
  - ledger-reconstructed positions are marked trusted (entry_price_state
    "known") so the monitor handoff never replaces them with a market-price
    fallback;
  - the market-price fallback is side-aware (NO positions get the complement);
  - a flip residual re-anchors basis in the NEW held side;
  - closing a long NO at 77 after entry at 84 books approximately -8.2c and
    never a phantom positive PnL.
"""

from decimal import Decimal

import pytest

from merid.event_venues.kalshi.fills_ledger import KalshiFill
from merid.event_venues.kalshi.position_cache import (
    CachedPosition,
    KalshiPositionCache,
    _get_fallback_price_for_market,
)

TICKER = "KXXRP15M-26OCT061500-00"
AGENT = "kalshi_15m_agent"


def _fill(fill_id, *, side, action, qty_cc, yes_cents, no_cents,
          canon_side=None, canon_action=None, canon_leg=None,
          delta_cc=None, proceeds=None, fee="0.01", client_order_id="coid-x",
          order_id="ord-x", is_exit=None, entry_or_exit=None):
    """Build a KalshiFill with canonical fields like production records."""
    if canon_side is None:
        canon_side = side
    if canon_action is None:
        canon_action = action
    if canon_leg is None:
        canon_leg = yes_cents if canon_side == "yes" else no_cents
    if delta_cc is None:
        delta_cc = qty_cc if (canon_action, canon_side) in (("buy", "yes"), ("sell", "no")) else -qty_cc
    return KalshiFill(
        fill_id=fill_id,
        market_ticker=TICKER,
        side=side,
        action=action,
        count_fp=Decimal(qty_cc) / Decimal("100"),
        quantity_cc=qty_cc,
        yes_price_dollars=Decimal(yes_cents) / Decimal("100"),
        no_price_dollars=Decimal(no_cents) / Decimal("100"),
        fee_cost=Decimal(fee),
        proceeds_dollars=Decimal(proceeds) if proceeds is not None else None,
        client_order_id=client_order_id,
        order_id=order_id,
        agent_id=AGENT,
        fill_source="http_poller",
        execution_price_cents=yes_cents if canon_side == "yes" else no_cents,
        canonical_position_side=canon_side,
        canonical_position_action=canon_action,
        canonical_leg_price_cents=canon_leg,
        canonical_yes_delta_cc=delta_cc,
        is_exit=is_exit,
        entry_or_exit=entry_or_exit,
    )


class _FakeLedger:
    def __init__(self, fills):
        self._fills = list(fills)

    def get_fills_by_market(self, market_id):
        return [f for f in self._fills if f.market_ticker == market_id]


def _cache_with_fills(fills):
    cache = KalshiPositionCache()
    cache._fills_ledger = _FakeLedger(fills)
    cache._pending_tp_targets = {}
    cache._order_id_to_client_tag = {}
    # Keep provenance rehydration out of the test surface.
    cache.rehydrate_cached_position = lambda p: p
    return cache


async def test_recompute_complement_entry_uses_no_leg_basis():
    """SELL_YES@16 (NO leg 84) opening long NO must rebuild with basis 84."""
    entry = _fill(
        "f-entry", side="yes", action="sell", qty_cc=100,
        yes_cents=16, no_cents=84,
        canon_side="yes", canon_action="sell", canon_leg=16, delta_cc=-100,
        proceeds="-0.84", entry_or_exit="entry", is_exit=False,
    )
    cache = _cache_with_fills([entry])
    pos = await cache.recompute_position_from_ledger(TICKER, AGENT)

    assert pos is not None
    assert pos.thesis_side == "no" and pos.side == "no"
    assert pos.quantity_cc == 100
    # Held-side basis: the NO leg (84), NOT the YES execution leg (16).
    assert pos.avg_price_cents == 84
    assert pos.entry_fill_price_cents == 84
    # The basis came from the durable ledger — it is trusted, and the monitor
    # handoff must not substitute a market-price fallback for it.
    assert pos.entry_price_state == "known"


async def test_recompute_flat_after_close_returns_none():
    """Entry + full close replayed -> no residual position."""
    entry = _fill(
        "f-entry", side="yes", action="sell", qty_cc=100,
        yes_cents=16, no_cents=84, canon_leg=16, delta_cc=-100,
        proceeds="-0.84", is_exit=False,
    )
    exit_ = _fill(
        "f-exit", side="no", action="sell", qty_cc=100,
        yes_cents=23, no_cents=77,
        canon_side="yes", canon_action="buy", canon_leg=23, delta_cc=+100,
        proceeds="0.7576", fee="0.0124", is_exit=True, entry_or_exit="exit",
    )
    cache = _cache_with_fills([entry, exit_])
    assert await cache.recompute_position_from_ledger(TICKER, AGENT) is None


async def test_recompute_multi_fill_vwap_held_side():
    """Two complement-form NO entries VWAP in NO space."""
    f1 = _fill("f1", side="yes", action="sell", qty_cc=100,
               yes_cents=16, no_cents=84, canon_leg=16, delta_cc=-100)
    f2 = _fill("f2", side="yes", action="sell", qty_cc=100,
               yes_cents=20, no_cents=80, canon_leg=20, delta_cc=-100)
    cache = _cache_with_fills([f1, f2])
    pos = await cache.recompute_position_from_ledger(TICKER, AGENT)

    assert pos.side == "no" and pos.quantity_cc == 200
    assert pos.avg_price_cents == 82  # (84 + 80) / 2, NO space
    assert pos.entry_price_state == "known"


async def test_recompute_flip_reanchors_to_new_held_side():
    """An over-close that flips the position re-anchors to the flip fill's
    new held-side leg, not the stale thesis leg or old epoch basis."""
    entry = _fill("f-entry", side="yes", action="sell", qty_cc=100,
                  yes_cents=16, no_cents=84, canon_leg=16, delta_cc=-100)
    flip = _fill("f-flip", side="yes", action="buy", qty_cc=200,
                 yes_cents=30, no_cents=70,
                 canon_side="yes", canon_action="buy", canon_leg=30, delta_cc=+200)
    cache = _cache_with_fills([entry, flip])
    pos = await cache.recompute_position_from_ledger(TICKER, AGENT)

    assert pos is not None
    assert pos.side == "yes" and pos.quantity_cc == 100
    assert pos.avg_price_cents == 30
    assert pos.entry_fill_price_cents == 30
    assert pos.entry_price_state == "known"


def test_fallback_price_is_held_side_aware():
    """YES mids/defaults must be complemented for a NO position."""
    yes_fb = _get_fallback_price_for_market(TICKER, held_side="yes")
    no_fb = _get_fallback_price_for_market(TICKER, held_side="no")
    assert yes_fb == 100 - no_fb or (yes_fb == 50 and no_fb == 50)
    assert no_fb == 100 - yes_fb
    # XRP asset default is 55c YES-space when no live market state exists.
    assert no_fb in (45, 50)


def _no_position(qty_cc=100, avg=84):
    return CachedPosition(
        market_id=TICKER,
        agent_id=AGENT,
        contracts=Decimal(qty_cc) / Decimal("100"),
        quantity_cc=qty_cc,
        side="no",
        thesis_side="no",
        outcome_side="no",
        book_side="ask",
        avg_price_cents=avg,
        entry_cash_proceeds_usd=Decimal(-qty_cc * avg) / Decimal("10000"),
        entry_price_state="known",
    )


def test_apply_exit_fill_books_real_loss_not_phantom_profit():
    """Long NO entry 84 -> exit fill sell NO @77 (canonical buy_yes@23)
    books ~-8.2c realized, never the +56c the corrupted basis produced."""
    pos = _no_position()
    pos.apply_fill(
        contracts=1,
        price_cents=23,          # canonical execution leg (YES)
        fee_cents=1,
        side="yes",              # canonical side of the exit fill
        action="buy",
        quantity_cc=100,
        yes_price_cents=23,
        no_price_cents=77,
        proceeds_dollars=Decimal("0.7576"),
        is_exit=True,
    )
    assert pos.quantity_cc == 0
    assert pos.contracts == 0
    # -0.0824 realized: 77c proceeds - 84c basis - ~1.24c fee (in proceeds).
    assert pos.realized_pnl_usd == pytest.approx(Decimal("-0.0824"), abs=Decimal("0.005"))
    assert pos.realized_pnl_usd < 0


def test_apply_exit_fill_partial_closes_only_filled_qty():
    """A 3-contract NO position closed by a 1-contract fill leaves 200cc
    open and books only the proportional basis."""
    pos = _no_position(qty_cc=300, avg=84)
    pos.apply_fill(
        contracts=1,
        price_cents=77,
        fee_cents=1,
        side="no",
        action="sell",
        quantity_cc=100,
        yes_price_cents=23,
        no_price_cents=77,
        proceeds_dollars=Decimal("0.7576"),
        is_exit=True,
    )
    assert pos.quantity_cc == 200
    assert pos.side == "no"
    # Basis stays 84 on the residual; realized booked only for the closed 1/3.
    assert pos.avg_price_cents == 84
    assert pos.realized_pnl_usd == pytest.approx(Decimal("-0.0824"), abs=Decimal("0.005"))
    # 2/3 of the entry cash basis remains open.
    assert pos.entry_cash_proceeds_usd == pytest.approx(Decimal("-1.68"), abs=Decimal("0.01"))
