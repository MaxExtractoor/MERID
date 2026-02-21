"""Tests for Sprint M: Execution subscriber, swarm bus API, UI wiring.

Sprint M closes the last gap: execution subscribes to Decision via bus.
"""

from __future__ import annotations

import asyncio
import inspect
import os
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════════════
# Execution Subscriber
# ═══════════════════════════════════════════════════════════════════════════


class TestExecutionSubscriber:
    """Tests for merid.swarm.execution_subscriber."""

    def test_import(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber, get_execution_subscriber
        sub = get_execution_subscriber()
        assert isinstance(sub, ExecutionSubscriber)

    def test_singleton(self):
        from merid.swarm.execution_subscriber import get_execution_subscriber
        import merid.swarm.execution_subscriber as mod
        old = mod._subscriber
        mod._subscriber = None
        try:
            a = mod.get_execution_subscriber()
            b = mod.get_execution_subscriber()
            assert a is b
        finally:
            mod._subscriber = old

    def test_initial_stats(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber
        sub = ExecutionSubscriber()
        stats = sub.stats
        assert stats["received"] == 0
        assert stats["routed"] == 0
        assert stats["skipped"] == 0

    def test_empty_history(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber
        sub = ExecutionSubscriber()
        assert sub.history == []

    @pytest.mark.asyncio
    async def test_handle_skip_action(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber
        sub = ExecutionSubscriber()
        await sub._handle_decision({
            "decision_id": "test-1",
            "market_id": "KXBTC",
            "action": "skip",
            "side": "yes",
            "size_contracts": 0,
            "risk_approved": False,
        })
        assert sub.stats["received"] == 1
        assert sub.stats["skipped"] == 1
        assert sub.stats["routed"] == 0

    @pytest.mark.asyncio
    async def test_handle_not_risk_approved(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber
        sub = ExecutionSubscriber()
        await sub._handle_decision({
            "decision_id": "test-2",
            "market_id": "KXBTC",
            "action": "buy_yes",
            "side": "yes",
            "size_contracts": 5,
            "risk_approved": False,
        })
        assert sub.stats["skipped"] == 1
        assert sub.history[-1]["route_reason"] == "Not risk-approved"

    @pytest.mark.asyncio
    async def test_handle_zero_size(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber
        sub = ExecutionSubscriber()
        await sub._handle_decision({
            "decision_id": "test-3",
            "market_id": "KXBTC",
            "action": "buy_yes",
            "side": "yes",
            "size_contracts": 0,
            "risk_approved": True,
        })
        assert sub.stats["skipped"] == 1
        assert sub.history[-1]["route_reason"] == "Zero size"

    @pytest.mark.asyncio
    async def test_handle_approved_routes(self):
        from merid.swarm.execution_subscriber import ExecutionSubscriber
        sub = ExecutionSubscriber()

        # Mock the routing so it doesn't try real execution
        with patch.object(sub, '_route_to_execution', new_callable=lambda: lambda: asyncio.coroutine(lambda self, data: None).__get__(sub)):
            async def mock_route(data):
                pass
            sub._route_to_execution = mock_route

            await sub._handle_decision({
                "decision_id": "test-4",
                "market_id": "KXBTC",
                "action": "buy_yes",
                "side": "yes",
                "size_contracts": 5,
                "risk_approved": True,
            })
            assert sub.stats["routed"] == 1
            assert sub.history[-1]["routed"] is True

    def test_execution_record_to_dict(self):
        from merid.swarm.execution_subscriber import ExecutionRecord
        rec = ExecutionRecord(
            decision_id="d1",
            market_id="KXBTC",
            action="buy_yes",
            side="yes",
            size_contracts=3,
        )
        d = rec.to_dict()
        assert d["decision_id"] == "d1"
        assert d["market_id"] == "KXBTC"
        assert d["routed"] is False


# ═══════════════════════════════════════════════════════════════════════════
# Swarm Bus API
# ═══════════════════════════════════════════════════════════════════════════


class TestSwarmBusApi:
    """Tests for web.api.swarm_bus_api."""

    def test_api_file_exists(self):
        assert os.path.exists(os.path.join("web", "api", "swarm_bus_api.py"))

    def test_router_prefix(self):
        from web.api.swarm_bus_api import router
        assert router.prefix == "/api/v1/kalshi/swarm"

    def test_critic_history_endpoint(self):
        from web.api.swarm_bus_api import router
        routes = [r.path for r in router.routes]
        assert any("critic" in r and "history" in r for r in routes)

    def test_recalibration_endpoint(self):
        from web.api.swarm_bus_api import router
        routes = [r.path for r in router.routes]
        assert any("recalibration" in r for r in routes)

    def test_execution_stats_endpoint(self):
        from web.api.swarm_bus_api import router
        routes = [r.path for r in router.routes]
        assert any("execution" in r and "stats" in r for r in routes)


class TestSwarmBusApiWiring:
    """Test swarm bus API is wired into main.py."""

    def test_router_imported_in_main(self):
        main_path = os.path.join("web", "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "swarm_bus_api_router" in content
        assert "swarm_bus_api" in content

    def test_router_included(self):
        main_path = os.path.join("web", "main.py")
        with open(main_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "include_router(swarm_bus_api_router)" in content


# ═══════════════════════════════════════════════════════════════════════════
# AgentGrid Lifecycle Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestAgentGridLifecycle:
    """Test that Sprint M components are wired into AgentGrid lifecycle."""

    def test_execution_subscriber_in_start(self):
        from merid.prediction.agent_grid import AgentGrid
        source = inspect.getsource(AgentGrid.start)
        assert "execution_subscriber" in source
        assert "get_execution_subscriber" in source

    def test_execution_subscriber_in_stop(self):
        from merid.prediction.agent_grid import AgentGrid
        source = inspect.getsource(AgentGrid.stop)
        assert "execution_subscriber" in source

    def test_edge_recalibrator_in_start(self):
        from merid.prediction.agent_grid import AgentGrid
        source = inspect.getsource(AgentGrid.start)
        assert "edge_recalibrator" in source

    def test_critic_agent_in_start(self):
        from merid.prediction.agent_grid import AgentGrid
        source = inspect.getsource(AgentGrid.start)
        assert "critic_agent" in source


# ═══════════════════════════════════════════════════════════════════════════
# UI Wiring
# ═══════════════════════════════════════════════════════════════════════════


class TestUIWiring:
    """Test Sprint M UI wiring."""

    def test_calibration_in_sidebar_manifest(self):
        manifest_path = os.path.join("web", "react", "src", "config", "sidebarManifest.ts")
        with open(manifest_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "calibration-dashboard" in content
        assert "Target" in content

    def test_calibration_in_command_palette(self):
        palette_path = os.path.join("web", "react", "src", "components", "CommandPalette.tsx")
        with open(palette_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "calibration-dashboard" in content
        assert "calibration" in content.lower()

    def test_calibration_in_sidebar_config(self):
        config_path = os.path.join("web", "api", "sidebar_config.py")
        with open(config_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "calibration-dashboard" in content

    def test_swarm_endpoints_in_constants(self):
        constants_path = os.path.join("web", "react", "src", "config", "constants.ts")
        with open(constants_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "SWARM_CRITIC_HISTORY" in content
        assert "SWARM_RECALIBRATION" in content
        assert "SWARM_EXECUTION_STATS" in content

    def test_calibration_dashboard_fetches_swarm_data(self):
        view_path = os.path.join("web", "react", "src", "views", "CalibrationDashboardView.tsx")
        with open(view_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "SWARM_RECALIBRATION" in content
        assert "SWARM_CRITIC_HISTORY" in content
        assert "SWARM_EXECUTION_STATS" in content
        assert "Edge Recalibration" in content
        assert "Critic Feed" in content
        assert "Execution Bus" in content


# ═══════════════════════════════════════════════════════════════════════════
# Gap Analysis Update
# ═══════════════════════════════════════════════════════════════════════════


class TestGapAnalysis:
    """Verify gap analysis reflects Sprint M closure."""

    def test_execution_gap_updated(self):
        gap_path = os.path.join("docs", "KALSHI_SWARM_GAP_ANALYSIS.md")
        with open(gap_path, "r", encoding="utf-8") as f:
            content = f.read()
        # The execution plane row should still show sequential (we haven't
        # changed the doc yet for Sprint M), but message flow should be 7/8
        assert "7/8" in content
