"""
Targeted invariants for the execution-planning refactor.

After this refactor, price / role / order_type / TIF / sizing are finalized in
`_prepare_order_for_gate` *before* the pre-trade gate inserts a PENDING record.
These tests verify that invariant for both the planning helper and the two
routing entry points.
"""

import time
from types import SimpleNamespace
from decimal import Decimal
from unittest.mock import MagicMock, Mock, AsyncMock

import pytest

# Pre-import submodules so string-based monkeypatch.setattr can resolve them
# when the test file is collected as part of a larger suite.
import merid.event_venues.kalshi.market_state
import merid.event_venues.kalshi.position_cache
import merid.event_venues.kalshi.dynamic_risk
import merid.event_venues.kalshi.position_sanity_checker
import merid.event_venues.kalshi.fills_ledger
import merid.event_venues.kalshi.order_deduplication
import merid.event_venues.kalshi.order_gate
import merid.risk.global_slot_allocator
import merid.risk.unified_risk_manager
import merid.risk.profiles.crypto_15m_profile

from merid.prediction.trading_mode import TradingMode
import merid.event_venues.kalshi.order_router as order_router
from merid.event_venues.kalshi.order_router import (
    OrderIntent,
    _prepare_order_for_gate,
    _route_live,
    route_order_async,
)


def make_intent(**overrides) -> OrderIntent:
    defaults = {
        "ticker": "KXBTC15M-TEST",
        "side": "BUY_YES",
        "action": "buy",
        "price_cents": 45,
        "count": 1,
        "mode": TradingMode.LIVE,
        "order_type": "limit",
        "time_in_force": "gtc",
        "edge_pct": 0.05,
        "aggressiveness": 0.0,
        "post_only": False,
        "snapshot_ts": time.time(),
        "snapshot_age_ms": 0.0,
        "model_prob": 0.95,
        "effective_equity_usd": 10000.0,
        "source": "kalshi_tools",
        "agent_id": "BTC_15M",
        "group_id": "BTC-15m-test",
        "take_profit_price_cents": 60,
        "stop_loss_price_cents": 40,
        "window_resolution_id": "win_test",
        "exit_policy_id": "exit_test",
        "risk_tier": "A",
        "max_hold_seconds": 600,
        "confidence": 0.5,
        "time_to_expiry_seconds": 600.0,
        "p_selected": 0.95,
    }
    defaults.update(overrides)
    return OrderIntent(**defaults)


def make_state(**overrides) -> SimpleNamespace:
    defaults = {
        "book_initialized": True,
        "executable": True,
        "book_age_s": 0.0,
        "book_updated_ts": time.time(),
        "last_book_update_ts": time.time(),
        "last_rest_update_ts": time.time(),
        "mid_cents": 50.0,
        "best_bid_cents": 49,
        "best_ask_cents": 51,
        "best_bid_size": 1,
        "best_ask_size": 1,
        "best_no_bid_cents": None,
        "best_no_ask_cents": None,
        "depth_10c": 100,
        "yes_depth": 100,
        "no_depth": 100,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_store_with_state(state):
    return MagicMock(
        get=Mock(return_value=state),
        _states={},
        is_market_entry_ready=Mock(return_value=(True, "")),
        is_market_execution_ready=Mock(return_value=(True, "")),
    )


@pytest.fixture
def router_mocks(monkeypatch):
    """Patch the router so planning is deterministic and no real services are hit."""
    monkeypatch.setattr(order_router, "BOOK_FRESHNESS_AVAILABLE", False)
    monkeypatch.setattr(
        order_router, "_apply_risk_based_order_sizing", lambda intent, bankroll_usd=None: 1
    )
    monkeypatch.setattr(
        order_router, "_apply_depth_based_order_sizing", lambda intent, state=None: 1
    )
    monkeypatch.setattr(
        order_router, "get_venue_gate",
        lambda: MagicMock(mode=TradingMode.LIVE, live_enabled=True),
    )
    monkeypatch.setattr(
        "merid.risk.profiles.risk_envelope_service.get_risk_envelope_service",
        lambda: MagicMock(
            get_config=Mock(
                return_value=MagicMock(max_single_order_notional_usd=10.0)
            )
        ),
    )
    monkeypatch.setattr(order_router, "_is_authorized_caller", lambda caller: True)
    monkeypatch.setattr(order_router, "_is_kalshi_15m_crypto_agent", lambda agent: True)
    monkeypatch.setattr(order_router, "_check_global_rate_limit", lambda intent: None)
    monkeypatch.setattr(order_router, "_check_intent_risk", lambda intent: None)
    monkeypatch.setattr(order_router, "_resolve_max_slippage_cents", lambda: 5)
    monkeypatch.setattr(
        order_router,
        "_get_strategy_policy",
        lambda intent: {"min_edge": 0.02, "min_confidence": 0.50},
    )
    monkeypatch.setattr(
        "merid.risk.profiles.crypto_15m_profile.get_active_profile",
        lambda: MagicMock(
            profile=MagicMock(
                guardrails_max_snapshot_age_ms=5000,
                profile_name="",
                agent_max_yes_position=100,
                agent_max_no_position=100,
            )
        ),
    )
    monkeypatch.setattr(
        "merid.risk.unified_risk_manager.get_unified_risk_manager",
        lambda: MagicMock(
            check_order=Mock(return_value=(True, "")),
            calibrate_from_balance=Mock(),
            record_fill=Mock(),
            release=Mock(),
            record_pnl=Mock(),
            get_loss_adjusted_size_scale=Mock(return_value=1.0),
        ),
    )

    # Keep planning tests isolated from production service initialization.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        lambda: MagicMock(
            is_reconciliation_halted=Mock(return_value=False),
            get_position=Mock(return_value=None),
            get_all_positions=Mock(return_value={}),
        ),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.rate_limiter.get_rate_limiter",
        lambda: MagicMock(acquire=AsyncMock(return_value=True)),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.monitoring.get_monitor",
        lambda: MagicMock(update_order_metrics=AsyncMock()),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.bankroll_service_v2.get_bankroll_service",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(order_router, "TRADING_SCOPE_AVAILABLE", False)
    monkeypatch.setattr(order_router, "LIQUIDITY_FALLBACK_AVAILABLE", False)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_intent_contract.persist_order_decision",
        Mock(),
    )


