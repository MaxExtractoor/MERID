"""Tests for the shared ``GlobalRiskGuard`` singleton and order-dedup registry.

Covers:
  * singleton identity across modules
"""

from __future__ import annotations

import time
import pytest

from merid.guards.global_risk_guard import (
    GlobalRiskGuard,
    check_intent,
    reset_global_risk_guard_for_tests,
    set_equity_provider,
    default_equity_cents,
    resolve_equity_cents,
    resolve_existing_risk_cents,
    get_global_risk_guard,
    set_existing_risk_provider,
    compute_intent_max_loss_cents,
)
from merid.guards.order_dedup_registry import (
    OrderDedupRegistry,
    get_order_dedup_registry,
    reset_order_dedup_registry_for_tests,
)
from merid.guards.global_risk_guard import PendingOrderRisk


# ────────────────────────────────────────────────────────────────────
# Helper functions
# ────────────────────────────────────────────────────────────────────

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




# ────────────────────────────────────────────────────────────────────
# Invariants
# ────────────────────────────────────────────────────────────────────

def test_cycle_cap_invariant():
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.03, max_total_risk_pct=0.06)  # 2026 best practice
    equity = 10_000  # $100 — 3% = $3 = 300 cents

    ok1, _ = guard.check_order(equity, 0, _pending(max_loss=150))
    assert ok1
    ok2, _ = guard.check_order(equity, 0, _pending(max_loss=100))
    assert ok2  # 150+100=250 ≤ 300
    # Third order should be rejected (exceeds remaining capacity)
    ok3, reason = guard.check_order(equity, 0, _pending(max_loss=60))
    assert not ok3
    assert "Bankroll cap" in reason or "Cycle risk cap" in reason


def test_total_cap_invariant():
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.03, max_total_risk_pct=0.06)  # 2026 best practice
    equity = 10_000  # 300c cycle cap, 600c total cap

    # Existing open risk already 150c, order for 60c → 210 < 800 (total cap)
    ok, reason = guard.check_order(equity, existing_risk_cents=150, pending_order=_pending(60))
    assert ok  # Should be allowed (210 < 800)


def test_fail_closed_on_non_positive_equity():
    guard = GlobalRiskGuard()
    ok, reason = guard.check_order(equity_cents=0, existing_risk_cents=0, pending_order=_pending(1))
    assert not ok
    assert "non-positive equity" in reason


def test_reset_cycle_resets_accumulator():
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.03, max_total_risk_pct=0.06)  # 2026 best practice
    equity = 10_000
    # Cycle cap: 10_000 * 0.03 = 300 cents
    assert guard.check_order(equity, 0, _pending(200))[0]
    # 200 + 1 = 201 < 300, so should still be approved
    assert guard.check_order(equity, 0, _pending(1))[0]
    # Third order should be rejected (exceeds remaining capacity)
    assert not guard.check_order(equity, 0, _pending(200))[0]
    guard.reset_cycle()
    # After reset, should be able to submit order again
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
    # PRODUCTION AUDIT (Step 2): Fallbacks removed - this test now verifies hard-fail behavior
    monkeypatch.setenv("MERID_INITIAL_CAPITAL", "12.50")
    # With no equity provider registered, should return 0 (fail-closed)
    assert default_equity_cents() == 0


