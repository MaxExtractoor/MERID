"""Shadow lifecycle test: decision -> ledger -> paper order -> fill -> exit.

This is the canonical one-contract paper/shadow pass for the order decision
ledger.  It exercises the same code paths that a canary live run uses, but in
``TradingMode.PAPER`` with an in-memory ledger.  It asserts that:

1. ``compute_trade_decision`` (or a manually built ``TradeDecision``) mints a
   durable ``decision_id`` that appears in the ledger ``start`` event.
2. ``OrderIntent`` carries the same ``decision_id``, ``config_hash`` and
   ``build_sha``.
3. ``route_order_async`` appends ``submission`` and ``fill`` events.
4. An exit order appends an ``exit`` event to the parent decision with
   ``realized_pnl_cents``.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest


@pytest.fixture
def env_for_shadow(monkeypatch):
    """Force paper mode and one-contract canary limits for the shadow pass."""
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "paper")
    monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "false")
    monkeypatch.setenv("MERID_ORDER_DECISION_LEDGER_ENABLED", "1")
    monkeypatch.setenv("MERID_MAX_CONTRACTS_PER_ORDER", "1")
    monkeypatch.setenv("MERID_FIXED_EXPOSURE_CAP_USD", "0.90")
    monkeypatch.setenv("MERID_MAX_EXPOSURE_USD", "0.90")
    monkeypatch.setenv("KALSHI_TRADER_MAX_POSITION", "1")
    monkeypatch.setenv("MERID_LIVE_CANARY", "1")
    monkeypatch.setenv("MERID_CFB_RTI_ADAPTER", "0")
    monkeypatch.setenv("MERID_REQUIRE_EXIT_PARENTAGE", "0")
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    # pytest-asyncio is not in the router caller allowlist; pretend the test
    # module itself is the caller so the paper path can run.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._get_caller_module",
        lambda: "tests.test_order_decision_shadow_lifecycle",
    )
    # The shadow harness is not connected to live market data; bypass the
    # round-trip net-of-cost gate so the paper execution path can be exercised.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.order_router._round_trip_net_of_cost_gate",
        lambda intent: None,
    )
    # Bypass the market-state entry-readiness gate (no live WS orderbook).
    monkeypatch.setattr(
        "merid.event_venues.kalshi.market_state.KalshiMarketStateStore.is_market_entry_ready",
        lambda self, ticker: (True, ""),
    )
    # Provide a fake bankroll so the risk envelope does not fail-closed.
    monkeypatch.setattr(
        "merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync",
        lambda *a, **k: 100.0,
    )


@pytest.fixture
def shadow_ledger(tmp_path, env_for_shadow):
    """Isolated ``OrderDecisionLedger`` for one shadow pass."""
    from merid.execution.order_decision_ledger import (
        OrderDecisionLedger,
        reset_order_decision_ledger,
    )

    return reset_order_decision_ledger(log_dir=tmp_path)


def _make_trade_decision(
    *,
    decision_id: str,
    run_id: str,
    ticker: str,
    asset: str,
    side: str,
    price_cents: int,
    approved_size_cc: int = 100,
    config_hash: str = "cfg_shadow",
    build_sha: str = "sha_shadow",
) -> "TradeDecision":
    """Build a minimal, positive-EV ``TradeDecision`` for the shadow pass."""
    from merid.prediction.trade_decision import TradeDecision

    price_dollars = Decimal(str(price_cents)) / Decimal("100")
    if side == "no":
        p_yes = Decimal("0.3769")
        p_no = Decimal("0.6231")
        p_selected = p_no
    else:
        p_yes = Decimal("0.6231")
        p_no = Decimal("0.3769")
        p_selected = p_yes

    return TradeDecision(
        run_id=run_id,
        decision_id=decision_id,
        ticker=ticker,
        asset=asset,
        timestamp_utc=datetime.now(timezone.utc),
        p_yes_raw=p_yes,
        p_yes_calibrated=p_yes,
        p_yes_uncertainty=Decimal("0.02"),
        p_no_calibrated=p_no,
        p_selected=p_selected,
        p_opposite=p_yes if side == "no" else p_no,
        selected_outcome=side,
        selected_action="buy",
        selected_outcome_price=price_dollars,
        approved_size_cc=Decimal(str(approved_size_cc)),
        ev_gate_allowed=True,
        ev_gate_result={
            "net_ev": Decimal("0.2262"),
            "gross_ev": Decimal("0.3462"),
            "expected_entry_fee": Decimal("0.0400"),
            "expected_exit_cost": Decimal("0.0400"),
            "tail_risk": Decimal("0.7538"),
            "ev_to_tail_ratio": Decimal("0.3001"),
            "min_dollar_ev": Decimal("0"),
            "min_ev_to_tail_ratio": Decimal("0"),
        },
        adverse_selection_reserve=Decimal("0"),
        uncertainty_reserve=Decimal("0.02"),
        entry_fee_yes=Decimal("0.02"),
        entry_fee_no=Decimal("0.02"),
        exit_cost_reserve_yes=Decimal("0.02"),
        exit_cost_reserve_no=Decimal("0.02"),
        confidence=Decimal("0.85"),
        confidence_valid=True,
        confidence_source="shadow_test",
        data_state="healthy",
        regime_label="both_sides",
        settlement_reference="cfb_rti_live",
        config_hash=config_hash,
        build_sha=build_sha,
    )


def _start_ledger_record(ledger, decision: "TradeDecision") -> None:
    from merid.execution.order_decision_ledger import (
        build_order_decision_record_from_trade_decision,
    )

    record = build_order_decision_record_from_trade_decision(
        decision,
        ev_gate_result=decision.ev_gate_result,
        build_sha=decision.build_sha,
    )
    ledger.start(record)


def _build_intent(
    *,
    decision: "TradeDecision",
    price_cents: int,
    kalshi_side: str,
    mode,
    entry_or_exit: str = "entry",
    pre_position_fp: int = 0,
    expected_post_position_fp: int = 100,
    parent_decision_id: str | None = None,
    parent_entry_intent_id: str | None = None,
    parent_entry_fill_id: str | None = None,
) -> "OrderIntent":
    from merid.event_venues.kalshi.order_router import OrderIntent

    return OrderIntent(
        ticker=decision.ticker,
        price_cents=price_cents,
        count=1,
        count_fp=Decimal("1"),
        kalshi_side=kalshi_side,
        mode=mode,
        order_type="limit",
        time_in_force="ioc",
        decision_id=decision.decision_id,
        run_id=decision.run_id,
        process_id="12345",
        reason="shadow_test",
        rationale="shadow lifecycle validation",
        source="merid.prediction.agent_grid_15m",
        agent_id=f"{decision.asset}_15M",
        session_id="test_session",
        config_hash=decision.config_hash,
        build_sha=decision.build_sha,
        confidence=0.85,
        confidence_valid=True,
        confidence_source="shadow_test",
        settlement_reference="cfb_rti_live",
        data_state="healthy",
        regime_label="both_sides",
        p_yes=float(decision.p_yes_calibrated),
        p_no=float(decision.p_no_calibrated),
        p_selected=float(decision.p_selected),
        edge_pct=0.10,
        aggressiveness=1.0,
        policy_mode="AGGRESSIVE_CONVICTION",
        gross_edge=0.10,
        net_edge_pretrade=0.05,
        ev_net_cents=10.0,
        all_in_cost_cents=2.0,
        selected_outcome_price_cents=price_cents,
        model_prob=float(decision.p_selected),
        min_required_edge=0.05,
        take_profit_price_cents=55,
        stop_loss_price_cents=40,
        window_resolution_id="wr_shadow",
        exit_policy_id="ep_shadow",
        risk_tier="A",
        max_hold_seconds=600,
        entry_or_exit=entry_or_exit,
        pre_position_fp=pre_position_fp,
        expected_post_position_fp=expected_post_position_fp,
        pre_position_size=pre_position_fp // 100,
        expected_post_position_size=expected_post_position_fp // 100,
        yes_bid_cents=55,
        yes_ask_cents=56,
        no_bid_cents=44,
        no_ask_cents=45,
        yes_depth=100,
        no_depth=100,
        time_to_expiry_seconds=600,
        settlement_input_price=60000.0,
        cf_rti_basis="cfb_rti_live",
        liquidity_role="taker",
        execution_mode="taker",
        parent_decision_id=parent_decision_id,
        parent_entry_intent_id=parent_entry_intent_id,
        parent_entry_fill_id=parent_entry_fill_id,
    )


@pytest.mark.asyncio
async def test_order_decision_paper_entry_and_exit_lifecycle(shadow_ledger, env_for_shadow):
    """Paper entry and exit produce a complete, auditable ledger lifecycle."""
    from merid.event_venues.kalshi.order_router import (
        OrderIntent,
        route_order_async,
    )
    from merid.execution.order_decision_ledger import get_order_decision_ledger
    from merid.prediction.trading_mode import TradingMode

    ledger = get_order_decision_ledger()

    # 1. Decision and ledger start.
    ticker = "KXBTC15M-SHADOW-TEST"
    entry_decision = _make_trade_decision(
        decision_id="shadow_btc_entry_001",
        run_id="shadow_run_001",
        ticker=ticker,
        asset="BTC",
        side="no",
        price_cents=45,
    )
    _start_ledger_record(ledger, entry_decision)

    entry_record = ledger.get(entry_decision.decision_id)
    assert entry_record is not None
    assert entry_record.config_hash == "cfg_shadow"
    assert entry_record.build_sha == "sha_shadow"
    assert entry_record.executable_price_cents == 45
    assert entry_record.selected_side == "no"

    # 2. Paper entry order.
    entry_intent = _build_intent(
        decision=entry_decision,
        price_cents=45,
        kalshi_side="BUY_NO",
        mode=TradingMode.PAPER,
    )

    entry_result = await route_order_async(entry_intent)
    assert entry_result.request_completed
    assert entry_result.has_execution
    assert entry_result.status == "filled_paper"

    # 3. Ledger must reflect submission + fill on the entry decision.
    entry_record = ledger.get(entry_decision.decision_id)
    assert entry_record.order_status in ("filled", "filled_paper", "filled_mock", "exited")
    assert entry_record.submitted_price_cents == 45
    assert entry_record.intended_qty_cc == 100
    assert entry_record.client_order_id is not None
    assert len(entry_record.fills) == 1
    assert entry_record.fills[0].qty_cc == 100
    assert entry_record.fills[0].side == "no"
    assert entry_record.fills[0].action == "buy"

    # 4. Exit decision and intent.
    exit_decision = _make_trade_decision(
        decision_id="shadow_btc_exit_001",
        run_id="shadow_run_002",
        ticker=ticker,
        asset="BTC",
        side="no",
        price_cents=44,
    )
    _start_ledger_record(ledger, exit_decision)

    exit_fill_id = entry_record.fills[0].fill_id
    exit_intent = _build_intent(
        decision=exit_decision,
        price_cents=44,
        kalshi_side="SELL_NO",
        mode=TradingMode.PAPER,
        entry_or_exit="exit",
        pre_position_fp=100,
        expected_post_position_fp=0,
        parent_decision_id=entry_decision.decision_id,
        parent_entry_intent_id=entry_intent.intent_id,
        parent_entry_fill_id=exit_fill_id,
    )

    exit_result = await route_order_async(exit_intent)
    assert exit_result.request_completed
    assert exit_result.has_execution
    assert exit_result.status == "filled_paper"

    # 5. Parent decision must carry an exit event and realized P&L.
    entry_record = ledger.get(entry_decision.decision_id)
    assert len(entry_record.exits) == 1
    assert entry_record.exits[0].exit_price_cents == 44
    assert entry_record.exits[0].qty_cc == 100
    # NO-side position: bought at 45c, sold at 44c -> 1 cent gross profit.
    assert entry_record.realized_pnl_cents == 1

    # 6. Exit decision must also have its own fill recorded.
    exit_record = ledger.get(exit_decision.decision_id)
    assert exit_record is not None
    assert exit_record.submitted_price_cents == 44
    assert len(exit_record.fills) == 1
    assert exit_record.fills[0].side == "no"
    assert exit_record.fills[0].action == "sell"


def test_order_intent_provenance_propagation(shadow_ledger):
    """OrderIntent carries the same provenance as its originating TradeDecision."""
    from merid.event_venues.kalshi.order_router import OrderIntent
    from merid.prediction.trading_mode import TradingMode

    decision = _make_trade_decision(
        decision_id="provenance_001",
        run_id="provenance_run_001",
        ticker="KXETH15M-SHADOW-TEST",
        asset="ETH",
        side="yes",
        price_cents=50,
        config_hash="cfg_provenance",
        build_sha="sha_provenance",
    )

    intent = _build_intent(
        decision=decision,
        price_cents=50,
        kalshi_side="BUY_YES",
        mode=TradingMode.PAPER,
    )

    assert intent.decision_id == decision.decision_id
    assert intent.run_id == decision.run_id
    assert intent.config_hash == decision.config_hash
    assert intent.build_sha == decision.build_sha
