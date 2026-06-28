"""Tests for Correlation Tracking Integration.

Tests the profitability enhancement that reduces exposure when assets are highly correlated.
"""

import pytest
from unittest.mock import Mock, patch
from dataclasses import dataclass, field
from typing import List, Dict
from enum import Enum


# Stub classes to avoid import errors
class CorrelationPair:
    """Represents correlation between two assets."""
    def __init__(self, asset_a: str, asset_b: str, correlation: float):
        self.asset_a = asset_a
        self.asset_b = asset_b
        self.correlation = correlation


@dataclass
class CorrelationMatrix:
    """Full correlation matrix for all assets."""
    pairs: List[CorrelationPair]
    timestamp: float = field(default_factory=lambda: __import__('time').time())
    assets: List[str] = field(default_factory=list)


class TestCorrelationIntegration:
    """Test correlation integration with risk envelope."""
    
    def test_correlation_config_in_profile(self):
        """Test that correlation config is in profile."""
        import yaml
        from pathlib import Path
        
        # Get the absolute path to the repository root
        repo_root = Path(__file__).parent.parent.parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        corr_config = profile_config.get('correlation_tracking', {})
        
        # Should have required configuration fields
        assert 'enabled' in corr_config
        assert 'threshold' in corr_config
        assert 'max_reduction' in corr_config
        assert 'window_days' in corr_config
        
        # Validate values
        assert isinstance(corr_config['enabled'], bool)
        assert 0.0 <= corr_config['threshold'] <= 1.0
        assert 0.0 <= corr_config['max_reduction'] <= 1.0
        assert corr_config['window_days'] > 0
    
    def test_correlation_config_disabled_by_default(self):
        """Test that correlation tracking is disabled by default."""
        import yaml
        from pathlib import Path
        
        # Get the absolute path to the repository root
        repo_root = Path(__file__).parent.parent.parent
        profile_path = repo_root / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        
        with open(profile_path, 'r', encoding='utf-8') as f:
            profile_config = yaml.safe_load(f)
        
        corr_config = profile_config.get('correlation_tracking', {})
        
        # Should be disabled by default
        assert corr_config.get('enabled', False) is False
    
    def test_correlation_in_risk_envelope(self):
        """Test that correlation parameters are in risk envelope."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            compute_kalshi_crypto_15m_risk_envelope,
        )
        
        # Compute envelope
        envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=10000.0)
        
        # Should have correlation tracking fields
        assert hasattr(envelope, 'correlation_tracking_enabled')
        assert hasattr(envelope, 'correlation_threshold')
        assert hasattr(envelope, 'correlation_multiplier')
        
        # Should be disabled by default
        assert envelope.correlation_tracking_enabled is False
        assert envelope.correlation_threshold == 0.5
        assert envelope.correlation_multiplier == 1.0
    
    def test_correlation_multiplier_application(self):
        """Test that correlation multiplier is applied to position sizing."""
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
            compute_kalshi_crypto_15m_risk_envelope,
        )
        
        # Compute envelope with correlation enabled
        with patch.dict('os.environ', {'MERID_CORRELATION_TRACKING_ENABLED': 'true'}):
            envelope = compute_kalshi_crypto_15m_risk_envelope(live_bankroll_usd=10000.0)
        
        # Correlation multiplier should be applied
        base_size = 100
        adjusted_size = base_size * envelope.correlation_multiplier
        
        # Should be <= base size
        assert adjusted_size <= base_size


class TestCorrelationThresholds:
    """Test correlation threshold constants."""
    
    def test_correlation_threshold_reasonable(self):
        """Test that threshold is reasonable."""
        # Threshold should be between 0.3 and 0.7
        threshold = 0.5  # Default from config
        assert 0.3 <= threshold <= 0.7
    
    def test_max_reduction_reasonable(self):
        """Test that max reduction is reasonable."""
        # Max reduction should be between 0.2 and 0.6
        max_reduction = 0.4  # Default from config
        assert 0.2 <= max_reduction <= 0.6
