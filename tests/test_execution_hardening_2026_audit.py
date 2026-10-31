"""Hardening-pack tests for the 2026 execution-chain audit follow-up.

Covers the four priority boundaries:
  1. Feed integrity — missing seq on a sequenced orderbook delta invalidates
     execution (Kalshi documents contiguous seq, including conflated mode).
  2. Endpoint capability — reduce_only requires IOC; IOC rejects expiry.
  3. Own-liquidity depth — STP-aware walk (taker_at_cross halts; maker skips).
  4. Fee model — 6dp model fee + balance alignment + order-scope reconcile;
     independent oracle agreement on the golden fixture.
"""

from decimal import Decimal

import pytest

from merid.event_venues.kalshi.contract_fingerprint import (
    compute_contract_fingerprints,
    fingerprints_match,
)
from merid.event_venues.kalshi.client import validate_kalshi_wire_compat
from merid.event_venues.kalshi.executable_quote import (
    QuotePurpose,
    _vwap_with_ownership,
    _own_qty_by_level,
)
from merid.event_venues.kalshi.parabolic_fees import (
    estimate_order_fee_bound_cents,
    kalshi_fee_cents_exact,
    model_trade_fee_dollars,
    reconcile_order_fees_dollars,
)
from merid.audit.economics_oracle import (
    OracleOwnOrder,
    asks_for,
    evaluate_buy,
    model_fee_dollars as oracle_model_fee,
    fee_bound_dollars as oracle_fee_bound,
    walk as oracle_walk,
)


# ── 1. Feed integrity ────────────────────────────────────────────────────

class _Ob:
    initialized = True
    last_seq = 10


def _market_state():
    from merid.event_venues.kalshi.market_state import KalshiMarketStateStore
    return KalshiMarketStateStore()


def test_missing_seq_invalidates_tracked_book():
    store = _market_state()
    ok, expected, got = store._validate_delta_sequence(
        "KXBTCD-T1", {"side": "yes", "price_dollars": 0.5, "delta_fp": 1}, _Ob()
    )
    assert ok is False
    assert expected == 11
    assert got is None


def test_unparseable_seq_invalidates_tracked_book():
    store = _market_state()
    ok, expected, got = store._validate_delta_sequence(
        "KXBTCD-T1", {"seq": "bogus"}, _Ob()
    )
    assert ok is False
    assert expected == 11
    assert got == "bogus"


def test_contiguous_seq_still_valid():
    store = _market_state()
    ok, expected, got = store._validate_delta_sequence(
        "KXBTCD-T1", {"seq": 11}, _Ob()
    )
    assert ok is True and got == 11


def test_no_baseline_still_unchecked():
    # No prior seq => no contiguity claim can be evaluated; executability
    # remains governed by the separate bootstrap/initialization gates.
    class _Fresh:
        initialized = False
        last_seq = None
    store = _market_state()
    ok, _, _ = store._validate_delta_sequence("KXBTCD-T1", {}, _Fresh())
    assert ok is True


# ── 2. Endpoint capability matrix ────────────────────────────────────────

def test_reduce_only_requires_ioc():
    assert validate_kalshi_wire_compat(
        {"reduce_only": True, "time_in_force": "immediate_or_cancel"}
    ) is None
    r = validate_kalshi_wire_compat(
        {"reduce_only": True, "time_in_force": "good_till_canceled"}
    )
    assert r and r.startswith("reduce_only_requires_ioc")
    r = validate_kalshi_wire_compat(
        {"reduce_only": True, "time_in_force": "fill_or_kill"}
    )
    assert r and r.startswith("reduce_only_requires_ioc")


def test_ioc_rejects_expiration():
    r = validate_kalshi_wire_compat(
        {"time_in_force": "immediate_or_cancel", "expiration_time": 123}
    )
    assert r and r.startswith("tif_with_expiration")
    assert validate_kalshi_wire_compat(
        {"time_in_force": "good_till_canceled", "expiration_time": 123}
    ) is None


def test_post_only_ioc_still_rejected():
    r = validate_kalshi_wire_compat(
        {"post_only": True, "time_in_force": "immediate_or_cancel"}
    )
    assert r and r.startswith("post_only_incompatible_with_tif")


