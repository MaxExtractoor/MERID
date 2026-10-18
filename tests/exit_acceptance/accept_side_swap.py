"""Side-swap metamorphic test â€” directional symmetry of the decision path.

Invariant: swap YES<->NO, complement probabilities, swap all book-side and
outcome-specific policy inputs -> the corresponding decisions and economics
must swap.  Only the asymmetries declared in DOCUMENTED_ASYMMETRIES may
deviate; the submit-time revalidation gate takes held-side economics only
and must be perfectly symmetric by construction.
"""
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.prediction.paired_side_eval import (                    # noqa: E402
    DOCUMENTED_ASYMMETRIES, from_decision, get, swap_decision,
    update_stage,
)
from merid.prediction.trade_decision import (                     # noqa: E402
    EdgeBreakdown, TradeDecision, _select_best_side,
)
from merid.execution.submit_revalidation import (                 # noqa: E402
    AcquisitionBook, SubmitRevalidationInput, revalidate_entry,
)

PASS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


def _bd(side, p_sel, price, net):
    return EdgeBreakdown(
        p_yes=0.6, p_no=0.4, selected_side=side,
        p_selected=p_sel, p_opposite=1.0 - p_sel,
        executable_entry_price=price, entry_fee=0.01,
        exit_cost_reserve=0.01, model_risk_reserve=0.0,
        gross_edge=net + 0.02, net_edge=net)


def make_decision(**kw):
    base = dict(
        run_id="r1", decision_id="d_swap", ticker="KXBTC15M-T-00",
        asset="BTC", timestamp_utc=datetime.now(timezone.utc),
        p_yes_raw=Decimal("0.62"), p_yes_calibrated=Decimal("0.60"),
        p_yes_uncertainty=Decimal("0.02"),
        p_no_calibrated=Decimal("0.40"),
        data_state="healthy", regime_label="normal",
        yes_entry_vwap=Decimal("0.55"), no_entry_vwap=Decimal("0.42"),
        yes_depth_cc=Decimal("300"), no_depth_cc=Decimal("150"),
        fee_yes=Decimal("0.015"), fee_no=Decimal("0.012"),
        expected_exit_cost_yes=Decimal("0.02"),
        expected_exit_cost_no=Decimal("0.018"),
        entry_fee_yes=Decimal("1.5"), entry_fee_no=Decimal("1.2"),
        exit_cost_reserve_yes=Decimal("2.0"),
        exit_cost_reserve_no=Decimal("1.8"),
        model_risk_reserve_yes=Decimal("0.5"),
        model_risk_reserve_no=Decimal("0.4"),
        gross_edge_yes=Decimal("5.0"), gross_edge_no=Decimal("-2.0"),
        net_edge_yes=Decimal("3.0"), net_edge_no=Decimal("-4.4"),
        selected_outcome="yes", selected_action="buy",
        selection_reason="best_executable_edge_yes",
        best_side="yes", best_net_edge=Decimal("3.0"),
        edge_threshold=Decimal("1.0"),
        policy_version="trade_decision_v2",
    )
    base.update(kw)
    return TradeDecision(**base)


print("== paired record: both sides from one snapshot ==")
d = make_decision()
rec = from_decision(d)
check("yes eligible + selected", rec.yes.eligible and
      rec.selected_side == "yes" and
      rec.yes.eligibility_reason == "selected")
check("no marked not_selected", not rec.no.eligible and
      rec.no.eligibility_reason == "not_selected:lower_net_edge")
check("yes economics carried",
      rec.yes.model_prob == 0.60 and rec.yes.net_edge_cents == 3.0
      and rec.yes.acq_price_cents == 55.0 and rec.yes.depth_cc == 300.0
      and rec.yes.fee_cents == 1.5 and rec.yes.exit_reserve_cents == 2.0)
check("no economics carried", rec.no.model_prob == 0.40 and
      rec.no.net_edge_cents == -4.4 and rec.no.acq_price_cents == 42.0)
check("complement sum ok", rec.complement_sum_ok is True)
check("asymmetries declared", bool(rec.asymmetries) and
      "counter_model_premium" in rec.asymmetries)

print("== metamorphic swap: decision -> mirror record ==")
sw = swap_decision(d)
check("probs complemented", float(sw.p_yes_calibrated) == 0.40
      and float(sw.p_no_calibrated) == 0.60)
