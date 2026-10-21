"""
Incident regression tests for the exit price guard (2026-08-19).

These tests cover the BTC 40c stale-data loss incident: an automated
discretionary exit must be rejected unless it is based on a fresh quote,
attributable to an allowed reason, and bounded by the configured max loss /
slippage.  Emergency / near-expiry liquidation is preserved.
"""

import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest


@pytest.fixture(autouse=True)
def _disable_persistence_and_fees(monkeypatch):
    """Keep tests hermetic: do not write to logs/order_decisions.jsonl.

    Fees are mocked to a predictable round-trip 4c so assertions are stable
    across fee-schedule environment differences.
    """
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_intent_contract.persist_order_decision",
        lambda record: None,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.parabolic_fees.kalshi_taker_fee_cents_parabolic",
        lambda *_a, **_k: 2,
    )


@pytest.fixture(autouse=True)
def _reset_ev_gate_state(monkeypatch):
    """Keep the EV exit gate hermetic: no file persistence, no env enable,
    and no live RTI fetch (the default provider must not hit the network)."""
    monkeypatch.setenv("MERID_EV_EXIT_DISABLE_PERSIST", "1")
    monkeypatch.delenv("MERID_ENABLE_EV_EXIT_GATE", raising=False)
    monkeypatch.delenv("MERID_EV_EXIT_GATE_KILL", raising=False)
    import merid.event_venues.kalshi.settlement_aligned_exit as sae

    monkeypatch.setattr(sae, "_default_rti_provider", lambda _asset: None)
    sae._evaluator = None
    sae._registry = None
    sae._resolver = None
    yield
    sae._evaluator = None
    sae._registry = None
    sae._resolver = None


@pytest.fixture(autouse=True)
def _seed_canonical_position_cache():
    """Seed the canonical cache with an open position for the test market.

    The exit guard now rejects exits when the canonical position cache reports
    a flat or missing position. These tests call the guard directly with a
    monitor-side Position snapshot, so the canonical cache must be seeded to
    satisfy the new safety contract.
    """
    from merid.event_venues.kalshi.position_cache import CachedPosition, get_position_cache

    market_id = "KXBTC15M-26AUG100000-00"
    cache = get_position_cache()
    cache._positions[market_id] = CachedPosition(
        market_id=market_id,
        agent_id="test",
        contracts=1,
        side="no",
        thesis_side="no",
        avg_price_cents=74,
    )
    yield
    cache._positions.pop(market_id, None)


def _make_state(*, no_bid=None, no_ask=None, yes_bid=None, yes_ask=None,
                age_ms=1000, seconds_to_expiry=300.0, source="ws"):
    """Build a minimal market state for the exit guard."""
    state = Mock()
    state.book_updated_ts = time.monotonic() - (age_ms / 1000.0)
    state.seconds_to_expiry = seconds_to_expiry
    state.book_source = source
    state.no_bid_cents = no_bid
    state.no_ask_cents = no_ask
    state.best_bid_cents = yes_bid
    state.best_ask_cents = yes_ask
    state.book = None
    return state