def test_canonical_intent_rejects_reduce_only_gtc():
    from merid.event_venues.kalshi.order_intent_contract import (
        CanonicalOrderIntent,
        validate_canonical_intent,
        OrderIntentValidationError,
    )
    intent = CanonicalOrderIntent(
        market_ticker="KXBTCD-T1",
        contract="yes",
        action="sell",
        purpose="close",
        qty_cc=100,
        limit_cents=50,
        strategy_signal="up",
        expected_position_before=100,
        expected_position_after=0,
        expected_realized_pnl_cents=None,
        reason="test",
        reduce_only=True,
        time_in_force="gtc",
    )
    with pytest.raises(OrderIntentValidationError) as exc:
        validate_canonical_intent(intent)
    assert "reduce_only_requires_ioc" in str(exc.value)


def test_canonical_intent_accepts_reduce_only_ioc():
    from merid.event_venues.kalshi.order_intent_contract import (
        CanonicalOrderIntent,
        validate_canonical_intent,
    )
    intent = CanonicalOrderIntent(
        market_ticker="KXBTCD-T1",
        contract="yes",
        action="sell",
        purpose="close",
        qty_cc=100,
        limit_cents=50,
        strategy_signal="up",
        expected_position_before=100,
        expected_position_after=0,
        expected_realized_pnl_cents=None,
        reason="test",
        reduce_only=True,
        time_in_force="ioc",
        time_to_expiry_seconds=60.0,
    )
    # purpose=close skips the entry-only checks; may still hit other
    # close-path guards, so assert only that the reduce_only check passes.
    try:
        validate_canonical_intent(intent)
    except Exception as exc:
        assert "reduce_only_requires_ioc" not in str(exc)


# ── 3. Own-liquidity depth / STP simulation ──────────────────────────────

def test_taker_at_cross_stops_before_own_level():
    levels = [(50, 10), (49, 10), (48, 10)]  # own qty at 49
    vwap, covered, top, blocked, anomaly = _vwap_with_ownership(
        levels, {49: 10}, 30, stp="taker_at_cross"
    )
    assert covered == 10           # only external depth before the barrier
    assert vwap == 50.0
    assert blocked == 10
    assert anomaly is False


def test_maker_stp_skips_own_and_continues():
    levels = [(50, 10), (49, 10), (48, 10)]  # own qty at 49
    vwap, covered, top, blocked, anomaly = _vwap_with_ownership(
        levels, {49: 10}, 30, stp="maker"
    )
    assert covered == 20           # 50x10 + 48x10; own 49s skipped
    assert blocked == 10


def test_mixed_level_taker_conservative():
    levels = [(50, 10)]            # 4 own of 10
    vwap, covered, top, blocked, anomaly = _vwap_with_ownership(
        levels, {50: 4}, 10, stp="taker_at_cross"
    )
    assert covered == 0            # unknown queue position -> no fill credit
    assert blocked == 4


def test_own_gt_level_flags_anomaly():
    levels = [(50, 5)]
    _, covered, _, _, anomaly = _vwap_with_ownership(
        levels, {50: 9}, 5, stp="maker"
    )
    assert anomaly is True
    assert covered == 0


def test_own_overlay_entry_complement():
    # Buying YES at ask level 57 collides with own buy-no@43 (100-57).
    orders = [
        type("O", (), {
            "market_id": "KXBTCD-T1", "status": "resting",
            "side": "buy", "outcome_id": "no", "price": Decimal("0.43"),
            "remaining_size": Decimal("3"), "raw_data": {},
            "size": Decimal("3"), "filled_size": Decimal("0"),
        })(),
        type("O", (), {
            "market_id": "KXBTCD-T1", "status": "resting",
            "side": "sell", "outcome_id": "yes", "price": Decimal("0.55"),
            "remaining_size": Decimal("2"), "raw_data": {},
            "size": Decimal("2"), "filled_size": Decimal("0"),
        })(),
    ]
    own_map, unatt = _own_qty_by_level(
        "KXBTCD-T1", "yes", QuotePurpose.ENTRY, own_orders=orders
    )
    assert own_map.get(57) == 3
    assert own_map.get(55) == 2
    assert unatt == 0


# ── 4. Fee model + independent oracle ────────────────────────────────────

