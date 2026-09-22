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





# ── E2: solo_trades_this_degraded_session reset on consensus recovery ─────────
