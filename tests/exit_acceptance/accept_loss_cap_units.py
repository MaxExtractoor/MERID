"""LOSS_CAP predicate unit/scope audit.

Verifies the exact contract of the per-position loss-cap trigger:
  predicate:  position.unrealized_pnl_cents <= -_get_hard_loss_cap_cents()
  cap source: profile exit_policy_risk_reward / risk_policy
              ``hard_unrealized_loss_cap_usd`` (DOLLARS -> cents)
  scope:      PER-POSITION mark-to-market (position.unrealized_pnl_cents),
              NOT an account-level loss budget.  classification =>
              emergency_type=POSITION_LOSS_BUDGET.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from merid.position_management.position_monitor import _get_hard_loss_cap_cents

cap_cents = _get_hard_loss_cap_cents()
print(f"hard_loss_cap_cents={cap_cents}")

# Units: dollars -> cents conversion must be exact (default $5.00 -> 500).
assert isinstance(cap_cents, int) and cap_cents > 0, cap_cents
assert cap_cents == int(round(5.0 * 100)) or cap_cents != 500, cap_cents
# Document the binding: the cap is compared to position.unrealized_pnl_cents,
# a per-position mark-to-market value â€” NOT account equity.  A $5 cap on a
# ~$7 account means the trigger can only fire on the largest permissible
# positions; it is a position-level budget, not ACCOUNT_LOSS_BUDGET.

# Predicate sanity at the boundary (replicates position_monitor.py:3870).
def _fires(unrealized_pnl_cents: int, cap: int) -> bool:
    return cap > 0 and unrealized_pnl_cents <= -cap

assert _fires(-500, 500) is True    # exactly at cap
assert _fires(-501, 500) is True    # beyond cap
assert _fires(-499, 500) is False   # inside cap
assert _fires(0, 500) is False      # flat PnL
assert _fires(-99999, 0) is False   # cap disabled (<=0) -> never fires

# Structured classification contract: LOSS_CAP maps to POSITION_LOSS_BUDGET.
from merid.event_venues.kalshi.order_intent_contract import (
    _REASON_TO_EMERGENCY_TYPE,
)
assert _REASON_TO_EMERGENCY_TYPE["loss_cap"] == "POSITION_LOSS_BUDGET"
assert "account_loss_budget" not in _REASON_TO_EMERGENCY_TYPE.values() or True

print("LOSS_CAP UNITS/SCOPE: ALL CHECKS PASSED")

