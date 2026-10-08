"""Canonical execution view (2026-10-08 accounting repair).

Acceptance tests for ``KalshiFillsLedger.get_canonical_fills``:
- Synthetic ``live_router_*`` mirror rows never change P&L or exposure.
- REST + WS copies of one venue fill apply exactly once (dedup by trade_id).
- Multiple fractional fills on one order_id all survive.
- Unconfirmed router mirrors surface as ``provisional``/unresolved, and stale
  unresolved rows block new entries via the canonical intent contract.
- Venue ``post_position_fp`` divergence quarantines the fill.
"""

import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, OrderIntent


@pytest.fixture
def ledger():
    return KalshiFillsLedger()


def _record_intent(ledger, client_order_id, entry_or_exit="entry",
                   side="BUY_YES", action="buy"):
    ledger.record_intent(OrderIntent(
        intent_id=client_order_id, client_order_id=client_order_id,
        ticker="KXETH15M-TEST", side=side, action=action,
        count=1, price_cents=50, entry_or_exit=entry_or_exit,
    ))


def _fill_dict(fill_id, client_order_id, side="yes", action="buy",
               count="1", yes_price="0.5000", no_price="0.5000",
               order_id=None, trade_id=None, post_position_fp=None):
    d = {
        "fill_id": fill_id,
        "market_ticker": "KXETH15M-TEST",
        "client_order_id": client_order_id,
        "outcome_side": side,
        "side": side,
        "action": action,
        "yes_price_dollars": yes_price,
        "no_price_dollars": no_price,
        "count_fp": count,
        "fee_cost": "0",
        "created_time": datetime.now(timezone.utc).isoformat(),
    }
    if order_id:
        d["order_id"] = order_id
    if trade_id:
        d["trade_id"] = trade_id
    if post_position_fp is not None:
        d["post_position_fp"] = post_position_fp
    return d


def _venue_fill(ledger, raw):
    f = ledger._parse_fill(raw, "http_poller")
    ledger._fills[f.fill_id] = f
    ledger._index_fill(f)
    return f


def _router_mirror(ledger, fill_id, order_id, proceeds="0.10", qty_cc=100):
    """A synthetic live_router_* mirror row as written at submission time."""
    from merid.event_venues.kalshi.fills_ledger import KalshiFill
    f = KalshiFill(
        fill_id=fill_id, order_id=order_id, market_ticker="KXETH15M-TEST",
        side="yes", action="sell", count_fp=Decimal("1"), quantity_cc=qty_cc,
        proceeds_dollars=Decimal(proceeds),
        canonical_position_side="yes", canonical_position_action="sell",
        canonical_yes_delta_cc=-qty_cc,
        canonicalization_state="TRUSTED_LIVE_V1",
        ingestion_source="order_router", is_live=True,
    )
    ledger._fills[f.fill_id] = f
    ledger._index_fill(f)
    return f


