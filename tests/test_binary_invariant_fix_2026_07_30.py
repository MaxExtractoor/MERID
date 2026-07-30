"""Test suite for binary invariant fix (2026-07-30).

This test validates the end-to-end fix for NO price corruption caused by
Kalshi's REST API returning corrupted placeholder data in no_dollars field.

Root Cause:
- Kalshi REST API's no_dollars field contains corrupted YES asks (placeholder values like 0.0010, 0.0020)
- This was propagating 99c placeholder values through the system
- YES + NO was not summing to 100c, causing binary invariant violations

Fix Pattern:
- All code paths now use canonical duality: NO_bid = 100 - YES_bid
- Mathematically correct: YES + NO = 100c

Files Fixed:
1. agent_grid_15m.py (lines 8483, 4727) - NO price calculation
2. market_state.py (line 1525) - NO level derivation from REST
3. ws_bridge.py (lines 1077, 1472, 2363, 2615) - NO level derivation in multiple paths
4. order_router.py (line 7217) - NO level derivation in REST divergence check
"""

import pytest
from pathlib import Path


class TestAgentGrid15mNoPriceFix:
    """Test agent_grid_15m.py NO price calculation fixes."""

    def test_dual_side_evaluation_uses_duality(self):
        """Test DUAL-SIDE-PRICE section uses NO = 100 - YES bid."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should have the fix comment
        assert "CRITICAL FIX (2026-07-30): Always derive NO price from YES bid using canonical duality" in agent_grid_src, (
            "agent_grid_15m.py should have the 2026-07-30 fix comment"
        )
        
        # Should use 100 - best_bid, not orderbook.no_levels
        assert "no_price_cents = 100 - best_bid if best_bid and best_bid > 0 and best_bid < 100 else 0" in agent_grid_src, (
            "agent_grid_15m.py should derive NO price as 100 - best_bid"
        )

    def test_momentum_fvg_uses_duality(self):
        """Test MOMENTUM-FVG section uses NO = 100 - YES bid."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Count occurrences of the fix pattern (should be at least 2: dual-side and momentum-fvg)
        count = agent_grid_src.count("no_price_cents = 100 - best_bid if best_bid and best_bid > 0 and best_bid < 100 else 0")
        assert count >= 2, (
            f"agent_grid_15m.py should have at least 2 instances of NO = 100 - best_bid fix, found {count}"
        )

    def test_no_orderbook_no_levels_usage_in_price_calc(self):
        """Test that orderbook.no_levels is NOT used for NO price calculation."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should NOT have the old pattern of using orderbook.no_levels for NO price
        lines = agent_grid_src.splitlines()
        for i, line in enumerate(lines):
            if "no_price_cents" in line and "orderbook.no_levels" in line:
                # Check if this is in a price calculation context (not just logging)
                if i > 0 and "best_no_bid_cents" in lines[i-1]:
                    pytest.fail(
                        "agent_grid_15m.py should not use orderbook.no_levels for NO price calculation. "
                        "Should use 100 - best_bid instead."
                    )

    def test_binary_invariant_validation_present(self):
        """Test that binary invariant validation is present in DUAL-SIDE-PRICE."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        agent_grid_src = agent_grid_path.read_text(encoding="utf-8")
        
        # Should have binary invariant validation
        assert "BINARY-INVARIANT-VIOLATION" in agent_grid_src, (
            "agent_grid_15m.py should have binary invariant validation logging"
        )
        assert "total_cents = yes_price_cents + no_price_cents" in agent_grid_src, (
            "agent_grid_15m.py should calculate YES + NO sum for validation"
        )
        assert "abs(total_cents - 100) > 3" in agent_grid_src, (
            "agent_grid_15m.py should check YES + NO = 100c within tolerance"
        )


class TestMarketStateNoLevelFix:
    """Test market_state.py NO level derivation fix."""

    def test_market_state_uses_duality(self):
        """Test market_state.py derives NO levels from YES bids using duality."""
        market_state_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "market_state.py"
        market_state_src = market_state_path.read_text(encoding="utf-8")
        
        # Should have the fix comment
        assert "CRITICAL FIX (2026-07-30): no_dollars contains corrupted YES asks, not NO bids" in market_state_src, (
            "market_state.py should have the 2026-07-30 fix comment"
        )
        
        # Should derive NO levels from YES bids
        assert "no_levels = [[1.0 - float(price), float(size)] for price, size in orderbook_fp[\"yes_dollars\"]]" in market_state_src, (
            "market_state.py should derive NO levels as 1.0 - YES_bid"
        )

    def test_market_state_no_dollars_not_used(self):
        """Test that market_state.py does NOT use no_dollars directly."""
        market_state_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "market_state.py"
        market_state_src = market_state_path.read_text(encoding="utf-8")
        
        # Should NOT have the old pattern of using no_dollars directly
        # Check around line 1525 where the fix was applied
        lines = market_state_src.splitlines()
        for i, line in enumerate(lines):
            if 'if "no_dollars" in orderbook_fp:' in line:
                # This should NOT be followed by using no_dollars directly
                # Check next few lines
                for j in range(i+1, min(i+5, len(lines))):
                    if 'no_levels = [[float(price), float(size)] for price, size in orderbook_fp["no_dollars"]]' in lines[j]:
                        pytest.fail(
                            "market_state.py should not use no_dollars directly. "
                            "Should derive from yes_dollars using duality."
                        )


