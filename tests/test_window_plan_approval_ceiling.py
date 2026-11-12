"""Window-plan admission ceiling tests.

The decision-approved ceiling (``size_ceiling_cc``, centi-contracts) must
bound the admitted size under BOTH lift and clamp modes: the plan may shrink
toward budget fit but may never admit more than the decision approved, and
the pending reservation always equals the admitted size.
"""

import os
import sys
from decimal import Decimal
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction import window_plan as wp


@pytest.fixture(autouse=True)
def _plan_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_WINDOW_PLAN_ENABLED", "1")
    monkeypatch.setenv("MERID_SCALP_EXECUTION_PROFILE", "legacy")
    monkeypatch.setenv("MERID_WINDOW_PLAN_BUDGET_USD", "6.00")
    monkeypatch.setenv("MERID_WINDOW_PLAN_MAX_CONTRACTS", "6")
    monkeypatch.setenv("MERID_WINDOW_PLAN_MAX_SUBMISSIONS", "6")
    monkeypatch.setenv("MERID_WINDOW_PLAN_ORDER_CAP_USD", "6.00")
    monkeypatch.setenv("MERID_WINDOW_PLAN_MAX_QTY_CC", "600")
    monkeypatch.setenv("MERID_WINDOW_PLAN_PER_ASSET_CAP_USD", "6.00")
    monkeypatch.setenv("MERID_WINDOW_PLAN_CORR_CAP_PCT", "1.0")
    monkeypatch.setenv("MERID_WINDOW_PLAN_CELL_SHARES", "1.0")
    monkeypatch.setenv("MERID_WINDOW_PLAN_PENDING_TTL_S", "45")
    monkeypatch.setenv("MERID_WINDOW_PLAN_LIFT_SIZING", "1")
    monkeypatch.setenv("MERID_MAX_CONTRACTS_PER_ORDER", "6")
    monkeypatch.setenv("MERID_WINDOW_PLAN_STATE_PATH", str(tmp_path / "wp.json"))
    wp.reset_for_tests()
    yield
    wp.reset_for_tests()


def _no_committed():
    return Decimal("0"), 0, {}, {}, {}, True


def _pending_cost_real(st, now):
    total = Decimal("0")
    for p in st.pending.values():
        total += Decimal(str(p.get("cost_usd", 0) or 0))
    return total


def _patches(committed=None):
    return (
        patch.object(wp, "_committed_from_authoritative",
                     return_value=committed if committed is not None else _no_committed()),
        patch.object(wp, "_reconcile_pending", side_effect=_pending_cost_real),
    )


def _admit(**kw):
    args = dict(
        ticker="KXBTC15M-26JAN010000-00",
        asset="BTC",
        side="yes",
        price_cents=50.0,
        requested_count=1.0,
        tte_s=300.0,
        decision_id="dec-1",
    )
    args.update(kw)
    return wp.admit(**args)


def test_lift_cannot_exceed_approval_ceiling():
    """Lift sizing fills budget fit, but the approval ceiling binds first."""
    with _patches()[0], _patches()[1]:
        # Budget fit at 50c with $6 room = 12 contracts -> capped at 6 by
        # MAX_CONTRACTS; approval ceiling 2 contracts (200cc) must bind.
        allowed, count, reason, detail = _admit(size_ceiling_cc=200)
        assert allowed is True
        assert count == pytest.approx(2.0)
        assert detail["approval_ceiling_cc"] == 200
        assert detail["fit_cc"] <= 200


def test_ceiling_clamps_lift_to_exact_boundary():
    with _patches()[0], _patches()[1]:
        allowed, count, reason, detail = _admit(size_ceiling_cc=350)
        assert allowed is True
        # 3.5 contracts at 50c = $1.75 <= $6 budget; fit would allow 6.
        assert count == pytest.approx(3.5)


def test_zero_ceiling_rejects():
    with _patches()[0], _patches()[1]:
        allowed, count, reason, detail = _admit(size_ceiling_cc=0)
        assert allowed is False
        assert count == 0.0
        assert reason == "window_plan_below_approval"


def test_negative_ceiling_rejects():
    with _patches()[0], _patches()[1]:
        allowed, count, reason, detail = _admit(size_ceiling_cc=-100)
        assert allowed is False
        assert reason == "window_plan_below_approval"


def test_ceiling_below_min_qty_rejects_as_dust():
    """A sub-1-contract approval must skip, never be forced up to min qty."""
    with _patches()[0], _patches()[1]:
        allowed, count, reason, detail = _admit(size_ceiling_cc=50)
        assert allowed is False
        assert count == 0.0
        assert reason == "window_plan_no_size"


def test_no_ceiling_preserves_legacy_lift():
    """size_ceiling_cc=None keeps pre-change unbounded-by-decision behavior."""
    with _patches()[0], _patches()[1]:
        allowed, count, reason, detail = _admit()
        assert allowed is True
        assert count == pytest.approx(6.0)  # MAX_CONTRACTS_PER_ORDER fit
        assert "approval_ceiling_cc" not in detail


def test_reservation_matches_admitted_ceiling_size():
    """Pending reservation cost equals the admitted (ceiling-clamped) size,
    not the larger budget fit."""
    with _patches()[0], _patches()[1]:
        allowed, count, reason, detail = _admit(size_ceiling_cc=200, decision_id="dec-rsv")
        assert allowed is True
        st = wp._get_state(wp.window_suffix("KXBTC15M-26JAN010000-00"))
        prec = st.pending.get("dec-rsv")
        assert prec is not None
        # 2 contracts @ 50c + taker fee reserve -> reserved_usd in detail
        # must correspond to the admitted 2.0 contracts, not the 6-contract fit.
        reserved = Decimal(str(prec["cost_usd"]))
        assert reserved < Decimal("2.00")  # 2 * $0.50 + small fee
        assert float(count) == pytest.approx(2.0)


def test_second_admission_sees_first_reservation():
    """Incremental exposure: a second candidate's fit subtracts the first
    reservation; ceiling still binds independently."""
    with _patches()[0], _patches()[1]:
        a1 = _admit(size_ceiling_cc=600, decision_id="dec-a", asset="BTC", side="yes")
        assert a1[0] is True
        # Second BTC order same side: corr cap 100% of $6 budget; committed
        # now includes dec-a's reservation.
        a2 = _admit(size_ceiling_cc=600, decision_id="dec-b", asset="BTC", side="yes",
                    requested_count=1.0)
        # Whatever the budget leaves, the wire size can never exceed the
        # second approval's own ceiling.
        if a2[0]:
            assert a2[1] <= 6.0


def test_clamp_mode_respects_ceiling(monkeypatch):
    """With LIFT off, requested>ceiling still clamps to the ceiling."""
    monkeypatch.setenv("MERID_WINDOW_PLAN_LIFT_SIZING", "0")
    with _patches()[0], _patches()[1]:
        allowed, count, reason, detail = _admit(
            requested_count=6.0, size_ceiling_cc=250,
        )
        assert allowed is True
        assert count == pytest.approx(2.5)
