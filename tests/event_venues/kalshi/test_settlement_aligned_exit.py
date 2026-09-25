"""Regression tests for the settlement-aligned sell-vs-hold exit evaluator.

These tests pin the 2026-09 exit-policy contract: a discretionary exit may
only submit when a fresh, sequence-confirmed RTI/model valuation says selling
at the confirmed executable same-side bid beats holding to settlement by a
declared margin.  Direct contract-price stops and entry-price-relative P&L
are never the authorization.

Scenarios (per the exit-policy audit directive):
1. Winning-contract false-stop: bid dips below entry while the model is still
   valid and the contract goes on to settle YES -> HOLD.
2. True invalidation: model falls materially and persistently -> SELL_SIGNALLED.
3. Stale or unsequenced book -> HOLD_DATA_INSUFFICIENT, never an exit.
4. Wrong-price-side: ask movement must not create a loss trigger.
5. Missing entry provenance -> blocked + operational alert.
6. Time-to-expiry: identical displacement at 600s vs 30s differs per policy.
7. Fill-before-ack: an exit fill resolves the attempt to FILLED.
8. Canonical settlement identity + hold-vs-sell counterfactual P&L.
"""

import time
from decimal import Decimal
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi.settlement_aligned_exit import (
    EvDecision,
    EvGatePolicy,
    ExitAttemptResolver,
    ExitClass,
    ExitEvaluationRegistry,
    SettlementAlignedExitEvaluator,
    AttemptStatus,
    build_liquidation_quote,
    canonical_market_key,
    classify_exit_reason,
    classify_trigger_reason,
    is_full_market_key,
    resolve_market_pk,
)


MARKET = "KXBTC15M-26AUG100000-00"


def _make_rti(*, eligible: bool = True, age_ms: int = 50):
    """A fresh, sequence-confirmed, execution-eligible RTI observation."""
    return SimpleNamespace(
        source_ts_ms=int(time.time() * 1000) - age_ms,
        observed_ts_ms=int(time.time() * 1000) - age_ms,
        observed_ts_mono_ns=time.monotonic_ns() - age_ms * 1_000_000,
        sequence=12345,
        timestamp_quality="GOOD",
        execution_eligible=eligible,
        value_decimal=Decimal("101000.00"),
        cfb_60s_average_decimal=Decimal("101000.00"),
    )


def _make_state(
    *,
    yes_bid=50,
    yes_ask=52,
    no_bid=None,
    no_ask=None,
    age_ms: int = 500,
    seconds_to_expiry: float = 600.0,
    sequence_confirmed: bool = True,
    executable: bool = True,
):
    return SimpleNamespace(
        best_bid_cents=yes_bid,
        best_ask_cents=yes_ask,
        best_no_bid_cents=no_bid,
        no_bid_cents=no_bid,
        best_no_ask_cents=no_ask,
        book_updated_ts=time.monotonic() - age_ms / 1000.0,
        seconds_to_expiry=seconds_to_expiry,
        live_sequence_confirmed=sequence_confirmed,
        snapshot_complete=sequence_confirmed,
        transition="VALID",
        book_health="HEALTHY",
        data_quality="OK",
        executable=executable,
        book=None,
        book_source="ws",
        data_source="ws",
    )