def test_model_fee_golden_fills():
    # Verified live fills (AGENTS): 1 @47c -> $0.0175 ; 1 @1.1c -> $0.0008
    assert model_trade_fee_dollars(0.47, Decimal("1"), "taker") == Decimal("0.017437")
    assert estimate_order_fee_bound_cents(0.47, Decimal("1"), "taker") == Decimal("1.75")
    assert estimate_order_fee_bound_cents(0.011, Decimal("1"), "taker") == Decimal("0.08")


def test_exact_matches_bound_estimate():
    for p in (0.01, 0.10, 0.47, 0.55, 0.92, 0.99):
        for q in ("0.5", "1", "2.5", "6"):
            assert kalshi_fee_cents_exact(p, Decimal(q), "taker") == \
                estimate_order_fee_bound_cents(p, Decimal(q), "taker")


def test_order_scope_reconciliation():
    # Accumulator tolerance: one balance-precision unit per fill.
    actual = [Decimal("0.0175"), Decimal("0.0174"), Decimal("0.0175")]
    model = [Decimal("0.017437"), Decimal("0.017437"), Decimal("0.017437")]
    res = reconcile_order_fees_dollars(actual, model)
    assert res["within_documented_scope"] is True
    res2 = reconcile_order_fees_dollars(
        [a + Decimal("0.01") for a in actual], model
    )
    assert res2["within_documented_scope"] is False


def test_oracle_agrees_on_golden_book():
    # Spec fixture: YES bid 56, NO bid 43 -> YES ask 57, NO ask 44.
    # p_yes=0.60 -> YES gross edge +0.03, NO gross edge -0.04 before fees.
    yes_bids = [(56, 10)]
    no_bids = [(43, 10)]
    assert asks_for("yes", yes_bids, no_bids) == [(57, 10)]
    assert asks_for("no", yes_bids, no_bids) == [(44, 10)]

    r_yes = evaluate_buy("yes", 1, 99, Decimal("0.60"), yes_bids, no_bids)
    r_no = evaluate_buy("no", 1, 99, Decimal("0.60"), yes_bids, no_bids)
    # gross EV per contract before fees
    assert (r_yes.net_ev_dollars + r_yes.fee_dollars) == Decimal("0.03")
    assert (r_no.net_ev_dollars + r_no.fee_dollars) == Decimal("-0.04")


def test_oracle_stp_agrees_with_production_walk():
    levels = [(50, 10), (49, 10)]
    own = {49: 10}
    prod = _vwap_with_ownership(levels, own, 20, stp="taker_at_cross")
    ref = oracle_walk(levels, 20, own, stp="taker_at_cross")
    assert prod[1] == ref[0]      # covered
    assert prod[0] == float(ref[1] / ref[0])  # vwap


def test_oracle_monotonicity_properties():
    # Worse buy price cannot improve EV; higher fee cannot improve EV.
    base = evaluate_buy("yes", 1, 99, Decimal("0.60"), [(56, 5)], [(43, 5)])
    worse_book = evaluate_buy("yes", 1, 99, Decimal("0.60"), [(56, 5)], [(40, 5)])
    assert worse_book.net_ev_dollars < base.net_ev_dollars
    own_barrier = evaluate_buy(
        "yes", 10, 99, Decimal("0.60"), [(56, 5)], [(43, 10)],
        own_orders=[OracleOwnOrder("buy", "no", 43, 10)],
    )
    # Own buy-no@43 sits at YES-ask@57 — taker_at_cross gives zero external depth.
    assert own_barrier.executable_qty == 0


# ── 5. Contract fingerprints ─────────────────────────────────────────────

def test_fingerprint_semantics_exclude_volatile():
    m = {
        "rules_primary": "pays $1 if BTC above strike at expiry",
        "close_time": "2026-11-01T00:00:00Z",
        "price_ranges": [{"start": 1, "end": 99}],
        "yes_bid": 55, "volume": 12345,
    }
    s1, e1 = compute_contract_fingerprints(m)
    m2 = dict(m, yes_bid=60, volume=99999)
    s2, e2 = compute_contract_fingerprints(m2)
    assert (s1, e1) == (s2, e2)  # volatile fields must not change fingerprint


