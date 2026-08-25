"""
Allocator decision instrumentation and exit evaluation instrumentation tests.

These tests are intentionally independent of production market data and network
state.  They verify that:

- Every candidate submitted to ``GlobalAllocator.allocate`` receives one
  ``AllocationDecision`` with a concrete terminal reason and stage.
- Per-asset decision counters can be built from ``get_allocation_decisions``.
- ``ExitPolicyResolver.evaluate`` returns one ``ExitEvaluation`` containing all
  five required triggers, with ``triggered=None`` for ineligible triggers and a
  chosen reason derived only from eligible+triggered triggers.

No selection thresholds, edge thresholds, or exit priorities are changed in this
slice; the tests only make the decisions measurable.
"""

from decimal import Decimal
from typing import Any, Dict

import pytest

from merid.position_management.exit_policy_resolver import ExitPolicyResolver
from merid.position_management.position import Position, PositionSide, RiskParamsState, TrailingType
from merid.risk.profiles.global_allocator import (
    GlobalAllocator,
    OrderCandidate,
    REASON_ASSET_CAP,
    REASON_BUDGET_LIMIT,
    REASON_EXPECTED_VALUE_BELOW_MINIMUM,
    REASON_KNAPSACK_CAP,
    REASON_POSITION_CAP,
    REASON_PRICE_OUT_OF_RANGE,
    REASON_QUANTITY_ROUNDED_TO_ZERO,
)

ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")


def _order_candidate(
    asset: str,
    *,
    price: int = 50,
    edge: float = 3.0,
    count: int = 1,
    confidence: float = 0.55,
    candidate_id: str = "",
) -> OrderCandidate:
    if not candidate_id:
        candidate_id = f"cid-{asset}"
    return OrderCandidate(
        asset=asset,
        ticker=f"KX{asset}15M-TEST",
        side="yes",
        action="buy",
        price_cents=price,
        count=count,
        edge_pct=edge,
        confidence=confidence,
        model_prob=0.5,
        agent_name=f"{asset}_15M",
        candidate_id=candidate_id,
    )


def _default_allocator() -> GlobalAllocator:
    return GlobalAllocator(
        venue_cap_usd=1.00,
        min_edge_pct=0.025,
        min_confidence=0.50,
        min_price_cents=10,
        max_price_cents=75,
    )


def _build_asset_counters(allocator: GlobalAllocator, cycle_id: Any) -> Dict[str, Dict[str, Any]]:
    """Mirror the per-asset counter aggregation that agent_grid performs."""
    decisions = allocator.get_allocation_decisions(cycle_id)
    counters: Dict[str, Dict[str, Any]] = {}
    for d in decisions:
        if d.asset not in counters:
            counters[d.asset] = {
                "asset": d.asset,
                "candidates_generated": 0,
                "allocator_evaluated": 0,
                "selected": 0,
                "allocator_rejected": 0,
                "total_rejections": 0,
                "terminal": 0,
                "signal_rejected": 0,
                "router_rejected": 0,
                "execution_failed": 0,
                "constraint_reasons": {},
            }
        ctr = counters[d.asset]
        ctr["candidates_generated"] += 1
        ctr["allocator_evaluated"] += 1
        if d.selected:
            ctr["selected"] += 1
        else:
            ctr["allocator_rejected"] += 1
            ctr["total_rejections"] += 1
            if d.terminal_reason:
                ctr["terminal"] += 1
            concrete = d.constraint_reasons[0] if d.constraint_reasons else d.terminal_reason
            if concrete:
                ctr["constraint_reasons"][concrete] = ctr["constraint_reasons"].get(concrete, 0) + 1
    return counters


