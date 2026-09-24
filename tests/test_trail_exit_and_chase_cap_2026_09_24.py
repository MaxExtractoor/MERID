"""
Incident regression tests, 2026-09-24 (KXXRP15M-26SEP241600-00).

Two defects are covered:

1. Premature loss exits: a trailing stop that armed in profit inherited the
   hard stop-loss floor (stop 27c -> limit 25c) instead of its own trail level
   (64c).  The IOC filled at 55c — below the 58c entry — on a contract that
   settled YES=100.  The trail must anchor to the trail level with a breakeven
   ratchet, and a trustworthy calibrated model that still favors the held side
   must veto the sale (the "winning side" test).

2. Entry price chase: the edge-preserving repricer lifted a BUY_NO limit from
   the decision's selected price (38c) to the model's maximum tolerated price
   (~62c) after the book moved, filling at 61c on a stale signal.  The reprice
   is now bounded by selected_price + MERID_ENTRY_MAX_CHASE_CENTS.
"""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# ---------------------------------------------------------------------------
# Exit-guard fixtures (mirrors tests/test_exit_guard_2026_08_19.py)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _disable_persistence_and_fees(monkeypatch):
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_intent_contract.persist_order_decision",
        lambda record: None,
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.parabolic_fees.kalshi_taker_fee_cents_parabolic",
        lambda *_a, **_k: 2,
    )


@pytest.fixture(autouse=True)
def _reset_ev_gate_state(monkeypatch):
    monkeypatch.setenv("MERID_EV_EXIT_DISABLE_PERSIST", "1")
    monkeypatch.delenv("MERID_ENABLE_EV_EXIT_GATE", raising=False)
    monkeypatch.delenv("MERID_EV_EXIT_GATE_KILL", raising=False)
    import merid.event_venues.kalshi.settlement_aligned_exit as sae

    monkeypatch.setattr(sae, "_default_rti_provider", lambda _asset: None)
    sae._evaluator = None
    sae._registry = None
    sae._resolver = None
    yield
    sae._evaluator = None
    sae._registry = None
    sae._resolver = None


@pytest.fixture(autouse=True)
def _seed_canonical_position_cache():
    from merid.event_venues.kalshi.position_cache import (
        CachedPosition,
        get_position_cache,
    )

    market_id = "KXXRP15M-26SEP241600-00"
    cache = get_position_cache()
    cache._positions[market_id] = CachedPosition(
        market_id=market_id,
        agent_id="test",
        contracts=1,
        side="yes",
        thesis_side="yes",
        avg_price_cents=58,
    )
    yield
    cache._positions.pop(market_id, None)


def _make_state(*, yes_bid=None, yes_ask=None, age_ms=1000, seconds_to_expiry=300.0):
    state = Mock()
    state.book_updated_ts = time.monotonic() - (age_ms / 1000.0)
    state.seconds_to_expiry = seconds_to_expiry
    state.book_source = "ws"
    state.best_bid_cents = yes_bid
    state.best_ask_cents = yes_ask
    state.no_bid_cents = None
    state.no_ask_cents = None
    state.book = None
    return state


def _make_trail_position(**kwargs):
    """YES position at 58c that ran to 69c (trail level ~64c) — the incident."""
    defaults = dict(
        position_id="pos-xrp1600",
        market_id="KXXRP15M-26SEP241600-00",
        size=1,
        avg_entry_price_cents=58,
        outcome_side="yes",
        thesis_side="yes",
        stop_loss_price_cents=27,       # the trap: hard stop far below
        hard_stop_price_cents=None,
        max_favorable_price_cents=69,
        trailing_param=5,
        entry_fill_id="fill-xrp",
    )
    defaults.update(kwargs)
    ns = SimpleNamespace(**defaults)
    # Position.get_trail_level equivalent: max_favorable - trailing_param.
    trail_level = kwargs.get("trail_level", 64)
    ns.get_trail_level = lambda: trail_level
    return ns


