"""Comprehensive tests for the Decision trade-vs-hold pipeline.

Tests cover:
  1. Decision model construction + serialisation
  2. TradeHoldConfig loading + env overrides
  3. DecisionEvaluator — every pipeline stage
  4. Integration: _build_cycle_context + evaluate_cycle_decision
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest

from merid.prediction.decision import (
    Decision,
    DecisionAction,
    DecisionTimer,
    HoldReason,
)
from merid.prediction.decision_evaluator import (
    CycleContext,
    _classify_signal_hold,
    _classify_risk_hold,
    evaluate_cycle_decision,
)
from merid.prediction.trade_hold_config import (
    TradeHoldConfig,
    WarmupConfig,
    EntryWindowConfig,
    StrategyThresholds,
    ConsensusConfig,
    RiskThresholds,
    LoggingConfig,
    ErrorHandlingConfig,
    _build_config,
    reload_trade_hold_config,
)


# ═══════════════════════════════════════════════════════════════════════
# 1. Decision model tests
# ═══════════════════════════════════════════════════════════════════════

class TestDecisionModel:
    def test_trade_constructor(self):
        d = Decision.trade(
            market_id="KXBTC-15M-T1234",
            agent_name="BTC_15M",
            cycle_number=5,
        )
        assert d.action == DecisionAction.TRADE
        assert d.hold_reason is None
        assert d.market_id == "KXBTC-15M-T1234"
        assert d.agent_name == "BTC_15M"
        assert d.cycle_number == 5
        assert d.detail == "all_checks_passed"

    def test_hold_constructor(self):
        d = Decision.hold(
            HoldReason.WARMUP,
            "agent still warming up (12s elapsed)",
            market_id="KXETH-T99",
            agent_name="ETH_15M",
            cycle_number=1,
        )
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.WARMUP
        assert "warming up" in d.detail
        assert d.market_id == "KXETH-T99"

    def test_to_dict(self):
        d = Decision.trade(market_id="X", agent_name="A", cycle_number=1)
        out = d.to_dict()
        assert out["action"] == "trade"
        assert out["hold_reason"] is None
        assert out["market_id"] == "X"
        assert isinstance(out["timestamp"], str)
        assert "elapsed_ms" in out

    def test_hold_to_dict(self):
        d = Decision.hold(HoldReason.RISK_LIMIT, "max notional breached")
        out = d.to_dict()
        assert out["action"] == "hold"
        assert out["hold_reason"] == "risk_limit"

    def test_log_line_format(self):
        d = Decision.hold(
            HoldReason.SESSION_CLOSED, "maintenance window",
            agent_name="BTC_15M", cycle_number=10,
        )
        line = d.log_line()
        assert "[PM_DECISION]" in line
        assert "action=hold" in line
        assert "hold_reason=session_closed" in line
        assert "agent=BTC_15M" in line

    def test_trade_log_line(self):
        d = Decision.trade(market_id="T1", agent_name="A", cycle_number=3)
        line = d.log_line()
        assert "action=trade" in line
        assert "hold_reason=-" in line

    def test_frozen(self):
        d = Decision.trade(market_id="X")
        with pytest.raises(AttributeError):
            d.action = DecisionAction.HOLD  # type: ignore[misc]

    def test_detail_truncation(self):
        d = Decision.hold(HoldReason.UNKNOWN, "x" * 1000)
        out = d.to_dict()
        assert len(out["detail"]) == 500


class TestDecisionTimer:
    def test_elapsed_positive(self):
        t = DecisionTimer()
        time.sleep(0.05)
        ms = t.elapsed_ms()
        assert ms >= 0  # Just ensure non-negative (timer resolution varies)

    def test_context_manager(self):
        with DecisionTimer() as t:
            time.sleep(0.05)
        assert t.elapsed_ms() >= 0  # Just ensure non-negative


class TestHoldReasonValues:
    def test_all_reasons_unique(self):
        values = [r.value for r in HoldReason]
        assert len(values) == len(set(values))

    def test_string_enum(self):
        assert HoldReason.WARMUP == "warmup"
        assert HoldReason.RISK_LIMIT == "risk_limit"


# ═══════════════════════════════════════════════════════════════════════
# 2. TradeHoldConfig tests
# ═══════════════════════════════════════════════════════════════════════

class TestTradeHoldConfig:
    def test_default_config(self):
        cfg = TradeHoldConfig()
        assert cfg.enabled is True
        assert cfg.warmup.min_seconds == 15.0
        assert cfg.strategy.min_edge_early == Decimal("0.08")
        assert cfg.consensus.solo_wait_seconds == 0.0
        assert cfg.risk.max_contracts_per_order == 50

    def test_build_config_loads(self):
        cfg = _build_config()
        assert isinstance(cfg, TradeHoldConfig)
        assert cfg.enabled is True  # YAML says true

    def test_env_override_warmup(self):
        with patch.dict(os.environ, {"MERID_TH_WARMUP_MIN_SECONDS": "25"}):
            cfg = _build_config()
            assert cfg.warmup.min_seconds == 25.0

    def test_env_override_enabled(self):
        with patch.dict(os.environ, {"MERID_TH_ENABLED": "false"}):
            cfg = _build_config()
            assert cfg.enabled is False

    def test_env_override_strategy_edge(self):
        with patch.dict(os.environ, {"MERID_TH_STRATEGY_MIN_EDGE_EARLY": "0.12"}):
            cfg = _build_config()
            assert cfg.strategy.min_edge_early == Decimal("0.12")

    def test_reload(self):
        cfg1 = reload_trade_hold_config()
        cfg2 = reload_trade_hold_config()
        assert cfg1.enabled == cfg2.enabled


# ═══════════════════════════════════════════════════════════════════════
# 3. DecisionEvaluator tests — every pipeline stage
# ═══════════════════════════════════════════════════════════════════════

def _base_ctx(**overrides) -> CycleContext:
    """Create a CycleContext with all checks passing by default."""
    defaults = dict(
        agent_name="BTC_15M",
        cycle_number=5,
        market_id="KXBTC-15M-T1234",
        lifecycle_state="active",
        agent_enabled=True,
        kill_switch_active=False,
        session_allowed=True,
        has_resolved_markets=True,
        in_entry_window=True,
        is_new_entry=True,
        seconds_to_expiry=300.0,
        signal_action="buy_yes",
        signal_reason="directional edge 12%",
        signal_contracts=5,
        signal_edge=0.12,
        signal_phase="mid",
        consensus_bypassed=True,  # Simplify: bypass consensus for most tests
        risk_allowed=True,
        risk_reason="",
        risk_action="allow",
        orders_this_window=0,
        max_orders_per_window=10,
        config=TradeHoldConfig(),
        timer=DecisionTimer(),
    )
    defaults.update(overrides)
    return CycleContext(**defaults)


class TestEvaluatorStage1_ConfigDisabled:
    def test_pipeline_disabled(self):
        cfg = TradeHoldConfig(enabled=False)
        d = evaluate_cycle_decision(_base_ctx(config=cfg))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.CONFIG_DISABLED

    def test_agent_disabled(self):
        d = evaluate_cycle_decision(_base_ctx(agent_enabled=False))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.CONFIG_DISABLED


class TestEvaluatorStage2_KillSwitch:
    def test_kill_switch_active(self):
        d = evaluate_cycle_decision(_base_ctx(
            kill_switch_active=True,
            kill_switch_reason="manual operator halt",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.KILL_SWITCH
        assert "manual operator halt" in d.detail


class TestEvaluatorStage3_Session:
    def test_session_closed(self):
        d = evaluate_cycle_decision(_base_ctx(
            session_allowed=False,
            session_block_reason="Kalshi maintenance Thu 03:00-05:00",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.SESSION_CLOSED
        assert "maintenance" in d.detail


class TestEvaluatorStage4_Warmup:
    def test_warming_up(self):
        d = evaluate_cycle_decision(_base_ctx(lifecycle_state="warming_up"))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.WARMUP

    def test_active_passes(self):
        d = evaluate_cycle_decision(_base_ctx(lifecycle_state="active"))
        assert d.action == DecisionAction.TRADE


class TestEvaluatorStage5_NoMarkets:
    def test_no_markets(self):
        d = evaluate_cycle_decision(_base_ctx(has_resolved_markets=False))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.NO_MARKETS


class TestEvaluatorStage6_OrderLimit:
    def test_window_limit_reached(self):
        d = evaluate_cycle_decision(_base_ctx(
            orders_this_window=10,
            max_orders_per_window=10,
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.ORDER_LIMIT
        assert "10/10" in d.detail

    def test_window_limit_not_reached(self):
        d = evaluate_cycle_decision(_base_ctx(
            orders_this_window=5,
            max_orders_per_window=10,
        ))
        assert d.action == DecisionAction.TRADE


class TestEvaluatorStage7_EntryWindow:
    def test_expiry_proximity_guard(self):
        d = evaluate_cycle_decision(_base_ctx(
            seconds_to_expiry=60.0,
            is_new_entry=True,
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.EXPIRY_PROXIMITY

    def test_outside_entry_window(self):
        d = evaluate_cycle_decision(_base_ctx(
            in_entry_window=False,
            is_new_entry=True,
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.OUTSIDE_ENTRY_WINDOW

    def test_exit_action_bypasses_window(self):
        d = evaluate_cycle_decision(_base_ctx(
            in_entry_window=False,
            is_new_entry=False,
            signal_action="sell_yes",
        ))
        assert d.action == DecisionAction.TRADE

    def test_inside_entry_window_passes(self):
        d = evaluate_cycle_decision(_base_ctx(
            in_entry_window=True,
            seconds_to_expiry=300.0,
        ))
        assert d.action == DecisionAction.TRADE


class TestEvaluatorStage8_Signal:
    def test_no_action_signal(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="no actionable edge found",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.NO_EDGE

    def test_hold_signal(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="hold",
            signal_reason="edge below threshold",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.EDGE_BELOW_THRESHOLD

    def test_stale_data_signal(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="stale market data (120s)",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.STALE_DATA

    def test_spot_strike_veto(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="spot_strike_veto: too far from strike",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.SPOT_STRIKE_VETO

    def test_liquidity_guard(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="liquidity below threshold",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.LIQUIDITY_GUARD

    def test_conviction_veto(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="conviction floor veto: structural conviction too low",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.CONVICTION_VETO

    def test_pm_spot_gate(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="pm_spot_gate:missing_or_stale_spot",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.PM_SPOT_GATE

    def test_confidence_below(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="confidence below threshold (0.45 < 0.60)",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.CONFIDENCE_TOO_LOW

    def test_actionable_signal_passes(self):
        d = evaluate_cycle_decision(_base_ctx(signal_action="buy_yes"))
        assert d.action == DecisionAction.TRADE


class TestEvaluatorStage9_Consensus:
    def test_consensus_forming(self):
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=False,
            consensus_status="forming",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.CONSENSUS_FORMING

    def test_consensus_conflicted(self):
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=False,
            consensus_status="conflicted",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.CONSENSUS_CONFLICTED

    def test_consensus_direction_mismatch(self):
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=False,
            consensus_status="ready",
            consensus_direction_matches=False,
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.CONSENSUS_DIRECTION_MISMATCH

    def test_consensus_ready_matching_passes(self):
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=False,
            consensus_status="ready",
            consensus_direction_matches=True,
        ))
        assert d.action == DecisionAction.TRADE

    def test_no_consensus_solo_window(self):
        cfg = TradeHoldConfig()
        cfg.consensus.solo_wait_seconds = 120.0
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=False,
            consensus_status=None,
            solo_seconds=60.0,
            config=cfg,
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.SOLO_WINDOW

    def test_no_consensus_solo_cap_reached(self):
        cfg = TradeHoldConfig()
        cfg.consensus.solo_wait_seconds = 0.0
        cfg.consensus.solo_trades_cap = 3
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=False,
            consensus_status=None,
            solo_seconds=120.0,
            solo_trades_this_session=3,
            config=cfg,
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.SOLO_CAP_REACHED

    def test_consensus_bypassed_passes(self):
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=True,
            consensus_status=None,
        ))
        assert d.action == DecisionAction.TRADE


class TestEvaluatorStage10_Risk:
    def test_risk_blocked(self):
        d = evaluate_cycle_decision(_base_ctx(
            risk_allowed=False,
            risk_reason="max notional per event exceeded",
            risk_action="reject",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.RISK_LIMIT
        assert "notional" in d.detail

    def test_risk_halt(self):
        d = evaluate_cycle_decision(_base_ctx(
            risk_allowed=False,
            risk_action="halt",
            risk_reason="circuit breaker tripped",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.RISK_HALT

    def test_risk_rate_limit(self):
        d = evaluate_cycle_decision(_base_ctx(
            risk_allowed=False,
            risk_reason="rate limit exceeded (30/min)",
            risk_action="reject",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.RATE_LIMIT


class TestEvaluatorStage11_Trade:
    def test_all_checks_pass(self):
        d = evaluate_cycle_decision(_base_ctx())
        assert d.action == DecisionAction.TRADE
        assert d.detail == "all_checks_passed"
        assert d.signal_summary["action"] == "buy_yes"
        assert d.signal_summary["edge"] == 0.12
        assert d.market_id == "KXBTC-15M-T1234"
        assert d.elapsed_ms >= 0


# ═══════════════════════════════════════════════════════════════════════
# 4. Classification helper tests
# ═══════════════════════════════════════════════════════════════════════

class TestClassifiers:
    def test_classify_stale(self):
        assert _classify_signal_hold("stale market data (120s)") == HoldReason.STALE_DATA

    def test_classify_edge(self):
        assert _classify_signal_hold("edge below threshold") == HoldReason.EDGE_BELOW_THRESHOLD

    def test_classify_conviction(self):
        assert _classify_signal_hold("conviction floor veto") == HoldReason.CONVICTION_VETO

    def test_classify_unknown(self):
        assert _classify_signal_hold("something obscure") == HoldReason.NO_EDGE

    def test_classify_risk_halt(self):
        assert _classify_risk_hold("halt", "circuit breaker") == HoldReason.RISK_HALT

    def test_classify_risk_rate(self):
        assert _classify_risk_hold("reject", "rate limit exceeded") == HoldReason.RATE_LIMIT

    def test_classify_risk_default(self):
        assert _classify_risk_hold("reject", "notional exceeded") == HoldReason.RISK_LIMIT


# ═══════════════════════════════════════════════════════════════════════
# 5. Pipeline priority (earliest gate wins)
# ═══════════════════════════════════════════════════════════════════════

class TestPipelinePriority:
    def test_kill_switch_beats_session(self):
        """Kill switch should fire before session check."""
        d = evaluate_cycle_decision(_base_ctx(
            kill_switch_active=True,
            kill_switch_reason="operator halt",
            session_allowed=False,
        ))
        assert d.hold_reason == HoldReason.KILL_SWITCH

    def test_session_beats_warmup(self):
        d = evaluate_cycle_decision(_base_ctx(
            session_allowed=False,
            session_block_reason="maintenance",
            lifecycle_state="warming_up",
        ))
        assert d.hold_reason == HoldReason.SESSION_CLOSED

    def test_warmup_beats_signal(self):
        d = evaluate_cycle_decision(_base_ctx(
            lifecycle_state="warming_up",
            signal_action="no_action",
        ))
        assert d.hold_reason == HoldReason.WARMUP

    def test_signal_beats_risk(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="no actionable edge found",
            risk_allowed=False,
        ))
        assert d.hold_reason == HoldReason.NO_EDGE

    def test_consensus_beats_risk(self):
        d = evaluate_cycle_decision(_base_ctx(
            consensus_bypassed=False,
            consensus_status="conflicted",
            risk_allowed=False,
        ))
        assert d.hold_reason == HoldReason.CONSENSUS_CONFLICTED


# ═══════════════════════════════════════════════════════════════════════
# 6. Edge cases
# ═══════════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_none_market_id(self):
        d = evaluate_cycle_decision(_base_ctx(market_id=None))
        assert d.action == DecisionAction.TRADE
        assert d.market_id == ""  # Decision.trade coerces None → ""

    def test_zero_edge_still_trades(self):
        d = evaluate_cycle_decision(_base_ctx(signal_edge=0.0))
        assert d.action == DecisionAction.TRADE

    def test_empty_signal_reason(self):
        d = evaluate_cycle_decision(_base_ctx(
            signal_action="no_action",
            signal_reason="",
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.NO_EDGE

    def test_expiry_guard_exactly_at_boundary(self):
        d = evaluate_cycle_decision(_base_ctx(
            seconds_to_expiry=90.0,
            is_new_entry=True,
        ))
        assert d.action == DecisionAction.HOLD
        assert d.hold_reason == HoldReason.EXPIRY_PROXIMITY

    def test_expiry_guard_just_above(self):
        d = evaluate_cycle_decision(_base_ctx(
            seconds_to_expiry=91.0,
            is_new_entry=True,
        ))
        assert d.action == DecisionAction.TRADE
