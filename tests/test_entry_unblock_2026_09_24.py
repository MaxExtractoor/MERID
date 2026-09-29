"""Regression tests for the 2026-09-24 entry-unblocking changeset.

Operator directive: keep the live stack trading consistently so decision and
fill telemetry accrue.  Diagnosis showed three dominant blockers:

1. The 75c canonical collar banned every favorite-side buy (the exact price
   band the settlement-convergence lane and converging mid-window trades
   live in).  Ceilings are now symmetric at 95c; the corrected-fee EV gate
   remains the real arbiter.
2. Loss-limit halts (daily loss / drawdown) were configured on.  They are now
   disabled for data collection: drawdown is still tracked, never latching.
3. Submit-time price gates dropped attempts whenever the book drifted between
   decision and wire.  The divergence guard now reprices inside the signal's
   edge-preserving budget (the budget already enforces net edge >=
   min_required at the fill price), and the mid-anchored fair/slippage caps
   only bind orders without edge provenance.
"""

import os
import time
from types import SimpleNamespace

import pytest
import yaml

from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    RepriceWouldCross,
    _adjust_order_price_for_fill_rate,
    _max_edge_preserving_buy_price,
    _validate_price_against_orderbook,
    _ws_rest_divergence_guard,
)


# ── 1. Canonical collar ─────────────────────────────────────────────────────


def test_canonical_yes_ceiling_is_95():
    """YES entries up to 95c must be inside the canonical range."""
    from merid.event_venues.kalshi.binary_price_space import (
        is_price_in_canonical_range,
        get_canonical_price_range,
    )

    assert get_canonical_price_range("yes") == (10, 95)
    assert is_price_in_canonical_range(85, "yes") is True
    assert is_price_in_canonical_range(95, "yes") is True
    assert is_price_in_canonical_range(96, "yes") is False
    assert get_canonical_price_range("no") == (25, 95)