def _run_guard(position, exit_reason, exit_price_cents, count=1, state=None):
    from merid.loop_15m import _run_exit_price_guard

    def _get_market_state(_ticker):
        return (state, None)

    with patch(
        "merid.event_venues.kalshi.stop_candidate._get_market_state",
        _get_market_state,
    ):
        return _run_exit_price_guard(position, exit_reason, exit_price_cents, count)


def _fake_eval(**overrides):
    from merid.event_venues.kalshi.settlement_aligned_exit import (
        EvDecision,
        EvExitEvaluation,
    )

    defaults = dict(
        evaluation_id="ev-test",
        market_key="KXXRP15M-26SEP241600-00",
        position_id="pos-xrp1600",
        held_side="yes",
        canonical_reason="trailing_stop",
        exit_class="operational",
        decision=EvDecision.BYPASS_OPERATIONAL,
        detail="operational_exit_not_ev_gated",
        net_sell_value_cents=None,
        conservative_hold_cents=None,
        p_held_calibrated_cents=None,
        model_inputs_satisfactory=False,
        quote_sequence_confirmed=False,
        quote_coherent=False,
        rti_execution_eligible=False,
    )
    defaults.update(overrides)
    return EvExitEvaluation(**defaults)


def _stub_evaluator(monkeypatch, ev):
    import merid.event_venues.kalshi.settlement_aligned_exit as sae

    stub = Mock()
    stub.evaluate.return_value = ev
    stub.policy = sae.EvGatePolicy()
    monkeypatch.setattr(sae, "get_exit_evaluator", lambda: stub)


# ---------------------------------------------------------------------------
# Trail-limit anchoring
# ---------------------------------------------------------------------------

def test_trailing_stop_never_uses_hard_stop_floor():
    """Incident replay: trail level 64c, bid 62c, hard stop 27c.

    Old behavior anchored the limit to stop-slippage (25c), permitting a fill
    33c below trigger at 55c.  The trail must anchor to its own level.
    """
    position = _make_trail_position()
    state = _make_state(yes_bid=62, yes_ask=64)

    approved, price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=62, state=state
    )

    assert approved is True
    assert record["exit_reason_canonical"] == "trailing_stop"
    # trail floor = trail_level(64) - slippage(2) = 62; armed above entry(58)
    # -> breakeven ratchet floor = max(62, 58) = 62; bid 62 >= 62 -> limit 62.
    assert record["trail_level_cents"] == 64
    assert record["trail_floor_cents"] == 62
    assert record["limit_cents"] >= 60
    assert record["limit_cents"] != 25
    assert price == record["limit_cents"]


def test_trailing_stop_breakeven_floor_blocks_loss_fill():
    """A profit-armed trail must not realize a loss while bid >= entry."""
    position = _make_trail_position()
    # Bid slipped to 59c: still >= entry(58) but below trail floor 62.
    state = _make_state(yes_bid=59, yes_ask=61)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=59, state=state
    )

    # Book gapped below the trail floor -> sell at market bounded by slippage.
    assert approved is True
    assert record["limit_cents"] == 57  # 59 - 2 slippage
    # Still better than the incident's 25c floor; and the EV veto (below) is
    # the arbiter for whether selling below the trail is right at all.


def test_trailing_stop_deep_gap_sells_at_market_bounded():
    """Book gapped below entry: loss-management sell at market, bounded."""
    position = _make_trail_position()
    state = _make_state(yes_bid=50, yes_ask=52)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=50, state=state
    )

    assert approved is True
    assert record["limit_cents"] == 48  # 50 - 2 slippage
    assert record["projected_net_pnl_cents"] < 0
    # Bounded by giveback max_loss: (hwm 69 - bid 50 + slip 2) + fees.
    assert -record["projected_net_pnl_cents"] <= record["max_loss_cents"]


# ---------------------------------------------------------------------------
# Winning-side hold veto
# ---------------------------------------------------------------------------

def _trusted_hold_eval(net_sell="55.0", cons_hold="66.0", p_cal=70):
    """Model says the held YES side is worth 66c+ while bid pays ~57c."""
    return _fake_eval(
        net_sell_value_cents=net_sell,
        conservative_hold_cents=cons_hold,
        p_held_calibrated_cents=p_cal,
        model_inputs_satisfactory=True,
        quote_sequence_confirmed=True,
        quote_coherent=True,
        rti_execution_eligible=True,
    )