def _make_position(*, side="yes", entry=60, **overrides):
    """A position with complete, trustworthy entry provenance."""
    fields = dict(
        position_id="pos-evtest01",
        market_id=MARKET,
        size=1,
        side=side,
        outcome_side=side,
        thesis_side=side,
        avg_entry_price_cents=entry,
        entry_fill_price_cents=entry,
        all_in_entry_basis_cents=entry,
        entry_fill_id="fill-entry-1",
        entry_order_id="ord-entry-1",
        entry_signal_id="sig-1",
        entry_model="bachelier",
        entry_model_version="v2",
        entry_model_probability=None,
        entry_book_capture_quality="AT_FILL",
        entry_book_snapshot_id=None,
        risk_params_state="original_persisted",
        client_order_id=None,
        entry_intent_id=None,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _stub_calibrator(*, dual_no: bool = False):
    """Deterministic tail calibrator for eval-time calibration tests."""
    from merid.risk.probability.tail_calibrator import TailProbabilityCalibrator

    if dual_no:
        # Legacy single-curve path makes the NO curve the exact YES dual.
        return TailProbabilityCalibrator(
            held_prices=[0.10, 0.20, 0.30],
            actual_probs=[0.0, 0.05, 0.15],
            buffer=0.05,
            n_trades=30,
            metadata={"source": "test"},
        )
    return TailProbabilityCalibrator(
        yes_held_prices=[0.10, 0.20, 0.30],
        yes_actual_probs=[0.0, 0.05, 0.15],
        no_held_prices=[0.70, 0.80, 0.90],
        no_actual_probs=[0.15, 0.05, 0.0],
        buffer=0.05,
        n_trades=30,
        metadata={"source": "test"},
    )


def _make_evaluator(tail_calibrator=None, **policy_overrides):
    """A hermetic evaluator: in-memory registry, no file persistence, no
    production calibration artifact (pass a stub to test calibrated paths).

    ``require_calibrated_model`` defaults off here so the economics tests can
    drive the signal path directly; the calibration-prohibition test opts in
    explicitly.
    """
    policy_kwargs = dict(min_consecutive=1, require_calibrated_model=False)
    policy_kwargs.update(policy_overrides)
    registry = ExitEvaluationRegistry(persist_dir=None)
    return (
        SettlementAlignedExitEvaluator(
            policy=EvGatePolicy(**policy_kwargs),
            registry=registry,
            rti_provider=lambda _asset: _make_rti(),
            tail_calibrator=tail_calibrator,
        ),
        registry,
    )


# ── 1. Winning-contract false-stop ────────────────────────────────────────────

def test_winning_contract_false_stop_holds():
    """Long YES @60c; bid dips to 50c; model still valid; settles YES -> HOLD.

    This is the "sold a winning YES" inversion: the contract-price stop fires
    on the mark, but the settlement-aligned EV says the position is worth more
    held than sold.
    """
    evaluator, registry = _make_evaluator()
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=state,
        fair_value_cents=65,  # model still sees 65% for YES
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )

    assert ev.decision == EvDecision.HOLD_SELL_VALUE_INFERIOR
    assert ev.detail == "hold_ev_favorable"
    assert ev.bid_cents == 50
    assert ev.model_prob_cents == 65

    # Counterfactual: the market settles YES.  Holding was worth 40c/contract;
    # had the false stop sold at 50c the realized P&L would be -10c.
    registry.record_exit_fill(
        market_key=MARKET, held_side="yes", quantity=1, price_cents=50
    )
    rec = registry.on_settlement(MARKET, "yes")
    assert rec is not None
    assert Decimal(rec.actual_pnl_cents) == Decimal("-10")
    assert Decimal(rec.hold_to_settlement_pnl_cents) == Decimal("40")
    assert Decimal(rec.counterfactual_delta_cents) == Decimal("-50")


# ── 2. True invalidation ──────────────────────────────────────────────────────

def test_true_invalidation_signals_exit_after_persistence():
    """Long YES @60c; model collapses to 20c; a persistent breach signals exit."""
    evaluator, _registry = _make_evaluator(min_consecutive=2)
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    first = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert first.decision == EvDecision.HOLD_PERSISTENCE_NOT_MET
    assert first.detail == "ev_breach_pending_persistence"
    assert first.consecutive_breach == 1

    second = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert second.decision == EvDecision.SELL_SIGNALLED
    assert second.detail == "net_sell_exceeds_conservative_hold"
    assert second.consecutive_breach == 2


# ── 3. Stale / unsequenced book ───────────────────────────────────────────────

def test_stale_book_is_data_insufficient_not_exit():
    """A loss 'trigger' in a stale book is insufficient data, never an exit."""
    evaluator, _registry = _make_evaluator()
    position = _make_position(side="yes", entry=60)
    stale_state = _make_state(yes_bid=40, yes_ask=42, age_ms=60_000)

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=stale_state,
        fair_value_cents=20,
        book_age_ms=60_000,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )

    assert ev.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "stale_book" in ev.detail


def test_unsequenced_book_is_data_insufficient_not_exit():
    """A book that is not sequence-confirmed cannot authorize a sell."""
    evaluator, _registry = _make_evaluator()
    position = _make_position(side="yes", entry=60)
    unsequenced = _make_state(
        yes_bid=40, yes_ask=42, sequence_confirmed=False
    )

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=unsequenced,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )

    assert ev.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "book_not_sequence_confirmed" in ev.detail


# ── 4. Wrong price side ───────────────────────────────────────────────────────

def test_ask_movement_does_not_create_loss_trigger():
    """Changing the YES ask while the YES bid is fixed must not move the quote.

    The held-side liquidation value is the observed same-side bid only; the
    ask is never a liquidation price.
    """
    position = _make_position(side="yes", entry=60)
    evaluator, _registry = _make_evaluator()

    # Coherent asks above the bid: the liquidation value and the decision are
    # identical regardless of where the ask sits.
    for ask in (52, 60, 75, 99):
        state = _make_state(yes_bid=50, yes_ask=ask)
        quote = build_liquidation_quote(MARKET, "yes", state)
        assert quote.bid_cents == 50, f"ask={ask} moved the held-side bid"
        ev = evaluator.evaluate(
            position,
            market_key=MARKET,
            canonical_reason="stop_loss",
            kalshi_state=state,
            fair_value_cents=65,
            seconds_to_expiry=600.0,
            rti_observation=_make_rti(),
            record=False,
        )
        assert ev.bid_cents == 50
        assert ev.decision == EvDecision.HOLD_SELL_VALUE_INFERIOR

    # An ask below the bid is a crossed book: incoherent, never a loss trigger.
    state = _make_state(yes_bid=50, yes_ask=30)
    quote = build_liquidation_quote(MARKET, "yes", state)
    assert quote.bid_cents == 50  # bid extraction still unchanged
    assert quote.coherent is False
    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=state,
        fair_value_cents=65,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
        record=False,
    )
    assert ev.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "book_incoherent" in ev.detail


