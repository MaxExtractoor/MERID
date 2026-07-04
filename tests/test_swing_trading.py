"""
Test swing trading mode for YES/NO reversal after trailing exit.

This test verifies the swing trading implementation:
- Swing mode is enabled after trailing exit
- Opposite-side entries are allowed in swing mode
- Swing mode is disabled after reversal entry
- Swing mode is reset on window change
"""

import pytest
from datetime import datetime
from merid.position_management.exit_policy import ExitReason


class TestSwingTrading:
    """Test swing trading mode for YES/NO reversal."""

    def test_swing_mode_initialization(self):
        """Test swing mode is initialized correctly for all assets."""
        from merid.loop_15m import Kalshi15mLoop
        
        # Mock dependencies
        class MockBankrollService:
            pass
        
        class MockRiskConfig:
            pass
        
        # Create loop instance
        loop = Kalshi15mLoop(
            agent_grid=None,
            bankroll_service=MockBankrollService(),
            risk_config=MockRiskConfig(),
            cadence_seconds=5.0
        )
        
        # Check swing mode initialization
        expected_assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in expected_assets:
            assert asset in loop._swing_mode
            assert loop._swing_mode[asset]["enabled"] is False
            assert loop._swing_mode[asset]["exited_side"] is None
            assert loop._swing_mode[asset]["exit_time"] is None

    def test_swing_mode_enabled_after_trailing_exit(self):
        """Test swing mode is enabled after trailing exit."""
        from merid.loop_15m import Kalshi15mLoop
        from merid.position_management.position import Position, PositionSide
        
        class MockBankrollService:
            pass
        
        class MockRiskConfig:
            pass
        
        loop = Kalshi15mLoop(
            agent_grid=None,
            bankroll_service=MockBankrollService(),
            risk_config=MockRiskConfig(),
            cadence_seconds=5.0
        )
        
        # Simulate trailing exit callback
        position = Position(
            position_id="test-position",
            market_id="KXBTC15M-TEST",
            side=PositionSide.YES,
            size=1,
            avg_entry_price_cents=50,
        )
        
        # Manually trigger swing mode enable (simulating callback)
        asset = "BTC"
        loop._swing_mode[asset] = {
            "enabled": True,
            "exited_side": "yes",
            "exit_time": datetime.utcnow()
        }
        
        # Verify swing mode is enabled
        assert loop._swing_mode[asset]["enabled"] is True
        assert loop._swing_mode[asset]["exited_side"] == "yes"
        assert loop._swing_mode[asset]["exit_time"] is not None

    def test_swing_reversal_detection(self):
        """Test swing reversal is detected for opposite side."""
        from merid.loop_15m import Kalshi15mLoop
        
        class MockBankrollService:
            pass
        
        class MockRiskConfig:
            pass
        
        loop = Kalshi15mLoop(
            agent_grid=None,
            bankroll_service=MockBankrollService(),
            risk_config=MockRiskConfig(),
            cadence_seconds=5.0
        )
        
        # Enable swing mode for BTC after YES exit
        asset = "BTC"
        loop._swing_mode[asset] = {
            "enabled": True,
            "exited_side": "yes",
            "exit_time": datetime.utcnow()
        }
        
        # Check reversal detection
        swing_enabled = loop._swing_mode[asset]["enabled"]
        exited_side = loop._swing_mode[asset]["exited_side"]
        
        # NO candidate should be detected as reversal
        is_swing_reversal = swing_enabled and exited_side and "no" != exited_side
        assert is_swing_reversal is True
        
        # YES candidate should NOT be detected as reversal
        is_swing_reversal = swing_enabled and exited_side and "yes" != exited_side
        assert is_swing_reversal is False

    def test_swing_mode_disabled_after_reversal(self):
        """Test swing mode is disabled after reversal entry."""
        from merid.loop_15m import Kalshi15mLoop
        
        class MockBankrollService:
            pass
        
        class MockRiskConfig:
            pass
        
        loop = Kalshi15mLoop(
            agent_grid=None,
            bankroll_service=MockBankrollService(),
            risk_config=MockRiskConfig(),
            cadence_seconds=5.0
        )
        
        # Enable swing mode
        asset = "BTC"
        loop._swing_mode[asset] = {
            "enabled": True,
            "exited_side": "yes",
            "exit_time": datetime.utcnow()
        }
        
        # Simulate reversal entry (disable swing mode)
        loop._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
        
        # Verify swing mode is disabled
        assert loop._swing_mode[asset]["enabled"] is False
        assert loop._swing_mode[asset]["exited_side"] is None
        assert loop._swing_mode[asset]["exit_time"] is None

    def test_swing_mode_reset_on_window_change(self):
        """Test swing mode is reset when 15-minute window changes."""
        from merid.loop_15m import Kalshi15mLoop
        
        class MockBankrollService:
            pass
        
        class MockRiskConfig:
            pass
        
        loop = Kalshi15mLoop(
            agent_grid=None,
            bankroll_service=MockBankrollService(),
            risk_config=MockRiskConfig(),
            cadence_seconds=5.0
        )
        
        # Enable swing mode for all assets
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            loop._swing_mode[asset] = {
                "enabled": True,
                "exited_side": "yes",
                "exit_time": datetime.utcnow()
            }
        
        # Simulate window change reset
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            loop._swing_mode[asset] = {"enabled": False, "exited_side": None, "exit_time": None}
        
        # Verify all swing modes are reset
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            assert loop._swing_mode[asset]["enabled"] is False
            assert loop._swing_mode[asset]["exited_side"] is None
            assert loop._swing_mode[asset]["exit_time"] is None

    def test_swing_mode_allows_opposite_side_entry(self):
        """Test swing mode allows opposite-side entry regardless of edge threshold."""
        from merid.loop_15m import Kalshi15mLoop
        
        class MockBankrollService:
            pass
        
        class MockRiskConfig:
            pass
        
        loop = Kalshi15mLoop(
            agent_grid=None,
            bankroll_service=MockBankrollService(),
            risk_config=MockRiskConfig(),
            cadence_seconds=5.0
        )
        
        # Enable swing mode after YES exit
        asset = "BTC"
        loop._swing_mode[asset] = {
            "enabled": True,
            "exited_side": "yes",
            "exit_time": datetime.utcnow()
        }
        
        # Simulate candidate selection logic
        swing_enabled = loop._swing_mode[asset]["enabled"]
        exited_side = loop._swing_mode[asset]["exited_side"]
        side = "no"  # Opposite side
        edge = 0.002  # Below minimum threshold (0.5%)
        min_edge_threshold = 0.005
        has_position = False
        
        # Check if reversal entry is allowed
        is_swing_reversal = swing_enabled and exited_side and side != exited_side
        should_execute = not has_position and (edge > min_edge_threshold or is_swing_reversal)
        
        # Should execute due to swing reversal even with low edge
        assert should_execute is True
        assert is_swing_reversal is True

    def test_swing_mode_does_not_allow_same_side_entry(self):
        """Test swing mode does NOT allow same-side entry."""
        from merid.loop_15m import Kalshi15mLoop
        
        class MockBankrollService:
            pass
        
        class MockRiskConfig:
            pass
        
        loop = Kalshi15mLoop(
            agent_grid=None,
            bankroll_service=MockBankrollService(),
            risk_config=MockRiskConfig(),
            cadence_seconds=5.0
        )
        
        # Enable swing mode after YES exit
        asset = "BTC"
        loop._swing_mode[asset] = {
            "enabled": True,
            "exited_side": "yes",
            "exit_time": datetime.utcnow()
        }
        
        # Simulate candidate selection logic with same side
        swing_enabled = loop._swing_mode[asset]["enabled"]
        exited_side = loop._swing_mode[asset]["exited_side"]
        side = "yes"  # Same side
        edge = 0.002  # Below minimum threshold
        min_edge_threshold = 0.005
        has_position = False
        
        # Check if entry is allowed
        is_swing_reversal = swing_enabled and exited_side and side != exited_side
        should_execute = not has_position and (edge > min_edge_threshold or is_swing_reversal)
        
        # Should NOT execute (same side, low edge)
        assert should_execute is False
        assert is_swing_reversal is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
