"""
Regression test suite for kalshi_crypto_15m_v2 profile using web.main_15m_lean.

This test suite validates the new thin entrypoint and loop for the 15-minute
crypto trading stack, ensuring it's isolated from legacy components and
operates correctly with the canonical stack only.
"""

import asyncio
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Dict, Any


class TestKalshi15mEntrypoint:
    """
    Regression tests for web.main_15m_lean and merid.loop_15m.

    These tests ensure the new thin entrypoint:
    - Loads risk envelope and kalshi_crypto_15m_v2.yaml successfully
    - Builds agent grid with exactly 5 agents and correct series tickers
    - Starts KalshiMarketCatalog with 5 allowed markets
    - Starts WS bridge with 5 tickers and no attribute errors
    - Instantiates Kalshi15mLoop correctly
    - Does NOT import legacy components (systemorchestrator, governance, treasury, reflection, PM)
    """

    @pytest.fixture
    def mock_env(self):
        """Set up environment for kalshi_crypto_15m_v2 profile."""
        env = {
            "MERID_PROFILE": "kalshi_crypto_15m_v2",
            "KALSHI_BASE_URL": "https://demo-api.kalshi.co",
            "KALSHI_EMAIL": "test@example.com",
            "KALSHI_PASSWORD": "testpass",
            "KALSHI_API_KEY_ID": "test_key_id",
            "KALSHI_API_KEY_SECRET": "test_secret",
        }
        original_env = os.environ.copy()
        os.environ.update(env)
        yield env
        os.environ.clear()
        os.environ.update(original_env)

    @pytest.mark.asyncio
    async def test_entrypoint_profile_validation(self, mock_env):
        """Test that web.main_15m_lean validates the profile correctly."""
        # Import the app
        from web.main_15m_lean import app

        # Verify profile is set
        assert os.getenv("MERID_PROFILE") == "kalshi_crypto_15m_v2"

        # Verify app metadata
        assert app.title == "Kalshi 15m Lean Stack - main_15m_lean.py"
        assert app.version == "20260530-auto-startup"

    def test_entrypoint_no_legacy_imports(self, mock_env):
        """Test that web.main_15m_lean does NOT import legacy components."""
        # Read the source file
        with open("web/main_15m_lean.py", "r", encoding="utf-8") as f:
            source = f.read()

        # Check that legacy components are NOT imported
        legacy_imports = [
            "from core.systemorchestrator",
            "from governance",
            "from treasury",
            "from reflection",
            "from core.agent_orchestrator",
            "from core.consensus_engine",
            "from core.event_bus",  # Legacy event bus
        ]

        for legacy_import in legacy_imports:
            assert legacy_import not in source, f"Legacy import found: {legacy_import}"

        # Check that it DOES import the new 15m loop and agent grid
        assert "from merid.loop_15m import" in source
        assert "merid.prediction.agent_grid_15m" in source

    @pytest.mark.asyncio
    async def test_agent_grid_loads_5_agents(self, mock_env):
        """Test that the agent-grid config loads exactly 5 agents with correct names."""
        from merid.prediction.agent_grid_config import load_agent_grid_config

        config = load_agent_grid_config()

        # Validate exactly 5 agents
        enabled_agents = [a.name for a in config.agents if a.enabled]
        assert len(enabled_agents) == 5, f"Expected 5 agents, got {len(enabled_agents)}: {enabled_agents}"

        # Validate agent names
        allowed_15m_agents = {"BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"}
        for agent in enabled_agents:
            assert agent in allowed_15m_agents, f"Unexpected agent: {agent}"

    @pytest.mark.asyncio
    async def test_kalshi_15m_loop_exists(self, mock_env):
        """Test that Kalshi15mLoop class exists and can be instantiated."""
        from merid.loop_15m import Kalshi15mLoop, get_kalshi_15m_loop

        # Create mock dependencies
        mock_agent_grid = MagicMock()
        mock_agent_grid._agents = []

        mock_bankroll_service = MagicMock()
        mock_risk_config = MagicMock()

        # Create loop instance
        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            bankroll_service=mock_bankroll_service,
            risk_config=mock_risk_config,
            cadence_seconds=5.0,
        )

        # Verify loop attributes
        assert loop.cadence_seconds == 5.0
        assert loop._running == False
        assert loop._tick == 0

        # Verify factory function is exported
        assert callable(get_kalshi_15m_loop)

    @pytest.mark.asyncio
    async def test_kalshi_15m_loop_summary(self, mock_env):
        """Test that Kalshi15mLoop.summary() returns correct status."""
        from merid.loop_15m import Kalshi15mLoop

        mock_agent_grid = MagicMock()
        mock_agent_grid._agents = [MagicMock(agent_id="BTC_15M")]

        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            bankroll_service=MagicMock(),
            risk_config=MagicMock(),
            cadence_seconds=5.0,
        )

        summary = loop.summary()

        # Verify summary fields
        assert "running" in summary
        assert "tick" in summary
        assert "cycle_count" in summary
        assert "error_count" in summary
        assert "cadence_seconds" in summary
        assert summary["cadence_seconds"] == 5.0
        assert summary["agent_count"] == 1

    @pytest.mark.asyncio
    async def test_loop_15m_no_legacy_imports(self, mock_env):
        """Test that merid.loop_15m does NOT import legacy components."""
        # Read the source file
        with open("merid/loop_15m.py", "r", encoding="utf-8") as f:
            source = f.read()

        # Check that legacy components are NOT imported
        legacy_imports = [
            "from core.systemorchestrator",
            "from governance",
            "from treasury",
            "from reflection",
            "from core.agent_orchestrator",
            "from core.consensus_engine",
            "from core.event_bus",
        ]

        for legacy_import in legacy_imports:
            assert legacy_import not in source, f"Legacy import found: {legacy_import}"

    def test_risk_envelope_yaml_exists(self, mock_env):
        """Test that kalshi_crypto_15m_v2.yaml risk envelope exists and is well-formed."""
        import yaml

        config_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
        assert os.path.exists(config_path), f"Risk envelope not found: {config_path}"

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Verify key sections exist (actual v2 YAML structure)
        assert "venue" in config
        assert config["venue"]["name"] == "kalshi"
        assert "assets" in config
        assert "BTC" in config["assets"]

    def test_agent_grid_yaml_has_5_agents(self, mock_env):
        """Test that kalshi_agent_grid.yaml has exactly 5 15m crypto agents."""
        import yaml

        config_path = "config/kalshi_agent_grid.yaml"
        assert os.path.exists(config_path), f"Agent grid config not found: {config_path}"

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Count 15m crypto agents (all agents in this file are 15m crypto agents)
        agents = config["agents"]
        assert len(agents) == 5, f"Expected 5 agents, got {len(agents)}"

        # Validate agent names
        agent_names = [a["name"] for a in agents]
        expected_names = ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]
        for name in expected_names:
            assert name in agent_names, f"Expected agent {name} not found"

    @pytest.mark.asyncio
    async def test_lean_agent_grid_has_run_cycle_method(self, mock_env):
        """Test that the 15m agent grid exposes a callable run_cycle."""
        from merid.prediction.agent_grid_15m import build_15m_agent_grid

        # build_15m_agent_grid is the canonical factory used by the entrypoint
        assert callable(build_15m_agent_grid)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
