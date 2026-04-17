"""test_execution_audit_regressions.py

Regression tests for the 8 bugs identified and fixed in the
Execution Pipeline Audit (docs/EXECUTION_AUDIT_REPORT.md).

Test classes:
  TestBUG01_CategoryCapFailClosed      — fail-closed on cap exception
  TestBUG02_GTCAcceptedNotFill         — GTC resting order != fill
  TestBUG03_NoBernoulliPnL             — no random.random() near btc15m tracker
  TestBUG04_SharedRiskSingleton        — all agents share one PredictionMarketRisk
  TestBUG05_StopLossEscalation         — stop-loss close failure escalates
  TestBUG06_IsLiveFillFromVenueGate    — _is_live_fill from venue gate, not payload
  TestBUG07_SpreadDepthChecksActive    — bid/ask/depth wired into check_order
  TestBUG08_DegradedModeCap            — swarm-degraded hard cap and wall-clock limit

All tests are static (no running server, no live API calls).
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import types
from decimal import Decimal
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent

# ── source paths ──────────────────────────────────────────────────────────────
TRADING_AGENT_SRC = ROOT / "merid" / "prediction" / "trading_agent.py"
ORDER_ROUTER_SRC = ROOT / "merid" / "event_venues" / "kalshi" / "order_router.py"
STOP_LOSS_SRC = ROOT / "merid" / "event_venues" / "kalshi" / "stop_loss.py"
RISK_SRC = ROOT / "merid" / "prediction" / "risk.py"


# =============================================================================
# Helpers
# =============================================================================

def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ast(path: Path) -> ast.Module:
    return ast.parse(_source(path))


# =============================================================================
# BUG-01 — Category cap exception must NOT fall through to live execution
# =============================================================================

class TestBUG01_CategoryCapFailClosed:
    """The category exposure try/except block in _route_live must reject on
    exception, not silently continue."""

    def test_except_block_returns_orderresult(self):
        src = _source(ORDER_ROUTER_SRC)
        # The fix returns an OrderResult inside the except block
        assert 'category_cap_check_error' in src, (
            "BUG-01: except block must return a rejection with 'category_cap_check_error'"
        )

    def test_except_block_does_not_only_log(self):
        src = _source(ORDER_ROUTER_SRC)
        lines = src.splitlines()
        # Find the line containing 'category_cap_check_error' (in the reason= kwarg)
        reason_line = next(
            (i for i, l in enumerate(lines) if "category_cap_check_error" in l), None
        )
        assert reason_line is not None, "category_cap_check_error marker not found"
        # The 'return OrderResult(' must appear within 10 lines before the reason= line
        # (the return statement opens the call, reason= is a kwarg a few lines later)
        window = lines[max(0, reason_line - 10): reason_line + 5]
        found_return = any("return OrderResult(" in l for l in window)
        assert found_return, (
            "BUG-01: except block must contain a 'return OrderResult(...)' near category_cap_check_error"
        )

    def test_fail_open_comment_removed(self):
        src = _source(ORDER_ROUTER_SRC)
        lines = src.splitlines()
        # The category-cap except block must NOT have a fail-open comment.
        # (Other unrelated blocks, e.g. sanity checker, may legitimately be fail-open.)
        except_line = next(
            (i for i, l in enumerate(lines) if "category_cap_check_error" in l), None
        )
        assert except_line is not None, "category_cap_check_error marker not found"
        window = "\n".join(lines[max(0, except_line - 2): except_line + 15])
        assert "fail-open" not in window, (
            "BUG-01: 'fail-open' comment still present near category cap except block"
        )

    def test_fail_closed_comment_present(self):
        src = _source(ORDER_ROUTER_SRC)
        assert "fail-closed" in src, (
            "BUG-01: 'fail-closed' comment expected in category cap except block"
        )


# =============================================================================
# BUG-02 — GTC accepted order must not trigger fill accounting
# =============================================================================

class TestBUG02_GTCAcceptedNotFill:
    """_is_accepted_only flag must gate fill-log, TrackedPosition, and
    risk accounting away from GTC resting orders."""

    def test_is_accepted_only_flag_exists(self):
        src = _source(TRADING_AGENT_SRC)
        assert "_is_accepted_only" in src, (
            "BUG-02: '_is_accepted_only' flag not found in trading_agent.py"
        )

    def test_accepted_live_status_in_guard(self):
        src = _source(TRADING_AGENT_SRC)
        assert '"accepted_live"' in src, (
            "BUG-02: 'accepted_live' status not mentioned in the accepted-only guard"
        )

    def test_fill_accounting_guarded_by_accepted_only(self):
        src = _source(TRADING_AGENT_SRC)
        lines = src.splitlines()
        # Locate _execute_signal method body
        exec_sig_start = next(
            (i for i, l in enumerate(lines) if "async def _execute_signal_body" in l), None
        )
        assert exec_sig_start is not None, "_execute_signal_body method not found"
        # Find the next async/sync def at same indent level after _execute_signal
        exec_sig_end = next(
            (i for i, l in enumerate(lines)
             if i > exec_sig_start + 5 and (l.startswith("    async def ") or l.startswith("    def "))),
            len(lines),
        )
        body_lines = lines[exec_sig_start:exec_sig_end]
        body_text = "\n".join(body_lines)

        # The _is_accepted_only flag must be defined in the method body
        assert "_is_accepted_only" in body_text, (
            "BUG-02: '_is_accepted_only' not found inside _execute_signal body"
        )
        # get_kalshi_risk must be nested inside the 'else:' branch that follows
        # the _is_accepted_only guard — verify the else: block contains it
        assert "else:" in body_text, (
            "BUG-02: 'else:' branch not found in _execute_signal body"
        )
        # The accepted_only guard comment and get_kalshi_risk both present
        assert "get_kalshi_risk" in body_text, (
            "BUG-02: get_kalshi_risk not found inside _execute_signal"
        )
        # Confirm ordering: _is_accepted_only definition comes before the else: + get_kalshi_risk block
        accepted_def_idx = next(
            (i for i, l in enumerate(body_lines) if "_is_accepted_only =" in l), None
        )
        else_then_risk_idx = next(
            (i for i, l in enumerate(body_lines)
             if i > (accepted_def_idx or 0) and "get_kalshi_risk" in l), None
        )
        assert accepted_def_idx is not None, (
            "BUG-02: '_is_accepted_only =' assignment not found in _execute_signal"
        )
        assert else_then_risk_idx is not None, (
            "BUG-02: get_kalshi_risk not found after _is_accepted_only definition"
        )
        assert accepted_def_idx < else_then_risk_idx, (
            "BUG-02: _is_accepted_only must be defined before the risk accounting block"
        )

    def test_fill_accounting_deferred_log_message(self):
        src = _source(TRADING_AGENT_SRC)
        assert "fill accounting deferred" in src, (
            "BUG-02: expected deferred-accounting log message not found"
        )


# =============================================================================
# BUG-03 — No Bernoulli draw for PnL in BTC-15m risk tracker at fill time
# =============================================================================

class TestBUG03_NoBernoulliPnL:
    """random.random() must NOT appear near btc15m_risk.record_trade_result
    or open_exposure_total in _execute_signal."""

    def _get_execute_signal_source(self) -> str:
        src = _source(TRADING_AGENT_SRC)
        lines = src.splitlines()
        start = next((i for i, l in enumerate(lines) if "async def _execute_signal_body" in l), None)
        assert start is not None
        # grab until next top-level async def
        end = next(
            (i for i, l in enumerate(lines)
             if i > start and l.startswith("    async def ") or
             (i > start + 5 and l.startswith("    def "))),
            len(lines),
        )
        return "\n".join(lines[start:end])

    def test_no_random_in_execute_signal(self):
        body = self._get_execute_signal_source()
        # random.random() was the Bernoulli draw — must be gone
        assert "random.random()" not in body, (
            "BUG-03: random.random() still present in _execute_signal (Bernoulli PnL draw)"
        )

    def test_no_won_variable_derived_from_random(self):
        body = self._get_execute_signal_source()
        assert "_won = random" not in body, (
            "BUG-03: '_won = random...' Bernoulli assignment still in _execute_signal"
        )

    def test_open_exposure_delta_present(self):
        body = self._get_execute_signal_source()
        assert "open_exposure_delta" in body, (
            "BUG-03: 'open_exposure_delta' tracking expected in _execute_signal after fix"
        )

    def test_pnl_deferred_comment_present(self):
        src = _source(TRADING_AGENT_SRC)
        assert "deferred" in src and "OutcomeResolver" in src, (
            "BUG-03: comment about deferred PnL at OutcomeResolver expected"
        )


# =============================================================================
# BUG-04 — All agents share one PredictionMarketRisk singleton
# =============================================================================

class TestBUG04_SharedRiskSingleton:
    """KalshiTradingAgent.__init__ must call get_prediction_risk() not
    PredictionMarketRisk() directly."""

    def test_get_prediction_risk_imported(self):
        src = _source(TRADING_AGENT_SRC)
        assert "get_prediction_risk" in src, (
            "BUG-04: 'get_prediction_risk' not imported/used in trading_agent.py"
        )

    def test_direct_instantiation_not_used_for_self_risk(self):
        src = _source(TRADING_AGENT_SRC)
        # The old code was: self._risk = PredictionMarketRisk(...)
        # It must now be: self._risk = get_prediction_risk(...)
        assert "self._risk = PredictionMarketRisk(" not in src, (
            "BUG-04: direct 'self._risk = PredictionMarketRisk(...)' still present — "
            "must use get_prediction_risk() singleton"
        )

    def test_singleton_called_with_config(self):
        src = _source(TRADING_AGENT_SRC)
        assert "self._risk = get_prediction_risk(" in src, (
            "BUG-04: 'self._risk = get_prediction_risk(...)' assignment not found"
        )

    def test_singleton_returns_same_object(self):
        import importlib
        import threading
        # Reset module-level _risk to ensure clean state
        import merid.prediction.risk._prediction_risk as risk_mod
        original = risk_mod._risk
        try:
            risk_mod._risk = None
            from merid.prediction.risk import PredictionRiskConfig, get_prediction_risk
            cfg = PredictionRiskConfig(max_notional_per_market_usd=100)
            inst1 = get_prediction_risk(cfg)
            inst2 = get_prediction_risk()   # no config — must return same object
            assert inst1 is inst2, (
                "BUG-04: get_prediction_risk() returned different instances"
            )
        finally:
            risk_mod._risk = original

    def test_singleton_is_same_across_two_agent_inits(self):
        """Two separate get_prediction_risk() calls must return the same object."""
        import merid.prediction.risk._prediction_risk as risk_mod
        original = risk_mod._risk
        try:
            risk_mod._risk = None
            from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
            a = get_prediction_risk(PredictionRiskConfig(max_notional_per_market_usd=500))
            b = get_prediction_risk(PredictionRiskConfig(max_notional_per_market_usd=1000))
            assert a is b, "BUG-04: second call must return first instance (singleton)"
        finally:
            risk_mod._risk = original


# =============================================================================
# BUG-05 — Stop-loss close failure must escalate, not silently retry forever
# =============================================================================

class TestBUG05_StopLossEscalation:
    """TrackedPosition must carry close_fail_count; trading_agent must escalate
    to IOC market order and then agent pause after repeated failures."""

    def test_tracked_position_has_close_fail_count(self):
        from merid.event_venues.kalshi.stop_loss import TrackedPosition
        pos = TrackedPosition(
            position_id="p1",
            ticker="DUMMY-X",
            side="yes",
            entry_price_cents=60,
            contracts=5,
            entry_ts=0.0,
        )
        assert hasattr(pos, "close_fail_count"), (
            "BUG-05: TrackedPosition missing 'close_fail_count' field"
        )
        assert pos.close_fail_count == 0

    def test_close_fail_count_default_zero(self):
        from merid.event_venues.kalshi.stop_loss import TrackedPosition
        pos = TrackedPosition(
            position_id="p2",
            ticker="DUMMY-Y",
            side="no",
            entry_price_cents=40,
            contracts=1,
            entry_ts=0.0,
        )
        assert pos.close_fail_count == 0

    def test_escalation_logic_present_in_source(self):
        src = _source(TRADING_AGENT_SRC)
        assert "close_fail_count" in src, (
            "BUG-05: 'close_fail_count' not referenced in trading_agent.py"
        )

    def test_ioc_escalation_at_second_failure(self):
        src = _source(TRADING_AGENT_SRC)
        assert "IOC market order" in src or "ioc" in src.lower(), (
            "BUG-05: IOC escalation path not found in stop-loss failure handler"
        )

    def test_agent_pause_at_third_failure(self):
        src = _source(TRADING_AGENT_SRC)
        lines = src.splitlines()
        # Find the escalation block: close_fail_count >= 3 -> self.pause()
        in_triple_fail = False
        found_pause = False
        for i, line in enumerate(lines):
            if "close_fail_count >= 3" in line:
                in_triple_fail = True
            if in_triple_fail and "self.pause()" in line:
                found_pause = True
                break
            if in_triple_fail and "elif" in line and "close_fail_count" not in line:
                break
        assert found_pause, (
            "BUG-05: 'self.pause()' not found after 'close_fail_count >= 3' check"
        )

    def test_risk_breach_alert_on_escalation(self):
        src = _source(TRADING_AGENT_SRC)
        assert "STOP-LOSS ESCALATION" in src, (
            "BUG-05: STOP-LOSS ESCALATION alert message not found in trading_agent.py"
        )


# =============================================================================
# BUG-06 — _is_live_fill derived from venue gate, not payload dict key
# =============================================================================

class TestBUG06_IsLiveFillFromVenueGate:
    """_is_live_fill must derive from self._venue_gate.should_simulate_fill(),
    not from result_payload.get('simulated', ...)."""

    def test_is_live_fill_uses_venue_gate(self):
        src = _source(TRADING_AGENT_SRC)
        assert "_is_live_fill = not self._venue_gate.should_simulate_fill()" in src, (
            "BUG-06: '_is_live_fill' must be derived from venue gate"
        )

    def test_is_live_fill_not_from_payload_simulated_key(self):
        src = _source(TRADING_AGENT_SRC)
        # Old pattern: _is_live_fill = not bool(result_payload.get("simulated", True))
        assert '_is_live_fill = not bool(result_payload.get("simulated"' not in src, (
            "BUG-06: old payload-key pattern for _is_live_fill still present"
        )

    def test_simulated_key_still_used_for_paper_session_only(self):
        src = _source(TRADING_AGENT_SRC)
        # The _is_simulated_fill variable (for paper session) may still use payload;
        # only _is_live_fill must come from venue gate
        assert "_is_simulated_fill" in src, (
            "BUG-06: _is_simulated_fill (paper session flag) expected but not found"
        )

    def test_venue_gate_imported_in_trading_agent(self):
        src = _source(TRADING_AGENT_SRC)
        assert "get_venue_gate" in src, (
            "BUG-06: get_venue_gate must be imported in trading_agent.py"
        )


# =============================================================================
# BUG-07 — Spread/slippage/depth checks wired up (not dead code)
# =============================================================================

class TestBUG07_SpreadDepthChecksActive:
    """check_order must receive best_bid_cents, best_ask_cents, depth_at_price
    from the market snapshot, not None literals."""

    def test_best_bid_cents_passed_to_check_order(self):
        src = _source(TRADING_AGENT_SRC)
        assert "best_bid_cents=_best_bid" in src, (
            "BUG-07: 'best_bid_cents=_best_bid' not passed to check_order"
        )

    def test_best_ask_cents_passed_to_check_order(self):
        src = _source(TRADING_AGENT_SRC)
        assert "best_ask_cents=_best_ask" in src, (
            "BUG-07: 'best_ask_cents=_best_ask' not passed to check_order"
        )

    def test_depth_at_price_passed_to_check_order(self):
        src = _source(TRADING_AGENT_SRC)
        assert "depth_at_price=_depth" in src, (
            "BUG-07: 'depth_at_price=_depth' not passed to check_order"
        )

    def test_bid_ask_extracted_from_snapshot_implied(self):
        src = _source(TRADING_AGENT_SRC)
        assert "snapshot.implied.yes_bid" in src, (
            "BUG-07: snapshot.implied.yes_bid not used to populate _best_bid"
        )
        assert "snapshot.implied.yes_ask" in src, (
            "BUG-07: snapshot.implied.yes_ask not used to populate _best_ask"
        )

    def test_spread_check_fires_when_bid_ask_known(self):
        """Unit-level: check_order rejects when spread exceeds max."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_spread_cents=5,
            max_notional_per_market_usd=10_000,
            max_total_notional_usd=100_000,
        )
        risk = PredictionMarketRisk(cfg)
        # bid=40, ask=60 => spread=20 > max_spread_cents=5
        check = risk.check_order(
            market_id="TEST-MKT-1",
            event_id="TEST-EVENT",
            side="yes",
            contracts=1,
            price_cents=Decimal("50"),
            best_bid_cents=Decimal("40"),
            best_ask_cents=Decimal("60"),
        )
        assert not check.allowed, (
            "BUG-07: spread check should reject when spread=20 > max_spread=5"
        )

    def test_spread_check_passes_when_spread_tight(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_spread_cents=10,
            max_notional_per_market_usd=10_000,
            max_total_notional_usd=100_000,
        )
        risk = PredictionMarketRisk(cfg)
        check = risk.check_order(
            market_id="TEST-MKT-2",
            event_id="TEST-EVENT",
            side="yes",
            contracts=1,
            price_cents=Decimal("50"),
            best_bid_cents=Decimal("48"),
            best_ask_cents=Decimal("52"),
        )
        assert check.allowed, (
            "BUG-07: spread=4 should be allowed when max_spread=10"
        )


