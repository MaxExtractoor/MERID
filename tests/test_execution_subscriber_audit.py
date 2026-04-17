"""test_execution_subscriber_audit.py

Regression tests for the 6 bugs fixed in the Execution Subscriber Audit:

  A1  ExecutionSubscriber.start() wired into MeridLoop.run()
  B1  AgentGrid routing failure logs at WARNING, not DEBUG
  D1  _route_to_execution checks VenueGate + ExecutionGuard before any order
  E2  solo_trades_this_degraded_session reset to 0 on swarm consensus recovery
  F1  reset_execution_subscriber() cancels old task before dropping reference
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
import types

import pytest

ROOT = Path(__file__).resolve().parent.parent
SUB_SRC = ROOT / "merid" / "swarm" / "execution_subscriber.py"
LOOP_SRC = ROOT / "merid" / "loop.py"
AGENT_SRC = ROOT / "merid" / "prediction" / "trading_agent.py"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _good_decision(**kwargs):
    base = {
        "decision_id": "test-dec-001",
        "market_id": "KXBTC-123",
        "action": "buy_yes",
        "side": "yes",
        "size_contracts": 5,
        "limit_price_cents": 55,
        "risk_approved": True,
        "_created_at": __import__("time").time(),
    }
    base.update(kwargs)
    return base


# ── A1: MeridLoop.run() wires ExecutionSubscriber ────────────────────────────

class TestA1LoopWiresSubscriber:
    def test_run_starts_subscriber_when_execution_enabled(self):
        """MeridLoop.run() must call ExecutionSubscriber.start() when
        enable_execution=True and 'prediction' is an active domain."""
        src = LOOP_SRC.read_text()
        assert "get_execution_subscriber" in src, (
            "MeridLoop.run() must import get_execution_subscriber"
        )
        assert "_execution_subscriber" in src, (
            "MeridLoop must track _execution_subscriber for shutdown"
        )
        assert "await self._execution_subscriber.start()" in src, (
            "MeridLoop.run() must await ExecutionSubscriber.start()"
        )

    def test_run_stops_subscriber_on_shutdown(self):
        """MeridLoop.run() must await ExecutionSubscriber.stop() before exit."""
        src = LOOP_SRC.read_text()
        assert "await self._execution_subscriber.stop()" in src, (
            "MeridLoop.run() must await ExecutionSubscriber.stop() on shutdown"
        )

    def test_subscriber_only_started_when_execution_enabled(self):
        """ExecutionSubscriber must NOT start when enable_execution=False."""
        src = LOOP_SRC.read_text()
        # The guard must be: enable_execution AND prediction in active_domains
        assert "self.config.enable_execution" in src
        # The start block must be inside the enable_execution conditional
        start_idx = src.find("await self._execution_subscriber.start()")
        guard_idx = src.rfind("self.config.enable_execution", 0, start_idx)
        assert guard_idx != -1, (
            "ExecutionSubscriber.start() must be guarded by enable_execution check"
        )


# ── B1: AgentGrid failure logged at WARNING ───────────────────────────────────

class TestB1AgentGridWarningLog:
    def test_agentgrid_failure_logs_warning_not_debug(self):
        """AgentGrid routing failure must use logger.warning, not logger.debug."""
        src = SUB_SRC.read_text()
        # Find the except block that catches AgentGrid failures
        # It should contain logger.warning, not logger.debug
        assert "logger.warning(\"ExecutionSubscriber: AgentGrid routing failed" in src, (
            "AgentGrid routing failure must be logged at WARNING level"
        )

    def test_agentgrid_failure_debug_log_removed(self):
        """The old logger.debug for AgentGrid routing failure must be gone."""
        src = SUB_SRC.read_text()
        assert 'logger.debug(f"AgentGrid routing failed: {exc}")' not in src, (
            "Old logger.debug for AgentGrid failure must have been replaced"
        )


# ── D1: VenueGate + ExecutionGuard called before any order ───────────────────

class TestD1RouteToExecutionGates:
    """_route_to_execution must enforce VenueGate and ExecutionGuard."""

    def test_venue_gate_import_present(self):
        src = SUB_SRC.read_text()
        assert "from merid.prediction.venue_gate import get_venue_gate" in src

    def test_execution_guard_import_present(self):
        src = SUB_SRC.read_text()
        assert "from merid.execution_guard import get_execution_guard" in src

    def test_venue_gate_check_called_before_order(self):
        src = SUB_SRC.read_text()
        route_start = src.find("async def _route_to_execution")
        route_end = src.find("\n    async def ", route_start + 1)
        route_body = src[route_start:route_end] if route_end != -1 else src[route_start:]
        assert "gate.check_venue(" in route_body
        assert "gate.check_can_trade()" in route_body
        # Gates must appear before any _kalshi_place_order call
        gate_pos = route_body.find("gate.check_venue(")
        order_pos = route_body.find("_kalshi_place_order")
        assert gate_pos < order_pos, (
            "VenueGate check must appear before _kalshi_place_order in _route_to_execution"
        )

    def test_execution_guard_check_called_before_order(self):
        src = SUB_SRC.read_text()
        route_start = src.find("async def _route_to_execution")
        route_end = src.find("\n    async def ", route_start + 1)
        route_body = src[route_start:route_end] if route_end != -1 else src[route_start:]
        assert "guard.pre_trade_check(" in route_body
        guard_pos = route_body.find("guard.pre_trade_check(")
        order_pos = route_body.find("_kalshi_place_order")
        assert guard_pos < order_pos, (
            "ExecutionGuard.pre_trade_check() must appear before _kalshi_place_order"
        )

    @pytest.mark.asyncio
    async def test_venue_gate_block_raises_and_skips_order(self):
        """When VenueGate raises, no order placement must occur."""
        from merid.swarm.execution_subscriber import ExecutionSubscriber

        sub = ExecutionSubscriber()
        data = _good_decision()

        mock_gate = MagicMock()
        mock_gate.check_venue.side_effect = Exception("venue blocked")
        mock_get_venue_gate = MagicMock(return_value=mock_gate)
        mock_place = AsyncMock()

        # Patch at the call site inside the subscriber module
        with patch("merid.swarm.execution_subscriber.ExecutionSubscriber._route_to_execution",
                   wraps=sub._route_to_execution):
            pass  # just ensure the method is the patched one

        import merid.swarm.execution_subscriber as sub_mod
        with patch.object(sub_mod, "__builtins__", sub_mod.__builtins__):  # noqa: keep context
            # Inline-patch the imports inside the method via builtins trick:
            # instead, monkeypatch via sys.modules stubs
            import sys
            vg_mod = types.ModuleType("merid.prediction.venue_gate")
            vg_mod.get_venue_gate = mock_get_venue_gate
            sys.modules["merid.prediction.venue_gate"] = vg_mod

            eg_mod = types.ModuleType("merid.execution_guard")
            mock_verdict = MagicMock(allowed=True)
            mock_guard = MagicMock()
            mock_guard.pre_trade_check.return_value = mock_verdict
            eg_mod.get_execution_guard = MagicMock(return_value=mock_guard)
            sys.modules["merid.execution_guard"] = eg_mod

            kt_mod = types.ModuleType("merid.prediction.kalshi_tools")
            kt_mod._kalshi_place_order = mock_place
            sys.modules["merid.prediction.kalshi_tools"] = kt_mod

            with pytest.raises(RuntimeError, match="VenueGate blocked"):
                await sub._route_to_execution(data)
            mock_place.assert_not_called()

    @pytest.mark.asyncio
    async def test_execution_guard_block_raises_and_skips_order(self):
        """When ExecutionGuard blocks, no order placement must occur."""
        import sys
        from merid.swarm.execution_subscriber import ExecutionSubscriber

        sub = ExecutionSubscriber()
        data = _good_decision()

        mock_gate = MagicMock()
        mock_gate.check_venue.return_value = None
        mock_gate.check_can_trade.return_value = None
        vg_mod = types.ModuleType("merid.prediction.venue_gate")
        vg_mod.get_venue_gate = MagicMock(return_value=mock_gate)
        sys.modules["merid.prediction.venue_gate"] = vg_mod

        mock_verdict = MagicMock()
        mock_verdict.allowed = False
        mock_verdict.reason = "global kill switch"
        mock_guard = MagicMock()
        mock_guard.pre_trade_check.return_value = mock_verdict
        eg_mod = types.ModuleType("merid.execution_guard")
        eg_mod.get_execution_guard = MagicMock(return_value=mock_guard)
        sys.modules["merid.execution_guard"] = eg_mod

        mock_place = AsyncMock()
        kt_mod = types.ModuleType("merid.prediction.kalshi_tools")
        kt_mod._kalshi_place_order = mock_place
        sys.modules["merid.prediction.kalshi_tools"] = kt_mod

        with pytest.raises(RuntimeError, match="ExecutionGuard blocked"):
            await sub._route_to_execution(data)
        mock_place.assert_not_called()

    @pytest.mark.asyncio
    async def test_execution_guard_allowed_proceeds_to_order(self):
        """When both gates pass, _kalshi_place_order must be called."""
        import sys
        from merid.swarm.execution_subscriber import ExecutionSubscriber

        sub = ExecutionSubscriber()
        data = _good_decision()

        mock_gate = MagicMock()
        mock_gate.check_venue.return_value = None
        mock_gate.check_can_trade.return_value = None
        vg_mod = types.ModuleType("merid.prediction.venue_gate")
        vg_mod.get_venue_gate = MagicMock(return_value=mock_gate)
        sys.modules["merid.prediction.venue_gate"] = vg_mod

        mock_verdict = MagicMock(allowed=True)
        mock_guard = MagicMock()
        mock_guard.pre_trade_check.return_value = mock_verdict
        eg_mod = types.ModuleType("merid.execution_guard")
        eg_mod.get_execution_guard = MagicMock(return_value=mock_guard)
        sys.modules["merid.execution_guard"] = eg_mod

        # AgentGrid not running — force fallback direct placement path
        mock_grid = MagicMock()
        mock_grid.is_running = False
        ag_mod = types.ModuleType("merid.prediction.agent_grid")
        ag_mod.get_agent_grid = MagicMock(return_value=mock_grid)
        sys.modules["merid.prediction.agent_grid"] = ag_mod

        mock_place = AsyncMock()
        kt_mod = types.ModuleType("merid.prediction.kalshi_tools")
        kt_mod._kalshi_place_order = mock_place
        sys.modules["merid.prediction.kalshi_tools"] = kt_mod

        await sub._route_to_execution(data)
        mock_place.assert_called_once()


# ── E2: solo_trades_this_degraded_session reset on consensus recovery ─────────

class TestE2SoloTradesCounterReset:
    def test_counter_reset_on_consensus_recovery_present_in_source(self):
        """Source must reset solo_trades_this_degraded_session = 0 when
        swarm_degraded is cleared."""
        src = AGENT_SRC.read_text()
        # Find the recovery block
        recovery_idx = src.find("Swarm consensus recovered")
        assert recovery_idx != -1, "Swarm recovery log line not found"
        # In the same vicinity (within 300 chars) the counter reset must exist
        vicinity = src[recovery_idx: recovery_idx + 300]
        assert "solo_trades_this_degraded_session = 0" in vicinity, (
            "solo_trades_this_degraded_session must be reset to 0 on recovery"
        )

    def test_counter_reset_after_flag_cleared(self):
        """The counter reset must come AFTER swarm_degraded is set to False."""
        src = AGENT_SRC.read_text()
        false_pos = src.find("self.state.swarm_degraded = False\n")
        assert false_pos != -1
        reset_pos = src.find(
            "self.state.solo_trades_this_degraded_session = 0  # E2:",
            false_pos,
        )
        assert reset_pos != -1, (
            "Counter reset must appear after swarm_degraded = False"
        )
        assert reset_pos > false_pos


# ── F1: reset_execution_subscriber stops old task ─────────────────────────────

class TestF1ResetSubscriber:
    def test_reset_function_exists(self):
        src = SUB_SRC.read_text()
        assert "async def reset_execution_subscriber" in src

    def test_reset_clears_global(self):
        src = SUB_SRC.read_text()
        reset_start = src.find("async def reset_execution_subscriber")
        reset_end = src.find("\nasync def ", reset_start + 1)
        body = src[reset_start:reset_end] if reset_end != -1 else src[reset_start:]
        assert "_subscriber = None" in body, (
            "reset_execution_subscriber must set _subscriber = None"
        )
        assert "await old.stop()" in body, (
            "reset_execution_subscriber must await old.stop() before dropping ref"
        )

    @pytest.mark.asyncio
    async def test_reset_calls_stop_on_old_instance(self):
        """reset_execution_subscriber() must call stop() on the previous instance."""
        import sys, types

        for mod in ["core.streaming_bus"]:
            if mod not in sys.modules:
                sys.modules[mod] = types.ModuleType(mod)

        # Force a fresh import to get a clean module-level _subscriber
        import importlib
        import merid.swarm.execution_subscriber as sub_mod
        importlib.reload(sub_mod)

        old_instance = sub_mod.get_execution_subscriber()
        old_instance.stop = AsyncMock()

        await sub_mod.reset_execution_subscriber()

        old_instance.stop.assert_called_once()
        assert sub_mod._subscriber is None

    @pytest.mark.asyncio
    async def test_reset_then_get_returns_new_instance(self):
        """After reset, get_execution_subscriber() returns a different object."""
        import merid.swarm.execution_subscriber as sub_mod
        import importlib
        importlib.reload(sub_mod)

        first = sub_mod.get_execution_subscriber()
        first.stop = AsyncMock()

        await sub_mod.reset_execution_subscriber()
        second = sub_mod.get_execution_subscriber()

        assert second is not first