# ── 5. Missing entry provenance ───────────────────────────────────────────────

def test_missing_entry_provenance_blocks_and_alerts():
    """No entry fill/book snapshot -> discretionary exit blocked + alert."""
    evaluator, _registry = _make_evaluator()
    position = _make_position(
        entry_fill_id=None,
        entry_order_id=None,
        entry_signal_id=None,
        entry_model=None,
        entry_model_version=None,
        entry_book_capture_quality=None,
        risk_params_state=None,
        entry_fill_price_cents=None,
        all_in_entry_basis_cents=None,
        avg_entry_price_cents=None,
    )
    state = _make_state(yes_bid=30, yes_ask=32)

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=state,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )

    assert ev.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "missing_entry_provenance" in ev.detail
    assert ev.alert is True
    assert ev.provenance_ok is False
    assert "entry_linkage" in ev.missing_provenance


# ── 6. Time-to-expiry ─────────────────────────────────────────────────────────

def test_identical_displacement_differs_by_time_to_expiry():
    """Same model collapse at 600s can signal; at 30s discretionary defers.

    Inside the near-expiry window the book is one-sided and RTI-derived hold
    value is untrustworthy, so discretionary exits defer to the operational
    expiry path rather than selling on a stale thesis.
    """
    evaluator, _registry = _make_evaluator()
    position = _make_position(side="yes", entry=60)

    far = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=_make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0),
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    near = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=_make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=30.0),
        fair_value_cents=20,
        seconds_to_expiry=30.0,
        rti_observation=_make_rti(),
    )

    assert far.decision == EvDecision.SELL_SIGNALLED
    assert near.decision == EvDecision.HOLD_NEAR_SETTLEMENT_POLICY_REQUIRED
    assert "near_expiry_final_averaging_minute" in near.detail
    assert near.rti_phase == "final_averaging_minute"


# ── 7. Fill-before-ack ────────────────────────────────────────────────────────

def test_fill_before_ack_resolves_attempt_filled():
    """An exchange fill resolves the attempt to FILLED before any route ack."""
    resolver = ExitAttemptResolver(
        store=SimpleNamespace(get_exit_attempt_by_client_order_id=lambda _c: None)
    )
    attempt_id = resolver.begin_attempt(
        market_key=MARKET,
        position_id="pos-evtest01",
        client_order_id="co-exit-1",
    )
    assert resolver.status(attempt_id) == AttemptStatus.PENDING.value

    resolved = resolver.note_fill(
        market_key=MARKET,
        fill_id="fill-exit-1",
        client_order_id="co-exit-1",
        quantity=1,
        price_cents=50,
    )
    assert resolved == attempt_id
    assert resolver.status(attempt_id) == AttemptStatus.FILLED.value

    # A late ack cannot downgrade the filled attempt.
    status = resolver.note_ack(
        client_order_id="co-exit-1", ack_status="submitted", exchange_order_id="ex-1"
    )
    assert status == AttemptStatus.FILLED.value
    assert resolver.unmatched_fills == []


def test_unmatched_exit_fill_is_quarantined_not_wedged():
    """A fill with no matching attempt is recorded as unmatched, not dropped."""
    resolver = ExitAttemptResolver(
        store=SimpleNamespace(get_exit_attempt_by_client_order_id=lambda _c: None)
    )
    resolved = resolver.note_fill(
        market_key=MARKET, fill_id="fill-orphan", client_order_id="co-none"
    )
    assert resolved is None
    assert len(resolver.unmatched_fills) == 1


# ── 8. Canonical settlement identity + counterfactual ─────────────────────────

def test_canonical_settlement_market_pk_and_counterfactual():
    """Full ticker, market_id and settlement identifiers share one market_pk."""
    ticker = "KXBTC15M-26AUG100000-00"
    market_id = "kxbtc15m-26aug100000-00"  # same key, different case
    settlement_key = "KXBTC15M_26AUG100000_00"  # underscore variant
    pk = resolve_market_pk(ticker, market_id, settlement_key)
    assert pk == canonical_market_key(ticker)
    assert is_full_market_key(pk)

    registry = ExitEvaluationRegistry(persist_dir=None)
    registry.register_position(
        market_key=ticker,
        position_id="pos-evtest01",
        held_side="yes",
        quantity_contracts=1,
        entry_price_cents=60,
    )
    registry.record_exit_fill(
        market_key=market_id,  # arrives under the different-cased identifier
        held_side="yes",
        quantity=1,
        price_cents=50,
        fill_id="fill-exit-1",
    )
    rec = registry.on_settlement(
        settlement_key, "yes", settlement_price_cents=100  # and a third form
    )
    assert rec is not None
    assert rec.market_pk == pk
    assert Decimal(rec.actual_pnl_cents) == Decimal("-10")
    assert Decimal(rec.hold_to_settlement_pnl_cents) == Decimal("40")
    assert Decimal(rec.counterfactual_delta_cents) == Decimal("-50")


