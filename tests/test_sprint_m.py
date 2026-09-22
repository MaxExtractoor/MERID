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
        assert "_reg(swarm_bus_api_router)" in content


# ═══════════════════════════════════════════════════════════════════════════
# AgentGrid Lifecycle Wiring
# ═══════════════════════════════════════════════════════════════════════════




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

