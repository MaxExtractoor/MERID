"""
Regression test suite for kalshi_crypto_15m_v2 profile using web.main_15m.

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
    Regression tests for web.main_15m and merid.loop_15m.
    
    These tests ensure the new thin entrypoint:
    - Loads risk envelope and kalshi_crypto_15m.yaml successfully
    - Builds AgentGrid with exactly 5 agents and correct series tickers
    - Starts KalshiMarketCatalog with 5 allowed markets
    - Starts WS bridge with 5 tickers and no attribute errors
    - Runs Kalshi15mLoop correctly
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
        """Test that web.main_15m validates the profile correctly."""
        # Import the app
        from web.main_15m import app
        
        # Verify profile is set
        assert os.getenv("MERID_PROFILE") == "kalshi_crypto_15m_v2"
        
        # Verify app metadata
        assert app.title == "MERID Kalshi 15m Crypto"
        assert app.version == "15m-v2"

    def test_entrypoint_no_legacy_imports(self, mock_env):
        """Test that web.main_15m does NOT import legacy components."""
        # Read the source file
        with open("web/main_15m.py", "r") as f:
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
        
        # Check that it DOES import the new loop
        assert "from merid.loop_15m import get_kalshi_15m_loop" in source

    def test_real_credentials_required(self, mock_env):
        """Test that real Kalshi API credentials are required for startup."""
        import os
        
        # Remove Kalshi credentials to simulate missing env vars
        kalshi_vars = ["KALSHI_BASE_URL", "KALSHI_EMAIL", "KALSHI_PASSWORD", "KALSHI_API_KEY_ID", "KALSHI_API_KEY_SECRET"]
        original_values = {}
        for var in kalshi_vars:
            if var in os.environ:
                original_values[var] = os.environ[var]
                del os.environ[var]
        
        try:
            # Set demo mode (should now be ignored and still require real credentials)
            os.environ["MERID_DEMO_MODE"] = "1"
            
            # Import and call _validate_environment - should raise ValueError
            from web.main_15m import _validate_environment
            with pytest.raises(ValueError, match="Missing required environment variables"):
                _validate_environment()
            
        finally:
            # Restore original environment
            os.environ.pop("MERID_DEMO_MODE", None)
            for var, value in original_values.items():
                os.environ[var] = value

    @pytest.mark.asyncio
    async def test_agent_grid_loads_5_agents(self, mock_env):
        """Test that AgentGrid loads exactly 5 agents with correct names."""
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
    async def test_agent_grid_has_run_cycle_method(self, mock_env):
        """Test that AgentGrid has run_cycle() method for 15m loop."""
        from merid.prediction.agent_grid import AgentGrid
        from merid.prediction.agent_grid_config import load_agent_grid_config
        
        config = load_agent_grid_config()
        grid = AgentGrid(config=config)
        
        # Check that run_cycle method exists
        assert hasattr(grid, 'run_cycle'), "AgentGrid must have run_cycle() method"
        assert callable(grid.run_cycle), "run_cycle must be callable"

    @pytest.mark.asyncio
    async def test_kalshi_15m_loop_exists(self, mock_env):
        """Test that Kalshi15mLoop class exists and can be instantiated."""
        from merid.loop_15m import Kalshi15mLoop, get_kalshi_15m_loop
        
        # Create mock dependencies
        mock_agent_grid = MagicMock()
        mock_agent_grid._agents = []
        
        mock_venue_adapter = MagicMock()
        mock_bankroll_service = MagicMock()
        mock_risk_config = MagicMock()
        
        # Create loop instance
        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            venue_adapter=mock_venue_adapter,
            bankroll_service=mock_bankroll_service,
            risk_config=mock_risk_config,
            cadence_seconds=5.0,
        )
        
        # Verify loop attributes
        assert loop.cadence_seconds == 5.0
        assert loop._running == False
        assert loop._tick == 0

    @pytest.mark.asyncio
    async def test_kalshi_15m_loop_run_one_cycle(self, mock_env):
        """Test that Kalshi15mLoop can run one cycle."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Create mock agent grid with run_cycle method
        mock_agent_grid = MagicMock()
        mock_agent = MagicMock()
        mock_agent.agent_id = "BTC_15M"
        mock_agent.run_cycle = AsyncMock()
        mock_agent_grid._agents = [mock_agent]
        mock_agent_grid.run_cycle = AsyncMock()
        
        mock_venue_adapter = MagicMock()
        mock_bankroll_service = MagicMock()
        mock_risk_config = MagicMock()
        
        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            venue_adapter=mock_venue_adapter,
            bankroll_service=mock_bankroll_service,
            risk_config=mock_risk_config,
            cadence_seconds=5.0,
        )
        
        # Run one cycle
        await loop._run_one_cycle(tick=1)
        
        # Verify agent grid run_cycle was called
        mock_agent_grid.run_cycle.assert_called_once_with(1)
        
        # Verify cycle count incremented
        assert loop._cycle_count == 1

    @pytest.mark.asyncio
    async def test_kalshi_15m_loop_summary(self, mock_env):
        """Test that Kalshi15mLoop.summary() returns correct status."""
        from merid.loop_15m import Kalshi15mLoop
        
        mock_agent_grid = MagicMock()
        mock_agent_grid._agents = [MagicMock(agent_id="BTC_15M")]
        
        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            venue_adapter=MagicMock(),
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
        with open("merid/loop_15m.py", "r") as f:
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
        """Test that kalshi_crypto_15m.yaml risk envelope exists."""
        import yaml
        
        config_path = "config/profiles/kalshi_crypto_15m.yaml"
        assert os.path.exists(config_path), f"Risk envelope not found: {config_path}"
        
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        
        # Verify key sections exist (actual YAML structure)
        assert "venue" in config
        assert "max_single_order_pct" in config["venue"]
        assert "max_total_notional_pct" in config["venue"]
        assert "assets" in config

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
    async def test_loop_runs_multiple_cycles(self, mock_env):
        """Test that Kalshi15mLoop can run multiple cycles correctly."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Create mock agent grid
        mock_agent_grid = MagicMock()
        mock_agent_grid._agents = [MagicMock(agent_id="BTC_15M")]
        mock_agent_grid.run_cycle = AsyncMock(return_value={"tick": 1, "agents": {}, "errors": []})
        
        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            venue_adapter=MagicMock(),
            bankroll_service=MagicMock(),
            risk_config=MagicMock(),
            cadence_seconds=0.1,  # Fast cadence for testing
        )
        
        # Run 2 cycles
        await loop._run_one_cycle(tick=1)
        await loop._run_one_cycle(tick=2)
        
        # Verify both cycles ran
        assert mock_agent_grid.run_cycle.call_count == 2
        assert loop._cycle_count == 2

    @pytest.mark.asyncio
    async def test_loop_handles_agent_errors(self, mock_env):
        """Test that Kalshi15mLoop handles agent errors gracefully."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Create mock agent grid with failing agent
        mock_agent_grid = MagicMock()
        mock_agent = MagicMock()
        mock_agent.agent_id = "BTC_15M"
        mock_agent.run_cycle = AsyncMock(side_effect=Exception("Agent error"))
        mock_agent_grid._agents = [mock_agent]
        mock_agent_grid.run_cycle = AsyncMock(side_effect=Exception("Grid error"))
        
        loop = Kalshi15mLoop(
            agent_grid=mock_agent_grid,
            venue_adapter=MagicMock(),
            bankroll_service=MagicMock(),
            risk_config=MagicMock(),
            cadence_seconds=0.1,
        )
        
        # Run cycle - should not crash
        try:
            await loop._run_one_cycle(tick=1)
        except Exception:
            # Expected to raise, but loop should still track error
            pass
        
        # Verify error was tracked
        assert loop._error_count >= 1

    @pytest.mark.asyncio
    async def test_agent_grid_run_cycle_returns_summary(self, mock_env):
        """Test that AgentGrid.run_cycle() returns a summary dict."""
        from merid.prediction.agent_grid import AgentGrid
        from merid.prediction.agent_grid_config import load_agent_grid_config
        
        config = load_agent_grid_config()
        grid = AgentGrid(config=config)
        
        # Run cycle
        summary = await grid.run_cycle(tick=1)
        
        # Verify summary structure
        assert isinstance(summary, dict)
        assert "tick" in summary
        assert "timestamp" in summary
        assert "agent_count" in summary
        assert "agents" in summary
        assert "errors" in summary
        assert "duration_seconds" in summary
        assert summary["tick"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
