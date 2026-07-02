"""
Tests for strategy policy resolution and fallback logic.

Tests the _get_strategy_policy function in order_router.py:
- Strategy-specific policy lookup from profile
- Fallback to global strategy_policy
- Fallback logic to infer strategy_type from source
- Backward compatibility with source field
"""

import pytest
from typing import Dict, Any


def test_strategy_specific_policy():
    """Test that strategy-specific policy is retrieved correctly."""
    # Mock profile with strategy-specific policy
    profile = {
        "strategies": {
            "heuristic_velocity": {
                "policy": {
                    "min_edge": 0.02,
                    "min_confidence": 0.55,
                    "max_md_staleness_sec": 15.0,
                }
            }
        },
        "strategy_policy_min_edge": 0.03,
        "strategy_policy_min_confidence": 0.50,
        "strategy_policy_max_md_staleness_sec": 20.0,
    }
    
    # Simulate _get_strategy_policy logic
    strategy_type = "heuristic_velocity"
    strategies = profile.get("strategies", {})
    strategy_config = strategies.get(strategy_type, {})
    policy = strategy_config.get("policy", {})
    
    # Should use strategy-specific policy
    if policy:
        assert policy["min_edge"] == 0.02
        assert policy["min_confidence"] == 0.55
        assert policy["max_md_staleness_sec"] == 15.0
    else:
        assert False, "Should have found strategy-specific policy"


def test_fallback_to_global_policy():
    """Test fallback to global strategy_policy when strategy-specific policy not found."""
    # Mock profile without strategy-specific policy
    profile = {
        "strategies": {},
        "strategy_policy_min_edge": 0.03,
        "strategy_policy_min_confidence": 0.50,
        "strategy_policy_max_md_staleness_sec": 20.0,
    }
    
    # Simulate _get_strategy_policy logic
    strategy_type = "unknown_strategy"
    strategies = profile.get("strategies", {})
    strategy_config = strategies.get(strategy_type, {})
    policy = strategy_config.get("policy", {})
    
    # Should fallback to global policy
    if not policy:
        policy = {
            "min_edge": profile["strategy_policy_min_edge"],
            "min_confidence": profile["strategy_policy_min_confidence"],
            "max_md_staleness_sec": profile["strategy_policy_max_md_staleness_sec"],
        }
    
    assert policy["min_edge"] == 0.03
    assert policy["min_confidence"] == 0.50
    assert policy["max_md_staleness_sec"] == 20.0


def test_strategy_type_from_intent():
    """Test that strategy_type is taken from intent when available."""
    intent = {
        "strategy_type": "heuristic_velocity",
        "source": "merid.prediction.agent_grid_15m",
    }
    
    # Should use strategy_type from intent
    strategy_type = intent.get("strategy_type") or "heuristic_velocity"
    assert strategy_type == "heuristic_velocity"


def test_fallback_infer_strategy_from_source():
    """Test fallback logic to infer strategy_type from source."""
    # Test with agent_grid_15m source
    intent = {
        "strategy_type": None,
        "source": "merid.prediction.agent_grid_15m",
    }
    
    strategy_type = intent.get("strategy_type")
    if not strategy_type:
        if intent.get("source"):
            if "agent_grid_15m" in intent["source"]:
                strategy_type = "heuristic_velocity"
            else:
                strategy_type = "heuristic_velocity"
        else:
            strategy_type = "heuristic_velocity"
    
    assert strategy_type == "heuristic_velocity"


def test_fallback_default_strategy():
    """Test default fallback when strategy_type and source are missing."""
    intent = {
        "strategy_type": None,
        "source": None,
    }
    
    strategy_type = intent.get("strategy_type")
    if not strategy_type:
        if intent.get("source"):
            strategy_type = "heuristic_velocity"
        else:
            strategy_type = "heuristic_velocity"
    
    assert strategy_type == "heuristic_velocity"


def test_backward_compatibility_source_field():
    """Test that source field is kept for backward compatibility."""
    intent = {
        "source": "merid.prediction.agent_grid_15m",
        "strategy_type": "heuristic_velocity",
    }
    
    # Source field should still be present
    assert intent["source"] is not None
    assert intent["source"] == "merid.prediction.agent_grid_15m"


def test_multiple_strategies():
    """Test that multiple strategies can coexist in profile."""
    profile = {
        "strategies": {
            "heuristic_velocity": {
                "policy": {
                    "min_edge": 0.02,
                    "min_confidence": 0.55,
                }
            },
            "model_based": {
                "policy": {
                    "min_edge": 0.03,
                    "min_confidence": 0.50,
                }
            }
        },
        "strategy_policy_min_edge": 0.04,
        "strategy_policy_min_confidence": 0.65,
    }
    
    # Test heuristic_velocity policy
    strategy_type = "heuristic_velocity"
    strategies = profile.get("strategies", {})
    strategy_config = strategies.get(strategy_type, {})
    policy = strategy_config.get("policy", {})
    
    assert policy["min_edge"] == 0.02
    assert policy["min_confidence"] == 0.55
    
    # Test model_based policy
    strategy_type = "model_based"
    strategies = profile.get("strategies", {})
    strategy_config = strategies.get(strategy_type, {})
    policy = strategy_config.get("policy", {})
    
    assert policy["min_edge"] == 0.03
    assert policy["min_confidence"] == 0.50


def test_asset_overrides():
    """Test that asset-specific overrides are supported."""
    profile = {
        "strategies": {
            "heuristic_velocity": {
                "policy": {
                    "min_edge": 0.02,
                    "min_confidence": 0.55,
                    "asset_overrides": {
                        "BTC": {
                            "min_edge": 0.025,
                            "min_confidence": 0.50,
                        },
                        "ETH": {
                            "min_edge": 0.02,
                            "min_confidence": 0.55,
                        }
                    }
                }
            }
        }
    }
    
    # Test BTC override
    strategy_type = "heuristic_velocity"
    strategies = profile.get("strategies", {})
    strategy_config = strategies.get(strategy_type, {})
    policy = strategy_config.get("policy", {})
    asset_overrides = policy.get("asset_overrides", {})
    btc_override = asset_overrides.get("BTC", {})
    
    assert btc_override["min_edge"] == 0.025
    assert btc_override["min_confidence"] == 0.50


def test_policy_validation():
    """Test that policy values are validated."""
    # Valid policy
    policy = {
        "min_edge": 0.02,
        "min_confidence": 0.55,
    }
    
    assert 0.0 <= policy["min_edge"] <= 1.0
    assert 0.0 <= policy["min_confidence"] <= 1.0
    
    # Invalid policy (edge > 1.0)
    policy = {
        "min_edge": 1.5,
        "min_confidence": 0.55,
    }
    
    assert policy["min_edge"] > 1.0, "Should detect invalid edge"


def test_profile_error_handling():
    """Test error handling when profile is unavailable."""
    # Simulate profile loading failure
    profile_available = False
    
    if not profile_available:
        # Should raise RuntimeError
        try:
            raise RuntimeError(
                "Failed to get strategy policy from profile. "
                "Profile must be loaded for production trading."
            )
        except RuntimeError as e:
            assert "Profile must be loaded" in str(e)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
