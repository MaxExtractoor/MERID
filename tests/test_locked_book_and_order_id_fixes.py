"""Tests for 2026-09-25 fixes:

1. Locked books (bid == ask) are legal on Kalshi during fast crosses — the
   liquidation quote must not mark them incoherent; only strict cross
   (bid > ask) is invalid.  Market-state and quote coherence now agree.
2. Confirmed full-execution exits must retain the authoritative order_id via
   the attempt/monitor/fills-ledger fallback chain instead of logging
   ``order_id=None``.
"""

from types import SimpleNamespace

from merid.event_venues.kalshi.settlement_aligned_exit import (
    build_liquidation_quote,
)
from merid.loop_15m import _resolve_exit_order_id


def _state(bid, ask, **kw):
    ns = SimpleNamespace(
        best_bid_cents=bid,
        best_ask_cents=ask,
        best_bid_size=5,
        live_sequence_confirmed=True,
        snapshot_complete=True,
        transition="VALID",
        book_health="LIVE",
        data_quality="GOOD",
        book_source="WS_ORDERBOOK_DELTA_LIVE",
        executable=True,
        last_book_update_ts=None,
        last_ws_update_ts=None,
    )
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


class TestLiquidationQuoteCoherence:
    def test_locked_book_is_coherent(self):
        # bid == ask: legal Kalshi locked market; resting bid executable.
        q = build_liquidation_quote(
            "KXBTC15M-26SEP250845-45", "yes",
            kalshi_state=_state(79, 79),
        )
        assert q.coherent is True
        assert q.invalid_reason is None
        assert q.bid_cents == 79

    def test_crossed_book_is_incoherent(self):
        # bid > ask: strict inversion -> corrupt split-tape book.
        q = build_liquidation_quote(
            "KXBTC15M-26SEP250845-45", "yes",
            kalshi_state=_state(85, 80),
        )
        assert q.coherent is False
        assert q.invalid_reason == "crossed_book"

    def test_locked_no_side_is_coherent(self):
        # Same-side quote for held=NO uses explicit NO-space prices; the
        # helper deliberately never synthesizes them from the YES side.
        q = build_liquidation_quote(
            "KXBTC15M-26SEP250845-45", "no",
            kalshi_state=_state(79, 79, best_no_bid_cents=21, best_no_ask_cents=21),
        )
        assert q.coherent is True
        assert q.invalid_reason is None
        assert q.bid_cents == 21


class _Fills:
    def __init__(self, fills):
        self._fills = fills

    def get_fills_by_market(self, market_id):
        return list(self._fills)


class TestResolveExitOrderId:
    _pos = SimpleNamespace(position_id="pos12345", market_id="KXBTC15M-T-45")
    _intent = SimpleNamespace(client_order_id="cli-abc")

    def test_result_order_id_wins(self):
        result = SimpleNamespace(order_id="ord-from-result")
        assert _resolve_exit_order_id(result, None, self._pos, self._intent) == "ord-from-result"

    def test_durable_attempt_fallback(self):
        result = SimpleNamespace(order_id=None)
        attempt = SimpleNamespace(exchange_order_id="ord-from-attempt")
        assert _resolve_exit_order_id(result, attempt, self._pos, self._intent) == "ord-from-attempt"

    def test_monitor_registry_fallback(self):
        monitor = SimpleNamespace()
        monitor._get_exit_orders_for_position = lambda pid: ["ord-1", "ord-2"]
        result = SimpleNamespace(order_id=None)
        assert _resolve_exit_order_id(result, None, self._pos, self._intent, monitor) == "ord-2"

    def test_genuinely_missing_returns_none(self):
        result = SimpleNamespace(order_id=None)
        assert _resolve_exit_order_id(result, None, self._pos, self._intent) is None