def test_conflicting_market_identifiers_raise():
    """Identifier disagreement is an error, not a silent misattribution."""
    with pytest.raises(ValueError):
        resolve_market_pk("KXBTC15M-26AUG100000-00", "KXETH15M-26AUG100000-00")


# ── Taxonomy (fail-closed classification) ─────────────────────────────────────

def test_exit_reason_taxonomy_fails_closed():
    """Flat stop losses stay discretionary; policy exits are operational;
    unknown reasons fail closed."""
    for reason in (
        "stop_loss",
        "loss_cut_40pct",
        "value_switch_exit",
    ):
        _, canonical, cls = classify_exit_reason(reason)
        assert cls == ExitClass.DISCRETIONARY, f"{reason} -> {canonical} -> {cls}"

    for reason in (
        "trailing_stop",
        "trail",
        "take_profit",
        "ratchet_floor",
        "scale_out",
        "signal_reversal",
        "current_edge_reversal",
        "model_invalidation",
        "time_stop",
    ):
        _, canonical, cls = classify_exit_reason(reason)
        assert cls == ExitClass.OPERATIONAL, f"{reason} -> {canonical} -> {cls}"

    _, _, cls = classify_exit_reason("expiry_liquidation")
    assert cls == ExitClass.EMERGENCY
    _, _, cls = classify_exit_reason("reconciliation")
    assert cls == ExitClass.OPERATIONAL
    _, _, cls = classify_exit_reason("manual")
    assert cls == ExitClass.OPERATIONAL
    _, _, cls = classify_exit_reason("brand_new_reason_string")
    assert cls == ExitClass.UNKNOWN

    assert classify_trigger_reason("POSITION_MONITOR_STOP") == ExitClass.DISCRETIONARY
    assert classify_trigger_reason("STOP_LOSS") == ExitClass.DISCRETIONARY
    assert classify_trigger_reason("VALUE_SWITCH_EXIT") == ExitClass.DISCRETIONARY
    assert classify_trigger_reason("EDGE_STOP") == ExitClass.OPERATIONAL
    assert classify_trigger_reason("TRAILING_STOP") == ExitClass.OPERATIONAL
    assert classify_trigger_reason("TAKE_PROFIT") == ExitClass.OPERATIONAL
    assert classify_trigger_reason("RECONCILIATION") == ExitClass.OPERATIONAL
    assert classify_trigger_reason("SOME_NEW_TRIGGER") == ExitClass.UNKNOWN


# ── Release-gate additions ────────────────────────────────────────────────────

def test_unused_book_fields_cannot_move_held_side_liquidation():
    """Ask/mid changes on either side never alter the held-side liquidation bid."""
    position_yes = _make_position(side="yes", entry=60)
    position_no = _make_position(side="no", entry=40)
    evaluator, _registry = _make_evaluator()

    for yes_ask in (52, 60, 75, 99):
        state = _make_state(yes_bid=50, yes_ask=yes_ask, no_bid=48, no_ask=50)
        assert build_liquidation_quote(MARKET, "yes", state).bid_cents == 50
        assert build_liquidation_quote(MARKET, "no", state).bid_cents == 48

    # Opposite-side movement (NO ask changes) also cannot move the YES bid.
    for no_ask in (50, 60, 80, 95):
        state = _make_state(yes_bid=50, yes_ask=52, no_bid=48, no_ask=no_ask)
        ev = evaluator.evaluate(
            position_yes,
            market_key=MARKET,
            canonical_reason="stop_loss",
            kalshi_state=state,
            fair_value_cents=65,
            seconds_to_expiry=600.0,
            rti_observation=_make_rti(),
            record=False,
        )
        assert ev.bid_cents == 50
        ev_no = evaluator.evaluate(
            position_no,
            market_key=MARKET,
            canonical_reason="stop_loss",
            kalshi_state=state,
            fair_value_cents=35,  # held-side P(NO)
            seconds_to_expiry=600.0,
            rti_observation=_make_rti(),
            record=False,
        )
        assert ev_no.bid_cents == 48


def test_no_side_probability_normalized_after_calibration():
    """For a long NO the held probability is 1 - p_yes AFTER calibration."""
    evaluator, _registry = _make_evaluator(require_calibrated_model=True)
    position = _make_position(side="no", entry=40)
    state = _make_state(yes_bid=50, yes_ask=52, no_bid=48, no_ask=50)
    state.calibrated_fair_value = 0.20  # P(YES) after calibration
    state.annualized_vol_source = "resolved"
    state.calibration_version = "cal-2026-09"

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=state,
        fair_value_cents=80,  # held-side P(NO) = 1 - 0.20
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.p_held_calibrated_cents == 80
    assert ev.model_inputs_satisfactory is True