@pytest.mark.parametrize("asset", ASSETS)
def test_allocator_decision_contains_concrete_constraint(asset):
    """A candidate that is not selected by the knapsack carries a concrete reason."""
    allocator = _default_allocator()
    # Create five candidates at 30c.  Total 150c > $1 cap, so the knapsack must
    # reject at least two.  Each non-selected candidate must have a concrete
    # terminal reason (BUDGET_LIMIT or KNAPSACK_CAP), not the opaque
    # ``allocator_loss`` label.
    candidates = [
        _order_candidate(a, price=30, edge=3.0 + i * 0.1) for i, a in enumerate(ASSETS)
    ]
    chosen = allocator.allocate(candidates, cycle_id=1)
    decisions = {d.candidate_id: d for d in allocator.get_allocation_decisions(1)}

    assert len(chosen) <= 3
    assert len(decisions) == len(ASSETS)

    d = decisions[f"cid-{asset}"]
    assert d.asset == asset
    if d.selected:
        assert d.terminal_reason is None
        assert d.rejection_stage is None
        assert d.approved_quantity_fp == 1.0
        assert d.stage_results.get("KNAPSACK") == "SELECTED"
    else:
        assert d.terminal_reason is not None
        assert d.constraint_reasons
        concrete = d.constraint_reasons[0]
        assert concrete in {REASON_BUDGET_LIMIT, REASON_KNAPSACK_CAP, REASON_ASSET_CAP}
        assert d.rejection_stage in ("ASSET_CAP", "BUDGET", "KNAPSACK")

    # Counter accounting: terminal == selected + allocator_rejected for the asset
    # (signal/router/execution are zero in this isolated allocator test).
    counters = _build_asset_counters(allocator, 1)
    ctr = counters[asset]
    assert ctr["candidates_generated"] == 1
    assert ctr["allocator_evaluated"] == 1
    assert ctr["selected"] == (1 if d.selected else 0)
    assert ctr["allocator_rejected"] == (0 if d.selected else 1)
    assert ctr["terminal"] == (0 if d.selected else 1)
    if not d.selected:
        assert ctr["constraint_reasons"] == {concrete: 1}


@pytest.mark.parametrize("asset", ASSETS)
def test_allocator_decision_rejected_by_price(asset):
    """A candidate outside the configured price range records PRICE_OUT_OF_RANGE."""
    allocator = _default_allocator()
    c = _order_candidate(asset, price=5, edge=5.0)  # below 10c min
    chosen = allocator.allocate([c], cycle_id=2)
    assert not chosen
    decisions = allocator.get_allocation_decisions(2)
    assert len(decisions) == 1
    d = decisions[0]
    assert d.rejection_stage == "PRICE"
    assert d.terminal_reason == REASON_PRICE_OUT_OF_RANGE
    assert d.constraint_reasons == [REASON_PRICE_OUT_OF_RANGE]


@pytest.mark.parametrize("asset", ASSETS)
def test_allocator_decision_rejected_by_edge(asset):
    """A candidate below the per-asset edge threshold records EXPECTED_VALUE_BELOW_MINIMUM."""
    allocator = _default_allocator()
    c = _order_candidate(asset, price=50, edge=1.0)  # 1% < 2.5% min
    chosen = allocator.allocate([c], cycle_id=3)
    assert not chosen
    d = allocator.get_allocation_decisions(3)[0]
    assert d.rejection_stage == "EDGE"
    assert d.terminal_reason == REASON_EXPECTED_VALUE_BELOW_MINIMUM


@pytest.mark.parametrize("asset", ASSETS)
def test_allocator_decision_rejected_by_count(asset):
    """A candidate with an invalid count records a concrete count-stage reason."""
    allocator = _default_allocator()
    c = _order_candidate(asset, price=50, edge=5.0, count=0)
    chosen = allocator.allocate([c], cycle_id=4)
    assert not chosen
    d = allocator.get_allocation_decisions(4)[0]
    assert d.rejection_stage == "COUNT"
    assert REASON_QUANTITY_ROUNDED_TO_ZERO in d.constraint_reasons


@pytest.mark.parametrize("asset", ASSETS)
def test_allocator_decision_selected_and_approved_quantity(asset):
    """A selected candidate records approved_quantity_fp and no terminal reason."""
    allocator = _default_allocator()
    c = _order_candidate(asset, price=50, edge=5.0, count=2)
    chosen = allocator.allocate([c], cycle_id=5)
    assert len(chosen) == 1
    d = allocator.get_allocation_decisions(5)[0]
    assert d.selected is True
    assert d.approved_quantity_fp == 2.0
    assert d.terminal_reason is None
    assert all(d.stage_results.get(s) == "PASS" for s in ("EDGE", "CONFIDENCE", "PRICE", "COUNT", "EXISTING_POSITION", "PENDING_ORDER", "POSITION_CAP", "ASSET_CAP", "BUDGET"))
    assert d.stage_results.get("KNAPSACK") == "SELECTED"


