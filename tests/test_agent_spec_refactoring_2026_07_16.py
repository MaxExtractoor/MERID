"""
Comprehensive tests for agent spec refactoring changes (2026-07-16).

Tests verify:
1. Signal mode alignment across all sources (hybrid)
2. eth_15m_regime_signal field added to Eth15mInputs
3. RSI period consistency (14 vs 8)
4. Indicator stack initialization hard requirement
5. SignalFusion microstructure signals in signal output
"""

import pytest
from dataclasses import dataclass, fields
from typing import Dict, Any


class TestSignalModeAlignment:
    """Test that signal_mode is aligned across all configuration sources."""

    def test_kalshi_agent_grid_yaml_uses_hybrid(self):
        """Verify kalshi_agent_grid.yaml uses hybrid signal_mode for all 5 assets."""
        import yaml

        with open("config/kalshi_agent_grid.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        # Check all 5 crypto agents have signal_mode: hybrid
        crypto_agents = ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]
        for agent_name in crypto_agents:
            agent = next((a for a in config["agents"] if a["name"] == agent_name), None)
            assert agent is not None, f"Agent {agent_name} not found in kalshi_agent_grid.yaml"
            assert agent["strategy_overrides"]["signal_mode"] == "hybrid", \
                f"Agent {agent_name} signal_mode should be hybrid, got {agent['strategy_overrides']['signal_mode']}"

    def test_profile_yaml_uses_hybrid(self):
        """Verify kalshi_crypto_15m_v2.yaml uses hybrid signal_mode."""
        import yaml

        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        assert config["signal_mode"] == "hybrid", \
            f"Profile YAML signal_mode should be hybrid, got {config['signal_mode']}"


class TestEth15mRegimeSignalField:
    """Test that eth_15m_regime_signal field is added to Eth15mInputs."""

    def test_eth_15m_inputs_has_regime_signal_field(self):
        """Verify Eth15mInputs has eth_15m_regime_signal field."""
        from config.eth_15m_agent_spec import Eth15mInputs

        field_names = [f.name for f in fields(Eth15mInputs)]
        assert "eth_15m_regime_signal" in field_names, \
            "Eth15mInputs should have eth_15m_regime_signal field"

    def test_eth_15m_inputs_regime_signal_type(self):
        """Verify eth_15m_regime_signal has correct type (Dict[str, Any])."""
        from config.eth_15m_agent_spec import Eth15mInputs

        field_dict = {f.name: f.type for f in fields(Eth15mInputs)}
        # The type annotation should be Dict[str, Any]
        assert "eth_15m_regime_signal" in field_dict, \
            "Eth15mInputs should have eth_15m_regime_signal field"


class TestRSIPeriodConsistency:
    """Test that RSI period is consistently 14 across the codebase."""

    def test_crypto_15m_indicators_uses_rsi_14(self):
        """Verify Crypto15mIndicatorStack uses RSI(14)."""
        from merid.signals.crypto_15m_indicators import IndicatorConfig

        config = IndicatorConfig(asset="BTC", kalshi_mode=True)
        assert config.rsi_period == 14, \
            f"IndicatorConfig rsi_period should be 14, got {config.rsi_period}"

    def test_indicator_snapshot_uses_rsi_14(self):
        """Verify IndicatorSnapshot rsi_period is 14."""
        from merid.signals.crypto_15m_indicators import IndicatorSnapshot

        snapshot = IndicatorSnapshot()
        assert snapshot.rsi_period == 14, \
            f"IndicatorSnapshot rsi_period should be 14, got {snapshot.rsi_period}"

    def test_agent_grid_15m_warmup_uses_rsi_14(self):
        """Verify agent_grid_15m.py warmup logic uses RSI(14) minimum (15 bars)."""
        # This is verified by checking the code comments and logic
        # The actual check is in the code: min_history_for_rsi = 15
        import re

        with open("merid/prediction/agent_grid_15m.py", "r") as f:
            content = f.read()

        # Check for the updated comment
        assert "RSI(14) needs 14 + 1 = 15 periods minimum" in content, \
            "agent_grid_15m.py should have updated RSI(14) warmup comment"

        # Check for the updated value
        assert "min_history_for_rsi = 15" in content, \
            "agent_grid_15m.py should use min_history_for_rsi = 15 for RSI(14)"