@pytest.fixture
def fresh_state(router_mocks, monkeypatch):
    state = make_state()
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        lambda: _fake_store_with_state(state),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.canonical_portfolio.get_canonical_portfolio_store",
        lambda: MagicMock(current=Mock(return_value=None)),
    )
    return state


@pytest.fixture
def route_live_env(fresh_state, monkeypatch):
    """Patch the full live submission environment for _route_live tests."""
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_cache.get_position_cache",
        lambda: MagicMock(
            get_position=Mock(return_value=None),
            get_all_positions=Mock(return_value={}),
            get_positions_by_asset=Mock(return_value=[]),
            get_total_notional_exposure=Mock(return_value=0.0),
            update_position=Mock(),
            register_tp_targets=Mock(),
            register_order_id_mapping=Mock(),
        ),
    )

    # Replace the slot allocator singleton factory with a deterministic stub.
    _stub_allocator = MagicMock()
    _stub_allocator.request_allocation = Mock(return_value=(True, "", "slot_1"))
    _stub_allocator.can_allocate = Mock(return_value=(True, ""))
    _stub_allocator.release_slot = Mock(return_value=True)
    _stub_allocator.release_slot_by_ticker = Mock(return_value=True)
    _stub_allocator.get_total_exposure = Mock(return_value=0.0)
    _stub_allocator.get_available_exposure = Mock(return_value=1000.0)
    _stub_allocator.get_summary = Mock(return_value=MagicMock())

    def _fake_global_slot_allocator():
        return _stub_allocator

    monkeypatch.setattr(
        "merid.risk.global_slot_allocator.get_global_slot_allocator",
        _fake_global_slot_allocator,
    )

    monkeypatch.setattr(
        "merid.event_venues.kalshi.dynamic_risk.get_dynamic_risk_engine",
        lambda: MagicMock(can_trade_now=Mock(return_value=(True, ""))),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.position_sanity_checker.get_position_sanity_checker",
        lambda: MagicMock(
            register_order_intent=Mock(),
            apply_fill=Mock(return_value=(True, "")),
        ),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
        lambda: MagicMock(record_intent=Mock(), record_fill=Mock()),
    )
    monkeypatch.setattr(
        "merid.risk.unified_risk_manager.get_unified_risk_manager",
        lambda: MagicMock(
            check_order=Mock(return_value=(True, "")),
            calibrate_from_balance=Mock(),
            record_fill=Mock(),
            release=Mock(),
        ),
    )
    monkeypatch.setattr(
        "merid.risk.profiles.crypto_15m_profile.get_active_profile",
        lambda: MagicMock(
            profile=MagicMock(
                agent_max_yes_position=100,
                agent_max_no_position=100,
                guardrails_max_snapshot_age_ms=5000,
                profile_name="",
            )
        ),
    )
    monkeypatch.setattr(
        "merid.risk.kill_switches.risk_controller",
        MagicMock(can_trade=Mock(return_value=True), record_pnl=Mock()),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_deduplication.get_order_cache",
        lambda: MagicMock(
            get=Mock(return_value=None),
            set=Mock(),
            get_metrics=Mock(),
            mark_completed=Mock(),
        ),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_gate.get_pre_trade_gate",
        lambda: MagicMock(
            mark_submitted=Mock(),
            mark_filled=Mock(),
            mark_rejected=Mock(),
        ),
    )