def test_fee_boundary_blocks_marginal_sell():
    """A breach that only exists before the taker fee must not signal a sell."""
    evaluator, _registry = _make_evaluator(
        slippage_cents=0,
        uncertainty_reserve_cents=0,
        hold_risk_reserve_cents=0,
        near_expiry_reserve_below_seconds=0.0,
        switch_margin_cents=2,
    )
    position = _make_position(side="yes", entry=60)

    # bid=53 vs fair=50: pre-fee edge 53 - 50 = 3 > margin 2, but the ~1.75c
    # taker fee pushes net sell below the threshold.
    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=_make_state(yes_bid=53, yes_ask=55),
        fair_value_cents=50,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.decision == EvDecision.HOLD_SELL_VALUE_INFERIOR
    assert ev.exit_fee_cents is not None
    assert Decimal(ev.exit_fee_cents) > 0

    # Control: a clearly profitable bid still signals under the same config.
    ev2 = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=_make_state(yes_bid=60, yes_ask=62),
        fair_value_cents=50,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev2.decision == EvDecision.SELL_SIGNALLED


def test_insufficient_bid_depth_is_not_fully_executable():
    """A top bid smaller than the order size cannot justify a sell."""
    evaluator, _registry = _make_evaluator()
    position = _make_position(side="yes", entry=60, size=5)
    book = SimpleNamespace(
        best_yes_bid=90,
        best_yes_ask=92,
        yes_bids=[SimpleNamespace(price_cents=90, size=1)],
        no_bids=[SimpleNamespace(price_cents=8, size=10)],
    )
    state = _make_state(yes_bid=90, yes_ask=92)
    state.book = book

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=50,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "insufficient_bid_depth" in ev.detail


def test_stale_observation_resets_persistence_streak():
    """Breaches interrupted by invalid data cannot combine into persistence."""
    evaluator, _registry = _make_evaluator(min_consecutive=5)
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    def _eval(rti):
        return evaluator.evaluate(
            position,
            market_key=MARKET,
            canonical_reason="value_switch_exit",
            kalshi_state=state,
            fair_value_cents=20,
            seconds_to_expiry=600.0,
            rti_observation=rti,
        )

    for _ in range(4):
        assert _eval(_make_rti()).consecutive_breach >= 1

    # One ineligible RTI observation breaks the streak.
    broken = _eval(_make_rti(eligible=False))
    assert broken.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert broken.consecutive_breach == 0

    # Four more breaches => streak of 4, not 8; still below the threshold.
    last = None
    for _ in range(4):
        last = _eval(_make_rti())
    assert last.decision == EvDecision.HOLD_PERSISTENCE_NOT_MET
    assert last.consecutive_breach == 4

    # The fifth consecutive breach signals.
    assert _eval(_make_rti()).decision == EvDecision.SELL_SIGNALLED


def test_new_window_ticker_does_not_inherit_persistence():
    """A new 15m contract (new market_pk) starts its own streak at zero."""
    evaluator, _registry = _make_evaluator(min_consecutive=3)
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    for _ in range(2):
        ev = evaluator.evaluate(
            position,
            market_key=MARKET,
            canonical_reason="value_switch_exit",
            kalshi_state=state,
            fair_value_cents=20,
            seconds_to_expiry=600.0,
            rti_observation=_make_rti(),
        )
        assert ev.consecutive_breach >= 1

    rolled = _make_position(
        side="yes", entry=60,
        market_id="KXBTC15M-26AUG101500-00",
        position_id="pos-evtest02",
    )
    ev = evaluator.evaluate(
        rolled,
        market_key="KXBTC15M-26AUG101500-00",
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.consecutive_breach == 1
    assert ev.decision == EvDecision.HOLD_PERSISTENCE_NOT_MET


def test_kill_switch_returns_gate_to_observe_only(monkeypatch):
    """MERID_EV_EXIT_GATE_KILL forces observe-only even when the gate is on."""
    import merid.event_venues.kalshi.settlement_aligned_exit as sae

    monkeypatch.setenv("MERID_ENABLE_EV_EXIT_GATE", "1")
    monkeypatch.delenv("MERID_EV_EXIT_GATE_KILL", raising=False)
    monkeypatch.setattr(
        "merid.config.live_config.get_resolved_live_config",
        lambda **_: SimpleNamespace(resolved=False),
        raising=False,
    )
    assert sae.ev_exit_gate_enabled() is True

    monkeypatch.setenv("MERID_EV_EXIT_GATE_KILL", "1")
    assert sae.ev_exit_gate_enabled() is False

    # A signalled eval under the kill switch still cannot submit.
    evaluator, _registry = _make_evaluator()
    position = _make_position(side="yes", entry=60)
    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=_make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0),
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.decision == EvDecision.SELL_SIGNALLED
    assert ev.gate_enabled is False
    assert ev.would_submit is False