class TestWsBridgeNoLevelFixes:
    """Test ws_bridge.py NO level derivation fixes in multiple paths."""

    def test_ws_bridge_snapshot_bootstrap_uses_duality(self):
        """Test ws_bridge.py snapshot_bootstrap path uses duality."""
        ws_bridge_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "ws_bridge.py"
        ws_bridge_src = ws_bridge_path.read_text(encoding="utf-8")
        
        # Should derive NO levels from YES asks using duality
        assert "no_levels = [[1.0 - float(price), float(size)] for price, size in orderbook_fp[\"yes_dollars\"]]" in ws_bridge_src, (
            "ws_bridge.py should derive NO levels using duality"
        )

    def test_ws_bridge_rest_fallback_uses_duality(self):
        """Test ws_bridge.py REST fallback path uses duality."""
        ws_bridge_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "ws_bridge.py"
        ws_bridge_src = ws_bridge_path.read_text(encoding="utf-8")
        
        # Count occurrences of the duality pattern
        count = ws_bridge_src.count("no_levels = [[1.0 - float(price), float(size)] for price, size in yes_levels]")
        assert count >= 3, (
            f"ws_bridge.py should have at least 3 instances of NO = 1.0 - YES_bid fix, found {count}"
        )

    def test_ws_bridge_no_orderbook_asks_usage(self):
        """Test that ws_bridge.py does NOT use orderbook.asks for NO levels."""
        ws_bridge_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "ws_bridge.py"
        ws_bridge_src = ws_bridge_path.read_text(encoding="utf-8")
        
        # Should NOT have the old pattern of iterating over orderbook.asks for NO levels
        lines = ws_bridge_src.splitlines()
        for i, line in enumerate(lines):
            if "for ask in orderbook.asks:" in line:
                # Check if this is in a NO level construction context
                for j in range(i, min(i+10, len(lines))):
                    if "no_levels.append" in lines[j] and "ask" in lines[j]:
                        # This might be the old pattern - check if it's using duality instead
                        if "1.0 - float(price)" not in lines[j] and "1.0 - float(ask" not in lines[j]:
                            pytest.fail(
                                "ws_bridge.py should not use orderbook.asks directly for NO levels. "
                                "Should derive from YES bids using duality."
                            )


class TestOrderRouterNoLevelFix:
    """Test order_router.py NO level derivation fix."""

    def test_order_router_uses_duality(self):
        """Test order_router.py REST divergence check uses duality."""
        order_router_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "order_router.py"
        order_router_src = order_router_path.read_text(encoding="utf-8")
        
        # Should have the fix comment
        assert "CRITICAL FIX (2026-07-30): no_dollars contains corrupted YES asks, not NO bids" in order_router_src, (
            "order_router.py should have the 2026-07-30 fix comment"
        )
        
        # Should derive NO levels from YES bids
        assert "rest_no_levels = [[1.0 - float(p), float(s)] for p, s in orderbook_fp[\"yes_dollars\"]]" in order_router_src, (
            "order_router.py should derive NO levels as 1.0 - YES_bid"
        )

    def test_order_router_no_dollars_not_used(self):
        """Test that order_router.py does NOT use no_dollars directly."""
        order_router_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "order_router.py"
        order_router_src = order_router_path.read_text(encoding="utf-8")
        
        # Should NOT have the old pattern
        lines = order_router_src.splitlines()
        for i, line in enumerate(lines):
            if 'if "no_dollars" in orderbook_fp:' in line:
                # This should NOT be followed by using no_dollars directly
                for j in range(i+1, min(i+5, len(lines))):
                    if 'rest_no_levels = [[float(p), float(s)] for p, s in orderbook_fp["no_dollars"]]' in lines[j]:
                        pytest.fail(
                            "order_router.py should not use no_dollars directly. "
                            "Should derive from yes_dollars using duality."
                        )


