"""REST-fallback vs WS-native orderbook snapshot equivalence (P2a).

The ws_bridge REST fallback builds ``orderbook_snapshot`` messages that are
applied through the same ``LocalOrderbook.apply_snapshot`` path as native
WebSocket snapshots.  The canonical level format is ``[price_dollars, size]``
— ``LocalOrderbook`` quantizes to the documented 0.01-cent grid and supports
subpenny venue books (e.g. a 0.9910-dollar bid = 99.10c).

Regression coverage for the 2026-11-19 fix: the fallback previously rounded
REST dollar prices to integer cents (``int(round(p * 100))``).  Integer
inputs are treated as *dollars* by ``LocalOrderbook._to_cents`` (``p * 100``
cents), so every level exceeded the ``0 < price_cents < 100`` range check
and was silently dropped — the fallback produced empty books, and even had
the units been right the rounding destroyed subpenny precision.
"""

from __future__ import annotations

from decimal import Decimal

from merid.event_venues.kalshi.orderbook import LocalOrderbook

TICKER = "KXBTC15M-26NOV192200-00"


def _fallback_levels(entries):
    """Replicates the patched ws_bridge REST-fallback conversion.

    The REST client returns ``(Decimal price_dollars, Decimal size)`` tuples;
    the fallback passes ``float(price)`` dollars straight into the snapshot.
    """
    out = []
    for entry in entries or []:
        if isinstance(entry, tuple) and len(entry) == 2:
            price, size = entry[0], entry[1]
        elif hasattr(entry, "price") and hasattr(entry, "size"):
            price, size = entry.price, entry.size
        else:
            continue
        if price is not None and size is not None:
            out.append([float(price), float(size)])
    return out


def _apply(levels_yes, levels_no):
    book = LocalOrderbook(TICKER)
    book.apply_snapshot(
        {
            "type": "orderbook_snapshot",
            "ticker": TICKER,
            "yes": levels_yes,
            "no": levels_no,
            "seq": 1,
        }
    )
    return book


class TestRestFallbackSnapshotEquivalence:
    def test_rest_decimal_tuples_match_ws_native_dollars(self):
        """REST (Decimal dollars) and WS-native (float dollars) snapshots
        must produce identical normalized books."""
        # REST client output shape: (Decimal dollars, Decimal size)
        rest_yes = [(Decimal("0.9900"), Decimal("10.5")), (Decimal("0.9750"), Decimal("4"))]
        rest_no = [(Decimal("0.0200"), Decimal("7")), (Decimal("0.0150"), Decimal("2"))]

        # WS-native snapshot shape: [price_dollars float, size float]
        ws_yes = [[0.99, 10.5], [0.975, 4.0]]
        ws_no = [[0.02, 7.0], [0.015, 2.0]]

        rest_book = _apply(_fallback_levels(rest_yes), _fallback_levels(rest_no))
        ws_book = _apply(ws_yes, ws_no)

        assert dict(rest_book.yes_levels) == dict(ws_book.yes_levels)
        assert dict(rest_book.no_levels) == dict(ws_book.no_levels)
        # 0.99 dollars -> 99c YES bid; 0.02 dollars -> 2c NO bid
        assert rest_book.yes_levels[99.0] == 10.5
        assert rest_book.no_levels[2.0] == 7.0

    def test_subpenny_prices_survive_fallback(self):
        """Subpenny venue prices must not be rounded to whole cents."""
        rest_yes = [(Decimal("0.9910"), Decimal("3"))]   # 99.10c
        rest_no = [(Decimal("0.0010"), Decimal("5"))]    # 0.10c

        book = _apply(_fallback_levels(rest_yes), _fallback_levels(rest_no))

        assert 99.1 in book.yes_levels, f"subpenny YES bid lost: {dict(book.yes_levels)}"
        assert 0.1 in book.no_levels, f"subpenny NO bid lost: {dict(book.no_levels)}"
        assert 99.0 not in book.yes_levels

    def test_old_integer_cent_shape_would_have_been_dropped(self):
        """Characterizes the pre-fix bug: integer *cents* are misread as
        dollars (99 -> $99 -> 9900c) and dropped by the range check.  This
        documents why the fallback emitted empty books before the fix."""
        book = _apply([[99, 5], [97, 3]], [[1, 10]])
        assert dict(book.yes_levels) == {}
        assert dict(book.no_levels) == {}

    def test_one_sided_and_empty_books(self):
        """Empty NO side is valid (one-sided markets exist); empty both
        sides still initializes the book for delta population."""
        book = _apply(_fallback_levels([(Decimal("0.5"), Decimal("1"))]), [])
        assert book.initialized
        assert 50.0 in book.yes_levels
        assert dict(book.no_levels) == {}

        empty = _apply([], [])
        assert empty.initialized
        assert dict(empty.yes_levels) == {}
        assert dict(empty.no_levels) == {}

    def test_size_precision_preserved(self):
        """Fractional contract sizes (centi-contract grid) survive."""
        book = _apply(_fallback_levels([(Decimal("0.42"), Decimal("12.34"))]), [])
        assert book.yes_levels[42.0] == pytest_approx(12.34)


def pytest_approx(x):
    import pytest

    return pytest.approx(x)