def test_fingerprint_rules_change_detected():
    m = {"rules_primary": "v1", "status": "open"}
    s1, e1 = compute_contract_fingerprints(m)
    m2 = dict(m, rules_primary="v2")
    s2, e2 = compute_contract_fingerprints(m2)
    assert s1 != s2
    assert not fingerprints_match((s1, e1), (s2, e2))


def test_fingerprint_missing_is_mismatch():
    s, e = compute_contract_fingerprints({"rules_primary": "x", "status": "open"})
    assert not fingerprints_match((s, e), (None, None))
    assert compute_contract_fingerprints(None) == (None, None)


# ── 6. Submit-time own-overlay vetoes (the last depth gate before wire) ──

from merid.execution.submit_revalidation import (
    SUBMIT_DEPTH_INSUFFICIENT,
    SUBMIT_DEPTH_UNRELIABLE,
    SUBMIT_EDGE_VALID,
    AcquisitionBook,
    SubmitRevalidationInput,
    _walk_book_owned,
    revalidate_entry,
)


def _inp(book, stp="taker_at_cross", qty_cc=500):
    return SubmitRevalidationInput(
        candidate_id="c1",
        held_side="yes",
        qty_cc=qty_cc,
        proposed_limit_cents=55,
        p_held_cents=Decimal("90"),
        prob_est_ts=None,
        book=book,
        fee_per_contract_cents=Decimal("0"),
        reserves_per_contract_cents=Decimal("0"),
        required_edge_per_contract_cents=Decimal("0"),
        self_trade_prevention=stp,
    )


def test_walk_book_owned_taker_halts_before_own():
    # qty_cc units: level 50c holds 1000cc; 400cc is own.
    elig, cost, anomaly = _walk_book_owned(
        [(50, 1000), (55, 1000)], {55: 400}, 60, 1500,
        stp="taker_at_cross")
    assert elig == 1000 and anomaly is False  # halted before the 55 level


def test_walk_book_owned_maker_skips_own():
    elig, cost, anomaly = _walk_book_owned(
        [(50, 1000), (55, 1000)], {55: 400}, 60, 1500, stp="maker")
    assert elig == 1500 and anomaly is False  # 1000@50 + 500 external @55


def test_submit_veto_on_incomplete_own_overlay():
    book = AcquisitionBook(levels=[(50, 1000)], own_evidence_complete=False)
    d = revalidate_entry(_inp(book))
    assert d.outcome == SUBMIT_DEPTH_UNRELIABLE
    assert d.reason == "own_overlay_incomplete"


def test_submit_veto_on_unattributable_own():
    book = AcquisitionBook(levels=[(50, 1000)], own_unattributable=2)
    d = revalidate_entry(_inp(book))
    assert d.outcome == SUBMIT_DEPTH_UNRELIABLE


def test_submit_veto_on_own_gt_public_anomaly():
    book = AcquisitionBook(levels=[(50, 1000)], own_levels={50: 1200})
    d = revalidate_entry(_inp(book))
    assert d.outcome == SUBMIT_DEPTH_UNRELIABLE
    assert d.reason == "own_gt_public_level"


def test_submit_taker_depth_insufficient_behind_own_barrier():
    # All reachable depth is behind/inside our own level at 50.
    book = AcquisitionBook(levels=[(50, 1000)], own_levels={50: 400})
    d = revalidate_entry(_inp(book))
    assert d.outcome == SUBMIT_DEPTH_INSUFFICIENT


def test_submit_maker_stp_skips_own_and_passes():
    # Same book under maker STP: own 400cc skipped; external 600cc covers
    # the 500cc request (eligible is capped at the requested qty).
    book = AcquisitionBook(levels=[(50, 1000)], own_levels={50: 400})
    d = revalidate_entry(_inp(book, stp="maker"))
    assert d.outcome == SUBMIT_EDGE_VALID
    assert d.eligible_qty_cc == 500
    # Requesting beyond external depth still fails closed: 800cc wanted,
    # only 600cc external remains after skipping own.
    d2 = revalidate_entry(_inp(book, stp="maker", qty_cc=800))
    assert d2.outcome == SUBMIT_DEPTH_INSUFFICIENT
    assert d2.eligible_qty_cc == 600