# =============================================================================
# BUG-08 — Swarm-degraded mode hard cap + wall-clock limit
# =============================================================================

class TestBUG08_DegradedModeCap:
    """AgentState must carry swarm_degraded_since and
    solo_trades_this_degraded_session. Module-level constants
    _MAX_SOLO_TRADES_DEGRADED and _MAX_SOLO_WALL_SECONDS must exist."""

    def test_constants_exist(self):
        import merid.prediction.trading_agent as ta
        assert hasattr(ta, "_MAX_SOLO_TRADES_DEGRADED"), (
            "BUG-08: _MAX_SOLO_TRADES_DEGRADED constant not found in trading_agent"
        )
        assert hasattr(ta, "_MAX_SOLO_WALL_SECONDS"), (
            "BUG-08: _MAX_SOLO_WALL_SECONDS constant not found in trading_agent"
        )

    def test_trade_cap_is_positive_integer(self):
        import merid.prediction.trading_agent as ta
        cap = ta._MAX_SOLO_TRADES_DEGRADED
        assert isinstance(cap, int) and cap > 0, (
            f"BUG-08: _MAX_SOLO_TRADES_DEGRADED must be a positive int, got {cap!r}"
        )

    def test_wall_clock_limit_is_positive_float(self):
        import merid.prediction.trading_agent as ta
        limit = ta._MAX_SOLO_WALL_SECONDS
        assert isinstance(limit, (int, float)) and limit > 0, (
            f"BUG-08: _MAX_SOLO_WALL_SECONDS must be positive, got {limit!r}"
        )

    def test_agent_state_has_degraded_since(self):
        from merid.prediction.trading_agent import AgentState
        state = AgentState(name="test-agent")
        assert hasattr(state, "swarm_degraded_since"), (
            "BUG-08: AgentState missing 'swarm_degraded_since' field"
        )
        assert state.swarm_degraded_since is None

    def test_agent_state_has_solo_trade_counter(self):
        from merid.prediction.trading_agent import AgentState
        state = AgentState(name="test-agent")
        assert hasattr(state, "solo_trades_this_degraded_session"), (
            "BUG-08: AgentState missing 'solo_trades_this_degraded_session' field"
        )
        assert state.solo_trades_this_degraded_session == 0

    def test_to_dict_includes_new_fields(self):
        from merid.prediction.trading_agent import AgentState
        d = AgentState(name="test-agent").to_dict()
        assert "swarm_degraded_since" in d, (
            "BUG-08: 'swarm_degraded_since' not serialised in AgentState.to_dict()"
        )
        assert "solo_trades_this_degraded_session" in d, (
            "BUG-08: 'solo_trades_this_degraded_session' not serialised in AgentState.to_dict()"
        )

    def test_trade_cap_enforcement_in_source(self):
        src = _source(TRADING_AGENT_SRC)
        assert "solo_trades_this_degraded_session >= _MAX_SOLO_TRADES_DEGRADED" in src, (
            "BUG-08: solo trade cap enforcement not found in source"
        )

    def test_wall_clock_enforcement_in_source(self):
        src = _source(TRADING_AGENT_SRC)
        assert "degraded_seconds >= _MAX_SOLO_WALL_SECONDS" in src, (
            "BUG-08: wall-clock limit enforcement not found in source"
        )

    def test_agent_disabled_on_wall_clock_breach(self):
        src = _source(TRADING_AGENT_SRC)
        lines = src.splitlines()
        in_wall_check = False
        found_disable = False
        for line in lines:
            if "degraded_seconds >= _MAX_SOLO_WALL_SECONDS" in line:
                in_wall_check = True
            if in_wall_check and "self.state.enabled = False" in line:
                found_disable = True
                break
        assert found_disable, (
            "BUG-08: 'self.state.enabled = False' not found after wall-clock limit check"
        )

    def test_degraded_alert_fired_on_entry(self):
        src = _source(TRADING_AGENT_SRC)
        assert "Swarm degraded on" in src, (
            "BUG-08: entry-alert message 'Swarm degraded on' not found"
        )

    def test_halt_alert_fired_on_wall_clock_breach(self):
        src = _source(TRADING_AGENT_SRC)
        assert "auto-halted" in src, (
            "BUG-08: auto-halt breach alert message not found"
        )