def test_operational_and_unknown_reasons_bypass_or_block_in_evaluator():
    """Operational/emergency reasons bypass EV math; unknown reasons block."""
    evaluator, _registry = _make_evaluator()
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    ev_op = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="reconciliation",
        kalshi_state=state,
        fair_value_cents=65,
        rti_observation=_make_rti(),
    )
    assert ev_op.decision == EvDecision.BYPASS_OPERATIONAL
    assert ev_op.exit_class == ExitClass.OPERATIONAL.value

    ev_em = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="expiry_liquidation",
        kalshi_state=state,
        fair_value_cents=65,
        rti_observation=_make_rti(),
    )
    assert ev_em.decision == EvDecision.BYPASS_EMERGENCY

    ev_unk = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="profit_exit_v2",
        kalshi_state=state,
        fair_value_cents=20,
        rti_observation=_make_rti(),
    )
    assert ev_unk.decision == EvDecision.BLOCK_UNKNOWN_REASON
    assert ev_unk.exit_class == ExitClass.UNKNOWN.value
    assert ev_unk.alert is True


def test_uncalibrated_model_blocks_gated_exit_but_records_economics():
    """default-vol / uncalibrated inputs block the gate; shadow data persists."""
    evaluator, registry = _make_evaluator(require_calibrated_model=True)
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)
    state.annualized_vol_source = "default"  # raw Bachelier, no resolved vol

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=20,  # strong sell economics
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "uncalibrated_model_inputs" in ev.detail
    assert ev.model_inputs_satisfactory is False
    assert ev.rti_phase == "pre_settlement"
    # Economics are still recorded for replay even though the exit is blocked.
    assert ev.net_sell_value_cents is not None
    assert ev.conservative_hold_cents is not None

    # Missing calibration alone (no vol_source field at all) also blocks.
    state2 = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)
    ev2 = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state2,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev2.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "uncalibrated_model_inputs" in ev2.detail


# ── Canary scope ──────────────────────────────────────────────────────────────

def _canary_evaluator(**policy_overrides):
    """Gate-enabled canary-mode evaluator scoped to BTC/YES/value_switch_exit."""
    kwargs = dict(
        discretionary_mode="ev_gated_canary",
        canary_assets=frozenset({"btc"}),
        canary_sides=frozenset({"yes"}),
        canary_reasons=frozenset({"value_switch_exit"}),
        canary_max_contracts=1,
        canary_max_orders_per_window=1,
        canary_min_seconds_to_expiry=120.0,
        canary_max_seconds_to_expiry=600.0,
    )
    kwargs.update(policy_overrides)
    return _make_evaluator(**kwargs)


def _strong_sell(evaluator, position, state, market=MARKET, reason="value_switch_exit"):
    return evaluator.evaluate(
        position,
        market_key=market,
        canonical_reason=reason,
        kalshi_state=state,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
        gate_enabled=True,
    )


def test_canary_in_scope_signals_and_would_submit():
    evaluator, _registry = _canary_evaluator()
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    ev = _strong_sell(evaluator, position, state)
    assert ev.decision == EvDecision.SELL_SIGNALLED
    assert ev.would_submit is True


def test_canary_scope_blocks_wrong_asset_side_reason():
    evaluator, _registry = _canary_evaluator()
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    # Wrong asset: same economics on an ETH market.
    eth_market = "KXETH15M-26AUG100000-00"
    position_eth = _make_position(side="yes", entry=60, market_id=eth_market)
    ev = _strong_sell(evaluator, position_eth, state, market=eth_market)
    assert ev.decision == EvDecision.HOLD_OUTSIDE_CANARY_SCOPE
    assert "asset_not_in_canary" in ev.detail
    assert ev.would_submit is False

    # Wrong side: NO position on the BTC market.
    position_no = _make_position(side="no", entry=60)
    state_no = _make_state(yes_bid=50, yes_ask=52, no_bid=50, no_ask=52,
                           seconds_to_expiry=600.0)
    ev_no = _strong_sell(evaluator, position_no, state_no)
    assert ev_no.decision == EvDecision.HOLD_OUTSIDE_CANARY_SCOPE
    assert "side_not_in_canary" in ev_no.detail

    # Wrong reason: a gated stop-loss trigger is not in the canary allowlist.
    ev_reason = _strong_sell(evaluator, position, state, reason="stop_loss")
    assert ev_reason.decision == EvDecision.HOLD_OUTSIDE_CANARY_SCOPE
    assert "reason_not_in_canary" in ev_reason.detail


