"""Scalper single-batch invariant tests (§2 + §5 of Momentum Scalper spec).

Covers:
  * ``SCALPER_SINGLE_BATCH_MODE`` — no new entry while existing open risk > 0
  * ``SCALPER_MAX_TRADES_PER_BATCH`` — at most N (default 3) entries per batch
  * Exits/sells bypass the scalper veto (always allowed, reduce exposure)
  * ``reset_cycle()`` advances ``batch_id`` and clears per-batch counters
  * Multi-caller simulation: CT + AgentGrid + lane cannot collectively open
    more than ``max_trades_per_batch`` entries or stack a second batch
  * Settings surface — scalper flags visible on ``core.settings``
"""

from __future__ import annotations

import pytest

from merid.guards.global_risk_guard import (
    GlobalRiskGuard,
    PendingOrderRisk,
    check_intent,
    get_global_risk_guard,
    reset_global_risk_guard_for_tests,
    set_equity_provider,
    set_existing_risk_provider,
)


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singletons():
    reset_global_risk_guard_for_tests()
    yield
    reset_global_risk_guard_for_tests()


def _pending(max_loss: int, ticker: str = "KXBTC-T", asset: str = "BTC") -> PendingOrderRisk:
    return PendingOrderRisk(
        ticker=ticker, asset=asset, contracts=1,
        entry_price_cents=max_loss, direction="long",
        max_loss_cents=max_loss, edge=0.05,
    )


def _scalper_guard(max_trades: int = 3) -> GlobalRiskGuard:
    return GlobalRiskGuard(
        max_cycle_risk_pct=0.03,
        max_total_risk_pct=0.08,
        scalper_single_batch_mode=True,
        max_trades_per_batch=max_trades,
    )


# ────────────────────────────────────────────────────────────────────
# Single-batch invariant
# ────────────────────────────────────────────────────────────────────

def test_scalper_blocks_new_entry_when_existing_open_risk():
    guard = _scalper_guard()
    # Existing open risk > 0 → any new BUY rejected with SCALPER_MODE_BLOCK
    ok, reason = guard.check_order(
        equity_cents=10_000,
        existing_risk_cents=1,          # even 1¢ of open risk triggers
        pending_order=_pending(max_loss=10),
    )
    assert not ok
    assert "SCALPER_MODE_BLOCK" in reason
    assert "existing open risk" in reason


def test_scalper_allows_entry_when_flat():
    guard = _scalper_guard()
    ok, _ = guard.check_order(
        equity_cents=10_000,
        existing_risk_cents=0,
        pending_order=_pending(max_loss=50),
    )
    assert ok


def test_scalper_max_trades_per_batch_enforced():
    guard = _scalper_guard(max_trades=3)
    equity = 1_000_000  # large enough that cycle cap is never the binder

    # First 3 entries (flat batch) pass
    for i in range(3):
        ok, _ = guard.check_order(
            equity_cents=equity,
            existing_risk_cents=0,
            pending_order=_pending(max_loss=10, ticker=f"T{i}"),
        )
        assert ok, f"entry #{i + 1} should have passed"

    # 4th rejected with SCALPER_MODE_BLOCK
    ok, reason = guard.check_order(
        equity_cents=equity,
        existing_risk_cents=0,
        pending_order=_pending(max_loss=10, ticker="T4"),
    )
    assert not ok
    assert "SCALPER_MODE_BLOCK" in reason
    assert "max trades per batch" in reason


def test_scalper_reset_cycle_starts_new_batch():
    guard = _scalper_guard(max_trades=2)
    equity = 1_000_000
    b0 = guard.batch_id

    assert guard.check_order(equity, 0, _pending(10, ticker="A"))[0]
    assert guard.check_order(equity, 0, _pending(10, ticker="B"))[0]
    # 3rd blocked
    assert not guard.check_order(equity, 0, _pending(10, ticker="C"))[0]

    guard.reset_cycle()
    assert guard.batch_id == b0 + 1
    # Fresh batch — can admit again (assuming flat)
    assert guard.check_order(equity, 0, _pending(10, ticker="D"))[0]


def test_scalper_disabled_by_default():
    guard = GlobalRiskGuard(max_cycle_risk_pct=0.03, max_total_risk_pct=0.08)
    assert guard.scalper_single_batch_mode is False
    # With scalper off, open risk does NOT block by itself
    ok, _ = guard.check_order(
        equity_cents=10_000,
        existing_risk_cents=50,
        pending_order=_pending(max_loss=10),
    )
    assert ok


def test_scalper_configure_runtime_toggle():
    guard = GlobalRiskGuard()
    assert guard.scalper_single_batch_mode is False
    guard.configure_scalper(True, max_trades_per_batch=2)
    assert guard.scalper_single_batch_mode is True
    assert guard.max_trades_per_batch == 2
    # Now blocks on open risk
    ok, reason = guard.check_order(10_000, 25, _pending(10))
    assert not ok
    assert "SCALPER_MODE_BLOCK" in reason


# ────────────────────────────────────────────────────────────────────
# Exits bypass scalper veto
# ────────────────────────────────────────────────────────────────────

def test_scalper_exits_always_allowed_via_check_intent():
    """Sells/exits reduce exposure and must never be blocked by scalper mode."""
    set_equity_provider(lambda: 10_000)
    set_existing_risk_provider(lambda: 150)  # open batch present

    # Seed singleton as scalper
    g = get_global_risk_guard()
    g.configure_scalper(True, max_trades_per_batch=3)

    try:
        ok, reason = check_intent(
            ticker="KXBTC-T", asset="BTC",
            side="yes", action="sell",
            price_cents=60, count=100,
        )
        assert ok
        assert reason == "exit_exempt"
    finally:
        set_equity_provider(None)
        set_existing_risk_provider(None)