def _make_position(**kwargs):
    defaults = dict(
        position_id="pos-12345678",
        market_id="KXBTC15M-26AUG100000-00",
        size=1,
        avg_entry_price_cents=74,
        outcome_side="no",
        thesis_side="no",
        stop_loss_price_cents=None,
        hard_stop_price_cents=None,
        entry_fill_id="fill-abc",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _patched_get_market_state(state=None):
    def _get_market_state(_ticker):
        return (state, None)
    return _get_market_state


def _run_guard(position, exit_reason, exit_price_cents=36, count=1, state=None):
    from merid.loop_15m import _run_exit_price_guard
    with patch(
        "merid.event_venues.kalshi.stop_candidate._get_market_state",
        _patched_get_market_state(state),
    ):
        return _run_exit_price_guard(position, exit_reason, exit_price_cents, count)


def test_stale_data_loss_exit_rejected_on_stale_quote():
    """Incident: a stale-data trigger with a stale quote must be rejected."""
    position = _make_position()
    state = _make_state(no_bid=42, no_ask=44, age_ms=12_264)

    approved, _price, record, _did = _run_guard(
        position, "stale_data", exit_price_cents=36, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "reconciliation"
    assert record["reject_reason"] == "stale_quote"
    assert record["best_bid_cents"] == 42


def test_fresh_quote_loss_exit_rejected_on_profit_floor():
    """A fresh quote does not make a 32c gross loss exit acceptable."""
    position = _make_position()
    state = _make_state(no_bid=42, no_ask=44, age_ms=100)

    approved, _price, record, _did = _run_guard(
        position, "stale_data", exit_price_cents=36, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "reconciliation"
    assert record["reject_reason"] == "profit_exit_not_profitable"
    assert record["projected_net_pnl_cents"] < -3
    assert record["best_bid_cents"] == 42


def test_emergency_expiry_liquidation_approved(monkeypatch):
    """Near-expiry emergency liquidation with a bounded loss is preserved.

    Scope: the mechanical guard (limit price, loss bound, emergency class).
    The 2026-09-24 settle-default gate (MERID_SETTLEMENT_GUARD_EV_GATE) is a
    separate sell-vs-settle policy that requires a trusted calibrated eval;
    without one this scenario correctly rides to settlement.  It is disabled
    here so this test keeps covering the mechanical path it was written for.
    """
    monkeypatch.setenv("MERID_SETTLEMENT_GUARD_EV_GATE", "0")
    position = _make_position()
    state = _make_state(no_bid=70, no_ask=72, seconds_to_expiry=30.0)

    approved, price, record, _did = _run_guard(
        position, "auto_exit_99c", exit_price_cents=99, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "expiry_liquidation"
    assert record["is_emergency"] is True
    assert record["limit_cents"] == 68  # 70c bid - 2c slippage
    assert record["projected_net_pnl_cents"] < 0
    assert record["projected_net_pnl_cents"] >= -15
    assert price == 68


def test_stop_loss_vetoed_observe_only_when_gate_disabled():
    """Discretionary stop-loss is observe-only while the EV gate is disabled.

    The legacy checks still compute the would-be limit price so the record is
    replayable, but the order is vetoed at the approval point.
    """
    position = _make_position(stop_loss_price_cents=70)
    # TTE inside the evidence-envelope terminal window: a mid-book stop only
    # reaches the discretionary veto here (outside it the envelope defers).
    state = _make_state(no_bid=70, no_ask=72, seconds_to_expiry=90.0)

    approved, price, record, _did = _run_guard(
        position, "stop_loss", exit_price_cents=70, state=state
    )

    assert approved is False
    assert record["exit_reason_canonical"] == "stop_loss"
    assert record["exit_class"] == "discretionary"
    assert record["reject_reason"] == "discretionary_exit_observe_only"
    assert record["legacy_would_approve"] is True
    assert record["limit_cents"] == 68  # stop 70 - 2c slippage (recorded for replay)
    assert record["projected_net_pnl_cents"] < 0  # bounded loss, recorded for replay
    assert "ev_evaluation" in record


def test_stop_loss_rejected_when_market_gapped_through_slippage():
    """If the best bid is worse than stop - slippage, do not chase the market."""
    position = _make_position(stop_loss_price_cents=70)
    # Market has already fallen to 67; stop - 2 = 68, so the bid is worse.
    # Inside the envelope terminal window so the slippage check is reached.
    state = _make_state(no_bid=67, no_ask=69, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "stop_loss", exit_price_cents=70, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "stop_beyond_slippage"


def test_take_profit_approved_when_gate_disabled(monkeypatch):
    """Take-profit is operational again (2026-09-23): it submits through the
    mechanical guard even while the EV gate is disabled."""
    # Hermetic pricing knobs: the IOC limit is bid - profit slippage,
    # clamped up to the fee-aware minimum profitable exit when that bound
    # is below the bid.  The live .env carries
    # MERID_TAKE_PROFIT_MIN_PROFIT_CENTS=12 and a 5c profit slippage —
    # without pinning, this assertion depends on operator tuning.
    monkeypatch.setenv("MERID_EXIT_PROFIT_SLIPPAGE_CENTS", "0")
    import merid.event_venues.kalshi.fees as _fees
    monkeypatch.setattr(_fees, "TAKE_PROFIT_MIN_PROFIT_CENTS", 2)
    position = _make_position()
    # Terminal window: the evidence envelope admits this take-profit so the
    # operational path under test executes.
    state = _make_state(no_bid=84, no_ask=86, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=84, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "take_profit"
    assert record["exit_class"] == "operational"
    assert record["status"] == "approved"
    assert record["limit_cents"] == 84


def test_take_profit_rejected_when_not_profitable():
    """A take-profit priced at a loss is rejected."""
    position = _make_position()
    state = _make_state(no_bid=70, no_ask=72, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=70, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "profit_exit_not_profitable"


def test_unknown_exit_reason_rejected():
    """Only explicitly allowed exit reasons may be submitted."""
    position = _make_position()
    state = _make_state(no_bid=50, no_ask=52)

    approved, _price, record, _did = _run_guard(
        position, "foobar", exit_price_cents=50, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "exit_reason_not_allowed"


def test_time_exit_with_small_loss_approved():
    """Time exits are operational and forced (2026-09-23): a bounded loss is
    approved so a stale position cannot ride to settlement."""
    position = _make_position()
    # 1c gross loss -> net -7 with mocked 4c round-trip fee; forced exit still approves.
    # Inside the envelope terminal window: time_exit is envelope-gated.
    state = _make_state(no_bid=73, no_ask=75, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "time_stop", exit_price_cents=73, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "time_exit"
    assert record["exit_class"] == "operational"
    assert record["is_forced"] is True
    assert record["status"] == "approved"
    assert record["projected_net_pnl_cents"] < 0


def test_time_exit_break_even_approved():
    """Break-even time exit is operational too; approved through the guard."""
    position = _make_position()
    state = _make_state(no_bid=74, no_ask=76, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "time_stop", exit_price_cents=74, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "time_exit"
    assert record["status"] == "approved"
    assert record["projected_net_pnl_cents"] < 0  # gross -2 minus round-trip fees


def test_quote_freshness_uses_age_threshold():
    """Quote just under the freshness threshold reaches the gate; just over is rejected."""
    position = _make_position()
    from merid.loop_15m import MERID_EXIT_MAX_QUOTE_AGE_MS

    # Bid 85c admits the take-profit through the evidence envelope's
    # profit-lock arm (bid >= 85), keeping TTE outside the terminal window so
    # the 10,000 ms quote-freshness tier is what the test exercises.
    # Just under the 10,000 ms default: the quote passes freshness and the
    # operational take-profit is approved (policy exits are no longer EV-gated).
    state = _make_state(no_bid=85, no_ask=86, age_ms=MERID_EXIT_MAX_QUOTE_AGE_MS - 1)
    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=85, state=state
    )
    assert approved is True
    assert record["status"] == "approved"

    # Just over the threshold: a profitable exit is rejected for stale quote.
    state = _make_state(no_bid=85, no_ask=86, age_ms=MERID_EXIT_MAX_QUOTE_AGE_MS + 100)
    approved, _price, record, _did = _run_guard(
        position, "take_profit", exit_price_cents=85, state=state
    )
    assert approved is False
    assert record["reject_reason"] == "stale_quote"


def test_current_edge_reversal_approved():
    """current_edge_reversal canonicalizes to signal_reversal (operational)."""
    position = _make_position()
    # Inside the envelope terminal window: signal_reversal is envelope-gated.
    state = _make_state(no_bid=84, no_ask=86, seconds_to_expiry=90.0)
    state.book_updated_ts = time.monotonic()  # avoid stale quote after slow module import

    approved, _price, record, _did = _run_guard(
        position, "current_edge_reversal", exit_price_cents=84, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "signal_reversal"
    assert record["exit_reason_original"] == "current_edge_reversal"
    assert record["exit_class"] == "operational"
    assert record["status"] == "approved"
    assert record["limit_cents"] == 82
    assert record["projected_net_pnl_cents"] > 0  # worst-case (82-74) minus fees


def _break_position_cache(mp):
    """Force the canonical position check inside the guard to raise.

    Takes a ``monkeypatch.context()`` manager, not the fixture itself: the
    conftest teardown fixture also calls ``get_position_cache`` and would hit
    the patched-in exception if the patch outlived the test body.
    """
    def _boom():
        raise RuntimeError("position cache unavailable")

    mp.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache", _boom
    )


def test_discretionary_exit_fails_closed_on_cache_error(monkeypatch):
    """A cache/reconciliation error must never produce a discretionary submit."""
    with monkeypatch.context() as m:
        _break_position_cache(m)
        position = _make_position()
        state = _make_state(no_bid=84, no_ask=86)

        # stop_loss remains discretionary (EV-gated): cache error fails closed.
        approved, _price, record, _did = _run_guard(
            position, "stop_loss", exit_price_cents=84, state=state
        )

    assert approved is False
    assert record["status"] == "rejected"
    assert record["reject_reason"] == "canonical_position_check_unavailable"
    assert record["exit_class"] == "discretionary"


def test_unknown_reason_fails_closed_on_cache_error(monkeypatch):
    """Unclassified reasons also fail closed when canonical state is unreadable."""
    with monkeypatch.context() as m:
        _break_position_cache(m)
        position = _make_position()
        state = _make_state(no_bid=84, no_ask=86)

        approved, _price, record, _did = _run_guard(
            position, "totally_unmapped_reason", exit_price_cents=50, state=state
        )

    assert approved is False
    assert record["status"] == "rejected"
    assert record["reject_reason"] == "canonical_position_check_unavailable"
    assert record["exit_class"] == "unknown"


def test_operational_exit_fails_open_to_intent_contract_on_cache_error(monkeypatch):
    """Operational exits keep defense-in-depth: cache failure defers to the
    intent contract's authoritative signed-YES revalidation, so the guard must
    continue to its downstream checks (here: stale_quote rejection)."""
    with monkeypatch.context() as m:
        _break_position_cache(m)
        position = _make_position()
        # "stale_data" canonicalizes to "reconciliation" (OPERATIONAL).
        state = _make_state(no_bid=42, no_ask=44, age_ms=12_264)

        approved, _price, record, _did = _run_guard(
            position, "stale_data", exit_price_cents=36, state=state
        )

    assert approved is False
    # Reached the quote-freshness gate -> the cache error did not block or approve.
    assert record["reject_reason"] == "stale_quote"
    assert record["exit_reason_canonical"] == "reconciliation"


def test_hard_profit_lock_approved_at_threshold_floor():
    """2026-10-05 incident: hard_profit_lock must pass the guard.

    Live incident: DOGE NO@85, held-side bid 92c, every hard-lock intent was
    rejected as exit_reason_not_allowed and the position rode to settlement.
    The guard must now approve with the IOC limit anchored at the lock
    threshold (fills >=90c or unfilled, never a faded 87c print).

    2026-10-21 update: the limit is a *floor*, not the fill price — an IOC
    sells at the best resting bid >= limit.  Anchoring the floor at exactly
    the 90c threshold meant a book that faded 1-2c during trigger->submit
    died unfilled (XRP NO@89 / SOL NO@90 settled -89c/-90c).  The limit is
    now max(entry+min_profit, threshold-sweep): for this entry at 74c the
    floor is 87c — still profit-protected, converts a transit fade, and a
    >=90c book still fills at the real bid.
    """
    position = _make_position()
    state = _make_state(no_bid=92, no_ask=93, age_ms=80)

    approved, price, record, _did = _run_guard(
        position, "hard_profit_lock", exit_price_cents=92, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "hard_profit_lock"
    assert record["exit_class"] == "emergency"
    assert record["status"] == "approved"
    # entry 74 -> profit floor 75; threshold-sweep floor 87 -> limit 87.
    assert record["limit_cents"] == 87
    assert price == 87


def test_hard_profit_lock_sweep_floored_at_breakeven_plus():
    """Entries inside the lock band keep >=threshold semantics.

    Entry 89 (a pinned_fav-band fill): threshold-sweep = 87 but the
    profit floor is entry+1 = 90, so the IOC still prices at 90 — a
    below-90 sell is a loss and the ride-to-settlement doctrine holds.
    """
    position = _make_position(avg_entry_price_cents=89)
    state = _make_state(no_bid=92, no_ask=93, age_ms=80)

    approved, price, record, _did = _run_guard(
        position, "hard_profit_lock", exit_price_cents=92, state=state
    )

    assert approved is True
    assert record["limit_cents"] == 90
    assert price == 90


def test_hard_profit_lock_sweep_zero_restores_threshold(monkeypatch):
    """MERID_HARD_LOCK_SWEEP_CENTS=0 restores the exact-threshold anchor."""
    monkeypatch.setenv("MERID_HARD_LOCK_SWEEP_CENTS", "0")
    position = _make_position()
    state = _make_state(no_bid=92, no_ask=93, age_ms=80)
    approved, price, record, _did = _run_guard(
        position, "hard_profit_lock", exit_price_cents=92, state=state
    )

    assert approved is True
    assert record["limit_cents"] == 90
    assert price == 90


def test_hard_profit_lock_missing_entry_fails_closed_to_threshold():
    """Without a verifiable entry price there is no profit floor, so the
    sweep must not enable a below-threshold sell that could realize a loss."""
    position = _make_position(avg_entry_price_cents=0)
    state = _make_state(no_bid=92, no_ask=93, age_ms=80)

    approved, price, record, _did = _run_guard(
        position, "hard_profit_lock", exit_price_cents=92, state=state
    )

    assert approved is True
    assert record["limit_cents"] == 90
    assert price == 90


def test_hard_profit_lock_not_vetoed_by_model_hold_advantage():
    """The winning-side hold veto must not silently neuter the lock.

    The veto fires precisely when the model values the held side above the
    bid - the same regime where a >=90c lock triggers.  The lock is a risk
    rule: it takes realized profit over residual EV by design.
    """
    position = _make_position()
    state = _make_state(no_bid=92, no_ask=93, age_ms=80)

    approved, _price, record, _did = _run_guard(
        position, "hard_profit_lock", exit_price_cents=92, state=state
    )

    assert approved is True
    assert record.get("reject_reason") != "ev_hold_advantage"


def test_hard_profit_lock_bypasses_discretionary_profit_floor():
    """A marginal lock is not vetoed by the per-contract profit floor.

    Entry 89c, bid 90c: net after fees may be below the discretionary floor,
    but a mechanical risk rule does not have a minimum-profit requirement.
    """
    position = _make_position(avg_entry_price_cents=89)
    from merid.event_venues.kalshi.position_cache import (
        CachedPosition,
        get_position_cache,
    )

    cache = get_position_cache()
    cache._positions["KXBTC15M-26AUG100000-00"] = CachedPosition(
        market_id="KXBTC15M-26AUG100000-00",
        agent_id="test",
        contracts=1,
        side="no",
        thesis_side="no",
        avg_price_cents=89,
    )
    state = _make_state(no_bid=90, no_ask=91, age_ms=80)

    approved, _price, record, _did = _run_guard(
        position, "hard_profit_lock", exit_price_cents=90, state=state
    )

    assert approved is True
    assert record.get("reject_reason") != "profit_exit_not_profitable"


class TestHardLockChasePricing:
    """2026-10-21 chase ladder: when the freshest bid is already below the
    lock threshold the guard prices a bounded salvage IOC at bid-sweep,
    floored at the position's salvage bound — it must never reprice the
    dead threshold level.

    Live failure: XRP NO@89 / SOL NO@90 latched >=90c, submitted one IOC
    at exactly 90 into a book already below it, missed, and rode to
    settlement 0 (-89c/-90c) because nothing ever repriced."""

    def test_model_edge_chase_floors_at_breakeven(self):
        """Model-edge entry 74, threshold 90, submit-time bid 87:
        chase floor = entry+min_profit = 75; limit = max(75, 87-4) = 83 —
        still a profit rescue, never a below-breakeven sell."""
        position = _make_position()  # entry 74, edge stamps absent -> model-edge
        state = _make_state(no_bid=87, no_ask=88, age_ms=80)

        approved, price, record, _did = _run_guard(
            position, "hard_profit_lock", exit_price_cents=87, state=state
        )

        assert approved is True
        assert record["lock_chase"] is True
        assert record["chase_floor_cents"] == 75
        assert record["limit_cents"] == 83
        assert price == 83

    def test_no_edge_chase_floors_at_tail_drop(self):
        """No-edge bounded-lane entry 89 (pinned_fav: entry_edge_pct=-2.89,
        gross entry_edge=+0.0062): chase floor = entry - drop_no_edge = 75;
        limit = max(75, 87-4) = 83.  The net claim — not the gross stamp —
        selects the deeper salvage floor."""
        position = _make_position(
            avg_entry_price_cents=89,
            entry_edge_pct=-2.89,
            entry_edge=0.0062,
        )
        from merid.event_venues.kalshi.position_cache import (
            CachedPosition,
            get_position_cache,
        )

        get_position_cache()._positions["KXBTC15M-26AUG100000-00"] = (
            CachedPosition(
                market_id="KXBTC15M-26AUG100000-00",
                agent_id="test",
                contracts=1,
                side="no",
                thesis_side="no",
                avg_price_cents=89,
            )
        )
        state = _make_state(no_bid=87, no_ask=88, age_ms=80)

        approved, price, record, _did = _run_guard(
            position, "hard_profit_lock", exit_price_cents=87, state=state
        )

        assert approved is True
        assert record["lock_chase"] is True
        assert record["chase_floor_cents"] == 75
        assert record["limit_cents"] == 83
        assert price == 83

    def test_no_edge_chase_loss_bound_admits_priced_depth(self):
        """A chase limit below entry projects a bounded loss; the priced
        limit IS the bound (not the generic 3c cap), so the salvage is not
        vetoed as max_loss_exceeded."""
        position = _make_position(
            avg_entry_price_cents=89,
            entry_edge_pct=-2.89,
        )
        from merid.event_venues.kalshi.position_cache import (
            CachedPosition,
            get_position_cache,
        )

        get_position_cache()._positions["KXBTC15M-26AUG100000-00"] = (
            CachedPosition(
                market_id="KXBTC15M-26AUG100000-00",
                agent_id="test",
                contracts=1,
                side="no",
                thesis_side="no",
                avg_price_cents=89,
            )
        )
        # bid 85 -> limit 81 -> worst-case (81-89) - fees, ~-10c: beyond the
        # generic 3c bound but inside the priced-limit bound.
        state = _make_state(no_bid=85, no_ask=86, age_ms=80)

        approved, _price, record, _did = _run_guard(
            position, "hard_profit_lock", exit_price_cents=85, state=state
        )

        assert approved is True
        assert record["limit_cents"] == 81
        assert record["projected_net_pnl_cents"] < -3
        assert record.get("reject_reason") != "max_loss_exceeded"
        assert record["max_loss_cents"] >= -record["projected_net_pnl_cents"]

    def test_model_edge_chase_never_sells_below_breakeven(self):
        """A collapsed bid below the profit floor reprices at entry+1,
        not the raw bid — the IOC cannot realize a loss on a model-edge
        entry (the ride doctrine owns below-breakeven)."""
        position = _make_position()  # entry 74
        # bid 60: chase floor 75 binds -> limit 75, IOC can only fill >=75.
        state = _make_state(no_bid=60, no_ask=62, age_ms=80)

        approved, price, record, _did = _run_guard(
            position, "hard_profit_lock", exit_price_cents=60, state=state
        )

        assert approved is True
        assert record["lock_chase"] is True
        assert record["limit_cents"] == 75
        assert price == 75

    def test_above_threshold_bid_keeps_threshold_anchor(self):
        """Regression: a bid still >= threshold keeps the swept anchor
        (chase path must not engage on the normal lock attempt)."""
        position = _make_position()  # entry 74
        state = _make_state(no_bid=92, no_ask=93, age_ms=80)

        approved, price, record, _did = _run_guard(
            position, "hard_profit_lock", exit_price_cents=92, state=state
        )

        assert approved is True
        assert "lock_chase" not in record
        assert record["limit_cents"] == 87