@pytest.mark.parametrize("asset", ASSETS)
def test_exit_eval_contains_all_trigger_results(asset):
    """``ExitPolicyResolver.evaluate`` returns all five triggers and a chosen reason."""
    position = Position(
        market_id=f"KX{asset}15M-TEST",
        side=PositionSide.YES,
        size=Decimal("1"),
        avg_entry_price_cents=50,
        take_profit_price_cents=75,
        trailing_type=TrailingType.FIXED_CENTS,
        high_watermark_cents=0,
        low_watermark_cents=0,
        risk_params_state=RiskParamsState.ORIGINAL_PERSISTED,
        risk_params_schema_version=2,
        client_order_id="test-client-order-id",
        entry_book_capture_quality="AT_FILL",
        entry_signal_id="test-signal",
        entry_model_probability=0.65,
        entry_market_probability=0.60,
        entry_edge=0.05,
        fill_source="ws",
        entry_edge_pct=0.05,
    )
    position.update_runtime_state(current_price_cents=60)

    resolver = ExitPolicyResolver()
    market_context = {
        "current_price_cents": 60,
        "time_to_expiry_seconds": 600.0,
        "current_edge_pct": 0.15,  # positive, above 20% of 5% = 0.01 threshold
        "book_snapshot_id": "snap-1",
    }
    evaluation = resolver.evaluate(position, market_context)

    assert evaluation.position_key == position.market_id
    assert evaluation.position_version == position.position_version
    assert evaluation.evaluation_id.startswith("exit_eval_")
    assert evaluation.book_snapshot_id == "snap-1"

    required_triggers = {"TAKE_PROFIT", "EDGE_DECAY", "CURRENT_EDGE_REVERSAL", "R_MULTIPLE", "TRAILING_STOP"}
    assert set(evaluation.triggers.keys()) == required_triggers

    # TAKE_PROFIT: configured and eligible but not hit (60 < 75)
    tp = evaluation.triggers["TAKE_PROFIT"]
    assert tp.configured is True
    assert tp.eligible is True
    assert tp.triggered is False

    # EDGE_DECAY: eligible (provenance resolved) and not triggered (0.15 >= 0.01)
    ed = evaluation.triggers["EDGE_DECAY"]
    assert ed.configured is True
    assert ed.eligible is True
    assert ed.triggered is False

    # CURRENT_EDGE_REVERSAL: ineligible because provenance is resolved; triggered=None
    cer = evaluation.triggers["CURRENT_EDGE_REVERSAL"]
    assert cer.configured is True
    assert cer.eligible is False
    assert cer.triggered is None
    assert cer.ineligible_reason is not None

    # R_MULTIPLE: configured and eligible but not triggered (R = 0.2 < 0.5)
    rm = evaluation.triggers["R_MULTIPLE"]
    assert rm.configured is True
    assert rm.eligible is True
    assert rm.triggered is False

    # TRAILING_STOP: configured and eligible but not triggered
    ts = evaluation.triggers["TRAILING_STOP"]
    assert ts.configured is True
    assert ts.eligible is True
    assert ts.triggered is False

    # No trigger fired, so chosen reason must be None.
    assert evaluation.chosen_exit_reason is None
    assert evaluation.chosen_exit_price_cents is None


@pytest.mark.parametrize("asset", ASSETS)
def test_exit_eval_current_edge_reversal_requires_negative_edge(asset):
    """Unresolved edge-decay provenance does NOT automatically become CURRENT_EDGE_REVERSAL."""
    position = Position(
        market_id=f"KX{asset}15M-TEST",
        side=PositionSide.YES,
        size=Decimal("1"),
        avg_entry_price_cents=50,
        risk_params_state=RiskParamsState.UNKNOWN,
        risk_params_schema_version=1,
        client_order_id=None,
        entry_book_capture_quality="UNKNOWN",
        fill_source="manual",
        entry_edge_pct=0.05,
    )
    position.update_runtime_state(current_price_cents=60)

    resolver = ExitPolicyResolver()
    # Provenance unresolved and current edge is small positive (below any threshold
    # but not actually reversed).  This must NOT trigger CURRENT_EDGE_REVERSAL.
    market_context = {
        "current_price_cents": 60,
        "time_to_expiry_seconds": 600.0,
        "current_edge_pct": 0.005,  # positive, just below threshold, not negative
    }
    evaluation = resolver.evaluate(position, market_context)

    cer = evaluation.triggers["CURRENT_EDGE_REVERSAL"]
    assert cer.eligible is True  # unresolved provenance, edge present
    assert cer.triggered is False  # edge is not negative
    assert evaluation.chosen_exit_reason is None

    # Only when the model edge flips to negative does CURRENT_EDGE_REVERSAL fire.
    market_context["current_edge_pct"] = -0.02
    evaluation = resolver.evaluate(position, market_context)
    cer = evaluation.triggers["CURRENT_EDGE_REVERSAL"]
    assert cer.eligible is True
    assert cer.triggered is True
    assert evaluation.chosen_exit_reason == "CURRENT_EDGE_REVERSAL"
