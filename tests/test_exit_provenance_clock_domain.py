"""Regression tests for the 2026-11-23 exit-provenance clock-domain repair.

Live incident: every entry fill was persisted with
``entry_book_capture_quality=POST_FILL`` and
``entry_book_timestamp`` rendered as 1970, because
``UnifiedMarketState.book_updated_ts`` is a *monotonic*-domain stamp
(``KalshiMarketState.last_book_update_ts = time.monotonic() - data_age``)
while ``book_age_s`` subtracted it from ``time.time()`` (wall).  The resulting
~1.7e12s age forced POST_FILL on every fill, and ``_can_act_on_model_exit``'s
exact ``== "AT_FILL"`` requirement then blocked all model-driven exits
(edge-decay profit, model-invalidation loss) for every position.
"""

import time
from datetime import datetime, timezone

from merid.event_venues.kalshi.unified_market_state import UnifiedMarketState
from merid.position_management.exit_policy import ExitPolicy, has_trusted_exit_provenance
from merid.position_management.position import Position, RiskParamsState


def _fresh_unified(book_updated_ts):
    u = UnifiedMarketState(ticker="KXTEST")
    u.book_updated_ts = book_updated_ts
    return u


class TestBookAgeClockDomain:
    def test_monotonic_stamp_yields_small_age(self):
        """A monotonic book_updated_ts must produce a small positive age."""
        u = _fresh_unified(time.monotonic() - 0.5)
        age = u.book_age_s
        assert age != float("inf")
        assert 0.0 <= age < 5.0

    def test_wall_epoch_stamp_still_works(self):
        """Legacy wall/epoch-stamped values stay on the wall clock."""
        u = _fresh_unified(time.time() - 2.0)
        age = u.book_age_s
        assert age != float("inf")
        assert 0.0 <= age < 10.0

    def test_unset_stamp_is_infinite(self):
        u = _fresh_unified(None)
        assert u.book_age_s == float("inf")
        u2 = _fresh_unified(0.0)
        assert u2.book_age_s == float("inf")

    def test_monotonic_stamp_does_not_explode(self):
        """The reported bug: monotonic stamp must NOT yield ~1.7e12s."""
        u = _fresh_unified(time.monotonic())
        assert u.book_age_s < 60.0


def _model_exit_position(quality: str) -> Position:
    """A fully-provenanced entry position with a given book-capture tier."""
    return Position(
        market_id="KXTEST15M-TEST",
        side="no",
        size=6,
        avg_entry_price_cents=71,
        entry_fill_price_cents=71,
        entry_signal_id="merid-test-signal",
        entry_model_probability=0.72,
        entry_edge=0.008,
        entry_fill_id="fill-abc",
        entry_order_id="order-abc",
        client_order_id="merid_testclient",
        entry_intent_id="intent_test",
        fill_source="alpha",
        risk_params_state=RiskParamsState.ORIGINAL_PERSISTED,
        risk_params_schema_version=2,
        entry_book_capture_quality=quality,
    )


def _policy_for(pos: Position) -> ExitPolicy:
    return ExitPolicy(
        position=pos,
        current_price_cents=72,
        unrealized_pnl_cents=6,
        r_multiple=0.5,
        time_since_entry_seconds=120.0,
        time_to_expiry_seconds=600.0,
    )


class TestModelExitProvenance:
    def test_at_fill_allows_model_exit(self):
        pos = _model_exit_position("AT_FILL")
        # __post_init__ preserves book fields only for AT_FILL; model-exit
        # gate must still pass on the economics provenance.
        assert _policy_for(pos)._can_act_on_model_exit() is True

    def test_near_pre_fill_allows_model_exit(self):
        """Resting/maker fills get the bounded near-fill tier; it must not
        permanently block model-driven exits (the reported DOGE blocker)."""
        pos = _model_exit_position("AT_FILL_OR_NEAREST_PRE_FILL")
        assert _policy_for(pos)._can_act_on_model_exit() is True

    def test_post_fill_still_blocked(self):
        pos = _model_exit_position("POST_FILL")
        assert _policy_for(pos)._can_act_on_model_exit() is False

    def test_unavailable_still_blocked(self):
        pos = _model_exit_position("UNAVAILABLE")
        assert _policy_for(pos)._can_act_on_model_exit() is False

    def test_unknown_still_blocked(self):
        pos = _model_exit_position("UNKNOWN")
        assert _policy_for(pos)._can_act_on_model_exit() is False

    def test_missing_signal_metadata_still_blocked(self):
        """Even with a good book tier, absent entry economics fail closed."""
        pos = _model_exit_position("AT_FILL_OR_NEAREST_PRE_FILL")
        pos.entry_signal_id = None
        pos.entry_model_probability = None
        pos.entry_edge = None
        assert _policy_for(pos)._can_act_on_model_exit() is False

    def test_trusted_provenance_helper_unaffected(self):
        """has_trusted_exit_provenance never checked book quality — unchanged."""
        pos = _model_exit_position("POST_FILL")
        assert has_trusted_exit_provenance(pos) is True