check("selected flipped", sw.selected_outcome == "no")
check("economics swapped", float(sw.entry_fee_yes) == 1.2
      and float(sw.net_edge_yes) == -4.4
      and float(sw.yes_entry_vwap) == 0.42)

from dataclasses import replace as _replace                       # noqa: E402
sw = _replace(sw, decision_id="d_swap_sw")
rec2 = from_decision(sw)
m1, m2 = rec.yes, rec2.no     # original YES must mirror swapped NO
check("mirror prob", m2.model_prob == m1.model_prob)
check("mirror price/depth", m2.acq_price_cents == m1.acq_price_cents
      and m2.depth_cc == m1.depth_cc)
check("mirror fee/reserves", m2.fee_cents == m1.fee_cents
      and m2.exit_reserve_cents == m1.exit_reserve_cents
      and m2.model_risk_reserve_cents == m1.model_risk_reserve_cents)
check("mirror edges", m2.gross_edge_cents == m1.gross_edge_cents
      and m2.net_edge_cents == m1.net_edge_cents)
check("mirror eligibility", m2.eligible == m1.eligible
      and m2.eligibility_reason == m1.eligibility_reason)
check("mirror selection", rec2.selected_side == "no"
      and rec2.yes.eligibility_reason == "not_selected:lower_net_edge")

print("== submit gate: perfectly symmetric on held-side economics ==")
book = AcquisitionBook(levels=[(54, 200), (55, 200), (57, 100)],
                       book_age_ms=100)
now = time.time()
inp_yes = SubmitRevalidationInput(
    candidate_id="c", held_side="yes", qty_cc=300,
    proposed_limit_cents=58, p_held_cents=Decimal("66"),
    prob_est_ts=now, book=book,
    fee_per_contract_cents=Decimal("1.75"),
    reserves_per_contract_cents=Decimal("3.75"),
    required_edge_per_contract_cents=Decimal("2"))
inp_no = SubmitRevalidationInput(
    candidate_id="c", held_side="no", qty_cc=300,
    proposed_limit_cents=58, p_held_cents=Decimal("66"),
    prob_est_ts=now, book=book,
    fee_per_contract_cents=Decimal("1.75"),
    reserves_per_contract_cents=Decimal("3.75"),
    required_edge_per_contract_cents=Decimal("2"))
dy, dn = revalidate_entry(inp_yes), revalidate_entry(inp_no)
check("same outcome", dy.outcome == dn.outcome == "submit_edge_valid",
      f"{dy.outcome}/{dn.outcome}")
check("same EV", dy.ev_order_cents == dn.ev_order_cents
      and dy.ev_per_contract_cents == dn.ev_per_contract_cents)
check("same bound", dy.max_price_cents == dn.max_price_cents
      and dy.permitted_limit_cents == dn.permitted_limit_cents)

print("== tie behavior: canonical engine picks neither side ==")
side, edge, reason = _select_best_side(
    _bd("yes", 0.6, 0.55, 0.03), _bd("no", 0.4, 0.35, 0.03))
check("directional_tie -> no-trade", side is None
      and reason == "directional_tie", f"{side}:{reason}")

print("== registry + stage update ==")
update_stage(d.decision_id, "yes", submit_result="submit_edge_valid",
             allocator_result="approved:300cc",
             final_direction="buy_yes",
             router_handoff={"side": "BUY_YES", "price_cents": 58,
                             "count_cc": 300})
stored = get(d.decision_id)
check("selected side stages recorded",
      stored is not None and stored.yes.submit_result == "submit_edge_valid"
      and stored.yes.allocator_result == "approved:300cc"
      and stored.yes.router_handoff["side"] == "BUY_YES")
check("sibling stays not_selected",
      stored is not None and stored.no.submit_result == "not_selected")

print("== complement-sum flag catches asymmetric probabilities ==")
bad = from_decision(make_decision(
    decision_id="d_bad", p_no_calibrated=Decimal("0.50"),
    selected_outcome="yes"))
check("asymmetric probs flagged", bad.complement_sum_ok is False)

fails = [n for n, ok in PASS if not ok]
print(f"\nSIDE-SWAP: {len(PASS) - len(fails)}/{len(PASS)} passed")
if fails:
    print("FAILURES:", fails)
sys.exit(0 if not fails else 1)