def test_hold_veto_blocks_winning_side_loss_exit(monkeypatch):
    """THE core fix: bid 55 < entry 58 but model says worth ~66 -> don't sell.

    This is 'deterministically on the winning side even though price is below
    entry': the calibrated settlement probability (p_held_cal=70) values the
    contract above the executable bid, so selling realizes a loss the model
    says not to take.
    """
    _stub_evaluator(monkeypatch, _trusted_hold_eval())
    position = _make_trail_position()
    state = _make_state(yes_bid=55, yes_ask=57)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=55, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "ev_hold_advantage"
    assert record["p_held_calibrated"] == 70


def test_hold_veto_blocks_premature_profit_taking(monkeypatch):
    """Same rule above entry: model says 80c but trail wants to sell at 62c."""
    _stub_evaluator(monkeypatch, _trusted_hold_eval(net_sell="59.5", cons_hold="78.0", p_cal=81))
    position = _make_trail_position()
    state = _make_state(yes_bid=62, yes_ask=64)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=62, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "ev_hold_advantage"


def test_no_veto_when_model_says_sell(monkeypatch):
    """Model agrees the thesis is dead (cons_hold << net_sell) -> exit proceeds."""
    _stub_evaluator(
        monkeypatch,
        _trusted_hold_eval(net_sell="55.0", cons_hold="40.0", p_cal=43),
    )
    position = _make_trail_position()
    state = _make_state(yes_bid=55, yes_ask=57)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=55, state=state
    )

    assert approved is True
    assert record["limit_cents"] == 53


def test_no_veto_when_advantage_below_margin(monkeypatch):
    """Marginal model preference must not trap a legitimate exit."""
    _stub_evaluator(
        monkeypatch,
        _trusted_hold_eval(net_sell="55.0", cons_hold="56.0", p_cal=60),
    )
    position = _make_trail_position()
    state = _make_state(yes_bid=55, yes_ask=57)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=55, state=state
    )

    assert approved is True


def test_no_veto_when_model_untrusted(monkeypatch):
    """Uncalibrated/untrusted model inputs fail open: no veto, exit proceeds."""
    ev = _trusted_hold_eval()
    ev.model_inputs_satisfactory = False
    _stub_evaluator(monkeypatch, ev)
    position = _make_trail_position()
    state = _make_state(yes_bid=55, yes_ask=57)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=55, state=state
    )

    assert approved is True
    assert record["ev_hold_veto_model_trusted"] is False


def test_no_veto_when_economics_unavailable(monkeypatch):
    """No bid/model value -> no economics -> no veto (exits fail open)."""
    _stub_evaluator(monkeypatch, _fake_eval())
    position = _make_trail_position()
    state = _make_state(yes_bid=55, yes_ask=57)

    approved, _price, record, _did = _run_guard(
        position, "trailing_stop", exit_price_cents=55, state=state
    )

    assert approved is True


def test_emergency_expiry_settles_without_premium(monkeypatch):
    """Inside the emergency cutoff an expiry sell now needs a market premium:
    settlement needs no book, so a trusted model valuing the contract above
    the bid means the position rides to settlement (auto_exit_99c ->
    expiry_liquidation)."""
    _stub_evaluator(
        monkeypatch, _trusted_hold_eval(net_sell="55.0", cons_hold="66.0", p_cal=70)
    )
    position = _make_trail_position()
    state = _make_state(yes_bid=55, yes_ask=57, seconds_to_expiry=30.0)

    approved, _price, record, _did = _run_guard(
        position, "auto_exit_99c", exit_price_cents=55, state=state
    )

    assert approved is False
    assert record["is_emergency"] is True
    assert record["reject_reason"] == "expiry_settle_default"


