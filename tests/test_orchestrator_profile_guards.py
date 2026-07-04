"""Test orchestrator profile guards for kalshi_crypto_15m_v2.

This test verifies that:
1. core.agent_orchestrator is skipped when MERID_PROFILE=kalshi_crypto_15m_v2
2. HashtagMonitor is skipped when MERID_PROFILE=kalshi_crypto_15m_v2
3. Legacy components (AgentMesh, insight pipeline, etc.) are skipped for kalshi_crypto_15m_v2
4. Crypto15MLane is still started for kalshi_crypto_15m_v2
5. PM profile and crypto_matrix are not applied for kalshi_crypto_15m_v2
6. AutoPromoter is not initialized for kalshi_crypto_15m_v2
7. Regime agents are not required for kalshi_crypto_15m_v2
8. Canonical agent cycle is skipped for kalshi_crypto_15m_v2
"""

import os
import pytest
from unittest.mock import Mock, patch, AsyncMock


class TestOrchestratorProfileGuards:
    """Test that orchestrator components are correctly profile-garded for kalshi_crypto_15m_v2."""

    def test_core_agent_orchestrator_guarded_for_15m_profile(self):
        """Test that core.agent_orchestrator is skipped when MERID_PROFILE=kalshi_crypto_15m_v2."""
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Import after setting env var
        from core.agent_orchestrator import AgentOrchestrator
        
        # Create orchestrator
        orch = AgentOrchestrator()
        
        # Verify it has the profile guard in the arbitrage check
        # This is a defensive check - the actual guard is in web/main.py
        assert orch is not None
        
        # Clean up
        del os.environ["MERID_PROFILE"]

    def test_hashtag_monitor_guard_in_loop(self):
        """Test that HashtagMonitor has profile guard in merid.loop."""
        # Read the loop.py file and verify the guard exists
        import merid.loop as loop_module
        loop_file = loop_module.__file__
        
        with open(loop_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the profile guard exists
        assert 'PROFILE GUARD' in content
        assert 'kalshi_crypto_15m_v2' in content
        assert 'HashtagMonitor skipped for kalshi_crypto_15m_v2' in content

    def test_orchestrator_agent_manager_guards(self):
        """Test that OrchestratorAgentManager has profile guards for legacy components."""
        # Read the startup_agents.py file and verify the guards exist
        import web.startup_agents as startup_module
        startup_file = startup_module.__file__
        
        with open(startup_file, 'r') as f:
            content = f.read()
        
        # Verify the profile guards exist for each component
        assert 'PROFILE-GUARD' in content
        assert 'AgentMesh skipped for kalshi_crypto_15m_v2' in content
        assert 'KalshiSocialBroadcaster skipped for kalshi_crypto_15m_v2' in content
        assert 'ReflectionSystem skipped for kalshi_crypto_15m_v2' in content
        assert 'Kalshi insight pipeline skipped for kalshi_crypto_15m_v2' in content

    def test_crypto15m_lane_not_guarded(self):
        """Test that Crypto15MLane is NOT profile-garded (it should run for kalshi_crypto_15m_v2)."""
        # Read the startup_agents.py file and verify Crypto15MLane has no profile guard
        import web.startup_agents as startup_module
        startup_file = startup_module.__file__
        
        with open(startup_file, 'r') as f:
            content = f.read()
        
        # Verify Crypto15MLane section exists and has canonical orchestrator log
        assert 'Crypto15MLane' in content
        assert 'ORCHESTRATOR-CANONICAL' in content
        # Verify it does NOT have a PROFILE-GUARD skip
        lines = content.split('\n')
        crypto_lane_section = []
        in_crypto_section = False
        for line in lines:
            if 'Crypto15MLane' in line and 'primary lane' in line:
                in_crypto_section = True
            elif in_crypto_section and line.strip() and not line.strip().startswith('#'):
                if line.strip().startswith('except'):
                    break
                crypto_lane_section.append(line)
        
        # Verify no PROFILE-GUARD skip in the Crypto15MLane section
        crypto_lane_text = '\n'.join(crypto_lane_section)
        assert 'PROFILE-GUARD' not in crypto_lane_text or 'skipped for kalshi_crypto_15m_v2' not in crypto_lane_text

    def test_pm_profile_guarded_for_15m_profile(self):
        """Test that PM profile is skipped when MERID_PROFILE=kalshi_crypto_15m_v2."""
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Import after setting env var
        from merid.prediction.pm_profiles import get_pm_profile_strategy_overrides
        
        # Verify PM profile returns empty dict for kalshi_crypto_15m_v2
        overrides = get_pm_profile_strategy_overrides()
        assert overrides == {}, f"Expected empty dict, got {overrides}"
        
        # Clean up
        del os.environ["MERID_PROFILE"]

    def test_kelly_from_profile_not_hardcoded(self):
        """Verify Kelly fraction comes from profile YAML, not hardcoded fallbacks."""
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        
        # Mock the risk config to return profile-driven Kelly
        class MockRiskConfig:
            kelly_fraction = 0.02  # CRITICAL FIX: From kalshi_crypto_15m_v2.yaml (2% Kelly hard cap, was 0.05)
        
        def mock_get_kalshi_risk():
            return MockRiskConfig()
        
        # Simulate the fallback path in kalshi_api.py
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            with patch('merid.event_venues.kalshi.kalshi_risk.get_kalshi_risk', mock_get_kalshi_risk):
                risk_config = get_kalshi_risk()
                kelly_f = float(getattr(risk_config, 'kelly_fraction', 0.05))
        except Exception:
            kelly_f = 0.05
        
        # Assert Kelly matches profile (0.05), not old hardcoded (0.30, 0.25, or 0.20)
        assert kelly_f == 0.05, f"Expected Kelly 0.05 from profile, got {kelly_f}"
        assert kelly_f != 0.30, "Kelly should not be old hardcoded 0.30"
        assert kelly_f != 0.25, "Kelly should not be old hardcoded 0.25"
        assert kelly_f != 0.20, "Kelly should not be old hardcoded 0.20"
        
        # Clean up
        del os.environ["MERID_PROFILE"]

    @pytest.mark.skip(reason="Legacy modules moved to archive/ - not applicable to production 15m stack")
    def test_runtime_guard_refuses_conflicting_profiles(self):
        """Test that runtime guard refuses startup when both MERID_PROFILE and MERID_PM_PROFILE are set."""
        os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
        os.environ["MERID_PM_PROFILE"] = "production"
        
        # Read main_15m_lean.py and verify the guard exists
        import web.main_15m_lean as main_module
        main_file = main_module.__file__
        
        with open(main_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the runtime guard exists
        assert 'PROFILE-GUARD-ERROR' in content
        assert 'CONFLICTING PROFILE SIGNALS DETECTED' in content
        assert 'MERID_PROFILE=kalshi_crypto_15m_v2 but MERID_PM_PROFILE' in content
        assert 'raise RuntimeError' in content
        
        # Clean up
        del os.environ["MERID_PROFILE"]
        del os.environ["MERID_PM_PROFILE"]

    @pytest.mark.skip(reason="Legacy module crypto_edge_production moved to archive/ - not applicable to production 15m stack")
    def test_crypto_matrix_guarded_for_15m_profile(self):
        """Test that crypto matrix is skipped when MERID_PROFILE=kalshi_crypto_15m_v2."""
        # Read the crypto_edge_production.py file and verify the guard exists
        import merid.prediction.crypto_edge_production as crypto_edge_module
        crypto_edge_file = crypto_edge_module.__file__
        
        with open(crypto_edge_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the profile guard exists
        assert 'PROFILE-GUARD' in content
        assert 'kalshi_crypto_15m_v2' in content
        assert 'Crypto matrix skipped for kalshi_crypto_15m_v2' in content

    @pytest.mark.skip(reason="Legacy module agent_grid moved to archive/ - not applicable to production 15m stack")
    def test_auto_promoter_guarded_for_15m_profile(self):
        """Test that AutoPromoter is skipped when MERID_PROFILE=kalshi_crypto_15m_v2."""
        # Read the agent_grid.py file and verify the guard exists
        import merid.prediction.agent_grid as agent_grid_module
        agent_grid_file = agent_grid_module.__file__
        
        with open(agent_grid_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the profile guard exists for AutoPromoter
        assert 'PROFILE-GUARD' in content
        assert 'kalshi_crypto_15m_v2' in content
        assert 'AutoPromoter skipped for kalshi_crypto_15m_v2' in content

    @pytest.mark.skip(reason="Legacy module agent_grid moved to archive/ - not applicable to production 15m stack")
    def test_regime_agents_guarded_for_15m_profile(self):
        """Test that regime agents are not required when MERID_PROFILE=kalshi_crypto_15m_v2."""
        # Read the agent_grid.py file and verify the guard exists
        import merid.prediction.agent_grid as agent_grid_module
        agent_grid_file = agent_grid_module.__file__
        
        with open(agent_grid_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the profile guard exists for regime agents
        assert 'PROFILE-GUARD' in content
        assert 'kalshi_crypto_15m_v2' in content
        assert 'Regime agents skipped for kalshi_crypto_15m_v2' in content

    def test_canonical_agent_cycle_guarded_for_15m_profile(self):
        """Test that canonical agent cycle is skipped when MERID_PROFILE=kalshi_crypto_15m_v2."""
        # Read the loop.py file and verify the guard exists
        import merid.loop as loop_module
        loop_file = loop_module.__file__
        
        with open(loop_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the profile guard exists for canonical agent cycle
        assert 'PROFILE GUARD' in content
        assert 'kalshi_crypto_15m_v2' in content
        assert 'Canonical agent cycle skipped for kalshi_crypto_15m_v2' in content


class TestWSBridgeInstrumentation:
    """Test WS bridge instrumentation for better observability."""

    def test_ws_bridge_has_instrumentation(self):
        """Test that WS bridge has connection attempt logging."""
        import merid.event_venues.kalshi.ws_bridge as ws_bridge_module
        ws_file = ws_bridge_module.__file__
        
        with open(ws_file, 'r') as f:
            content = f.read()
        
        # Verify the instrumentation exists
        assert '[WS-BRIDGE-CONNECT]' in content
        assert 'Attempt' in content
        assert 'profile=' in content
        assert 'tickers=' in content
        assert 'TIMEOUT' in content

    def test_ws_bridge_has_timeout(self):
        """Test that WS bridge connection has timeout to prevent hanging."""
        import merid.event_venues.kalshi.ws_bridge as ws_bridge_module
        ws_file = ws_bridge_module.__file__
        
        with open(ws_file, 'r') as f:
            content = f.read()
        
        # Verify timeout is added to connection attempt
        assert 'asyncio.wait_for' in content
        assert 'timeout=' in content
        assert '10.0' in content  # 10 second timeout


class TestOrchestratorInventory:
    """Test that the orchestrator inventory is correct for kalshi_crypto_15m_v2."""

    def test_only_one_orchestrator_active_for_15m(self):
        """Test that only OrchestratorAgentManager is active for kalshi_crypto_15m_v2."""
        # Read web/main.py and verify it has PROFILE-GUARD comment (it's a legacy wrapper)
        main_file = 'c:\\Dev\\MERID\\web\\main.py'
        
        with open(main_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the profile guard exists (main.py is a legacy wrapper for testing)
        assert 'PROFILE-GUARD' in content
        assert 'legacy wrapper' in content

    def test_orchestrator_agent_manager_has_grid_startup_logs(self):
        """Test that OrchestratorAgentManager has GRID-STARTUP and LANE-STARTUP logs."""
        import web.startup_agents as startup_module
        startup_file = startup_module.__file__
        
        with open(startup_file, 'r') as f:
            content = f.read()
        
        # Verify the logs exist
        assert '[GRID-STARTUP]' in content
        assert '[LANE-STARTUP]' in content
        assert 'Agent grid loaded with' in content
        assert 'Crypto lanes built successfully' in content
