"""Smoke test: HARD_STOP shadow gate + min-proceeds floor helpers."""
import asyncio
import os
import sys

sys.path.insert(0, r"C:\Dev\MERID")
os.environ["MERID_ENABLE_STOP_CANDIDATE_SUBMISSION"] = "true"
os.environ["MERID_PRICE_STOP_SHADOW"] = "1"

from merid.event_venues.kalshi.stop_candidate import (
    StopCandidate,
    maybe_submit_stop_candidate,
    price_stop_shadow_enabled,
    SHADOWED_PRICE_STOP_TRIGGERS,
)

async def main():
    assert price_stop_shadow_enabled() is True
    cand = StopCandidate(
        market_ticker="KXXRP15M-26OCT171530-30",
        trigger_reason="HARD_STOP",
        position_from_exchange_cc=-300,
        executable_exit_cents=13,
        entry_price_cents=32,
        fair_value_cents=80,
        seconds_to_expiry=400.0,
    )
    res = await maybe_submit_stop_candidate(cand)
    print("HARD_STOP result:", getattr(res, "status", None), "|", getattr(res, "reason", None))
    assert getattr(res, "reason", "") == "price_stop_shadowed:HARD_STOP", res

    # force=True must NOT bypass the shadow: a generic boolean cannot turn a
    # disabled strategy policy into a live submission.  Emergencies use a
    # distinct trigger class, not a flag.
    res2 = await maybe_submit_stop_candidate(cand, force=True)
    r2 = getattr(res2, "reason", "") if res2 is not None else "task-none"
    print("forced result:", getattr(res2, "status", None), "|", r2)
    assert getattr(res2, "reason", "") == "price_stop_shadowed:HARD_STOP", r2

    # Emergency triggers unaffected by shadow â€” should pass the shadow check
    # and fail later (position fetch unavailable offline).
    cap = StopCandidate(
        market_ticker="KXXRP15M-26OCT171530-30",
        trigger_reason="LOSS_CAP",
        position_from_exchange_cc=-300,
        executable_exit_cents=13,
        entry_price_cents=32,
        seconds_to_expiry=400.0,
    )
    res3 = await maybe_submit_stop_candidate(cap)
    r3 = getattr(res3, "reason", "") if res3 is not None else "none"
    print("LOSS_CAP result:", getattr(res3, "status", None), "|", r3)
    assert "price_stop_shadowed" not in str(r3), r3

    # Firewall helpers
    from merid.event_venues.kalshi.execution_risk_firewall import ExecutionRiskFirewall
    fw = ExecutionRiskFirewall.get_instance()

    class _I:  # minimal original_intent stub
        is_manual_emergency_close = False
        exit_reason = "exit_tp"
        reason = "take_profit"
    class _C:
        reason = "take_profit"

    assert fw._is_min_proceeds_exempt(_I(), _C()) is False
    _I.exit_reason = "expiry_liquidation"
    assert fw._is_min_proceeds_exempt(_I(), _C()) is True
    _I.exit_reason = "hard_stop"
    assert fw._is_min_proceeds_exempt(_I(), _C()) is True
    _I.exit_reason = "trailing_stop"
    assert fw._is_min_proceeds_exempt(_I(), _C()) is False
    # Look-alike reason containing "risk" as a substring must NOT exempt.
    _I.exit_reason = "counterparty_risk_review"
    assert fw._is_min_proceeds_exempt(_I(), _C()) is False
    _I.is_manual_emergency_close = True
    assert fw._is_min_proceeds_exempt(_I(), _C()) is True

    # Fee-adjusted floor: 32c entry -> 32 + 1.53 + ~1.53 (fee at 33c-ish) ~ 35
    fl = fw._fee_adjusted_floor_cents(32, 33)
    print("fee-adjusted floor for 32c entry @33c limit:", fl)
    assert fl in (35, 36), fl
    fl2 = fw._fee_adjusted_floor_cents(32, 90)
    print("floor @90c limit:", fl2)
    assert fl2 in (35, 36), fl2

    print("ALL CHECKS PASSED")

asyncio.run(main())