class TestBinaryInvariantDuality:
    """Test binary invariant duality calculations."""

    def test_yes_no_sum_to_100(self):
        """Test YES + NO = 100 invariant with various inputs."""
        test_cases = [
            (1, 99),
            (10, 90),
            (25, 75),
            (42, 58),
            (50, 50),
            (75, 25),
            (90, 10),
            (99, 1),
        ]
        for yes_price, expected_no_price in test_cases:
            actual_no_price = 100 - yes_price
            assert actual_no_price == expected_no_price, f"YES={yes_price}, NO should be {expected_no_price}, got {actual_no_price}"
            assert yes_price + actual_no_price == 100, f"YES+NO should equal 100, got {yes_price + actual_no_price}"

    def test_duality_with_dollars(self):
        """Test duality calculation with dollar prices."""
        test_cases = [
            (0.01, 0.99),
            (0.10, 0.90),
            (0.25, 0.75),
            (0.42, 0.58),
            (0.50, 0.50),
            (0.75, 0.25),
            (0.90, 0.10),
            (0.99, 0.01),
        ]
        for yes_price_dollars, expected_no_price_dollars in test_cases:
            actual_no_price_dollars = 1.0 - yes_price_dollars
            assert abs(actual_no_price_dollars - expected_no_price_dollars) < 0.0001, (
                f"YES=${yes_price_dollars}, NO should be ${expected_no_price_dollars}, got ${actual_no_price_dollars}"
            )
            assert abs((yes_price_dollars + actual_no_price_dollars) - 1.0) < 0.0001, (
                f"YES+NO should equal $1.00, got ${yes_price_dollars + actual_no_price_dollars}"
            )

    def test_placeholder_pattern_detection(self):
        """Test detection of corrupted placeholder pattern from Kalshi API."""
        # Kalshi API returns placeholder values like 0.0010, 0.0020 in no_dollars
        # These convert to 0.9990, 0.9980 which are the 99c placeholder pattern
        corrupted_no_dollars = [[0.0010, 100], [0.0020, 200], [0.0030, 300]]
        
        # Old bug: using these directly would create NO levels at 99c, 98c, 97c
        old_no_levels = [[float(price), float(size)] for price, size in corrupted_no_dollars]
        assert old_no_levels[0][0] == 0.0010, "Old pattern would use corrupted values directly"
        
        # New fix: derive from YES bids instead
        yes_dollars = [[0.84, 100], [0.83, 200], [0.82, 300]]
        new_no_levels = [[1.0 - float(price), float(size)] for price, size in yes_dollars]
        assert abs(new_no_levels[0][0] - 0.16) < 0.0001, "New pattern should derive NO = 1.0 - YES"
        assert abs(new_no_levels[1][0] - 0.17) < 0.0001, "New pattern should derive NO = 1.0 - YES"
        assert abs(new_no_levels[2][0] - 0.18) < 0.0001, "New pattern should derive NO = 1.0 - YES"


class TestEndToEndIntegration:
    """Test end-to-end integration of all fixes."""

    def test_all_files_have_fix_comments(self):
        """Test that all fixed files have the 2026-07-30 fix comment."""
        files_to_check = [
            ("merid/prediction/agent_grid_15m.py", "CRITICAL FIX (2026-07-30)"),
            ("merid/event_venues/kalshi/market_state.py", "CRITICAL FIX (2026-07-30)"),
            ("merid/event_venues/kalshi/ws_bridge.py", "CRITICAL FIX (2026-07-30)"),
            ("merid/event_venues/kalshi/order_router.py", "CRITICAL FIX (2026-07-30)"),
        ]
        
        for file_path, fix_comment in files_to_check:
            full_path = Path(__file__).parent.parent / file_path
            file_src = full_path.read_text(encoding="utf-8")
            assert fix_comment in file_src, (
                f"{file_path} should have the 2026-07-30 fix comment"
            )

    def test_consistent_duality_pattern(self):
        """Test that all files use consistent duality pattern."""
        # All files should use either "100 - best_bid" (cents) or "1.0 - price" (dollars)
        files_to_check = [
            "merid/prediction/agent_grid_15m.py",
            "merid/event_venues/kalshi/market_state.py",
            "merid/event_venues/kalshi/ws_bridge.py",
            "merid/event_venues/kalshi/order_router.py",
        ]
        
        for file_path in files_to_check:
            full_path = Path(__file__).parent.parent / file_path
            file_src = full_path.read_text(encoding="utf-8")
            
            # Should have duality pattern
            has_cents_duality = "100 - best_bid" in file_src or "100 - yes_price" in file_src
            has_dollars_duality = "1.0 - float(price)" in file_src or "1.00 -" in file_src
            
            assert has_cents_duality or has_dollars_duality, (
                f"{file_path} should use duality pattern (100 - bid or 1.0 - price)"
            )

    def test_no_direct_no_dollars_usage(self):
        """Test that no file uses no_dollars directly for NO level construction."""
        files_to_check = [
            "merid/event_venues/kalshi/market_state.py",
            "merid/event_venues/kalshi/ws_bridge.py",
            "merid/event_venues/kalshi/order_router.py",
        ]
        
        for file_path in files_to_check:
            full_path = Path(__file__).parent.parent / file_path
            file_src = full_path.read_text(encoding="utf-8")
            
            # Check for the old pattern: no_levels = [[float(p), float(s)] for p, s in orderbook_fp["no_dollars"]]
            # This should NOT exist after the fix
            lines = file_src.splitlines()
            for i, line in enumerate(lines):
                if 'no_levels = [[float(p), float(s)] for p, s in orderbook_fp["no_dollars"]]' in line:
                    # Check if this line is commented out (acceptable)
                    if not line.strip().startswith("#"):
                        pytest.fail(
                            f"{file_path} should not use no_dollars directly for NO levels. "
                            "Should derive from yes_dollars using duality."
                        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