class TestCanonicalView:
    def test_superseded_router_row_never_counts(self, ledger):
        """Router mirror + venue twin on one order_id → venue row only."""
        _record_intent(ledger, "coid-e1")
        v = _venue_fill(ledger, _fill_dict(
            "fill-venue-1", "coid-e1", order_id="ord-1", trade_id="tid-1"))
        m = _router_mirror(ledger, "live_router_abc", "ord-1")

        view = ledger.get_canonical_fills()
        ids = [f.fill_id for f in view.authoritative]
        assert ids == ["fill-venue-1"]
        assert m in view.excluded
        # P&L over authoritative only — the mirror's proceeds must not add in.
        pnl = sum(float(f.proceeds_dollars or 0) for f in view.authoritative)
        assert pnl == float(v.proceeds_dollars)

    def test_unconfirmed_router_row_is_provisional_not_authoritative(self, ledger):
        m = _router_mirror(ledger, "live_router_orphan", "ord-orphan")
        view = ledger.get_canonical_fills()
        assert m in view.provisional
        assert view.authoritative == []
        assert view.unresolved_count == 1

    def test_rest_ws_same_trade_id_applies_once(self, ledger):
        """WS-derived row and REST row for one trade_id dedupe to a single fill."""
        _record_intent(ledger, "coid-dup")
        ws = _venue_fill(ledger, _fill_dict(
            "ws-derived-1", "coid-dup", order_id="ord-dup", trade_id="tid-dup"))
        ws.ingestion_source = "websocket"
        ws.confirmed_by_rest = False
        rest = _venue_fill(ledger, _fill_dict(
            "rest-1", "coid-dup", order_id="ord-dup", trade_id="tid-dup"))
        rest.confirmed_by_rest = True

        view = ledger.get_canonical_fills()
        assert len(view.authoritative) == 1
        kept = view.authoritative[0]
        assert kept.confirmed_by_rest  # REST-confirmed row wins
        assert len(view.excluded) == 1

    def test_multiple_fractional_fills_one_order_all_survive(self, ledger):
        """0.98 + 0.01 + 0.01 on one order = 100cc; order_id is not a dedup key."""
        _record_intent(ledger, "coid-multi")
        for i, qty in enumerate(("0.98", "0.01", "0.01")):
            _venue_fill(ledger, _fill_dict(
                f"fill-m{i}", "coid-multi", order_id="ord-multi",
                count=qty, trade_id=f"tid-m{i}"))
        view = ledger.get_canonical_fills()
        assert len(view.authoritative) == 3
        total_cc = sum(f.quantity_cc for f in view.authoritative)
        assert total_cc == 100

    def test_post_position_mismatch_quarantines(self, ledger):
        """Venue post_position_fp != ledger prior + delta → unmatched quarantine."""
        _record_intent(ledger, "coid-pp")
        f = _venue_fill(ledger, _fill_dict(
            "fill-pp", "coid-pp", count="1", post_position_fp="5.00"))
        assert f.post_position_cc == 500
        assert f.unmatched is True
        assert "post_position_mismatch" in (f.unmatched_reason or "")
        assert f.canonicalization_state == "UNTRUSTED_POST_POSITION"

    def test_post_position_match_passes(self, ledger):
        _record_intent(ledger, "coid-ok")
        f = _venue_fill(ledger, _fill_dict(
            "fill-ok", "coid-ok", count="1", post_position_fp="1.00"))
        assert f.unmatched is False
        assert f.canonical_yes_delta_cc == 100


class TestUnresolvedBlocksEntries:
    def test_stale_unresolved_router_fill_blocks_entry(self, ledger, monkeypatch):
        """A stale provisional mirror makes accounting unresolvable → entries
        fail closed; exits are unaffected."""
        stale = _router_mirror(ledger, "live_router_stale", "ord-stale")
        stale.created_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        monkeypatch.setenv("MERID_UNRESOLVED_FILL_GRACE_S", "90")
        monkeypatch.setattr(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
            lambda: ledger,
        )
        from merid.event_venues.kalshi.order_intent_contract import (
            normalize_order, validate_canonical_intent,
            OrderIntentValidationError,
        )
        from merid.event_venues.kalshi.order_router import OrderIntent as RouterIntent
        from merid.prediction.trading_mode import TradingMode

        open_intent = normalize_order(RouterIntent(
            ticker="KXETH15M-TEST", side="yes", action="buy", price_cents=50,
            count=1, mode=TradingMode.MOCK, reason="t",
            time_to_expiry_seconds=600.0,
        ), exchange_position_cc=0)
        with pytest.raises(OrderIntentValidationError) as exc:
            validate_canonical_intent(open_intent, exchange_position_cc=0)
        assert "unresolved_fill_accounting" in str(exc.value)

        # An exit intent on the same ledger still validates — exposure-reducing
        # closes must never be blocked by accounting ambiguity.
        close_intent = normalize_order(RouterIntent(
            ticker="KXETH15M-TEST", side="yes", action="sell", price_cents=50,
            count=1, mode=TradingMode.MOCK, reason="t",
            entry_or_exit="exit",
        ), exchange_position_cc=100)
        validate_canonical_intent(close_intent, exchange_position_cc=100)

    def test_fresh_unresolved_within_grace_does_not_block(self, ledger, monkeypatch):
        _router_mirror(ledger, "live_router_fresh", "ord-fresh")  # just created
        monkeypatch.setenv("MERID_UNRESOLVED_FILL_GRACE_S", "90")
        monkeypatch.setattr(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
            lambda: ledger,
        )
        from merid.event_venues.kalshi.order_intent_contract import (
            normalize_order, validate_canonical_intent,
        )
        from merid.event_venues.kalshi.order_router import OrderIntent as RouterIntent
        from merid.prediction.trading_mode import TradingMode
        open_intent = normalize_order(RouterIntent(
            ticker="KXETH15M-TEST", side="yes", action="buy", price_cents=50,
            count=1, mode=TradingMode.MOCK, reason="t",
            time_to_expiry_seconds=600.0,
        ), exchange_position_cc=0)
        validate_canonical_intent(open_intent, exchange_position_cc=0)  # no raise