def test_canary_qty_and_expiry_window_bounds():
    evaluator, _registry = _canary_evaluator()
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    # Quantity exceeds the one-contract cap.
    position_big = _make_position(side="yes", entry=60, size=5)
    state_deep = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)
    state_deep.book = SimpleNamespace(yes_bids=[SimpleNamespace(price_cents=50, size=10)])
    ev = _strong_sell(evaluator, position_big, state_deep)
    assert ev.decision == EvDecision.HOLD_OUTSIDE_CANARY_SCOPE
    assert "qty_exceeds_canary_max_contracts" in ev.detail

    # s2e beyond the canary max: defer early-window sells until the canary band.
    position = _make_position(side="yes", entry=60)
    state_early = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=700.0)
    ev_early = _strong_sell(evaluator, position, state_early)
    # _strong_sell passes seconds_to_expiry=600; drive the early case directly.
    ev_early = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state_early,
        fair_value_cents=20,
        seconds_to_expiry=700.0,
        rti_observation=_make_rti(),
        gate_enabled=True,
    )
    assert ev_early.decision == EvDecision.HOLD_OUTSIDE_CANARY_SCOPE
    assert "above_canary_max_expiry" in ev_early.detail


def test_canary_window_order_cap():
    """One authorized exit per market window: the second sell is capped."""
    evaluator, registry = _canary_evaluator()
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    first = _strong_sell(evaluator, position, state)
    assert first.decision == EvDecision.SELL_SIGNALLED
    registry.note_exit_authorized(MARKET)

    second = _strong_sell(evaluator, position, state)
    assert second.decision == EvDecision.HOLD_OUTSIDE_CANARY_SCOPE
    assert "window_order_cap_reached" in second.detail
    assert registry.exit_orders_for(MARKET) == 1


def test_observe_only_mode_does_not_apply_canary_scope():
    """With the gate off, the true EV decision is visible (shadow), not masked
    by canary scope — the veto happens downstream at the guard."""
    evaluator, _registry = _make_evaluator(
        discretionary_mode="ev_gated_canary",
        canary_reasons=frozenset({"value_switch_exit"}),
    )
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)
    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
        gate_enabled=False,
    )
    # Gate off: canary scope is not consulted; the EV verdict stays visible.
    assert ev.decision == EvDecision.SELL_SIGNALLED
    assert ev.would_submit is False


# ── Audit fields on the evaluation record ─────────────────────────────────────

def test_eval_record_carries_fee_depth_asset_fields():
    evaluator, _registry = _make_evaluator()
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=70,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.asset == "BTC"
    assert ev.fee_model_version  # exact taker schedule, not empty
    assert ev.fee_order_type_assumption == "taker_marketable_limit"
    assert ev.exit_fee_cents is not None
    assert ev.seconds_to_expiry == 600.0


# ── Legacy-outcome annotation ─────────────────────────────────────────────────

def test_legacy_outcome_annotation_marks_eval(tmp_path):
    registry = ExitEvaluationRegistry(persist_dir=tmp_path)
    evaluator = SettlementAlignedExitEvaluator(
        policy=EvGatePolicy(min_consecutive=1, require_calibrated_model=False),
        registry=registry,
        rti_provider=lambda _a: _make_rti(),
    )
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)
    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="stop_loss",
        kalshi_state=state,
        fair_value_cents=80,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.legacy_would_approve is None

    registry.note_legacy_outcome(ev.evaluation_id, would_approve=True)
    assert registry.evaluations_for(MARKET)[-1].legacy_would_approve is True

    # The annotation line is persisted append-only alongside evaluations.
    lines = (tmp_path / "exit_evaluations.jsonl").read_text().strip().splitlines()
    import json as _json

    ann = [_json.loads(l) for l in lines if '"legacy_outcome"' in l]
    assert ann and ann[-1]["evaluation_id"] == ev.evaluation_id
    assert ann[-1]["record_type"] == "legacy_outcome"


# ── Resolver counters ─────────────────────────────────────────────────────────

def test_resolver_attempt_and_unmatched_counters():
    resolver = ExitAttemptResolver(store=None)
    assert resolver.attempts_in_flight() == 0
    assert resolver.unmatched_fill_count() == 0

    resolver.begin_attempt(market_key=MARKET, client_order_id="co-1")
    assert resolver.attempts_in_flight() == 1

    resolver.note_fill(market_key=MARKET, fill_id="f1", client_order_id="co-1",
                       quantity=1, price_cents=50)
    assert resolver.attempts_in_flight() == 0

    resolver.note_fill(market_key=MARKET, fill_id="f2", client_order_id="none",
                       quantity=1, price_cents=50)
    assert resolver.unmatched_fill_count() == 1


# ── Shadow window summary ─────────────────────────────────────────────────────

