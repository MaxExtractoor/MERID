"""Minimal repro/regression test for the SEV-1 NO-side price derivation concern.

Kalshi's orderbook carries YES bids and NO bids only; asks are derived by
duality (YES_ask = 100 - NO_bid, NO_ask = 100 - YES_bid).  This test pins the
derivation in ``KalshiMarketStateStore._sync_book_fields`` and the executable
exit-price selection in ``stop_candidate._get_executable_exit_cents`` against
an independently populated NO book:

    YES bid = 40c, NO bid = 59c  (YES ask = 41c, NO ask = 60c by duality)

If any of these derivations invert, exposure math inverts with them.
"""

from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
from merid.event_venues.kalshi.models import KalshiMarketState
from merid.event_venues.kalshi.stop_candidate import _get_executable_exit_cents


class _FakeBook:
    """Duck-typed LocalOrderbook with an independently populated NO ladder."""

    initialized = True
    yes_levels = {40: 10}  # YES bids: price_cents -> size
    no_levels = {59: 7}    # NO bids:  price_cents -> size
    _snapshot_ts = None

    def get_book(self, side, top_n=5):
        levels = self.yes_levels if side == "yes" else self.no_levels
        return sorted(levels.items(), key=lambda kv: -kv[0])[:top_n]

    def get_best_bid(self):
        return (40, 10)  # YES bid

    def get_best_ask(self):
        return (41, 5)  # YES ask (= 100 - best NO bid)

    def get_midpoint(self):
        return 40.5

    def get_spread(self):
        return 1


def _synced_state():
    store = KalshiMarketStateStore()
    state = KalshiMarketState(ticker="KXBTC15M-TEST")
    store._sync_book_fields(state, _FakeBook(), "KXBTC15M-TEST", via="ws")
    return state


def test_yes_fields_are_yes_space():
    state = _synced_state()
    assert state.best_bid_cents == 40  # YES bid, not NO
    assert state.best_ask_cents == 41  # YES ask


def test_no_fields_satisfy_duality():
    state = _synced_state()
    # NO bid comes from the actual NO ladder; NO ask derived from YES bid.
    assert state.best_no_bid_cents == 59
    assert state.best_no_ask_cents == 60  # 100 - YES bid
    # Duality identities must hold exactly.
    assert state.best_no_ask_cents == 100 - state.best_bid_cents
    assert state.best_ask_cents == 100 - state.best_no_bid_cents


def test_book_passes_duality_check_and_is_executable():
    state = _synced_state()
    # 40 + 59 = 99 -> 1c gap, within tolerance.
    assert state.executable is True


def test_executable_exit_prices_use_held_side_bid():
    state = _synced_state()
    # Long YES exits at the YES bid; long NO exits at the NO bid.
    assert _get_executable_exit_cents(state, "yes") == 40
    assert _get_executable_exit_cents(state, "no") == 59


def test_entry_pricing_formula_consistency():
    """The agent-grid entry formula (YES price = ask, NO price = 100 - YES bid)
    must agree with the book-derived NO ask."""
    state = _synced_state()
    yes_price_cents = state.best_ask_cents
    no_price_cents = 100 - state.best_bid_cents
    assert yes_price_cents == 41
    assert no_price_cents == state.best_no_ask_cents == 60
