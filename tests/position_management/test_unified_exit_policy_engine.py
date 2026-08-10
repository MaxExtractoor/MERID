"""
Tests for UnifiedExitPolicyEngine
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass
from typing import Optional

from merid.position_management.unified_exit_policy_engine import (
    UnifiedExitPolicyEngine,
    ExitPolicyResolution,
    ExitPolicy,
    ExitAction,
    ExitReason,
    get_unified_exit_policy_engine,
)


@dataclass
class MockPosition:
    """Mock position for testing."""
    position_id: str = "test_position"
    side: str = "yes"
    take_profit_price_cents: Optional[int] = None
    stop_loss_price_cents: Optional[int] = None
    trailing_activated: bool = False
    trailing_stop_price_cents: Optional[int] = None
    time_since_entry_seconds: float = 0.0
    unrealized_pnl_cents: int = 0
    r_multiple: float = 0.0
    
    def update_runtime_state(self, current_price_cents: int) -> None:
        """Update runtime state."""
        self.current_price_cents = current_price_cents


class TestUnifiedExitPolicyEngine:
    """Tests for UnifiedExitPolicyEngine."""
    
    @pytest.fixture
    def engine(self):
        """Create a test engine."""
        profile_config = {
            "exit_policy_risk_reward": {
                "tp_distance_pct": {"BTC": 0.15, "ETH": 0.12},
                "sl_distance_pct": {"BTC": 0.075, "ETH": 0.06},
            },
            "exit_policy_time_exit": {
                "max_hold_minutes": 15,
            },
            "trailing_enabled": False,
            "min_edge_threshold": 0.02,
        }
        return UnifiedExitPolicyEngine(profile_config)
    
    @pytest.fixture
    def mock_position(self):
        """Create a mock position."""
        return MockPosition()
    
    def test_resolve_exit_policy_basic(self, engine):
        """Test basic exit policy resolution."""
        edge_result = Mock(confidence=0.8, net_edge_cents=5.0)
        
        resolution = engine.resolve_exit_policy(
            edge_result=edge_result,
            asset="BTC",
            regime="normal",
        )
        
        assert resolution.asset == "BTC"
        assert resolution.regime == "normal"
        assert resolution.tp_r_multiple == 0.15
        assert resolution.edge_confidence == 0.8
        assert resolution.net_edge_cents_at_entry == 5.0
        assert resolution.max_hold_seconds == 900
    
    def test_resolve_exit_policy_conservative_regime(self, engine):
        """Test conservative regime adjustments."""
        edge_result = Mock(confidence=0.7, net_edge_cents=4.0)
        
        resolution = engine.resolve_exit_policy(
            edge_result=edge_result,
            asset="BTC",
            regime="conservative",
        )
        
        # Conservative: tighter TP, wider SL, longer hold
        assert resolution.tp_r_multiple == 0.15 * 0.75  # Tighter TP
        assert resolution.max_hold_seconds == 900 * 1.5  # Longer hold
    
    def test_resolve_exit_policy_aggressive_regime(self, engine):
        """Test aggressive regime adjustments."""
        edge_result = Mock(confidence=0.9, net_edge_cents=6.0)
        
        resolution = engine.resolve_exit_policy(
            edge_result=edge_result,
            asset="BTC",
            regime="aggressive",
        )
        
        # Aggressive: wider TP, tighter SL, shorter hold
        assert resolution.tp_r_multiple == 0.15 * 1.2  # Wider TP
        assert resolution.max_hold_seconds == int(900 * 0.67)  # Shorter hold
    
    def test_resolve_exit_policy_dict_edge_result(self, engine):
        """Test with dict edge result."""
        edge_result = {"confidence": 0.75, "net_edge_cents": 4.5}
        
        resolution = engine.resolve_exit_policy(
            edge_result=edge_result,
            asset="ETH",
            regime="normal",
        )
        
        assert resolution.asset == "ETH"
        assert resolution.edge_confidence == 0.75
        assert resolution.net_edge_cents_at_entry == 4.5
    
    def test_resolve_exit_policy_none_edge_result(self, engine):
        """Test with None edge result."""
        resolution = engine.resolve_exit_policy(
            edge_result=None,
            asset="BTC",
            regime="normal",
        )
        
        assert resolution.edge_confidence is None
        assert resolution.net_edge_cents_at_entry is None
    
    def test_evaluate_exit_hold(self, engine, mock_position):
        """Test hold action when no exit conditions met."""
        policy = ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            max_hold_seconds=900,
        )
        
        result = engine.evaluate_exit(
            position=mock_position,
            current_policy=policy,
            current_price_cents=50,
            time_to_expiry_seconds=600,
        )
        
        assert result.action == ExitAction.HOLD
        assert result.reason is None
    
    def test_evaluate_exit_take_profit(self, engine, mock_position):
        """Test take-profit exit."""
        mock_position.take_profit_price_cents = 60
        mock_position.side = "yes"
        
        policy = ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            max_hold_seconds=900,
        )
        
        result = engine.evaluate_exit(
            position=mock_position,
            current_policy=policy,
            current_price_cents=65,  # Above TP
            time_to_expiry_seconds=600,
        )
        
        assert result.action == ExitAction.EXIT_MARKET
        assert result.reason == ExitReason.TAKE_PROFIT
    
    def test_evaluate_exit_stop_loss(self, engine, mock_position):
        """Stop-loss is no longer a direct EXIT_MARKET; it is a StopCandidate event."""
        mock_position.stop_loss_price_cents = 40
        mock_position.side = "yes"

        policy = ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            max_hold_seconds=900,
        )

        result = engine.evaluate_exit(
            position=mock_position,
            current_policy=policy,
            current_price_cents=35,  # Below SL
            time_to_expiry_seconds=600,
        )

        # Stop-loss direct exit is disabled; the engine holds while the StopCandidate path records.
        assert result.action == ExitAction.HOLD
        assert result.reason != ExitReason.STOP_LOSS
    
    def test_evaluate_exit_time_stop(self, engine, mock_position):
        """Test time stop exit."""
        mock_position.time_since_entry_seconds = 1000  # Exceeds max hold
        
        policy = ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            max_hold_seconds=900,
        )
        
        result = engine.evaluate_exit(
            position=mock_position,
            current_policy=policy,
            current_price_cents=50,
            time_to_expiry_seconds=600,
        )
        
        assert result.action == ExitAction.EXIT_MARKET
        assert result.reason == ExitReason.TIME_STOP
    
    def test_evaluate_exit_edge_decay(self, engine, mock_position):
        """Test edge decay exit."""
        policy = ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            max_hold_seconds=900,
        )
        
        result = engine.evaluate_exit(
            position=mock_position,
            current_policy=policy,
            current_price_cents=50,
            time_to_expiry_seconds=600,
            current_edge_pct=0.01,  # Below threshold (0.02)
        )
        
        assert result.action == ExitAction.EXIT_MARKET
        assert result.reason == ExitReason.EDGE_DECAY
    
    def test_evaluate_exit_stale_data(self, engine, mock_position):
        """Test stale data exit."""
        policy = ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            max_hold_seconds=900,
        )
        
        result = engine.evaluate_exit(
            position=mock_position,
            current_policy=policy,
            current_price_cents=50,
            time_to_expiry_seconds=600,
            md_age_ms=10000,  # 10 seconds old
            max_age_ms=5000,  # Max 5 seconds
        )
        
        assert result.action == ExitAction.EXIT_MARKET
        assert result.reason == ExitReason.STALE_DATA
    
    def test_evaluate_exit_no_side_position(self, engine):
        """Test with position without side attribute."""
        position = Mock()  # No side attribute
        position.take_profit_price_cents = None
        position.stop_loss_price_cents = None
        position.trailing_activated = False
        position.time_since_entry_seconds = 100
        
        policy = ExitPolicyResolution(
            policy_id="test",
            asset="BTC",
            regime="normal",
            tp_r_multiple=1.0,
            tp_min_cents=3,
            max_hold_seconds=900,
        )
        
        result = engine.evaluate_exit(
            position=position,
            current_policy=policy,
            current_price_cents=50,
            time_to_expiry_seconds=600,
        )
        
        # Should not crash, should return HOLD
        assert result.action == ExitAction.HOLD


class TestGetUnifiedExitPolicyEngine:
    """Tests for singleton getter."""
    
    def test_singleton_returns_same_instance(self):
        """Test that singleton returns same instance."""
        engine1 = get_unified_exit_policy_engine()
        engine2 = get_unified_exit_policy_engine()
        
        assert engine1 is engine2
    
    @patch('merid.risk.profiles.crypto_15m_profile.get_active_profile')
    def test_singleton_loads_profile_config(self, mock_get_profile):
        """Test that singleton loads profile config."""
        mock_profile = Mock()
        mock_profile.profile = {
            "exit_policy_risk_reward": {
                "tp_distance_pct": {"BTC": 0.15},
            },
        }
        mock_get_profile.return_value = mock_profile
        
        # Clear singleton to force reload
        import merid.position_management.unified_exit_policy_engine as engine_module
        engine_module._unified_exit_policy_engine = None
        
        engine = get_unified_exit_policy_engine()
        
        assert engine._profile_config == mock_profile.profile
    
    @patch('merid.risk.profiles.crypto_15m_profile.get_active_profile')
    def test_singleton_handles_profile_load_failure(self, mock_get_profile):
        """Test that singleton handles profile load failure gracefully."""
        mock_get_profile.side_effect = Exception("Profile load failed")
        
        # Clear singleton to force reload
        import merid.position_management.unified_exit_policy_engine as engine_module
        engine_module._unified_exit_policy_engine = None
        
        engine = get_unified_exit_policy_engine()
        
        # Should still return engine with empty config
        assert engine is not None
        assert engine._profile_config == {}
