"""Direct runner for the lane-contract tests (bypasses pytest collection)."""
import sys
from decimal import Decimal
from types import SimpleNamespace

sys.path.insert(0, r"C:\Dev\MERID")
from merid.event_venues.kalshi.parabolic_fees import kalshi_fee_cents_exact
from merid.execution.submit_revalidation import input_from_intent


def _intent(**kw):
    base = dict(
        intent_id="intent_test", ticker="KXETH15M-T", side="no",
        action="BUY", price_cents=33, count=6, count_fp=None,
        p_selected=Decimal("0.366685"), p_yes=Decimal("0.633315"),
        p_no=Decimal("0.366685"), model_prob=None, snapshot_ts=None,
        decision_ts=None, post_only=True, liquidity_role="maker",
        execution_mode="maker", min_required_edge=None,
        edge_bound_source=None, self_trade_prevention_type=None,
        entry_model=None, market_status="open",
    )
    base.update(kw)
    return SimpleNamespace(**base)


results = []
def check(name, cond, extra=""):
    results.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + ("  " + extra if extra else ""))

# maker fee role
rin = input_from_intent(_intent(min_required_edge=Decimal("-0.10")))
exp = kalshi_fee_cents_exact(Decimal("0.33"), Decimal(1), "maker")
tak = kalshi_fee_cents_exact(Decimal("0.33"), Decimal(1), "taker")
check("maker_fee", rin.fee_per_contract_cents == exp,
      f"{rin.fee_per_contract_cents} vs maker={exp} taker={tak}")

# taker role
rin2 = input_from_intent(_intent(post_only=False, liquidity_role="taker",
                                 execution_mode="taker",
                                 min_required_edge=Decimal("0.015")))
check("taker_fee", rin2.fee_per_contract_cents == tak,
      str(rin2.fee_per_contract_cents))

# ETH replay
rin3 = input_from_intent(_intent(
    edge_bound_source="lane_floor:cheap_no_settle",
    min_required_edge=Decimal("-0.10")))
p = rin3.p_held_cents
mp = int(p - rin3.fee_per_contract_cents - rin3.reserves_per_contract_cents
         - rin3.required_edge_per_contract_cents)
check("eth_replay_max>=33", mp >= 33, f"max_price={mp}")
old_mp = int(p - tak - Decimal("0") - Decimal("3.1844"))
check("old_defect_reproduces_31", old_mp == 31, f"old_max={old_mp}")

# missing bound contract error
rin4 = input_from_intent(_intent(
    edge_bound_source="lane_floor:cheap_no_settle", min_required_edge=None))
check("missing_bound_fails_closed", rin4 is None)

# env default preserved
rin5 = input_from_intent(_intent(edge_bound_source=None,
                                 min_required_edge=None))
check("env_default_1.5", rin5 is not None and
      rin5.required_edge_per_contract_cents == Decimal("1.5"),
      str(rin5 and rin5.required_edge_per_contract_cents))

# route_bound falls through to default
rin6 = input_from_intent(_intent(edge_bound_source="route_bound",
                                 min_required_edge=None))
check("route_bound_default", rin6 is not None and
      rin6.required_edge_per_contract_cents == Decimal("1.5"))

# lane sweep
for lane, floor in [("cheap_no_settle", "-10"), ("pinned_fav", "-12"),
                    ("drift_fav", "-8"), ("settlement_convergence", "-5"),
                    ("window_quota", "-25")]:
    r = input_from_intent(_intent(
        edge_bound_source=f"lane_floor:{lane}",
        min_required_edge=Decimal(floor) / Decimal("100")))
    check(f"floor_{lane}", r is not None and
          r.required_edge_per_contract_cents == Decimal(floor),
          str(r and r.required_edge_per_contract_cents))

print()
n_fail = sum(1 for _, ok in results if not ok)
print(f"{len(results)-n_fail} passed, {n_fail} failed")
sys.exit(1 if n_fail else 0)