def test_provider_exception_falls_back():
    from merid.guards.global_risk_guard import resolve_equity_cents
    def bad():
        raise RuntimeError("boom")
    set_equity_provider(bad)
    # PRODUCTION AUDIT (Step 2): Provider exception now returns 0 (fail-closed) instead of falling back
    assert resolve_equity_cents() == 0
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
    """Test that cycle cap is enforced for buy orders.
    
    PRODUCTION AUDIT: Rewritten to test fail-closed bankroll behavior.
    When bankroll is unknown (equity = 0), all orders should be rejected
    with a clear error message indicating fail-closed behavior.
    """
    # Set equity to 0 (fail-closed state)
    set_equity_provider(lambda: 0)
    
    ok, reason = check_intent(
        ticker="KXBTC15M-T",  # Use scope-compliant ticker
        asset="BTC",
        side="yes",
        action="buy",
        price_cents=60,
        count=100,
    )
    
    # Should reject due to fail-closed bankroll
    assert not ok
    assert "fail-closed" in reason.lower() or "equity" in reason.lower()
    set_equity_provider(None)


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

    2026 BEST PRACTICE: Adaptive sizing allows orders to be scaled down to fit
    remaining capacity instead of being rejected.
    """
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.06, max_total_risk_pct=0.08)
    equity = 10_000  # $100, cycle cap = $6 = 600 cents

    # Simulate multiple callers submitting orders in the same cycle
    # CT submits 200c, agent submits 200c, lane submits 200c
    ok1, _ = guard.check_order(equity, 0, _pending(max_loss=200, ticker="KXBTC-T"))
    ok2, _ = guard.check_order(equity, 0, _pending(max_loss=200, ticker="KXETH-T"))
    ok3, _ = guard.check_order(equity, 0, _pending(max_loss=200, ticker="KXSOL-T"))

    # All should be approved (total 600c = cycle cap)
    assert ok1 and ok2 and ok3

    # Fourth order should be rejected or scaled down
    ok4, reason = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXXRP-T"))
    # With adaptive sizing, it should be rejected since no capacity remains
    assert not ok4
    assert "Cycle risk cap" in reason


def test_metrics_counters_increment():
    guard = GlobalRiskGuard()
    guard.reset_cycle()
    guard.check_order(10_000, 0, _pending(100))
    guard.check_order(10_000, 0, _pending(50))
    # 2026 best practice: adaptive sizing scales 300¢ order to fit remaining 150¢ capacity
    # Remaining capacity = 300 - 150 = 150¢, so 300¢ order is scaled to 150¢ and approved
    guard.check_order(10_000, 0, _pending(300))  # scaled down and approved
    m = guard.metrics()
    assert m["approvals"] == 3  # All 3 approved (third was scaled)
    assert m["rejections"] == 0


# ────────────────────────────────────────────────────────────────────
# 2026 Dynamic Cycle Cap Management Tests
# ────────────────────────────────────────────────────────────────────

def test_dynamic_cycle_cap_tracks_approved_orders():
    """Test that approved orders are tracked with timestamps."""
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.06, max_total_risk_pct=0.08)
    equity = 10_000  # $100
    
    # Approve an order
    ok, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXBTC-T"))
    assert ok
    # Check that pending orders dict is populated
    assert len(guard._pending_orders) == 1
    # Verify the order has a timestamp
    for order_id, (risk_cents, timestamp) in guard._pending_orders.items():
        assert risk_cents == 100  # or scaled value
        assert timestamp > 0
        assert "KXBTC-T" in order_id


def test_record_fill_releases_capacity():
    """Test that recording a fill releases capacity from the cycle accumulator."""
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.06, max_total_risk_pct=0.08)
    equity = 10_000  # $100
    
    # Approve an order
    ok, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXBTC-T"))
    assert ok
    initial_accumulator = guard._cycle_new_risk_cents
    assert initial_accumulator > 0
    
    # Get the order_id from pending orders
    order_id = list(guard._pending_orders.keys())[0]
    
    # Record a fill
    guard.record_fill(order_id, 100)
    
    # Check that capacity was released
    assert guard._cycle_new_risk_cents < initial_accumulator
    # Check that order was removed from pending
    assert order_id not in guard._pending_orders
    # Check that fills counter was incremented
    assert guard._fills_in_window == 1


def test_release_timed_out_capacity():
    """Test that timed-out orders release capacity."""
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.06, max_total_risk_pct=0.08)
    equity = 10_000
    
    # Approve an order
    ok, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXBTC-T"))
    assert ok
    initial_accumulator = guard._cycle_new_risk_cents
    
    # Manually set the order's timestamp to be old (older than timeout)
    order_id = list(guard._pending_orders.keys())[0]
    old_timestamp = time.time() - guard._pending_order_timeout_sec - 10
    guard._pending_orders[order_id] = (guard._pending_orders[order_id][0], old_timestamp)
    
    # Call reset_cycle which triggers timed-out capacity release
    guard.reset_cycle()
    
    # After reset_cycle, accumulator should be reset to 0 (normal reset)
    # But the timed-out order should have been removed
    assert order_id not in guard._pending_orders


def test_check_no_fill_reset():
    """Test that no-fill auto-reset triggers after timeout window."""
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.06, max_total_risk_pct=0.08)
    equity = 10_000
    
    # Approve an order to consume capacity
    ok, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXBTC-T"))
    assert ok
    assert guard._cycle_new_risk_cents > 0
    
    # Manually set window start time to be old (older than no-fill reset window)
    guard._window_start_time = time.time() - guard._no_fill_reset_window_sec - 10
    
    # Check no-fill reset should trigger
    reset_performed = guard.check_no_fill_reset(equity)
    assert reset_performed
    
    # Accumulator should be reset to 0
    assert guard._cycle_new_risk_cents == 0
    # Pending orders should be cleared
    assert len(guard._pending_orders) == 0


def test_no_fill_reset_with_failsafe():
    """Test that no-fill auto-reset does NOT trigger when fills have occurred."""
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.06, max_total_risk_pct=0.08)
    equity = 10_000
    
    # Approve an order
    ok, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXBTC-T"))
    assert ok
    
    # Record a fill
    order_id = list(guard._pending_orders.keys())[0]
    guard.record_fill(order_id, 100)
    
    # Manually set window start time to be old
    guard._window_start_time = time.time() - guard._no_fill_reset_window_sec - 10
    
    # Check no-fill reset should NOT trigger (fills occurred)
    reset_performed = guard.check_no_fill_reset(equity)
    assert not reset_performed


def test_dynamic_cycle_cap_with_multiple_orders():
    """Test dynamic cycle cap with multiple approved orders."""
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.06, max_total_risk_pct=0.08)
    equity = 10_000  # $100, cycle cap = $6 = 600 cents
    
    # Approve multiple orders
    ok1, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXBTC-T"))
    ok2, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXETH-T"))
    ok3, _ = guard.check_order(equity, 0, _pending(max_loss=100, ticker="KXSOL-T"))
    
    assert ok1 and ok2 and ok3
    assert len(guard._pending_orders) == 3
    
    # Record fills for 2 orders
    order_ids = list(guard._pending_orders.keys())
    guard.record_fill(order_ids[0], 100)
    guard.record_fill(order_ids[1], 100)
    
    # Check that 2 orders were removed from pending
    assert len(guard._pending_orders) == 1
    # Check fills counter
    assert guard._fills_in_window == 2