# ---------------------------------------------------------------------------
# _prepare_order_for_gate unit invariants
# ---------------------------------------------------------------------------


def test_plan_before_reservation_no_gate_leak(monkeypatch, fresh_state):
    """A planning rejection (crossed book) must never reserve a pre-trade gate record."""
    fresh_state.best_bid_cents = 60
    fresh_state.best_ask_cents = 40

    monkeypatch.setattr(order_router, "_run_pre_trade_gate", Mock(return_value=None))

    intent = make_intent()
    rejection, state = _prepare_order_for_gate(
        intent, TradingMode.LIVE, time.monotonic()
    )

    assert rejection is not None
    assert "crossed_book" in rejection.reason
    assert state is None
    assert order_router._run_pre_trade_gate.call_count == 0


def test_no_duality_inversion(fresh_state):
    """NO-side derived prices that cross must be rejected at planning time."""
    # YES bid=70, ask=60  =>  NO bid = 100-60 = 40, NO ask = 100-70 = 30
    # The NO book is crossed (bid 40 > ask 30).
    fresh_state.best_bid_cents = 70
    fresh_state.best_ask_cents = 60

    intent = make_intent(side="BUY_NO", action="buy", price_cents=45)
    rejection, state = _prepare_order_for_gate(
        intent, TradingMode.LIVE, time.monotonic()
    )

    assert rejection is not None
    assert "crossed_book" in rejection.reason
    assert state is None


def test_taker_buy_uses_taker_economics(fresh_state):
    """A marketable buy intent resolves to taker economics and IOC."""
    intent = make_intent(execution_mode="taker", aggressiveness=1.0, post_only=False)

    result, state = _prepare_order_for_gate(
        intent, TradingMode.LIVE, time.monotonic()
    )

    assert result is None
    assert state is fresh_state
    assert intent.liquidity_role == "taker"
    assert intent.post_only is False
    assert intent.aggressiveness == 1.0
    assert intent.order_type == "limit"
    assert intent.time_in_force == "IOC"
    # The taker repricer now caps the limit at mid + max_slippage (50 + 5 = 55)
    # so the order can absorb small ask moves without being rejected before it
    # reaches the exchange.
    assert intent.price_cents == 55
    assert intent.fee_type == "taker"
    assert intent.estimated_fee_cents is not None


def test_maker_buy_uses_maker_economics(fresh_state):
    """A resting buy intent resolves to maker economics and GTC."""
    intent = make_intent(aggressiveness=0.0, post_only=True)

    result, state = _prepare_order_for_gate(
        intent, TradingMode.LIVE, time.monotonic()
    )

    assert result is None
    assert state is fresh_state
    assert intent.liquidity_role == "maker"
    assert intent.post_only is True
    assert intent.aggressiveness == 0.0
    assert intent.order_type == "limit"
    assert intent.time_in_force == "GTC"
    assert intent.price_cents <= fresh_state.best_ask_cents
    assert intent.fee_type == "maker"
    assert intent.estimated_fee_cents is not None


# ---------------------------------------------------------------------------
# _route_live plan_done invariants
# ---------------------------------------------------------------------------


def _fake_port(captured_orders):
    """Minimal KalshiExecutionPort stand-in for _route_live tests."""
    class _FakePort:
        async def connect(self):
            pass

        async def get_market(self, ticker):
            return MagicMock(
                success=True,
                market=MagicMock(
                    active=True,
                    resolved=False,
                    best_bid=49,
                    best_ask=51,
                    volume=1000,
                    open_interest=1000,
                ),
            )

        async def get_balance(self):
            return MagicMock(success=True, available_usd=Decimal("1000"))

        async def create_order(self, request):
            captured_orders.append(request)
            return MagicMock(
                success=True,
                status="unfilled_ioc",
                order_id="test_order_id",
                client_order_id=request.client_order_id,
                filled_size=Decimal("0"),
                remaining_size=Decimal(str(request.size)),
                price_cents=request.price_cents,
            )

    return _FakePort()