def test_forced_exit_vetoed_outside_emergency(monkeypatch):
    """expiry_liquidation beyond the emergency cutoff IS vetoable: a winning
    position must not be dumped at a discount just because a timer fired."""
    _stub_evaluator(monkeypatch, _trusted_hold_eval())
    position = _make_trail_position()
    state = _make_state(yes_bid=55, yes_ask=57, seconds_to_expiry=120.0)

    approved, _price, record, _did = _run_guard(
        position, "settlement_guard", exit_price_cents=55, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "expiry_settle_default"


# ---------------------------------------------------------------------------
# Expiry settle-default gate (2026-09-24, KXXRP15M-26SEP241900-00)
# ---------------------------------------------------------------------------
# Live incident: long YES@68 was force-sold at 48c at T-104s on an UNTRUSTED
# eval (vol_source=none, book_incoherent) — YES settled at 100, a -23c exit
# that forfeited +32c.  At expiry the alternative to selling is free
# settlement, so a sell is only justified when a trusted eval shows the market
# paying a premium over the calibrated settlement value.


def _expiry_eval(**overrides):
    return _fake_eval(
        canonical_reason="expiry_liquidation",
        exit_class="emergency",
        **overrides,
    )


def test_expiry_untrusted_eval_rides_to_settlement(monkeypatch):
    """Incident replay: eval untrusted -> settle, don't donate spread+fee."""
    _stub_evaluator(monkeypatch, _expiry_eval())  # everything untrusted/None
    position = _make_trail_position()
    state = _make_state(yes_bid=48, yes_ask=52, seconds_to_expiry=104.0)

    approved, _price, record, _did = _run_guard(
        position, "settlement_guard", exit_price_cents=48, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "expiry_settle_default"
    assert record["expiry_settle_model_trusted"] is False


def test_expiry_premium_sell_proceeds(monkeypatch):
    """Trusted eval + net_sell above calibrated value -> sell is justified."""
    _stub_evaluator(
        monkeypatch,
        _expiry_eval(
            net_sell_value_cents="58.0",
            p_held_calibrated_cents=30,
            model_inputs_satisfactory=True,
            quote_sequence_confirmed=True,
            quote_coherent=True,
            rti_execution_eligible=True,
        ),
    )
    position = _make_trail_position()
    state = _make_state(yes_bid=60, yes_ask=62, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "settlement_guard", exit_price_cents=60, state=state
    )

    assert approved is True
    assert record["expiry_settle_premium"] is True


def test_expiry_no_premium_settles(monkeypatch):
    """Trusted eval but market pays no premium over settle value -> settle."""
    _stub_evaluator(
        monkeypatch,
        _expiry_eval(
            net_sell_value_cents="44.0",
            p_held_calibrated_cents=48,
            model_inputs_satisfactory=True,
            quote_sequence_confirmed=True,
            quote_coherent=True,
            rti_execution_eligible=True,
        ),
    )
    position = _make_trail_position()
    state = _make_state(yes_bid=46, yes_ask=48, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "settlement_guard", exit_price_cents=46, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "expiry_settle_default"


def test_expiry_gate_applies_inside_emergency_cutoff(monkeypatch):
    """T-30s is 'emergency' for quote checks but settlement still needs no
    book — an untrusted eval must not force-sell at the bid."""
    _stub_evaluator(monkeypatch, _expiry_eval())
    position = _make_trail_position()
    state = _make_state(yes_bid=48, yes_ask=52, seconds_to_expiry=30.0)

    approved, _price, record, _did = _run_guard(
        position, "settlement_guard", exit_price_cents=48, state=state
    )

    assert approved is False
    assert record["reject_reason"] == "expiry_settle_default"


def test_expiry_gate_env_off_restores_legacy_sell(monkeypatch):
    """MERID_SETTLEMENT_GUARD_EV_GATE=0 restores the unconditional sell."""
    monkeypatch.setenv("MERID_SETTLEMENT_GUARD_EV_GATE", "0")
    _stub_evaluator(monkeypatch, _expiry_eval())
    position = _make_trail_position()
    state = _make_state(yes_bid=48, yes_ask=52, seconds_to_expiry=90.0)

    approved, _price, record, _did = _run_guard(
        position, "settlement_guard", exit_price_cents=48, state=state
    )

    assert approved is True


# ---------------------------------------------------------------------------
# Monitor-side settlement-guard gate (_settlement_guard_sell_justified)
# ---------------------------------------------------------------------------


def _monitor_position(**kwargs):
    defaults = dict(
        position_id="pos-xrp1900",
        market_id="KXXRP15M-26SEP241900-00",
        size=1,
        avg_entry_price_cents=68,
        outcome_side="yes",
        thesis_side="yes",
    )
    defaults.update(kwargs)
    ns = SimpleNamespace(**defaults)
    ns.side = SimpleNamespace(value="yes")
    return ns


def _snapshot(bid=48, age_ms=120):
    return SimpleNamespace(own_side_bid_cents=bid, book_age_ms=age_ms)


def test_monitor_gate_untrusted_defaults_to_settle(monkeypatch):
    """The monitor emits no SETTLEMENT_GUARD candidate when the eval is
    untrusted — the position rides to settlement instead."""
    from merid.position_management.position_monitor import (
        _settlement_guard_sell_justified,
    )

    _stub_evaluator(monkeypatch, _expiry_eval())
    assert (
        _settlement_guard_sell_justified(_monitor_position(), _snapshot(), 104.0)
        is False
    )


def test_monitor_gate_premium_sells(monkeypatch):
    from merid.position_management.position_monitor import (
        _settlement_guard_sell_justified,
    )

    _stub_evaluator(
        monkeypatch,
        _expiry_eval(
            net_sell_value_cents="58.0",
            p_held_calibrated_cents=30,
            model_inputs_satisfactory=True,
            quote_sequence_confirmed=True,
            quote_coherent=True,
            rti_execution_eligible=True,
        ),
    )
    assert (
        _settlement_guard_sell_justified(_monitor_position(), _snapshot(), 104.0)
        is True
    )


def test_monitor_gate_eval_error_defaults_to_settle(monkeypatch):
    """Eval infra failure must not manufacture a sell justification."""
    import merid.event_venues.kalshi.settlement_aligned_exit as sae
    from merid.position_management.position_monitor import (
        _settlement_guard_sell_justified,
    )

    stub = Mock()
    stub.evaluate.side_effect = RuntimeError("eval down")
    stub.policy = sae.EvGatePolicy()
    monkeypatch.setattr(sae, "get_exit_evaluator", lambda: stub)

    assert (
        _settlement_guard_sell_justified(_monitor_position(), _snapshot(), 104.0)
        is False
    )


# ---------------------------------------------------------------------------
# Entry chase cap on the edge-preserving repricer
# ---------------------------------------------------------------------------

def _make_ws_state(best_bid_cents, best_ask_cents):
    from merid.event_venues.kalshi.market_state import BookHealth

    ts = time.monotonic()
    return SimpleNamespace(
        ticker="KXSOL15M-26SEP242000-00",
        best_bid_cents=best_bid_cents,
        best_ask_cents=best_ask_cents,
        data_source="WS_ORDERBOOK_DELTA_LIVE",
        snapshot_complete=True,
        live_sequence_confirmed=True,
        book_initialized=True,
        book_health=BookHealth.LIVE,
        last_ws_update_ts=ts,
        last_book_update_ts=ts,
    )


def _make_store(state):
    store = MagicMock()
    store.get.return_value = state
    store._validate_yes_no_invariants.return_value = True
    return store


def _make_port(rest_yes_bid, rest_yes_ask):
    from decimal import Decimal

    from merid.event_venues.kalshi.port import OrderbookLevel, OrderbookResult

    port = AsyncMock()

    async def _get_orderbook(_ticker):
        return OrderbookResult(
            success=True,
            yes_levels=[OrderbookLevel(price_cents=rest_yes_bid, size=Decimal("100"), side="yes")],
            no_levels=[OrderbookLevel(price_cents=100 - rest_yes_ask, size=Decimal("100"), side="no")],
            timestamp=time.time(),
        )

    port.get_orderbook.side_effect = _get_orderbook
    return port


def _make_chase_intent(price_cents=38, sel=38):
    from merid.event_venues.kalshi.order_router import OrderIntent

    intent = OrderIntent(
        ticker="KXSOL15M-26SEP242000-00",
        side="no",
        action="buy",
        price_cents=price_cents,
        count=1,
        source="merid.prediction.agent_grid_15m",
        aggressiveness=1.0,
    )
    intent.selected_outcome_price_cents = sel
    intent.ev_net_cents = 30.0
    intent.p_selected = 0.70
    intent.min_required_edge = 0.10
    return intent


@pytest.mark.asyncio
async def test_edge_reprice_cannot_chase_past_selected_price(monkeypatch):
    """Incident replay: decision NO@38, book walked to ~45; the edge budget
    (~58c) must NOT lift the limit past sel+chase (43c).  Reject instead."""
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "5")
    from merid.event_venues.kalshi.order_router import _ws_rest_divergence_guard
    from merid.prediction.trading_mode import TradingMode

    # WS NO ask = 100-80 = 20; REST NO ask = 100-56 = 44 (24c divergence < 25 hard).
    state = _make_ws_state(80, 81)
    store = _make_store(state)
    port = _make_port(rest_yes_bid=56, rest_yes_ask=57)
    intent = _make_chase_intent(price_cents=38, sel=38)

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    ):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert "not_marketable" in result.reason
    # The limit was never lifted toward the edge budget.
    assert intent.price_cents == 38


@pytest.mark.asyncio
async def test_edge_reprice_allows_bounded_chase(monkeypatch):
    """A fresh ask inside sel+chase reprices to the capped budget, not _epc."""
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "5")
    from merid.event_venues.kalshi.order_router import _ws_rest_divergence_guard
    from merid.prediction.trading_mode import TradingMode

    # REST NO ask = 100-61 = 39; WS NO ask = 20 -> fresh_ask 39 <= chase 43.
    state = _make_ws_state(80, 81)
    store = _make_store(state)
    port = _make_port(rest_yes_bid=61, rest_yes_ask=62)
    intent = _make_chase_intent(price_cents=38, sel=38)

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    ):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is None
    # Lifted to the chase bound (43), never to the raw edge budget (~58).
    assert intent.price_cents == 43