def test_profile_entry_ceiling_resolves_95_and_loss_limits_off():
    """The committed profile resolves max_entry=95c with loss halts disabled."""
    profile_path = (
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        + "/config/profiles/kalshi_crypto_15m_v2.yaml"
    )
    with open(profile_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    assert raw["price_range"]["max_price_cents"] == 95
    assert raw["guardrails"]["max_contract_price_cents"] == 95
    assert raw["canonical"]["price_range"]["max_cents"] == 95
    assert raw["guardrails"]["daily_loss_enabled"] is False
    assert raw["guardrails"]["drawdown_halt_enabled"] is False


# ── 2. Risk envelope: drawdown halt disabled ────────────────────────────────


def _envelope_from_profile(tmp_path, halt_enabled: bool):
    """Build a risk envelope from the real profile with the halt flag flipped."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(repo_root, "config/profiles/kalshi_crypto_15m_v2.yaml"),
              "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["guardrails"]["drawdown_halt_enabled"] = halt_enabled
    p = tmp_path / "profile.yaml"
    p.write_text(yaml.safe_dump(cfg), encoding="utf-8")

    from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
        compute_kalshi_crypto_15m_risk_envelope,
    )
    return compute_kalshi_crypto_15m_risk_envelope(
        live_bankroll_usd=10.0, profile_path=str(p)
    )


def test_drawdown_halt_disabled_never_latches(tmp_path):
    env = _envelope_from_profile(tmp_path, halt_enabled=False)
    assert env.drawdown_halt_enabled is False

    # Drive equity 30% below peak — past the 20% halt threshold.
    env.update_drawdown(10.0)
    env.update_drawdown(7.0)

    assert env.current_drawdown_pct >= env.drawdown_halt_pct
    assert env.is_halted is False
    # Deepest non-halt band still de-risks, but never collapses to zero.
    assert env.per_trade_risk_multiplier > 0.0

    allowed, reason = env.check_window_limit("agent", 0.5, time.time())
    assert "envelope_halted" not in reason


def test_drawdown_halt_enabled_still_halts(tmp_path):
    env = _envelope_from_profile(tmp_path, halt_enabled=True)
    assert env.drawdown_halt_enabled is True

    env.update_drawdown(10.0)
    env.update_drawdown(7.0)

    assert env.is_halted is True


def test_daily_loss_disabled_resolves_inf(tmp_path):
    env = _envelope_from_profile(tmp_path, halt_enabled=False)
    # daily_loss_enabled=false in the committed profile -> effectively no cap.
    assert env.daily_loss_enabled is False
    assert env.max_daily_loss_usd == float("inf")


# ── 3. Divergence-guard bounded reprice ─────────────────────────────────────


def _taker_buy_intent(price_cents: int, basis: int, ev_net: float,
                      min_edge: float, p_selected: float) -> OrderIntent:
    intent = OrderIntent(
        ticker="KXBTC15M-TEST",
        price_cents=price_cents,
        count=1,
        side="yes",
        action="buy",
        order_type="limit",
        time_in_force="ioc",
        source="test",
    )
    intent.aggressiveness = 1.0
    intent.post_only = False
    intent.selected_outcome_price_cents = basis
    intent.ev_net_cents = ev_net
    intent.min_required_edge = min_edge
    intent.p_selected = p_selected
    return intent


def _ws_state(yes_bid: int, yes_ask: int):
    from merid.event_venues.kalshi.market_state import BookHealth
    now = time.monotonic()
    return SimpleNamespace(
        best_bid_cents=yes_bid,
        best_ask_cents=yes_ask,
        data_source="WS_ORDERBOOK_DELTA_LIVE",
        snapshot_complete=True,
        live_sequence_confirmed=True,
        book_initialized=True,
        book_health=BookHealth.LIVE,
        last_ws_update_ts=now,
        last_book_update_ts=now,
    )


class _StubStore:
    def __init__(self, state):
        self._state = state

    def get(self, ticker):
        return self._state

    def _validate_yes_no_invariants(self, ticker, yb, ya, nb, na):
        return True

    def _set_snapshot_complete(self, *a, **k):
        pass

    def _set_book_health(self, *a, **k):
        pass


class _StubPort:
    """Returns a REST book whose YES BBO matches (yes_bid, yes_ask)."""

    def __init__(self, yes_bid: int, yes_ask: int):
        self._yb = yes_bid
        self._ya = yes_ask

    async def get_orderbook(self, ticker):
        return SimpleNamespace(
            success=True,
            yes_levels=[SimpleNamespace(price_cents=self._yb, size=100.0)],
            no_levels=[SimpleNamespace(price_cents=100 - self._ya, size=100.0)],
            timestamp=time.time(),
        )


def _patch_store(monkeypatch, state):
    import merid.event_venues.kalshi.market_state as ms
    monkeypatch.setattr(ms, "get_kalshi_market_state_store",
                        lambda: _StubStore(state))


@pytest.mark.asyncio
async def test_divergence_guard_reprices_within_edge_budget(monkeypatch):
    """Ask raced above the limit but stays inside the edge budget -> reprice+allow."""
    # WS book moved: 73/74.  REST book moved the same way (divergence=0 -> coherent).
    _patch_store(monkeypatch, _ws_state(73, 74))
    intent = _taker_buy_intent(
        price_cents=70, basis=70, ev_net=20.0, min_edge=0.05, p_selected=0.90
    )
    # edge cap ~85-89 (floor(70+20-5)=85, theoretical 89); chase cap sel+5=75
    # binds tighter — the fresh ask 74 fits inside it and the lift stops there.
    assert _max_edge_preserving_buy_price(intent) >= 85

    port = _StubPort(73, 74)
    result = await _ws_rest_divergence_guard(intent, port, mode=None, t0=time.monotonic())
    assert result is None  # allowed
    assert intent.price_cents == 75  # lifted to the chase bound, not the raw edge cap


@pytest.mark.asyncio
async def test_divergence_guard_rejects_when_ask_beyond_edge_budget(monkeypatch):
    """Ask beyond the edge budget must still reject — never pay past the model."""
    _patch_store(monkeypatch, _ws_state(70, 95))
    intent = _taker_buy_intent(
        price_cents=70, basis=70, ev_net=10.0, min_edge=0.05, p_selected=0.75
    )
    # edge cap <= 74 (theoretical max 74); fresh ask 95 is far beyond.
    assert (_max_edge_preserving_buy_price(intent) or 0) < 95

    port = _StubPort(70, 95)
    result = await _ws_rest_divergence_guard(intent, port, mode=None, t0=time.monotonic())
    assert result is not None
    assert "not_marketable" in (result.reason or "")


# ── 4. Taker repricer: edge budget dominates the mid-anchored fair cap ──────


def _wide_book_state(yes_bid: int, yes_ask: int):
    """YES book 69/88: mid 78-79, so fair_cap = mid+5 < ask — the exact shape
    that used to get every converging favorite buy rejected."""
    return SimpleNamespace(
        book_initialized=True,
        mid_cents=int(round((yes_bid + yes_ask) / 2.0)),
        best_bid_cents=yes_bid,
        best_ask_cents=yes_ask,
        best_bid_size=100,
        best_ask_size=100,
        best_no_bid_cents=100 - yes_ask,
        best_no_ask_cents=100 - yes_bid,
        yes_bids=[(yes_bid, 100)],
        no_bids=[(100 - yes_ask, 100)],
        last_book_update_wall_ts=time.time(),
        age_ms=10,
        last_good_mid_cents=None,
    )


def test_taker_repricer_uses_edge_budget_in_wide_book(monkeypatch):
    """ask > mid+slippage but <= edge budget -> price at the budget, no reject."""
    monkeypatch.setenv("MERID_MAX_SLIPPAGE_CENTS", "5")
    # YES 69/88: mid~78/79 -> fair_cap ~84 < ask 88 (old code rejected here).
    state = _wide_book_state(69, 88)
    intent = _taker_buy_intent(
        price_cents=88, basis=85, ev_net=10.0, min_edge=0.03, p_selected=0.92
    )
    intent.snapshot_age_ms = 10
    cap = _max_edge_preserving_buy_price(intent)
    assert cap is not None and cap >= 88

    adjusted = _adjust_order_price_for_fill_rate(intent, state)
    assert adjusted == min(99, cap)
    assert adjusted >= 88


def test_taker_repricer_still_rejects_beyond_edge_budget(monkeypatch):
    monkeypatch.setenv("MERID_MAX_SLIPPAGE_CENTS", "5")
    state = _wide_book_state(69, 88)
    intent = _taker_buy_intent(
        price_cents=88, basis=85, ev_net=4.0, min_edge=0.03, p_selected=0.80
    )
    intent.snapshot_age_ms = 10
    # p_selected*100-1 = 79 -> edge cap <=79 < ask 88 -> must raise.
    assert (_max_edge_preserving_buy_price(intent) or 0) < 88
    with pytest.raises(RepriceWouldCross):
        _adjust_order_price_for_fill_rate(intent, state)


def test_price_validation_edge_budget_dominates_slippage_cap(monkeypatch):
    """price > mid+slippage but <= edge budget -> no validation error."""
    monkeypatch.setenv("MERID_MAX_SLIPPAGE_CENTS", "5")
    state = _wide_book_state(69, 88)
    intent = _taker_buy_intent(
        price_cents=90, basis=85, ev_net=10.0, min_edge=0.03, p_selected=0.95
    )
    cap = _max_edge_preserving_buy_price(intent)
    assert cap is not None and cap >= 90

    err = _validate_price_against_orderbook(intent, state, "yes")
    assert err is None, f"expected no validation error, got {err}"
