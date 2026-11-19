"""Structural regression: the bid-priced maker pass must stay reachable at
is_late (TTE <= 120s).

2026-11-19 audit: ``elif maker_entries_enabled and not is_late:`` made the
else-branch — the ``route="maker_bid"`` eval, sole emission vehicle for
pinned_fav maker mode / drift_fav / late_edge_probe — unreachable in the
TTE 45-120s window those lanes are explicitly armed for (pf TTE-floor
exemption, lane window 45-840s).  Every pf maker-mode ENTER at TTE<120s
died as ``pinned_fav_maker_only`` with zero :maker_bid evals ever emitted.

The engine's per-lane floors (min_tte + exemptions) decide admission; the
grid must not pre-empt the emission vehicle.  This test asserts the branch
guard stays free of the is_late conjunction and that the else-branch keeps
a decision fallback for the is_late case (decision_maker is None there).
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "merid" / "prediction" / "agent_grid_15m.py"


def _branch_contains_maker_bid(body):
    """True when an If body's subtree evaluates route='maker_bid'."""
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.keyword) and node.arg == "route":
            if (
                isinstance(node.value, ast.Constant)
                and node.value.value == "maker_bid"
            ):
                return True
    return False


def test_bid_pass_branch_not_gated_on_is_late():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Inspect every branch (body and each elif's nested If in orelse).
        branches = [(node.test, node.body)]
        cur = node
        while cur.orelse and isinstance(cur.orelse[0], ast.If):
            cur = cur.orelse[0]
            branches.append((cur.test, cur.body))
        if cur.orelse:
            branches.append((None, cur.orelse))
        for test, body in branches:
            if not _branch_contains_maker_bid(body):
                continue
            if test is None:
                continue  # bare else: always reachable — the goal state.
            names = {
                n.id for n in ast.walk(test) if isinstance(n, ast.Name)
            }
            assert "is_late" not in names, (
                "the branch containing the maker_bid eval is gated on "
                "is_late — unreachable at TTE<=120s again"
            )
            checked += 1
    assert checked >= 1, "maker_bid eval not found under any guarded branch"


def test_bid_pass_else_branch_has_decision_fallback():
    """The else-branch assign `decision = decision_maker if ... else decision_taker`."""
    text = SRC.read_text(encoding="utf-8")
    anchor = text.index('route="maker_bid"')
    # The fallback assignment must appear before the maker_bid eval call.
    head = text[:anchor]
    assert "if decision_maker is not None" in head, (
        "else-branch lost the decision_maker-None fallback — "
        "decision would be None at is_late and crash on .indicators access"
    )


def test_pinned_fav_no_bid_fallback_present():
    """NO-side pf reachability must fall back to best_no_bid_cents when the
    YES ask is empty (one-sided converged book), not derive a fake 100c."""
    text = SRC.read_text(encoding="utf-8")
    anchor = text.index("_pf_no_px")
    segment = text[anchor : anchor + 700]
    assert "best_no_bid_cents" in segment, (
        "_pf_no_px lost the best_no_bid_cents fallback — a missing YES ask "
        "derives NO bid as 100 - 0 = 100c and silently fails reachability"
    )
