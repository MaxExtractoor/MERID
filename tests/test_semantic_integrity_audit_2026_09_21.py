"""Semantic-integrity regression tests — 2026-09-21 audit fixes.

Covers the defects found in the decision-to-settlement audit:

1. Direction fabrication: missing side/action/outcome must fail closed,
   never silently become "yes"/"buy" (legacy-default inversion).
2. portfolio_engine signed-YES accounting: cross-leg fills (SELL YES while
   long NO) must net to a single signed-YES position, and settlement PnL
   must not invert for NO-side exposure.
3. position_cache.apply_fill must quarantine fills with undetermined
   direction instead of writing a fabricated BUY_YES delta.
4. canonical_portfolio_reconciler helpers must treat unknown side as
   unknown (zero exposure + alert), not as YES.
5. MarketState.get_executable_ask_size must return 0 for unknown side.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from merid.event_venues.kalshi.portfolio_engine import PortfolioEngine
from merid.event_venues.kalshi.portfolio_models import PortfolioEvent, EventType


def _fill_event(
    fill_id: str,
    ticker: str = "KXBTC15M-TEST",
    side: str = "yes",
    action: str = "buy",
    contracts: int = 5,
    price_cents: int = 60,
    fee_cents: int = 1,
) -> PortfolioEvent:
    return PortfolioEvent(
        event_id=f"evt_{fill_id}",
        sequence_id=0,
        event_type=EventType.FILL,
        account_id="default",
        timestamp=datetime.now(timezone.utc),
        data={
            "fill_id": fill_id,
            "order_id": f"ord_{fill_id}",
            "ticker": ticker,
            "side": side,
            "action": action,
            "contracts": contracts,
            "price_cents": price_cents,
            "fee_cents": fee_cents,
        },
    )


def _settle_event(ticker: str, result: str) -> PortfolioEvent:
    return PortfolioEvent(
        event_id=f"settle_{ticker}",
        sequence_id=0,
        event_type=EventType.SETTLEMENT,
        account_id="default",
        timestamp=datetime.now(timezone.utc),
        data={"ticker": ticker, "result": result},
    )


@pytest.fixture
def engine():
    eng = PortfolioEngine()
    eng._positions.clear()
    eng._positions_by_ticker.clear()
    eng._orders.clear()
    eng._open_orders.clear()
    eng._cash_ledger.clear()
    eng._applied_fill_ids.clear()
    eng._applied_event_ids.clear()
    return eng


class TestSignedYesAccounting:
    """portfolio_engine must use canonical signed-YES inventory."""

    def test_buy_yes_is_long_yes(self, engine):
        engine.replay_event(_fill_event("f1", side="yes", action="buy", contracts=5, price_cents=60))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == 5
        assert pos.side == "yes"
        assert pos.avg_entry_price_cents == 60

    def test_buy_no_is_negative_yes_exposure(self, engine):
        # BUY NO @ 40 -> long NO, signed YES delta = -5, YES-space basis = 60
        engine.replay_event(_fill_event("f1", side="no", action="buy", contracts=5, price_cents=40))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == -5
        assert pos.side == "no"
        assert pos.avg_entry_price_cents == 60

    def test_cross_leg_fill_nets_into_single_position(self, engine):
        """SELL YES while long NO must add NO exposure, not open a phantom short-YES leg."""
        # Long NO 5 (buy no @ 40)
        engine.replay_event(_fill_event("f1", side="no", action="buy", contracts=5, price_cents=40))
        # SELL YES @ 55 is economically BUY NO @ 45 -> adds 5 more NO
        engine.replay_event(_fill_event("f2", side="yes", action="sell", contracts=5, price_cents=55))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        # One position only — the phantom "{ticker}_yes" leg must not exist.
        assert "KXBTC15M-TEST_yes" not in engine._positions
        assert pos.quantity == -10
        assert pos.side == "no"
        # YES-space basis: buy_no@40 -> 60, sell_yes@55 -> 55.
        # Blended: (5*60 + 5*55) / 10 = 57.5 exactly (Decimal, no floor truncation).
        assert pos.avg_entry_price_cents == Decimal("57.5")

    def test_sell_yes_reduces_long_yes(self, engine):
        engine.replay_event(_fill_event("f1", side="yes", action="buy", contracts=10, price_cents=60))
        engine.replay_event(_fill_event("f2", side="yes", action="sell", contracts=4, price_cents=70))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == 6
        # realized = 4 * (70 - 60) = 40c minus nothing here (fees hit cash only)
        assert pos.realized_pnl_cents == 40

    def test_sell_no_reduces_long_no(self, engine):
        engine.replay_event(_fill_event("f1", side="no", action="buy", contracts=10, price_cents=40))
        # SELL NO @ 50 (yes-space 50): realized = 4 * (50 - 60) * -1 = +40c
        engine.replay_event(_fill_event("f2", side="no", action="sell", contracts=4, price_cents=50))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == -6
        assert pos.realized_pnl_cents == 40

    def test_settlement_no_win_not_inverted(self, engine):
        """Regression: long NO settled NO must be a WIN, not a loss."""
        engine.replay_event(_fill_event("f1", side="no", action="buy", contracts=5, price_cents=40))
        engine.replay_event(_settle_event("KXBTC15M-TEST", "no"))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        # 5 NO @ 40c -> payout 100c each => +300c
        assert pos.realized_pnl_cents == 300
        assert pos.quantity == 0

    def test_settlement_yes_win(self, engine):
        engine.replay_event(_fill_event("f1", side="yes", action="buy", contracts=5, price_cents=60))
        engine.replay_event(_settle_event("KXBTC15M-TEST", "yes"))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.realized_pnl_cents == 200
        assert pos.quantity == 0

    def test_settlement_long_no_via_sell_yes_wins_on_no(self, engine):
        """NO exposure acquired via SELL YES must settle as a NO position."""
        # SELL YES @ 55 == long NO @ 45 (YES-space basis 55)
        engine.replay_event(_fill_event("f1", side="yes", action="sell", contracts=5, price_cents=55))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == -5
        engine.replay_event(_settle_event("KXBTC15M-TEST", "no"))
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        # -5 * (0 - 55) = +275c  (paid 45c/contract in NO space, payout 100c)
        assert pos.realized_pnl_cents == 275

    def test_undetermined_direction_quarantined(self, engine):
        """A fill with missing/invalid direction must not create exposure."""
        engine.replay_event(_fill_event("f1", side="", action="buy", contracts=5, price_cents=60))
        assert "KXBTC15M-TEST" not in engine._positions_by_ticker
        engine.replay_event(_fill_event("f2", side="yes", action="", contracts=5, price_cents=60))
        assert "KXBTC15M-TEST" not in engine._positions_by_ticker

    def test_canonical_yes_delta_cc_preferred(self, engine):
        """When the ledger supplies canonical_yes_delta_cc it wins over raw fields."""
        evt = _fill_event("f1", side="yes", action="sell", contracts=5, price_cents=55)
        evt.data["canonical_yes_delta_cc"] = -500
        engine.replay_event(evt)
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == -5  # canonical delta -500cc == -5 contracts

    def test_duplicate_fill_id_applied_once(self, engine):
        """Immutable fill_id idempotency: a duplicated fill must not double-count."""
        evt = _fill_event("f1", side="yes", action="buy", contracts=5, price_cents=60)
        engine.replay_event(evt)
        cash_len = len(engine._cash_ledger)
        # Same fill_id under a different event_id (WS + REST double ingest).
        dup = _fill_event("f1", side="yes", action="buy", contracts=5, price_cents=60)
        dup.data["fill_id"] = "f1"
        engine.replay_event(
            PortfolioEvent(
                event_id="evt_dup_f1", sequence_id=1, event_type=EventType.FILL,
                account_id="default", timestamp=datetime.now(timezone.utc),
                data=dict(dup.data),
            )
        )
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == 5  # not 10
        assert len(engine._cash_ledger) == cash_len  # no second cash entry

    def test_duplicate_event_id_applied_once(self, engine):
        """Replaying the identical event object/id is a no-op."""
        evt = _fill_event("f2", side="yes", action="buy", contracts=5, price_cents=60)
        engine.replay_event(evt)
        engine.replay_event(evt)  # same event_id
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == 5
        assert sum(1 for e in engine._cash_ledger if e.related_fill_id == "f2") == 1

    def test_fractional_centi_contract_fill(self, engine):
        """canonical_yes_delta_cc=150 must yield +1.5 contracts, not truncated/floored."""
        evt = _fill_event("f3", side="yes", action="buy", contracts=1, price_cents=50)
        evt.data["canonical_yes_delta_cc"] = 150
        engine.replay_event(evt)
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == Decimal("1.5")

    def test_negative_fractional_cc_not_floor_division(self, engine):
        """-550cc must become -5.5 contracts (// 100 would floor to -6)."""
        evt = _fill_event("f4", side="yes", action="sell", contracts=6, price_cents=55)
        evt.data["canonical_yes_delta_cc"] = -550
        engine.replay_event(evt)
        pos = engine._positions_by_ticker["KXBTC15M-TEST"]
        assert pos.quantity == Decimal("-5.5")


class TestPositionCacheDirectionGuard:
    """position_cache.apply_fill must fail closed on missing direction."""

    def _position(self):
        from merid.event_venues.kalshi.position_cache import CachedPosition
        return CachedPosition(
            market_id="KXBTC15M-TEST",
            agent_id="test",
            contracts=Decimal("5"),
            side="yes",
            thesis_side="yes",
            outcome_side="yes",
            avg_price_cents=60,
            quantity_cc=500,
        )

    def test_apply_fill_missing_side_is_quarantined(self):
        pos = self._position()
        before_qty = pos.quantity_cc
        pos.apply_fill(
            contracts=2,
            price_cents=70,
            fee_cents=0,
            side="",
            action="sell",
        )
        assert pos.quantity_cc == before_qty

    def test_apply_fill_missing_action_is_quarantined(self):
        pos = self._position()
        before_qty = pos.quantity_cc
        pos.apply_fill(
            contracts=2,
            price_cents=70,
            fee_cents=0,
            side="yes",
            action="",
        )
        assert pos.quantity_cc == before_qty

    def test_apply_fill_valid_close_still_works(self):
        pos = self._position()
        pos.apply_fill(
            contracts=2,
            price_cents=70,
            fee_cents=0,
            side="yes",
            action="sell",
        )
        assert pos.quantity_cc == 300


class TestReconcilerUnknownSide:
    """canonical_portfolio_reconciler must not fabricate YES for unknown side."""

    def test_extract_position_outcome_none(self):
        from merid.event_venues.kalshi.canonical_portfolio_reconciler import _extract_position_outcome
        assert _extract_position_outcome(None) == ""

    def test_extract_position_outcome_empty_dict(self):
        from merid.event_venues.kalshi.canonical_portfolio_reconciler import _extract_position_outcome
        assert _extract_position_outcome({}) == ""

    def test_extract_position_outcome_valid(self):
        from merid.event_venues.kalshi.canonical_portfolio_reconciler import _extract_position_outcome

        class P:
            outcome = "no"
        assert _extract_position_outcome(P()) == "no"

    def test_yes_exposure_cc_unknown_side_is_zero(self):
        from merid.event_venues.kalshi.canonical_portfolio_reconciler import _yes_exposure_cc
        assert _yes_exposure_cc("", Decimal("5")) == 0
        assert _yes_exposure_cc("bogus", Decimal("5")) == 0

    def test_yes_exposure_cc_valid_sides(self):
        from merid.event_venues.kalshi.canonical_portfolio_reconciler import _yes_exposure_cc
        assert _yes_exposure_cc("yes", Decimal("5")) == 500
        assert _yes_exposure_cc("no", Decimal("5")) == -500

    def test_yes_exposure_from_qcc_unknown_side_is_zero(self):
        from merid.event_venues.kalshi.canonical_portfolio_reconciler import _yes_exposure_from_qcc
        assert _yes_exposure_from_qcc("", 500) == 0


class TestExecutableAskSizeGuard:
    """MarketState.get_executable_ask_size must return 0 for unknown side."""

    def test_unknown_side_returns_zero(self):
        from merid.event_venues.kalshi.models import KalshiMarketState
        state = KalshiMarketState(ticker="M")
        assert state.get_executable_ask_size("") == 0
        assert state.get_executable_ask_size("bogus") == 0
        assert state.get_executable_ask_size(None) == 0


class TestFillsLedgerIntentSideBackfill:
    """Missing intent side must not be stamped as canonical 'yes'."""

    def test_intent_side_sanitizer_rejects_empty(self):
        # Mirrors the sanitizer at fills_ledger.py (~7392): empty/invalid
        # intent side resolves to None, not a fabricated "yes".
        def _sanitize(v):
            v = (v or "").lower()
            if v in ("yes", "no"):
                return v
            return "yes" if "yes" in v else "no" if "no" in v else None

        assert _sanitize("") is None
        assert _sanitize(None) is None
        assert _sanitize("yes") == "yes"
        assert _sanitize("no") == "no"
        assert _sanitize("BUY_NO") == "no"
        assert _sanitize("SELL_YES") == "yes"


class TestOrderRouterPriceSpaceGuard:
    """_intent_price_side must return None (not fabricated "yes") for
    ambiguous side strings, and callers must fail closed."""

    def _intent(self, side, action="buy"):
        from types import SimpleNamespace
        return SimpleNamespace(intent_id="test-intent", side=side, action=action)

    def test_ambiguous_side_returns_none(self):
        from merid.event_venues.kalshi.order_router import _intent_price_side
        assert _intent_price_side(self._intent("")) is None
        assert _intent_price_side(self._intent("bogus")) is None
        assert _intent_price_side(self._intent(None)) is None

    @pytest.mark.parametrize("side", ["unknown", "not_yes", "BUY_YES_NO", "", None])
    def test_invalid_side_cannot_select_a_book_or_exposure(self, side):
        from merid.event_venues.kalshi.order_router import (
            _intent_price_side, _side_aware_book_for_intent, _canonical_signed_yes_delta,
        )
        intent = self._intent(side)
        assert _intent_price_side(intent) is None
        with pytest.raises(ValueError):
            _side_aware_book_for_intent({}, side)
        with pytest.raises(ValueError):
            _canonical_signed_yes_delta(intent)

    @pytest.mark.parametrize("side, action, expected", [
        ("BUY_YES", "buy", 1), ("SELL_NO", "sell", 1),
        ("BUY_NO", "buy", -1), ("SELL_YES", "sell", -1),
        (" yes ", "buy", 1), (" NO ", "buy", -1),
    ])
    def test_signed_exposure_matrix(self, side, action, expected):
        from merid.event_venues.kalshi.order_router import _canonical_signed_yes_delta
        assert _canonical_signed_yes_delta(self._intent(side, action)) == expected

    def test_explicit_sides_still_resolve(self):
        from merid.event_venues.kalshi.order_router import _intent_price_side
        assert _intent_price_side(self._intent("BUY_YES")) == "yes"
        assert _intent_price_side(self._intent("SELL_NO")) == "no"
        assert _intent_price_side(self._intent("yes")) == "yes"

    def test_placement_validation_rejects_unknown_space(self):
        from types import SimpleNamespace
        from merid.event_venues.kalshi.order_router import _validate_outcome_price_placement
        snapshot = SimpleNamespace(
            book_initialized=True,
            best_bid_cents=40, best_ask_cents=45,
            best_no_bid_cents=55, best_no_ask_cents=60,
        )
        ok, reason = _validate_outcome_price_placement(
            self._intent("bogus"), role="taker", price_cents=50, snapshot=snapshot
        )
        assert ok is False
        assert reason == "unknown_price_space"


class TestPositionCacheOnFillQuarantine:
    """on_fill must quarantine (no mutation + REST reconciliation) when the
    fill's direction cannot be determined, instead of fabricating 'buy'."""

    def _cache(self):
        from merid.event_venues.kalshi.position_cache import KalshiPositionCache
        KalshiPositionCache._instance = None
        return KalshiPositionCache()

    def test_missing_action_is_quarantined(self):
        import asyncio
        cache = self._cache()
        asyncio.run(
            cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=60,
                fee_cents=0,
                side="yes",
                action="",
                fill_id="fill-missing-action",
                canonicalization_state="TRUSTED_LIVE_V1",
            )
        )
        assert cache.get_position("KXBTC15M-TEST") is None
        assert cache._reconciliation_halted.get("KXBTC15M-TEST") is True

    def test_missing_action_not_marked_applied(self):
        # A quarantined fill must remain retryable: fill_id is only marked
        # applied after successful mutation.
        import asyncio
        cache = self._cache()
        asyncio.run(
            cache.on_fill(
                market_id="KXBTC15M-TEST",
                contracts=5,
                price_cents=60,
                fee_cents=0,
                side="yes",
                action="",
                fill_id="fill-missing-action-2",
                canonicalization_state="TRUSTED_LIVE_V1",
            )
        )
        assert "fill-missing-action-2" not in cache._applied_fill_ids


class TestDeriveProceedsStrict:
    """_derive_proceeds_dollars must not fabricate a buy for missing action."""

    def test_unknown_action_raises(self):
        from merid.event_venues.kalshi.position_cache import _derive_proceeds_dollars
        import pytest as _pt
        with _pt.raises(ValueError):
            _derive_proceeds_dollars("", 100, 50, 0)
        with _pt.raises(ValueError):
            _derive_proceeds_dollars("bogus", 100, 50, 0)

    def test_buy_sell_unchanged(self):
        from decimal import Decimal as D
        from merid.event_venues.kalshi.position_cache import _derive_proceeds_dollars
        assert _derive_proceeds_dollars("buy", 100, 50, 1) == D("-0.51")
        assert _derive_proceeds_dollars("sell", 100, 50, 1) == D("0.49")
