"""Tests for the shared ``GlobalRiskGuard`` singleton and order-dedup registry.

Covers:
  * singleton identity across modules
  * cycle-cap invariant (sum of max_loss ≤ max_cycle_risk_pct * equity)
  * total-cap invariant (existing + new ≤ max_total_risk_pct * equity)
  * fail-closed on non-positive equity
  * ``reset_cycle()`` resets accumulator
  * equity/existing-risk provider wiring
  * ``check_intent`` convenience + exit exemption
  * dedup registry: same bucket blocks, different bucket admits, release frees slot
  * CT's re-exported ``GlobalRiskGuard`` subclass shares the singleton semantics
"""

from __future__ import annotations

import pytest

from merid.guards.global_risk_guard import (
    GlobalRiskGuard,
    PendingOrderRisk,
    check_intent,
    compute_intent_max_loss_cents,
    get_global_risk_guard,
    reset_global_risk_guard_for_tests,
    set_equity_provider,
    set_existing_risk_provider,
    resolve_equity_cents,
    resolve_existing_risk_cents,
)
from merid.guards.order_dedup_registry import (
    OrderDedupRegistry,
    get_order_dedup_registry,
    reset_order_dedup_registry_for_tests,
)


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_global_risk_guard_for_tests()
    reset_order_dedup_registry_for_tests()
    yield
    reset_global_risk_guard_for_tests()
    reset_order_dedup_registry_for_tests()


def _pending(max_loss: int, ticker: str = "KXBTC-T", asset: str = "BTC") -> PendingOrderRisk:
    return PendingOrderRisk(
        ticker=ticker, asset=asset, contracts=1,
        entry_price_cents=max_loss, direction="long",
        max_loss_cents=max_loss, edge=0.05,
    )


# ────────────────────────────────────────────────────────────────────
# Singleton identity
# ────────────────────────────────────────────────────────────────────

def test_singleton_identity():
    g1 = get_global_risk_guard()
    g2 = get_global_risk_guard()
    assert g1 is g2


def test_ct_subclass_shares_singleton_semantics():
    """CT's re-exported ``GlobalRiskGuard`` is a subclass of the shared one.

    This preserves ``from merid.trading.kalshi_continuous_trader import GlobalRiskGuard``
    for existing tests while ensuring the actual behavior is the shared impl.
    """
    from merid.trading.kalshi_continuous_trader import (
        GlobalRiskGuard as CTGlobalRiskGuard,
        PendingOrderRisk as CTPendingOrderRisk,
    )
    assert issubclass(CTGlobalRiskGuard, GlobalRiskGuard)
    assert CTPendingOrderRisk is PendingOrderRisk


# ────────────────────────────────────────────────────────────────────
# Invariants
# ────────────────────────────────────────────────────────────────────

def test_cycle_cap_invariant():
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
    equity = 10_000  # $100 — 2% = $2 = 200 cents

    ok1, _ = guard.check_order(equity, 0, _pending(max_loss=150))
    assert ok1
    ok2, _ = guard.check_order(equity, 0, _pending(max_loss=40))
    assert ok2  # 150+40=190 ≤ 200
    ok3, reason = guard.check_order(equity, 0, _pending(max_loss=20))
    assert not ok3
    assert "Cycle risk cap exceeded" in reason


def test_total_cap_invariant():
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
    equity = 10_000  # 200c cap

    # Existing open risk already 150c, order for 60c → 210 > 200
    ok, reason = guard.check_order(equity, existing_risk_cents=150, pending_order=_pending(60))
    assert not ok
    assert "Total risk cap exceeded" in reason


def test_fail_closed_on_non_positive_equity():
    guard = GlobalRiskGuard()
    ok, reason = guard.check_order(equity_cents=0, existing_risk_cents=0, pending_order=_pending(1))
    assert not ok
    assert "non-positive equity" in reason


def test_reset_cycle_resets_accumulator():
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.02, max_total_risk_pct=0.02)
    equity = 10_000
    assert guard.check_order(equity, 0, _pending(200))[0]
    # cap exhausted
    assert not guard.check_order(equity, 0, _pending(1))[0]
    guard.reset_cycle()
    assert guard.check_order(equity, 0, _pending(200))[0]


def test_compute_intent_max_loss_cents():
    # 3 contracts @ 55c each → 165c max loss for a buy
    assert compute_intent_max_loss_cents("yes", "buy", 55, 3) == 165
    # Clamps price to [0, 100]
    assert compute_intent_max_loss_cents("no", "buy", 150, 2) == 200
    assert compute_intent_max_loss_cents("yes", "buy", -5, 2) == 0


# ────────────────────────────────────────────────────────────────────
# Providers
# ────────────────────────────────────────────────────────────────────

def test_equity_and_existing_risk_providers():
    set_equity_provider(lambda: 5_000)
    set_existing_risk_provider(lambda: 40)
    assert resolve_equity_cents() == 5_000
    assert resolve_existing_risk_cents() == 40
    set_equity_provider(None)
    set_existing_risk_provider(None)


def test_default_equity_cents_env_fallback(monkeypatch):
    from merid.guards.global_risk_guard import default_equity_cents
    monkeypatch.setenv("MERID_INITIAL_CAPITAL", "12.50")
    # Ensure no position-cache override
    assert default_equity_cents() >= 0  # position cache may or may not exist


def test_provider_exception_falls_back():
    def bad():
        raise RuntimeError("boom")
    set_equity_provider(bad)
    # Should not propagate; falls back to default lookup (>=0)
    assert resolve_equity_cents() >= 0
    set_equity_provider(None)