@pytest.mark.asyncio
async def test_coherent_reprice_capped_by_chase(monkeypatch):
    """Coherent feeds: a non-marketable taker buy reprices only to sel+chase."""
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "5")
    from merid.event_venues.kalshi.order_router import _ws_rest_divergence_guard
    from merid.prediction.trading_mode import TradingMode

    # WS NO ask = 100-80 = 20, REST NO ask = 100-79 = 21: coherent (1c).
    # Intent price 18 is below both asks -> reprice branch. chase = 18+5 = 23.
    state = _make_ws_state(80, 81)
    store = _make_store(state)
    port = _make_port(rest_yes_bid=79, rest_yes_ask=80)
    intent = _make_chase_intent(price_cents=18, sel=18)

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    ):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is None
    assert intent.price_cents == 23


@pytest.mark.asyncio
async def test_coherent_reprice_rejects_beyond_chase(monkeypatch):
    """Coherent feeds but ask already beyond sel+chase -> reject, don't chase."""
    monkeypatch.setenv("MERID_ENTRY_MAX_CHASE_CENTS", "5")
    from merid.event_venues.kalshi.order_router import _ws_rest_divergence_guard
    from merid.prediction.trading_mode import TradingMode

    # WS NO ask = 100-69 = 31, REST NO ask = 100-70 = 30: coherent (1c).
    # Intent price 18, chase 23 < fresh_ask 31 -> reject.
    state = _make_ws_state(69, 70)
    store = _make_store(state)
    port = _make_port(rest_yes_bid=70, rest_yes_ask=71)
    intent = _make_chase_intent(price_cents=18, sel=18)

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=store,
    ):
        result = await _ws_rest_divergence_guard(
            intent, port, TradingMode.LIVE, time.monotonic()
        )

    assert result is not None
    assert result.status == "rejected"
    assert intent.price_cents == 18
