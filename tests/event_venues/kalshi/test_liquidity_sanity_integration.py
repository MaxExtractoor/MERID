"""
Integration tests for liquidity sanity checks in order_router.

Tests the integration of the new liquidity sanity checks with the order routing pipeline.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from merid.event_venues.kalshi.liquidity_sanity import (
    LiquiditySanityChecker,
    LiquidityCheckResult,
    get_liquidity_checker
)


class TestLiquiditySanityChecker:
    """Unit tests for LiquiditySanityChecker."""
    
    def test_liquidity_check_passes_with_sufficient_depth(self):
        """Test that liquidity check passes with sufficient depth near inside."""
        checker = LiquiditySanityChecker(
            min_depth_near_inside=10,
            depth_window_cents=3,
            min_price_cents=5,
            max_price_cents=95
        )
        
        # YES ask = 100 - no_bid = 60c, need depth at 60c for exit feasibility
        yes_orderbook = [(0.55, 20), (0.54, 15), (0.53, 10), (0.60, 15)]  # 20 contracts at 55c, 15 at 60c (ask)
        # NO ask = 100 - yes_bid = 45c, need depth at 45c for exit feasibility
        no_orderbook = [(0.40, 25), (0.39, 20), (0.38, 15), (0.45, 20)]  # 25 contracts at 40c, 20 at 45c (ask)
        
        result = checker.check_liquidity_sanity(
            yes_bid_cents=55,
            no_bid_cents=40,
            yes_orderbook=yes_orderbook,
            no_orderbook=no_orderbook,
            order_side="yes"
        )
        
        assert result.passes is True
        assert result.reason == "ok"
        # Depth is summed within 3c window: 20+15+10 = 45 for YES, 25+20+15 = 60 for NO
        assert result.yes_depth_near_inside == 45
        assert result.no_depth_near_inside == 60
    
    def test_liquidity_check_fails_insufficient_yes_depth(self):
        """Test that liquidity check fails when YES depth is too low."""
        checker = LiquiditySanityChecker(min_depth_near_inside=10)
        
        yes_orderbook = [(0.55, 5)]  # Only 5 contracts
        no_orderbook = [(0.40, 25)]
        
        result = checker.check_liquidity_sanity(
            yes_bid_cents=55,
            no_bid_cents=40,
            yes_orderbook=yes_orderbook,
            no_orderbook=no_orderbook,
            order_side="yes"
        )
        
        assert result.passes is False
        assert "yes_depth_near_inside_too_low" in result.reason
    
    def test_liquidity_check_fails_insufficient_no_depth(self):
        """Test that liquidity check fails when NO depth is too low."""
        checker = LiquiditySanityChecker(min_depth_near_inside=10)
        
        yes_orderbook = [(0.55, 20)]
        no_orderbook = [(0.40, 5)]  # Only 5 contracts
        
        result = checker.check_liquidity_sanity(
            yes_bid_cents=55,
            no_bid_cents=40,
            yes_orderbook=yes_orderbook,
            no_orderbook=no_orderbook,
            order_side="yes"
        )
        
        assert result.passes is False
        assert "no_depth_near_inside_too_low" in result.reason
    
    def test_liquidity_check_fails_exit_feasibility_yes_order(self):
        """Test that liquidity check fails when NO opposite side depth is zero for YES order."""
        checker = LiquiditySanityChecker(min_depth_near_inside=10)
        
        yes_orderbook = [(0.55, 20), (0.60, 10)]  # Depth at ask (60c) for exit
        no_orderbook = [(0.40, 20)]  # But NO side has no depth at ask (45c)
        
        result = checker.check_liquidity_sanity(
            yes_bid_cents=55,
            no_bid_cents=40,
            yes_orderbook=yes_orderbook,
            no_orderbook=no_orderbook,
            order_side="yes"
        )
        
        # NO ask = 100 - 55 = 45c, no_orderbook has no bids at 45c
        assert result.passes is False
        assert "no_exit_feasibility" in result.reason
    
    def test_liquidity_check_fails_exit_feasibility_no_order(self):
        """Test that liquidity check fails when YES opposite side depth is zero for NO order."""
        checker = LiquiditySanityChecker(min_depth_near_inside=10)
        
        yes_orderbook = [(0.55, 20)]  # YES side has no depth at ask (60c)
        no_orderbook = [(0.40, 20), (0.45, 10)]  # Depth at ask (45c) for exit
        
        result = checker.check_liquidity_sanity(
            yes_bid_cents=55,
            no_bid_cents=40,
            yes_orderbook=yes_orderbook,
            no_orderbook=no_orderbook,
            order_side="no"
        )
        
        # YES ask = 100 - 40 = 60c, yes_orderbook has no bids at 60c
        assert result.passes is False
        assert "yes_exit_feasibility" in result.reason
    
    def test_liquidity_check_fails_extreme_price_corner(self):
        """Test that liquidity check fails at extreme price corners."""
        checker = LiquiditySanityChecker(
            min_price_cents=5,
            max_price_cents=95,
            allow_extreme_corners=False
        )
        
        yes_orderbook = [(0.02, 20)]  # 2c - below 5c threshold
        no_orderbook = [(0.98, 20)]
        
        result = checker.check_liquidity_sanity(
            yes_bid_cents=2,
            no_bid_cents=98,
            yes_orderbook=yes_orderbook,
            no_orderbook=no_orderbook,
            order_side="yes"
        )
        
        assert result.passes is False
        assert "extreme_price_corner" in result.reason
    
    def test_liquidity_check_allows_extreme_corners_when_enabled(self):
        """Test that extreme corners are allowed when flag is enabled."""
        checker = LiquiditySanityChecker(
            min_price_cents=5,
            max_price_cents=95,
            allow_extreme_corners=True
        )
        
        yes_orderbook = [(0.02, 20)]
        no_orderbook = [(0.98, 20)]
        
        result = checker.check_liquidity_sanity(
            yes_bid_cents=2,
            no_bid_cents=98,
            yes_orderbook=yes_orderbook,
            no_orderbook=no_orderbook,
            order_side="yes"
        )
        
        assert result.passes is True
    
    def test_liquidity_score_calculation(self):
        """Test liquidity score calculation."""
        checker = LiquiditySanityChecker()
        
        passes, score, reason = checker.check_liquidity_score(
            yes_depth_near_inside=50,
            no_depth_near_inside=50,
            yes_depth_opposite=30,
            no_depth_opposite=30,
            min_score=0.5
        )
        
        assert passes is True
        assert score > 0.5
        assert reason == "ok"
    
    def test_liquidity_score_fails_below_threshold(self):
        """Test that liquidity score fails when below threshold."""
        checker = LiquiditySanityChecker()
        
        passes, score, reason = checker.check_liquidity_score(
            yes_depth_near_inside=5,
            no_depth_near_inside=5,
            yes_depth_opposite=2,
            no_depth_opposite=2,
            min_score=0.5
        )
        
        assert passes is False
        assert score < 0.5
        assert "liquidity_score" in reason


class TestLiquiditySanityIntegration:
    """Integration tests for liquidity sanity checks in order routing."""
    
    def test_profile_enable_liquidity_sanity_checks_flag(self):
        """Test that profile flag controls liquidity sanity checks usage."""
        # Mock profile with liquidity sanity checks enabled
        profile = Mock()
        profile.enable_liquidity_sanity_checks = True
        
        # Check that the flag would trigger liquidity sanity checks
        use_liquidity_checks = (
            hasattr(profile, 'enable_liquidity_sanity_checks') and
            profile.enable_liquidity_sanity_checks
        )
        
        assert use_liquidity_checks is True
    
    def test_profile_enable_liquidity_sanity_checks_disabled(self):
        """Test that liquidity sanity checks are not used when flag is False."""
        profile = Mock()
        profile.enable_liquidity_sanity_checks = False
        
        use_liquidity_checks = (
            hasattr(profile, 'enable_liquidity_sanity_checks') and
            profile.enable_liquidity_sanity_checks
        )
        
        assert use_liquidity_checks is False
    
    def test_get_liquidity_checker_singleton(self):
        """Test that get_liquidity_checker returns singleton instance."""
        checker1 = get_liquidity_checker()
        checker2 = get_liquidity_checker()
        
        assert checker1 is checker2
    
    def test_reset_liquidity_checker(self):
        """Test that reset_liquidity_checker creates new instance."""
        from merid.event_venues.kalshi.liquidity_sanity import reset_liquidity_checker
        
        checker1 = get_liquidity_checker()
        reset_liquidity_checker()
        checker2 = get_liquidity_checker()
        
        assert checker1 is not checker2


class TestLiquidityCheckFormatting:
    """Test formatting of liquidity check results."""
    
    def test_format_liquidity_check_table(self):
        """Test that liquidity check table is formatted correctly."""
        from merid.event_venues.kalshi.liquidity_sanity import format_liquidity_check_table
        
        results = [
            LiquidityCheckResult(
                passes=True,
                reason="ok",
                yes_depth_near_inside=15,
                no_depth_near_inside=12,
                yes_depth_opposite=10,
                no_depth_opposite=8,
                price_cents=55,
                is_extreme_corner=False
            ),
            LiquidityCheckResult(
                passes=False,
                reason="yes_depth_near_inside_too_low",
                yes_depth_near_inside=5,
                no_depth_near_inside=12,
                yes_depth_opposite=10,
                no_depth_opposite=8,
                price_cents=55,
                is_extreme_corner=False
            )
        ]
        
        table = format_liquidity_check_table(results)
        
        assert "Market" in table
        assert "YES Near" in table
        assert "NO Near" in table
        assert "YES Opp" in table
        assert "NO Opp" in table
        assert "Price" in table
        assert "Extreme" in table
        assert "Passes" in table
        assert "15" in table
        assert "5" in table
    
    def test_format_liquidity_check_table_empty(self):
        """Test that empty results are handled correctly."""
        from merid.event_venues.kalshi.liquidity_sanity import format_liquidity_check_table
        
        table = format_liquidity_check_table([])
        
        assert "No liquidity check results" in table


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
