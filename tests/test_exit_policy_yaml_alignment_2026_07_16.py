"""Tests for exit policy YAML alignment fixes (2026-07-16).

CRITICAL FIX: Updated all YAML configurations to align with 2:1 risk/reward ratio
- kalshi_agent_grid.yaml: time_based_r_multiple (0.8R, 0.6R, 0.4R), trailing_giveback_cents (5)
- kalshi_crypto_hedging.yaml: TP/SL values (0.8R, 1.6R, 0.4R)
"""

import pytest
from pathlib import Path
import yaml


class TestAgentGridYAMLAlignment:
    """Test that kalshi_agent_grid.yaml has correct exit policy values."""
    
    @pytest.fixture
    def agent_grid_config(self):
        """Load kalshi_agent_grid.yaml."""
        config_path = Path("config/kalshi_agent_grid.yaml")
        if not config_path.exists():
            pytest.skip("kalshi_agent_grid.yaml not found")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def test_time_based_r_multiple_values(self, agent_grid_config):
        """Verify time_based_r_multiple values align with 2:1 risk/reward ratio.
        
        CRITICAL FIX 2026-07-16: Values should be (0.8, 0.6, 0.4) not (1.0, 0.75, 0.5)
        """
        agents = agent_grid_config.get('agents', [])
        
        for agent in agents:
            take_profit = agent.get('take_profit', {})
            time_based = take_profit.get('time_based_r_multiple', {})
            
            # Verify new values
            assert time_based.get('over_7_min') == 0.8, \
                f"Agent {agent['name']}: over_7_min should be 0.8, got {time_based.get('over_7_min')}"
            assert time_based.get('between_4_7_min') == 0.6, \
                f"Agent {agent['name']}: between_4_7_min should be 0.6, got {time_based.get('between_4_7_min')}"
            assert time_based.get('under_4_min') == 0.4, \
                f"Agent {agent['name']}: under_4_min should be 0.4, got {time_based.get('under_4_min')}"
    
    def test_trailing_giveback_cents(self, agent_grid_config):
        """Verify trailing_giveback_cents is 5 cents, not 3 cents.
        
        CRITICAL FIX 2026-07-16: Updated from 3 to 5 to match profile
        """
        agents = agent_grid_config.get('agents', [])
        
        for agent in agents:
            take_profit = agent.get('take_profit', {})
            giveback = take_profit.get('trailing_giveback_cents')
            
            assert giveback == 5, \
                f"Agent {agent['name']}: trailing_giveback_cents should be 5, got {giveback}"
    
    def test_all_crypto_15m_agents_updated(self, agent_grid_config):
        """Verify all 5 crypto 15m agents have updated values."""
        agents = agent_grid_config.get('agents', [])
        crypto_15m_agents = [a for a in agents if a['name'].endswith('_15M')]
        
        assert len(crypto_15m_agents) == 5, \
            f"Expected 5 crypto 15m agents, found {len(crypto_15m_agents)}"
        
        expected_agents = {'BTC_15M', 'ETH_15M', 'SOL_15M', 'XRP_15M', 'DOGE_15M'}
        actual_agents = {a['name'] for a in crypto_15m_agents}
        
        assert actual_agents == expected_agents, \
            f"Expected agents {expected_agents}, found {actual_agents}"


class TestHedgingYAMLAlignment:
    """Test that kalshi_crypto_hedging.yaml has correct TP/SL values."""
    
    @pytest.fixture
    def hedging_config(self):
        """Load kalshi_crypto_hedging.yaml."""
        config_path = Path("config/kalshi_crypto_hedging.yaml")
        if not config_path.exists():
            pytest.skip("kalshi_crypto_hedging.yaml not found")
        
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    def test_take_profit_values(self, hedging_config):
        """Verify take profit values align with 2:1 risk/reward ratio.
        
        CRITICAL FIX 2026-07-16: Values should be (0.8, 1.6, 0.4) not (2.0, 4.0, 1.5)
        """
        take_profit = hedging_config.get('hedging', {}).get('take_profit', {})
        
        for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
            asset_config = take_profit.get(asset, {})
            
            assert asset_config.get('tp_1') == 0.8, \
                f"{asset}: tp_1 should be 0.8, got {asset_config.get('tp_1')}"
            assert asset_config.get('tp_2') == 1.6, \
                f"{asset}: tp_2 should be 1.6, got {asset_config.get('tp_2')}"
            assert asset_config.get('stop_loss') == 0.4, \
                f"{asset}: stop_loss should be 0.4, got {asset_config.get('stop_loss')}"
    
    def test_all_crypto_assets_present(self, hedging_config):
        """Verify all 5 crypto assets are present in hedging config."""
        take_profit = hedging_config.get('hedging', {}).get('take_profit', {})
        
        expected_assets = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
        # Filter out non-asset keys like 'enabled'
        actual_assets = {k for k in take_profit.keys() if k in expected_assets}
        
        assert actual_assets == expected_assets, \
            f"Expected assets {expected_assets}, found {actual_assets}"


class TestYAMLConsistency:
    """Test consistency between YAML files and code defaults."""
    
    def test_agent_grid_vs_profile_consistency(self):
        """Verify agent grid trailing_giveback_cents matches profile."""
        # Load agent grid
        agent_grid_path = Path("config/kalshi_agent_grid.yaml")
        if not agent_grid_path.exists():
            pytest.skip("kalshi_agent_grid.yaml not found")
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            agent_grid = yaml.safe_load(f)
        
        # Get trailing_giveback_cents from first agent
        agents = agent_grid.get('agents', [])
        if not agents:
            pytest.skip("No agents in agent grid")
        
        agent_giveback = agents[0].get('take_profit', {}).get('trailing_giveback_cents')
        
        # Load profile
        try:
            from merid.risk.profiles.crypto_15m_profile import get_active_profile
            profile = get_active_profile().profile
            profile_giveback = profile.trailing_stop_giveback_cents
        except Exception:
            pytest.skip("Profile not available")
        
        assert agent_giveback == profile_giveback, \
            f"Agent grid giveback ({agent_giveback}) != profile giveback ({profile_giveback})"
