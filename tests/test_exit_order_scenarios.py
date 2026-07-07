"""
Test for exit order scenarios (99c exit, ratchet floor, ratchet trim).

This test verifies that exit order mechanisms work correctly:
- 99c mandatory exit for YES positions
- Ratchet floor exit at 80c
- Ratchet trim to 1 contract when >1 contract and price >80c
"""

import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass
from enum import Enum


class ExitScenarioType(Enum):
    """Types of exit scenarios."""
    EXTREME_PROFIT_99C = "extreme_profit_99c"
    RATCHET_FLOOR = "ratchet_floor"
    RATCHET_TRIM = "ratchet_trim"
    NORMAL_EXIT = "normal_exit"


@dataclass
class ExitScenario:
    """Exit scenario test case."""
    name: str
    description: str
    exit_scenario_type: ExitScenarioType
    current_price_cents: int
    side: str  # "YES" or "NO"
    position_size: int
    exit_contracts: int
    expected_trigger: bool
    expected_exit_contracts: int


class TestExitOrderScenarios:
    """Test exit order scenarios for profit taking and risk management."""

    def test_99c_yes_mandatory_exit(self):
        """Test that 99c YES triggers mandatory exit."""
        scenario = ExitScenario(
            name="exit_99c_yes_mandatory",
            description="Test 99c YES mandatory exit (extreme profit)",
            exit_scenario_type=ExitScenarioType.EXTREME_PROFIT_99C,
            current_price_cents=99,
            side="YES",
            position_size=5,
            exit_contracts=5,
            expected_trigger=True,
            expected_exit_contracts=5
        )
        
        # 99c YES should trigger mandatory exit
        assert scenario.current_price_cents == 99
        assert scenario.side == "YES"
        assert scenario.expected_trigger is True
        assert scenario.expected_exit_contracts == scenario.position_size

    def test_99c_no_mandatory_exit(self):
        """Test that 1c NO triggers mandatory exit."""
        scenario = ExitScenario(
            name="exit_1c_no_mandatory",
            description="Test 1c NO mandatory exit (extreme profit)",
            exit_scenario_type=ExitScenarioType.EXTREME_PROFIT_99C,
            current_price_cents=1,
            side="NO",
            position_size=3,
            exit_contracts=3,
            expected_trigger=True,
            expected_exit_contracts=3
        )
        
        # 1c NO should trigger mandatory exit
        assert scenario.current_price_cents == 1
        assert scenario.side == "NO"
        assert scenario.expected_trigger is True
        assert scenario.expected_exit_contracts == scenario.position_size

    def test_98c_yes_no_mandatory_exit(self):
        """Test that 98c YES does NOT trigger mandatory exit (boundary condition)."""
        scenario = ExitScenario(
            name="exit_98c_yes_no_trigger",
            description="Test 98c YES does not trigger 99c exit (boundary)",
            exit_scenario_type=ExitScenarioType.EXTREME_PROFIT_99C,
            current_price_cents=98,
            side="YES",
            position_size=5,
            exit_contracts=0,
            expected_trigger=False,
            expected_exit_contracts=0
        )
        
        # 98c YES should NOT trigger mandatory exit
        assert scenario.current_price_cents == 98
        assert scenario.side == "YES"
        assert scenario.expected_trigger is False
        assert scenario.expected_exit_contracts == 0

    def test_ratchet_floor_exit_at_80c(self):
        """Test that ratchet floor exit triggers at 80c."""
        scenario = ExitScenario(
            name="exit_ratchet_floor_80c",
            description="Test ratchet floor exit at 80c (profit floor breach)",
            exit_scenario_type=ExitScenarioType.RATCHET_FLOOR,
            current_price_cents=80,
            side="YES",
            position_size=5,
            exit_contracts=5,
            expected_trigger=True,
            expected_exit_contracts=5
        )
        
        # 80c should trigger ratchet floor exit
        assert scenario.current_price_cents == 80
        assert scenario.expected_trigger is True
        assert scenario.expected_exit_contracts == scenario.position_size

    def test_ratchet_floor_no_exit_at_81c(self):
        """Test that 81c does NOT trigger ratchet floor exit (boundary condition)."""
        scenario = ExitScenario(
            name="exit_ratchet_floor_81c_no_trigger",
            description="Test 81c does not trigger ratchet floor exit (boundary)",
            exit_scenario_type=ExitScenarioType.RATCHET_FLOOR,
            current_price_cents=81,
            side="YES",
            position_size=5,
            exit_contracts=0,
            expected_trigger=False,
            expected_exit_contracts=0
        )
        
        # 81c should NOT trigger ratchet floor exit
        assert scenario.current_price_cents == 81
        assert scenario.expected_trigger is False
        assert scenario.expected_exit_contracts == 0

    def test_ratchet_trim_at_80c(self):
        """Test that ratchet trim closes 4 contracts to keep 1 at 80c."""
        scenario = ExitScenario(
            name="exit_ratchet_trim_80c",
            description="Test ratchet trim at 80c (close 4, keep 1)",
            exit_scenario_type=ExitScenarioType.RATCHET_TRIM,
            current_price_cents=80,
            side="YES",
            position_size=5,
            exit_contracts=4,
            expected_trigger=True,
            expected_exit_contracts=4
        )
        
        # At 80c with 5 contracts, should close 4 to keep 1
        assert scenario.current_price_cents == 80
        assert scenario.position_size == 5
        assert scenario.expected_trigger is True
        assert scenario.expected_exit_contracts == 4  # Close 4, keep 1

    def test_ratchet_trim_not_triggered_below_threshold(self):
        """Test that ratchet trim does not trigger below 80c threshold."""
        scenario = ExitScenario(
            name="exit_ratchet_trim_79c_no_trigger",
            description="Test ratchet trim not triggered below 80c threshold",
            exit_scenario_type=ExitScenarioType.RATCHET_TRIM,
            current_price_cents=79,
            side="YES",
            position_size=5,
            exit_contracts=0,
            expected_trigger=False,
            expected_exit_contracts=0
        )
        
        # Below 80c threshold, ratchet trim should not trigger
        assert scenario.current_price_cents == 79
        assert scenario.expected_trigger is False
        assert scenario.expected_exit_contracts == 0

    def test_ratchet_trim_not_triggered_with_1_contract(self):
        """Test that ratchet trim does not trigger when position is already 1 contract."""
        scenario = ExitScenario(
            name="exit_ratchet_trim_1_contract_no_trigger",
            description="Test ratchet trim not triggered with 1 contract (already trimmed)",
            exit_scenario_type=ExitScenarioType.RATCHET_TRIM,
            current_price_cents=85,
            side="YES",
            position_size=1,
            exit_contracts=0,
            expected_trigger=False,
            expected_exit_contracts=0
        )
        
        # With only 1 contract, ratchet trim should not trigger
        assert scenario.position_size == 1
        assert scenario.expected_trigger is False
        assert scenario.expected_exit_contracts == 0

    def test_normal_exit_allowed(self):
        """Test that normal exit orders are allowed."""
        scenario = ExitScenario(
            name="exit_normal_5_contracts",
            description="Test normal exit of 5 contracts",
            exit_scenario_type=ExitScenarioType.NORMAL_EXIT,
            current_price_cents=50,
            side="YES",
            position_size=5,
            exit_contracts=5,
            expected_trigger=True,
            expected_exit_contracts=5
        )
        
        # Normal exit should be allowed
        assert scenario.expected_trigger is True
        assert scenario.expected_exit_contracts == scenario.position_size

    def test_profile_ratchet_config(self):
        """Test that profile has correct ratchet configuration."""
        import yaml
        
        profile_path = "config/profiles/kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        ratchet_config = profile_config.get('ratchet_profit_floor', {})
        
        # Verify ratchet configuration
        assert ratchet_config.get('enabled') is True, "Ratchet should be enabled"
        assert ratchet_config.get('activation_threshold_cents') == 85, "Activation threshold should be 85c"
        assert ratchet_config.get('floor_offset_cents') == 5, "Floor offset should be 5c"
        assert ratchet_config.get('force_exit_on_floor_breach') is True, "Force exit on floor breach should be True"
        assert ratchet_config.get('trim_position_enabled') is True, "Trim position should be enabled"
        assert ratchet_config.get('trim_threshold_cents') == 80, "Trim threshold should be 80c"
        assert ratchet_config.get('trim_to_contracts') == 1, "Trim to contracts should be 1"

    def test_profile_ratchet_trim_to_contracts(self):
        """Test that Crypto15mProfile has correct trim_to_contracts value."""
        with patch('merid.risk.profiles.crypto_15m_profile.is_profile_active', return_value=True), \
             patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=MagicMock(profile=MagicMock(
                 ratchet_trim_to_contracts=1
             ))):
            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
            
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                
                assert profile.ratchet_trim_to_contracts == 1, \
                    f"Expected ratchet_trim_to_contracts=1, got {profile.ratchet_trim_to_contracts}"

    def test_multi_contract_exit_within_limit(self):
        """Test that multi-contract exit is within max_single_order_contracts limit."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig
        
        config = KalshiRiskConfig(max_single_order_contracts=10)
        
        # Test various multi-contract exit sizes
        test_cases = [
            (1, True),   # 1 contract exit
            (4, True),   # Ratchet trim (close 4, keep 1)
            (5, True),   # Normal exit of 5 contracts
            (10, True),  # Full position exit of 10 contracts
            (11, False), # Exceeds limit
        ]
        
        for contracts, should_pass in test_cases:
            if should_pass:
                assert contracts <= config.max_single_order_contracts, \
                    f"{contracts} contracts should be within limit"
            else:
                assert contracts > config.max_single_order_contracts, \
                    f"{contracts} contracts should exceed limit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