def _fake_client(captured_orders):
    """Build a fake Kalshi client that records submitted VenueOrders."""
    class FakeOpResult:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    class _FakeClient:
        connect = AsyncMock()
        get_market = AsyncMock(
            return_value=FakeOpResult(
                success=True,
                value=MagicMock(
                    best_bid=49, best_ask=51, volume=100, open_interest=100
                ),
            )
        )
        _request_with_resilience = AsyncMock(
            return_value=FakeOpResult(success=False, data=None)
        )
        get_order_by_client_id_result = AsyncMock(
            return_value=FakeOpResult(success=False, data=None)
        )
        get_balance_result = AsyncMock(
            return_value=FakeOpResult(success=True, data={"balance": Decimal("1000")})
        )

        async def place_order_result(self, order, **kwargs):
            captured_orders.append(order)
            placed = MagicMock(
                size=order.size,
                filled_size=0,
                remaining_size=order.size,
                price=order.price,
                order_id="test_order_id",
            )
            return FakeOpResult(success=True, error=None, data=placed)

    return _FakeClient()


@pytest.mark.asyncio
async def test_strict_snapshot_identity(route_live_env, monkeypatch, fresh_state):
    """The same BookSnapshot used for planning is the one used for submission."""
    captured_states = []

    def _check_liquidity(intent, state):
        captured_states.append(state)
        return None

    def _check_price(intent, state):
        captured_states.append(state)
        return None

    monkeypatch.setattr(order_router, "_check_market_liquidity", _check_liquidity)
    monkeypatch.setattr(order_router, "_validate_price_against_orderbook", _check_price)
    monkeypatch.setattr(
        "merid.event_venues.kalshi.client.get_kalshi_client",
        lambda: _fake_client([]),
    )
    monkeypatch.setattr(
        "merid.event_venues.kalshi.port.get_kalshi_execution_port",
        lambda: _fake_port([]),
    )

    intent = make_intent(execution_mode="taker", aggressiveness=1.0)
    prep_rejection, prepared_state = _prepare_order_for_gate(
        intent, TradingMode.LIVE, time.monotonic()
    )
    assert prep_rejection is None
    assert prepared_state is fresh_state

    await _route_live(
        intent, TradingMode.LIVE, time.monotonic(),
        prepared_state=prepared_state, plan_done=True,
    )

    assert any(s is fresh_state for s in captured_states)


@pytest.mark.asyncio
async def test_no_post_plan_mutation(route_live_env, monkeypatch, fresh_state):
    """Submission must not mutate the execution plan finalized by _prepare."""
    captured_orders = []

    monkeypatch.setattr(
        "merid.event_venues.kalshi.port.get_kalshi_execution_port",
        lambda: _fake_port(captured_orders),
    )

    intent = make_intent(execution_mode="taker", aggressiveness=1.0)
    t0 = time.monotonic()
    prep_rejection, prepared_state = _prepare_order_for_gate(
        intent, TradingMode.LIVE, t0
    )
    assert prep_rejection is None

    snapshot = {
        "price_cents": intent.price_cents,
        "liquidity_role": intent.liquidity_role,
        "post_only": intent.post_only,
        "order_type": intent.order_type,
        "time_in_force": intent.time_in_force,
        "estimated_fee_cents": intent.estimated_fee_cents,
    }

    await _route_live(
        intent, TradingMode.LIVE, t0,
        prepared_state=prepared_state, plan_done=True,
    )

    assert len(captured_orders) == 1
    request = captured_orders[0]

    assert request.price_cents == snapshot["price_cents"]
    assert request.order_type == snapshot["order_type"]
    assert request.time_in_force == snapshot["time_in_force"]
    assert request.size == Decimal(intent.count)

    assert intent.price_cents == snapshot["price_cents"]
    assert intent.liquidity_role == snapshot["liquidity_role"]
    assert intent.post_only == snapshot["post_only"]
    assert intent.order_type == snapshot["order_type"]
    assert intent.time_in_force == snapshot["time_in_force"]
    assert intent.estimated_fee_cents == snapshot["estimated_fee_cents"]


# ---------------------------------------------------------------------------
# End-to-end routing invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_order_async_plans_before_gate(router_mocks, monkeypatch, fresh_state):
    """route_order_async runs _prepare before _run_pre_trade_gate."""
    gate_calls = []
    live_calls = []

    def _fake_gate(intent, mode, t0):
        gate_calls.append((intent, mode))
        return None

    async def _fake_route_live(*args, **kwargs):
        live_calls.append(args)
        return MagicMock(status="submitted_live", mode=args[1])

    monkeypatch.setattr(order_router, "_run_pre_trade_gate", _fake_gate)
    monkeypatch.setattr(order_router, "_route_live", _fake_route_live)

    intent = make_intent(execution_mode="taker", aggressiveness=1.0)
    result = await route_order_async(intent)

    assert result.status == "submitted_live"
    assert len(gate_calls) == 1
    assert len(live_calls) == 1
    # _prepare lifts the taker limit to the slippage cap (55c) before the gate.
    assert gate_calls[0][0].price_cents == 55
    assert live_calls[0][0].price_cents == 55
