"""Regression: every slot-allocator price check in order_router must carry
decision_lane so lane-banded lanes (pinned_fav 82-91c maker band) are not
rejected by the generic 80c profile ceiling.

Live 2026-10-21: XRP pinned_fav resting bids at 82-90c were rejected
`slot_allocation_failed:Entry price 86c above maximum 80c` and
`invalid_order_request:entry_price_outside_canonical_range` — the allocator's
_lane_entry_band_cents hook existed but the router call sites dropped the
lane.  AST-level audit: all can_allocate call sites must pass decision_lane
and the canonical entry-range check must resolve the lane band.
"""

import ast


def _router_calls(func_name):
    with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    calls = []

    def _walk(node):
        for child in ast.iter_child_nodes(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and child.func.attr == func_name
            ):
                calls.append(child)
            _walk(child)

    _walk(tree)
    return calls


def _call_keywords(call):
    return {kw.arg for kw in call.keywords if kw.arg}


def test_all_can_allocate_sites_pass_decision_lane():
    """Every can_allocate() call in the router must forward the intent's
    decision_lane so the allocator resolves the lane entry band."""
    calls = _router_calls("can_allocate")
    assert calls, "order_router.py should call slot_allocator.can_allocate"
    missing = [c.lineno for c in calls if "decision_lane" not in _call_keywords(c)]
    assert not missing, (
        f"can_allocate call sites missing decision_lane kwarg at lines "
        f"{missing} — lane-banded orders fall back to the generic 80c ceiling"
    )


def test_canonical_range_check_is_lane_aware():
    """The canonical entry-price range validation must consult
    _lane_entry_band_cents so an 82-91c pinned_fav order is not rejected
    outside the generic [25,80] profile band."""
    with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
        src = f.read()
    tree = ast.parse(src)

    # The canonical-range rejection site produces
    # entry_price_outside_canonical_range — its enclosing block must reference
    # the lane-band accessor.
    lines = src.split("\n")
    hit_lines = [
        i for i, line in enumerate(lines) if "entry_price_outside_canonical_range" in line
    ]
    assert hit_lines, "canonical-range rejection not found in order_router.py"
    window = "\n".join(
        lines[max(0, hit_lines[0] - 60): hit_lines[0] + 10]
    )
    assert "_lane_entry_band_cents" in window, (
        "canonical entry-range check does not resolve the lane band — "
        "lane orders above the generic ceiling are rejected before routing"
    )