def test_scalper_buy_blocked_via_check_intent_when_open_risk():
    set_equity_provider(lambda: 10_000)
    set_existing_risk_provider(lambda: 50)  # open batch present

    g = get_global_risk_guard()
    g.configure_scalper(True, max_trades_per_batch=3)

    try:
        ok, reason = check_intent(
            ticker="KXETH-T", asset="ETH",
            side="yes", action="buy",
            price_cents=40, count=1,
        )
        assert not ok
        assert "SCALPER_MODE_BLOCK" in reason
    finally:
        set_equity_provider(None)
        set_existing_risk_provider(None)


# ────────────────────────────────────────────────────────────────────
# Multi-caller aggregate invariant (CT + AgentGrid + lane)
# ────────────────────────────────────────────────────────────────────

def test_scalper_multi_source_cannot_exceed_max_trades_per_batch():
    """CT, agent grid, and a crypto lane all try to open entries.

    With scalper mode on and ``max_trades_per_batch=3``, no more than 3
    entries total are admitted per batch across all callers.
    """
    set_equity_provider(lambda: 1_000_000)
    set_existing_risk_provider(lambda: 0)  # start flat

    g = get_global_risk_guard()
    g.reset_cycle()
    g.configure_scalper(True, max_trades_per_batch=3)

    try:
        admits = []
        # 5 candidates across 3 pseudo-callers
        for i, (tkr, asset) in enumerate([
            ("KXBTC-T", "BTC"),
            ("KXETH-T", "ETH"),
            ("KXSOL-T", "SOL"),
            ("KXXRP-T", "XRP"),
            ("KXDOGE-T", "DOGE"),
        ]):
            ok, _ = check_intent(
                ticker=tkr, asset=asset,
                side="yes", action="buy",
                price_cents=5, count=1,
            )
            admits.append(ok)
        assert sum(1 for a in admits if a) == 3
        assert admits[:3] == [True, True, True]
        assert admits[3:] == [False, False]
    finally:
        set_equity_provider(None)
        set_existing_risk_provider(None)


def test_scalper_second_batch_blocked_while_first_open():
    """After admitting a batch, simulate open risk; no new batch can stack."""
    # Batch 1: flat → admit 2 entries @ 10c each → existing_risk = 20c
    g = get_global_risk_guard()
    g.configure_scalper(True, max_trades_per_batch=3)
    g.reset_cycle()

    assert g.check_order(1_000_000, 0, _pending(10, ticker="A"))[0]
    assert g.check_order(1_000_000, 0, _pending(10, ticker="B"))[0]

    # Cycle flips, but positions still open (existing_risk_cents > 0)
    g.reset_cycle()
    ok, reason = g.check_order(
        equity_cents=1_000_000,
        existing_risk_cents=20,  # prior batch still open
        pending_order=_pending(10, ticker="C"),
    )
    assert not ok
    assert "SCALPER_MODE_BLOCK" in reason
    assert "existing open risk" in reason

    # Only after all positions close (existing_risk_cents → 0) may we admit
    ok2, _ = g.check_order(
        equity_cents=1_000_000,
        existing_risk_cents=0,
        pending_order=_pending(10, ticker="D"),
    )
    assert ok2


# ────────────────────────────────────────────────────────────────────
# Telemetry + settings surface
# ────────────────────────────────────────────────────────────────────

def test_scalper_metrics_surface():
    g = _scalper_guard(max_trades=2)
    g.check_order(1_000_000, 50, _pending(10))  # scalper block
    g.check_order(1_000_000, 0, _pending(10, ticker="X"))  # approved
    m = g.metrics()
    assert m["scalper_single_batch_mode"] is True
    assert m["max_trades_per_batch"] == 2
    assert m["scalper_blocks"] >= 1
    assert m["cycle_approved_count"] == 1
    assert "batch_id" in m


def test_core_settings_exposes_scalper_flags():
    from core import settings as s
    assert hasattr(s, "STRATEGY_MODE")
    assert hasattr(s, "SCALPER_MODE")
    assert hasattr(s, "SCALPER_SINGLE_BATCH_MODE")
    assert hasattr(s, "SCALPER_MAX_TRADES_PER_BATCH")
    assert hasattr(s, "SCALPER_MAX_BATCH_RISK_PCT")
    assert s.SCALPER_MAX_TRADES_PER_BATCH >= 1


def test_singleton_picks_up_scalper_config_from_settings(monkeypatch):
    """Flipping env + rebuilding singleton enables scalper mode."""
    monkeypatch.setenv("STRATEGY_MODE", "MOMENTUM_SCALPER")
    monkeypatch.setenv("SCALPER_SINGLE_BATCH_MODE", "true")
    monkeypatch.setenv("SCALPER_MAX_TRADES_PER_BATCH", "2")

    # Reload settings module so env changes take effect
    import importlib

    import core.settings as core_settings
    importlib.reload(core_settings)
    assert core_settings.SCALPER_SINGLE_BATCH_MODE is True
    assert core_settings.SCALPER_MAX_TRADES_PER_BATCH == 2

    reset_global_risk_guard_for_tests()
    g = get_global_risk_guard()
    assert g.scalper_single_batch_mode is True
    assert g.max_trades_per_batch == 2

    # Cleanup: reload without scalper env so other tests are unaffected
    monkeypatch.delenv("STRATEGY_MODE", raising=False)
    monkeypatch.delenv("SCALPER_SINGLE_BATCH_MODE", raising=False)
    monkeypatch.delenv("SCALPER_MAX_TRADES_PER_BATCH", raising=False)
    importlib.reload(core_settings)