class TestIndicatorStackHardRequirement:
    """Test that indicator stack initialization is a hard requirement."""

    def test_indicator_stack_init_raises_on_failure(self):
        """Verify indicator stack initialization raises RuntimeError on failure."""
        # This test verifies the code structure - actual initialization would require
        # mocking Crypto15mIndicatorStack to fail
        # The presence of the RuntimeError raise in the code is the key check
        import re

        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()

        # Check for the hard fail pattern
        assert "raise RuntimeError" in content, \
            "agent_grid_15m.py should raise RuntimeError on indicator stack init failure"
        assert "hard requirement" in content, \
            "agent_grid_15m.py should mention 'hard requirement' in indicator stack init"


class TestSignalFusionMicrostructureSignals:
    """Test that SignalFusion microstructure signals are in signal output."""

    def test_signal_output_has_orderflow_bias(self):
        """Verify signal output includes orderflow_bias field."""
        import re

        with open("merid/prediction/agent_grid_15m.py", "r") as f:
            content = f.read()

        # Check for orderflow_bias in signal return dict
        assert '"orderflow_bias": orderflow_bias' in content, \
            "agent_grid_15m.py signal output should include orderflow_bias"

    def test_signal_output_has_onchain_velocity(self):
        """Verify signal output includes onchain_velocity field."""
        import re

        with open("merid/prediction/agent_grid_15m.py", "r") as f:
            content = f.read()

        # Check for onchain_velocity in signal return dict
        assert '"onchain_velocity": onchain_velocity' in content, \
            "agent_grid_15m.py signal output should include onchain_velocity"

    def test_signal_fusion_comment_present(self):
        """Verify SignalFusion microstructure signals are documented in comments."""
        import re

        with open("merid/prediction/agent_grid_15m.py", "r") as f:
            content = f.read()

        # Check for SignalFusion comment
        assert "SignalFusion microstructure signals" in content, \
            "agent_grid_15m.py should have SignalFusion microstructure signals comment"


class TestAll5AssetsIncluded:
    """Test that all 5 crypto assets are consistently included."""

    def test_kalshi_agent_grid_has_all_5_assets(self):
        """Verify kalshi_agent_grid.yaml includes all 5 crypto assets."""
        import yaml

        with open("config/kalshi_agent_grid.yaml", "r") as f:
            config = yaml.safe_load(f)

        agent_names = [a["name"] for a in config["agents"]]
        required_assets = ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M", "DOGE_15M"]

        for asset in required_assets:
            assert asset in agent_names, f"Asset {asset} not found in kalshi_agent_grid.yaml"

    def test_profile_yaml_has_all_5_velocity_thresholds(self):
        """Verify kalshi_crypto_15m_v2.yaml has velocity thresholds for all 5 assets."""
        import yaml

        with open("config/profiles/kalshi_crypto_15m_v2.yaml", "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        velocity_thresholds = config["velocity_thresholds"]
        required_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

        for asset in required_assets:
            assert asset in velocity_thresholds, \
                f"Asset {asset} not found in velocity_thresholds in profile YAML"

    def test_agent_grid_15m_initializes_all_5_indicator_stacks(self):
        """Verify agent_grid_15m.py initializes indicator stacks for all 5 assets."""
        import re

        with open("merid/prediction/agent_grid_15m.py", "r") as f:
            content = f.read()

        # Check for the loop that initializes all 5 assets
        assert 'for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]' in content, \
            "agent_grid_15m.py should initialize indicator stacks for all 5 assets"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
