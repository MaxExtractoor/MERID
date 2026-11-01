"""Intent->revalidation bound contract across bounded lanes.

2026-11-01 defect (ETH cheap_no_settle cid-0a08bfe910c6, 33c limit vs
max_price=31): two stacked inconsistencies between selection and submit
revalidation —

1. The lane floor (-10c) the admission actually cleared never reached the
   intent; the formula bound (+3.18c) was stamped instead.
2. Revalidation charged the *taker* parabolic fee (1.548c @33c) on a
   post_only maker order (0.387c), shrinking max_price a further ~1.2c.

These tests pin the shared contract surface — ``input_from_intent`` —
for every bounded lane through one parameterized path (no per-lane
special cases), and the missing-provenance contract error.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi.parabolic_fees import (
    kalshi_fee_cents_exact,
)
from merid.execution.submit_revalidation import input_from_intent


def _intent(**kw):
    """Duck-typed OrderIntent carrying the contract fields."""
    base = dict(
        intent_id="intent_test",
        ticker="KXETH15M-T",
        side="no",
        action="BUY",
        price_cents=33,
        count=6,
        count_fp=None,
        p_selected=Decimal("0.366685"),
        p_yes=Decimal("0.633315"),
        p_no=Decimal("0.366685"),
        model_prob=None,
        snapshot_ts=None,
        decision_ts=None,
        post_only=True,
        liquidity_role="maker",
        execution_mode="maker",
        min_required_edge=None,
        edge_bound_source=None,
        self_trade_prevention_type=None,
        entry_model=None,
        market_status="open",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _mk_rin(**kw):
    rin = input_from_intent(_intent(**kw))
    assert rin is not None, "input_from_intent must not reject a "
    "complete intent"
    return rin


# -- fee role ----------------------------------------------------------------

def test_maker_intent_charges_maker_fee():
    """post_only/maker intent -> maker parabolic fee, not 4x taker."""
    rin = _mk_rin(min_required_edge=Decimal("-0.10"))
    expected = kalshi_fee_cents_exact(Decimal("0.33"), Decimal(1), "maker")
    taker = kalshi_fee_cents_exact(Decimal("0.33"), Decimal(1), "taker")
    assert rin.fee_per_contract_cents == expected
    assert rin.fee_per_contract_cents < taker  # maker = 25% of taker


def test_taker_intent_charges_taker_fee():
    """Crossing intent still pays the taker schedule."""
    rin = _mk_rin(post_only=False, liquidity_role="taker",
                  execution_mode="taker",
                  min_required_edge=Decimal("0.015"))
    assert rin.fee_per_contract_cents == kalshi_fee_cents_exact(
        Decimal("0.33"), Decimal(1), "taker")


# -- lane bound propagation (parameterized, shared path) ---------------------

@pytest.mark.parametrize("lane,floor_cents", [
    ("cheap_no_settle", "-10.0"),
    ("pinned_fav", "-12.0"),
    ("drift_fav", "-8.0"),
    ("settlement_convergence", "-5.0"),
    ("window_quota", "-25.0"),
])
def test_lane_floor_bound_survives_unclamped(lane, floor_cents):
    """Any bounded lane's negative floor must reach the revalidation
    bound — the same code path, no lane-name exceptions."""
    rin = _mk_rin(
        edge_bound_source=f"lane_floor:{lane}",
        min_required_edge=Decimal(floor_cents) / Decimal("100"),
    )
    assert rin.required_edge_per_contract_cents == Decimal(floor_cents)


def test_eth_episode_replay_passes_under_consistent_contract():
    """Replay cid-0a08bfe910c6's own evidence through the fixed contract:
    p_no=36.6685c, limit=33, lane floor -10c, maker fee -> max_price
    int(36.6685 - 0.387 - 0 - (-10)) = 46 >= 33, so the bound comparison
    the admission enforced is the one revalidation enforces."""
    rin = _mk_rin(
        edge_bound_source="lane_floor:cheap_no_settle",
        min_required_edge=Decimal("-0.10"),
    )
    p_held = rin.p_held_cents
    max_price = int(p_held - rin.fee_per_contract_cents
                    - rin.reserves_per_contract_cents
                    - rin.required_edge_per_contract_cents)
    assert max_price >= 33
    # And under the OLD defect pair (formula bound + taker fee) it would
    # have produced the observed 31 — documenting what actually fired.
    old_fee = kalshi_fee_cents_exact(Decimal("0.33"), Decimal(1), "taker")
    old_max = int(p_held - old_fee - Decimal("0") - Decimal("3.1844"))
    assert old_max == 31


def test_bounded_lane_missing_bound_fails_closed():
    """A lane-floor-stamped intent that lost its bound is a contract
    error — fail closed, never silently substitute the generic default."""
    rin = input_from_intent(_intent(
        edge_bound_source="lane_floor:cheap_no_settle",
        min_required_edge=None,
    ))
    assert rin is None


def test_unstamped_bound_uses_env_default():
    """Non-lane intents without a stamped bound keep the env default —
    unchanged legacy behavior."""
    rin = _mk_rin(edge_bound_source=None, min_required_edge=None)
    assert rin.required_edge_per_contract_cents == Decimal("1.5")


def test_route_bound_source_missing_edge_still_defaults():
    """route_bound (non-lane admission) is not a bounded-lane contract —
    missing stamp falls through to the env default as before."""
    rin = _mk_rin(edge_bound_source="route_bound",
                  min_required_edge=None)
    assert rin.required_edge_per_contract_cents == Decimal("1.5")


def test_fraction_and_cents_representations_equivalent():
    """The stamped bound accepts fraction or cents representation."""
    a = _mk_rin(min_required_edge=Decimal("-0.10"),
                edge_bound_source="lane_floor:x")
    b = _mk_rin(min_required_edge=Decimal("-10"),
                edge_bound_source="lane_floor:x")
    assert a.required_edge_per_contract_cents == \
        b.required_edge_per_contract_cents == Decimal("-10")
