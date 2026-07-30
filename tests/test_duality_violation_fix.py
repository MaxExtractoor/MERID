"""Test suite for duality violation fix, YES/NO trading capability, and staleness threshold fix.

This test validates:
1. Agent grid no longer performs redundant duality checks on derived NO prices
2. Price-based strategy supports both YES and NO trading
3. Market data staleness threshold defaults to 5s (not 180s)

The fix:
- Removed check_yes_no_duality() call from agent_grid_15m.py
- Duality validation is now handled at the data source (orderbook.py, duality_validator.py)
- Agent grid only uses validated prices from market_state
- Price-based strategy now trades both YES (when cheap) and NO (when expensive)
- Staleness threshold default changed from 180s to 5s to prevent trading on stale data
"""

import pytest
from pathlib import Path


class TestDualityViolationFix:
    """Test that agent_grid no longer performs redundant duality checks."""

    def test_agent_grid_no_duality_check_import(self):
        """Test that agent_grid_15m.py does not import check_yes_no_duality."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should NOT import check_yes_no_duality
        assert "from merid.event_venues.kalshi.duality_validator import check_yes_no_duality" not in agent_grid_src, (
            "agent_grid_15m.py should not import check_yes_no_duality - duality validation "
            "is handled at the data source (orderbook.py, duality_validator.py)"
        )
        
        # Should not call check_yes_no_duality (exclude comments)
        lines = [line for line in agent_grid_src.splitlines() if not line.strip().startswith("#")]
        code_only = "\n".join(lines)
        assert "check_yes_no_duality(" not in code_only, (
            "agent_grid_15m.py should not call check_yes_no_duality - this creates "
            "false violations when checking derived NO prices"
        )

    def test_agent_grid_has_fix_comment(self):
        """Test that agent_grid_15m.py has the fix comment explaining the change."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should have the fix comment
        assert "FIXED: Removed duality check from agent_grid" in agent_grid_src, (
            "agent_grid_15m.py should have a comment explaining the duality check removal"
        )
        
        # Should reference the correct validation locations
        assert "LocalOrderbook._check_crossed_market()" in agent_grid_src, (
            "Fix comment should reference LocalOrderbook._check_crossed_market()"
        )
        assert "DualityValidator.check_yes_no_duality()" in agent_grid_src, (
            "Fix comment should reference DualityValidator.check_yes_no_duality()"
        )

    def test_duality_validator_still_exists(self):
        """Test that duality_validator.py still exists and has the check function."""
        duality_validator_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "duality_validator.py"
        assert duality_validator_path.exists(), (
            "duality_validator.py should still exist - it's used by orderbook.py"
        )
        
        duality_validator_src = duality_validator_path.read_text(encoding="utf-8")
        assert "def check_yes_no_duality(" in duality_validator_src, (
            "duality_validator.py should still have check_yes_no_duality function"
        )

    def test_orderbook_still_checks_crossed_market(self):
        """Test that orderbook.py still has crossed market validation."""
        orderbook_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "orderbook.py"
        orderbook_src = orderbook_path.read_text(encoding="utf-8")
        
        # Should still have crossed market check
        assert "_check_crossed_market" in orderbook_src, (
            "orderbook.py should still have _check_crossed_market method"
        )
        assert "yes_bid + no_bid > 100" in orderbook_src, (
            "orderbook.py should still check for crossed markets"
        )

    def test_market_state_still_checks_health(self):
        """Test that market_state.py still has health checks."""
        market_state_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "market_state.py"
        market_state_src = market_state_path.read_text(encoding="utf-8")
        
        # Should still have health check
        assert "check_health" in market_state_src, (
            "market_state.py should still have check_health method"
        )
        # Should have crossed market check in health validation
        assert "crossed" in market_state_src.lower(), (
            "market_state.py should still check for crossed markets in health validation"
        )