def test_shadow_window_summary_counts():
    from merid.event_venues.kalshi.settlement_aligned_exit import (
        emit_shadow_window_summary,
    )

    registry = ExitEvaluationRegistry(persist_dir=None)
    resolver = ExitAttemptResolver(store=None)
    evaluator = SettlementAlignedExitEvaluator(
        policy=EvGatePolicy(min_consecutive=1, require_calibrated_model=False),
        registry=registry,
        rti_provider=lambda _a: _make_rti(),
    )
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)

    # One sell-signalled eval + one hold + one unknown reason.
    evaluator.evaluate(
        position, market_key=MARKET, canonical_reason="value_switch_exit",
        kalshi_state=state, fair_value_cents=20, seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    evaluator.evaluate(
        position, market_key=MARKET, canonical_reason="stop_loss",
        kalshi_state=state, fair_value_cents=80, seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    evaluator.evaluate(
        position, market_key=MARKET, canonical_reason="invented_reason_x",
        kalshi_state=state, fair_value_cents=20, seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )

    result = emit_shadow_window_summary(
        registry, resolver, window_seconds=3600.0
    )
    assert result["total_evals"] == 3
    assert result["legacy_trigger_count"] == 2  # discretionary evals
    assert result["ev_sell_count"] == 1
    assert result["ev_hold_count"] == 1
    assert result["unknown_reason_blocks"] == 1
    assert "BTC" in result["assets"]
    assert result["unmatched_fills"] == 0


# ── Eval-time tail calibration (production artifact semantics) ────────────────

def test_tail_calibration_caps_hold_value_at_eval():
    """The evaluator applies the same held-side tail cap as the entry path,
    indexed by the current executable bid — not the entry price."""
    evaluator, _registry = _make_evaluator(
        tail_calibrator=_stub_calibrator(),
        require_calibrated_model=True,
    )
    position = _make_position(side="yes", entry=60)
    # Held price 20c < 35c floor; stub curve: p_yes(0.20)=0.05, cap=0.10.
    state = _make_state(yes_bid=20, yes_ask=22, seconds_to_expiry=600.0)
    state.annualized_vol_source = "rti_realized"

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=50,  # raw model says 50; calibration caps at 10
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.p_held_calibrated_cents == 10
    assert ev.p_held_raw_cents == 50
    assert ev.model_calibration_version.startswith("tail_pava:n30:sha256:")
    assert ev.model_inputs_satisfactory is True
    # cons_hold uses the calibrated 10c, not the raw 50c.
    assert Decimal(ev.conservative_hold_cents) < Decimal(20)


def test_above_floor_price_is_calibration_identity():
    """Above the tail floor the artifact asserts no cap — p_cal == raw."""
    evaluator, _registry = _make_evaluator(
        tail_calibrator=_stub_calibrator(),
        require_calibrated_model=True,
    )
    position = _make_position(side="yes", entry=60)
    state = _make_state(yes_bid=50, yes_ask=52, seconds_to_expiry=600.0)
    state.annualized_vol_source = "rti_realized"

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.p_held_calibrated_cents == 20
    assert ev.model_inputs_satisfactory is True


def test_no_held_tail_with_dual_curve_is_provisional():
    """NO-held in the tail with only a YES-dual curve blocks as uncalibrated —
    same fail-closed posture as the NO-tail entry rule."""
    evaluator, _registry = _make_evaluator(
        tail_calibrator=_stub_calibrator(dual_no=True),
        require_calibrated_model=True,
    )
    position = _make_position(side="no", entry=60)
    # NO bid 20c < 35c floor -> tail zone; dual curve -> provisional.
    state = _make_state(yes_bid=80, yes_ask=82, no_bid=20, no_ask=22,
                        seconds_to_expiry=600.0)
    state.annualized_vol_source = "rti_realized"

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=50,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert ev.decision == EvDecision.HOLD_DATA_INSUFFICIENT
    assert "no_dual_provisional" in ev.detail
    assert ev.model_calibration_no_dual is True

    # Same position above the tail floor: dual does not matter (identity).
    state_ok = _make_state(yes_bid=50, yes_ask=52, no_bid=50, no_ask=52,
                           seconds_to_expiry=600.0)
    state_ok.annualized_vol_source = "rti_realized"
    ev2 = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state_ok,
        fair_value_cents=20,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert "no_dual_provisional" not in ev2.detail


def test_no_held_tail_with_real_curve_is_not_provisional():
    """A NO-held position in the tail with a real per-side NO curve gets its
    calibrated cap applied — model inputs stay satisfactory and the salvage
    economics are evaluated instead of structurally vetoed."""
    evaluator, _registry = _make_evaluator(
        tail_calibrator=_stub_calibrator(dual_no=False),
        require_calibrated_model=True,
    )
    position = _make_position(side="no", entry=60)
    state = _make_state(yes_bid=80, yes_ask=82, no_bid=20, no_ask=22,
                        seconds_to_expiry=600.0)
    state.annualized_vol_source = "rti_realized"

    ev = evaluator.evaluate(
        position,
        market_key=MARKET,
        canonical_reason="value_switch_exit",
        kalshi_state=state,
        fair_value_cents=50,
        seconds_to_expiry=600.0,
        rti_observation=_make_rti(),
    )
    assert "no_dual_provisional" not in ev.detail
    assert ev.model_calibration_no_dual is False
    # Held price 20c maps onto the stub NO curve -> cap applied, not identity.
    assert ev.p_held_calibrated_cents == 20
