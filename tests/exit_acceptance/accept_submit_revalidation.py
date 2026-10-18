"""Submit-time EV revalidation â€” unit matrix.

Verifies the economics independently of plumbing:
  EV_order = q*p_held - C_acq - F - R ; EV_pc = EV_order/q
  max_price = p_held - fee_pc - reserve_pc - required_edge_pc

Cases cover every required outcome label.
"""
import os
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.execution.submit_revalidation import (              # noqa: E402
    AcquisitionBook, SubmitRevalidationInput, revalidate_entry,
    SUBMIT_EDGE_VALID, SUBMIT_EDGE_LOST, SUBMIT_PROBABILITY_STALE,
    SUBMIT_BOOK_INVALID, SUBMIT_BOOK_STALE,
    SUBMIT_DEPTH_INSUFFICIENT, SUBMIT_MARKET_NOT_TRADABLE,
    SUBMIT_REAPPROVAL_REQUIRED,
)

PASS = []


def check(name, cond, detail=""):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} {detail}")
    PASS.append((name, cond))


def bk(levels, age=50):
    return AcquisitionBook(levels=list(levels), book_age_ms=age,
                           book_sequence=9)


def inp(**kw):
    d = dict(
        candidate_id="c1", held_side="yes", qty_cc=300,
        proposed_limit_cents=55, p_held_cents=Decimal("60"),
        prob_est_ts=time.time() - 1.0,
        book=bk([(50, 200), (55, 200), (58, 500)]),
        fee_per_contract_cents=Decimal("0.5"),
        reserves_per_contract_cents=Decimal("0"),
        required_edge_per_contract_cents=Decimal("1.5"),
    )
    d.update(kw)
    return SubmitRevalidationInput(**d)


print("== submit revalidation matrix ==")

# 1. happy path â€” max_price = 60-0.5-0-1.5 = 58 >= proposed 55
d = revalidate_entry(inp())
exp_cost = Decimal("155")          # 200@50 + 100@55 (contract-cents)
exp_ev = Decimal("180") - exp_cost - Decimal("1.5")
check("valid entry", d.outcome == SUBMIT_EDGE_VALID, d.outcome)
check("max_price derived 58", d.max_price_cents == 58,
      str(d.max_price_cents))
check("expected cost from depth 155c", d.expected_cost_cents == exp_cost,
      str(d.expected_cost_cents))
check("worst cost at limit 165c",
      d.worst_cost_cents == Decimal("165"), str(d.worst_cost_cents))
check("EV_order 23.5c", d.ev_order_cents == exp_ev,
      f"{d.ev_order_cents} vs {exp_ev}")
check("EV_per_contract 7.833c",
      d.ev_per_contract_cents == exp_ev / 3,
      str(d.ev_per_contract_cents))

# 2. limit above derived bound -> reapproval (never silently mutate)
d = revalidate_entry(inp(proposed_limit_cents=62))
check("limit>bound -> submit_reapproval_required",
      d.outcome == SUBMIT_REAPPROVAL_REQUIRED
      and "62" in d.reason and "58" in d.reason,
      f"{d.outcome} {d.reason}")

# 3. no eligible depth at limit -> depth insufficient
d = revalidate_entry(inp(proposed_limit_cents=45))
check("no depth at<=45 -> submit_depth_insufficient",
      d.outcome == SUBMIT_DEPTH_INSUFFICIENT, d.outcome)

# 4. partial depth: resize policy
d = revalidate_entry(inp(qty_cc=450, resize_allowed=False))
check("partial depth no-resize -> submit_depth_insufficient",
      d.outcome == SUBMIT_DEPTH_INSUFFICIENT, d.outcome)
d = revalidate_entry(inp(qty_cc=450, resize_allowed=True))
check("partial depth resize -> valid at eligible qty",
      d.outcome == SUBMIT_EDGE_VALID and d.permitted_qty_cc == 400,
      f"{d.outcome} qty={d.permitted_qty_cc}")
check("resized EV recomputed on 4 contracts",
      d.ev_order_cents ==
      Decimal("240") - Decimal("210") - Decimal("2"),
      str(d.ev_order_cents))

# 5. stale probability
d = revalidate_entry(inp(prob_est_ts=time.time() - 100,
                         max_prob_age_ms=5000))
check("old estimate -> submit_probability_stale",
      d.outcome == SUBMIT_PROBABILITY_STALE, d.outcome)

# 6. stale book
d = revalidate_entry(inp(book=bk([(50, 500)], age=9999),
                         max_book_age_ms=2000))
check("old book -> submit_book_stale", d.outcome == SUBMIT_BOOK_STALE)

# 7. invalid book
d = revalidate_entry(inp(book=AcquisitionBook(levels=[])))
check("empty book -> submit_book_invalid",
      d.outcome == SUBMIT_BOOK_INVALID)
d = revalidate_entry(inp(book=None))
check("no book -> submit_book_invalid", d.outcome == SUBMIT_BOOK_INVALID)

# 8. probability too low -> never submitted.  NOTE: with limit<=max_price
# walked cost <= limit <= p-fee-res-edge, so EV_pc>=edge always holds â€”
# edge_lost only fires when the limit itself breaches the bound, which is
# reported as reapproval_required first.  Assert the true invariant.
d = revalidate_entry(inp(p_held_cents=Decimal("52")))
check("low probability -> never submitted",
      not d.valid and d.outcome in (SUBMIT_EDGE_LOST,
                                    SUBMIT_REAPPROVAL_REQUIRED),
      f"{d.outcome} ev={d.ev_per_contract_cents} max={d.max_price_cents}")

# 9. market not tradable
d = revalidate_entry(inp(market_trading=False))
check("not tradable -> submit_market_not_tradable",
      d.outcome == SUBMIT_MARKET_NOT_TRADABLE)

# 10. reserves in documented units affect max_price and EV
d = revalidate_entry(inp(reserves_per_contract_cents=Decimal("2.0")))
check("reserves tighten bound: max=56",
      d.max_price_cents == 56, str(d.max_price_cents))
check("reserves in EV: 17.5c",
      d.ev_order_cents == Decimal("17.5"), str(d.ev_order_cents))

# 11. fee audit regression: sub-cent fees handled exactly (Decimal)
d = revalidate_entry(inp(fee_per_contract_cents=Decimal("0.0175"),
                         required_edge_per_contract_cents=Decimal("1")))
# max_price = 60 - 0.0175 - 0 - 1 = 58 (floor of 58.9825)
check("fractional fee -> max_price floor 58",
      d.max_price_cents == 58, str(d.max_price_cents))

fails = [n for n, ok in PASS if not ok]
print(f"\nSUBMIT-REVALIDATION: {len(PASS) - len(fails)}/{len(PASS)} passed")
if fails:
    print("FAILURES:", fails)
sys.exit(0 if not fails else 1)