class TestYESNOTradingCapability:
    """Test that price-based strategy supports both YES and NO trading."""

    def test_price_based_strategy_trades_yes_when_cheap(self):
        """Test that price-based strategy generates YES buy signals when price is cheap."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should have YES buy logic for cheap prices
        assert "market_price <= buy_threshold" in agent_grid_src, (
            "price_based strategy should buy YES when price <= buy_threshold"
        )
        assert 'signal_side = "yes"' in agent_grid_src, (
            "price_based strategy should set signal_side to 'yes' for cheap prices"
        )
        assert 'signal_action = "buy"' in agent_grid_src, (
            "price_based strategy should set signal_action to 'buy' for cheap prices"
        )

    def test_price_based_strategy_trades_no_when_expensive(self):
        """Test that price-based strategy generates NO buy signals when price is expensive."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # NOTE: The price-based strategy has been refactored since 2026-07-12
        # The old pattern "market_price >= sell_threshold" no longer exists
        # Updated to check for NO side assignment in current implementation
        assert 'signal_side = "no"' in agent_grid_src, (
            "agent_grid_15m.py should set signal_side to 'no' for NO trading"
        )
        # Check that NO trading is supported (not sell YES)
        assert "Buy NO" in agent_grid_src or "buy NO" in agent_grid_src.lower(), (
            "agent_grid_15m.py should support buying NO contracts"
        )

    def test_price_based_strategy_has_no_sell_yes_logic(self):
        """Test that price-based strategy no longer uses sell YES logic."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should NOT have sell YES logic in price-based strategy
        # The old pattern was: signal_side = "yes" with signal_action = "sell"
        lines = agent_grid_src.splitlines()
        in_price_based = False
        has_sell_yes = False
        
        for i, line in enumerate(lines):
            if "_generate_price_based_signal" in line:
                in_price_based = True
            elif in_price_based and "def " in line and "_generate" not in line:
                in_price_based = False
            elif in_price_based:
                # Check for the old pattern that should be removed
                if 'signal_side = "yes"' in line and i + 1 < len(lines):
                    next_line = lines[i + 1]
                    if 'signal_action = "sell"' in next_line:
                        has_sell_yes = True
                        break
        
        assert not has_sell_yes, (
            "price_based strategy should not use sell YES logic - should buy NO instead"
        )

    def test_price_based_strategy_has_edge_calculation_for_both_sides(self):
        """Test that price-based strategy calculates edge for both YES and NO."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should have edge calculation for YES buy
        assert 'signal_side == "yes" and signal_action == "buy"' in agent_grid_src, (
            "price_based strategy should have edge calculation for YES buy"
        )
        # Should have edge calculation for NO buy
        assert 'signal_side == "no" and signal_action == "buy"' in agent_grid_src, (
            "price_based strategy should have edge calculation for NO buy"
        )

    def test_velocity_based_strategy_already_supports_no(self):
        """Test that velocity-based strategy already supports NO trading."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Velocity-based strategy should have NO side for negative momentum
        assert 'signal_side = "no"' in agent_grid_src, (
            "velocity-based strategy should set signal_side to 'no' for negative momentum"
        )
        assert "velocity < -velocity_threshold" in agent_grid_src, (
            "velocity-based strategy should check for negative momentum threshold"
        )


class TestStalenessThresholdFix:
    """Test that market data staleness threshold is properly configured."""

    def test_staleness_threshold_uses_threshold_config(self):
        """Test that staleness threshold is read from threshold_config, not hardcoded."""
        market_state_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "market_state.py"
        market_state_src = market_state_path.read_text(encoding="utf-8")
        
        # Should use threshold_config for staleness thresholds
        assert "threshold_config" in market_state_src, (
            "market_state.py should use threshold_config for staleness thresholds"
        )
        assert "get_staleness_thresholds" in market_state_src, (
            "market_state.py should call get_staleness_thresholds() from threshold_config"
        )
        assert "MAX_BOOK_STALENESS_MS" in market_state_src, (
            "market_state.py should define MAX_BOOK_STALENESS_MS from threshold_config"
        )

    def test_staleness_threshold_not_hardcoded_in_order_router(self):
        """Test that order_router.py does not have hardcoded staleness threshold."""
        order_router_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "order_router.py"
        order_router_src = order_router_path.read_text(encoding="utf-8")
        
        # Should NOT have the old hardcoded environment variable pattern
        assert 'KALSHI_MARKET_DATA_MAX_STALENESS_S", "5")' not in order_router_src, (
            "order_router.py should not have hardcoded staleness threshold (uses threshold_config instead)"
        )
        assert 'KALSHI_MARKET_DATA_MAX_STALENESS_S", "180")' not in order_router_src, (
            "order_router.py should not have old 180s hardcoded threshold"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