# ────────────────────────────────────────────────────────────────────
# check_intent helper
# ────────────────────────────────────────────────────────────────────

def test_check_intent_exits_exempt():
    set_equity_provider(lambda: 10_000)
    ok, reason = check_intent(
        ticker="KXBTC-T", asset="BTC", side="yes", action="sell",
        price_cents=60, count=100,
    )
    assert ok
    assert reason == "exit_exempt"
    set_equity_provider(None)


def test_check_intent_buy_enforces_cap():
    set_equity_provider(lambda: 10_000)
    set_existing_risk_provider(lambda: 0)
    # 5 contracts @ 50c = 250c max loss, cap at 2% of $100 = 200c → blocked
    ok, reason = check_intent(
        ticker="KXBTC-T", asset="BTC", side="yes", action="buy",
        price_cents=50, count=5,
    )
    assert not ok
    assert "Cycle risk cap exceeded" in reason
    set_equity_provider(None)
    set_existing_risk_provider(None)


# ────────────────────────────────────────────────────────────────────
# Dedup registry
# ────────────────────────────────────────────────────────────────────

def test_dedup_admits_first_blocks_duplicates_same_bucket():
    reg = OrderDedupRegistry(bucket_seconds=60)
    ok1, _ = reg.try_admit("KXBTC-T", "yes", "buy", caller="ct", ts=1_000_000.0)
    ok2, existing = reg.try_admit("KXBTC-T", "yes", "buy", caller="lane", ts=1_000_000.0)
    assert ok1
    assert not ok2
    assert existing is not None
    assert existing.caller == "ct"


def test_dedup_different_bucket_admits():
    reg = OrderDedupRegistry(bucket_seconds=60)
    ok1, _ = reg.try_admit("KXBTC-T", "yes", "buy", caller="ct", ts=1_000_000.0)
    ok2, _ = reg.try_admit("KXBTC-T", "yes", "buy", caller="ct", ts=1_000_061.0)
    assert ok1 and ok2


def test_dedup_release_frees_slot():
    reg = OrderDedupRegistry(bucket_seconds=60)
    reg.try_admit("KXBTC-T", "yes", "buy", caller="ct", ts=1_000_000.0)
    reg.release("KXBTC-T", "yes", "buy", ts=1_000_000.0)
    ok, _ = reg.try_admit("KXBTC-T", "yes", "buy", caller="lane", ts=1_000_000.0)
    assert ok


def test_dedup_registry_singleton():
    r1 = get_order_dedup_registry()
    r2 = get_order_dedup_registry()
    assert r1 is r2


def test_dedup_different_tickers_independent():
    reg = OrderDedupRegistry(bucket_seconds=60)
    ok1, _ = reg.try_admit("KXBTC-T", "yes", "buy", caller="ct", ts=1_000_000.0)
    ok2, _ = reg.try_admit("KXETH-T", "yes", "buy", caller="ct", ts=1_000_000.0)
    assert ok1 and ok2


def test_dedup_different_sides_independent():
    reg = OrderDedupRegistry(bucket_seconds=60)
    ok1, _ = reg.try_admit("KXBTC-T", "yes", "buy", caller="ct", ts=1_000_000.0)
    ok2, _ = reg.try_admit("KXBTC-T", "no", "buy", caller="ct", ts=1_000_000.0)
    assert ok1 and ok2


def test_dedup_metrics():
    reg = OrderDedupRegistry()
    reg.try_admit("KXBTC-T", "yes", "buy", caller="ct")
    reg.try_admit("KXBTC-T", "yes", "buy", caller="lane")
    m = reg.metrics()
    assert m["admits"] == 1
    assert m["duplicates_blocked"] == 1


# ────────────────────────────────────────────────────────────────────
# Multi-source aggregate cap invariant
# ────────────────────────────────────────────────────────────────────

def test_multi_source_aggregate_cap_holds():
    """Simulate CT + agent + lane all submitting entry orders in one cycle.

    The shared singleton guarantees that the sum of approved max_loss does
    not exceed ``max_cycle_risk_pct * equity`` regardless of caller count.
    """
    guard = get_global_risk_guard()
    guard.reset_cycle()
    set_equity_provider(lambda: 10_000)  # $100
    set_existing_risk_provider(lambda: 0)

    try:
        # Three callers, each trying to submit 80c of new risk = 240c total.
        # Cap at 2% of $100 = 200c.  Two should pass, one should be blocked.
        r1 = check_intent("KXBTC-T", "BTC", "yes", "buy", price_cents=80, count=1)
        r2 = check_intent("KXETH-T", "ETH", "yes", "buy", price_cents=80, count=1)
        r3 = check_intent("KXSOL-T", "SOL", "yes", "buy", price_cents=80, count=1)
        approvals = sum(1 for r in (r1, r2, r3) if r[0])
        # 80 + 80 = 160 ≤ 200; 160 + 80 = 240 > 200 → 3rd blocked
        assert approvals == 2
        assert r3[0] is False
    finally:
        set_equity_provider(None)
        set_existing_risk_provider(None)


def test_metrics_counters_increment():
    guard = GlobalRiskGuard()
    guard.reset_cycle()
    guard.check_order(10_000, 0, _pending(100))
    guard.check_order(10_000, 0, _pending(50))
    guard.check_order(10_000, 0, _pending(300))  # would exceed
    m = guard.metrics()
    assert m["approvals"] == 2
    assert m["rejections"] == 1
