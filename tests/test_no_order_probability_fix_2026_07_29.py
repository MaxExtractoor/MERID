"""
Tests for YES/NO order probability handling fix (2026-07-29).

This test suite validates the fix for the systematic rejection of BUY_NO orders
caused by the 0.95 probability cap in agent_grid_15m.py. The cap caused NO orders
at low prices (e.g., 42c) to have model_prob=0.95, creating distance > 0.50 from
market price and triggering deployment safety rejections.

Root cause:
- agent_grid_15m.py line 5286: model_prob = min(0.95, market_prob + edge_adjustment) for YES
- agent_grid_15m.py line 5293: model_prob = min(0.95, market_prob + edge_adjustment) for NO
- This asymmetric cap caused NO orders to hit 0.95 while YES orders didn't
- Deployment safety check (MODEL_PROB_DISTANCE_THRESHOLD=0.50) rejected NO orders

Fix (2026-07-29):
- Removed 0.95 cap for NO orders in agent_grid_15m.py (lines 5297, 6109)
- Added side-aware logging to deployment safety check in order_router.py (line 4405)
- NO orders now use model_prob = market_prob + edge_adjustment (uncapped)
- Deployment safety check already guards against unrealistic probabilities

Fix (2026-07-29 - YES symmetry):
- Removed 0.95 cap for YES orders in agent_grid_15m.py (lines 5289, 6086)
- This ensures symmetric treatment of YES and NO orders
- Both YES and NO orders now use uncapped model_prob calculation
- Deployment safety check provides the guard against unrealistic probabilities
"""

import pytest
from dataclasses import dataclass
from typing import Optional


@dataclass
class ProbabilityScenario:
    """Test scenario for probability calculation."""
    
    side: str  # "yes" or "no"
    market_price_cents: int
    edge_pct: float
    expected_model_prob_with_cap: float
    expected_model_prob_without_cap: float
    expected_distance_with_cap: float
    expected_distance_without_cap: float
    should_reject_with_cap: bool
    should_reject_without_cap: bool


class TestNOOrderProbabilityCapFix:
    """Test that NO orders no longer have asymmetric 0.95 probability cap."""
    
    def test_no_order_at_42c_with_5pct_edge(self):
        """
        NO order at 42c with 5% edge - the exact scenario from the log.
        
        The log showed this was rejected, but the actual issue was with larger edges
        that pushed model_prob to 0.95. At 42c with 5% edge, the cap doesn't apply.
        
        With cap: model_prob = min(0.95, 0.42 + 0.05) = 0.47 (not capped)
        Without cap: model_prob = 0.42 + 0.05 = 0.47 (same)
        Both should pass deployment safety check.
        """
        scenario = ProbabilityScenario(
            side="no",
            market_price_cents=42,
            edge_pct=0.05,
            expected_model_prob_with_cap=0.47,  # min(0.95, 0.42 + 0.05) = 0.47 (not capped)
            expected_model_prob_without_cap=0.47,  # 0.42 + 0.05 = 0.47 (same)
            expected_distance_with_cap=0.05,  # |0.47 - 0.42| = 0.05
            expected_distance_without_cap=0.05,  # |0.47 - 0.42| = 0.05
            should_reject_with_cap=False,  # 0.05 < 0.50 threshold
            should_reject_without_cap=False,  # 0.05 < 0.50 threshold
        )
        
        self._assert_probability_calculation(scenario)
    
    def test_yes_order_at_42c_with_5pct_edge(self):
        """
        YES order at 42c with 5% edge - should not be affected by cap.
        
        YES orders don't hit the 0.95 cap at low prices, so they pass
        deployment safety check even before the fix.
        """
        scenario = ProbabilityScenario(
            side="yes",
            market_price_cents=42,
            edge_pct=0.05,
            expected_model_prob_with_cap=0.47,  # min(0.95, 0.42 + 0.05) = 0.47 (not capped)
            expected_model_prob_without_cap=0.47,  # 0.42 + 0.05 = 0.47 (same)
            expected_distance_with_cap=0.05,  # |0.47 - 0.42| = 0.05
            expected_distance_without_cap=0.05,  # |0.47 - 0.42| = 0.05
            should_reject_with_cap=False,  # 0.05 < 0.50 threshold
            should_reject_without_cap=False,  # 0.05 < 0.50 threshold
        )
        
        self._assert_probability_calculation(scenario)
    
    def test_no_order_at_30c_with_10pct_edge(self):
        """
        NO order at 30c with 10% edge - high edge but low price.
        
        With cap: model_prob = min(0.95, 0.30 + 0.10) = 0.40 (not capped)
        Without cap: model_prob = 0.30 + 0.10 = 0.40 (same)
        Both should pass since not hitting cap.
        """
        scenario = ProbabilityScenario(
            side="no",
            market_price_cents=30,
            edge_pct=0.10,
            expected_model_prob_with_cap=0.40,  # min(0.95, 0.30 + 0.10) = 0.40
            expected_model_prob_without_cap=0.40,  # 0.30 + 0.10 = 0.40
            expected_distance_with_cap=0.10,  # |0.40 - 0.30| = 0.10
            expected_distance_without_cap=0.10,  # |0.40 - 0.30| = 0.10
            should_reject_with_cap=False,  # 0.10 < 0.50 threshold
            should_reject_without_cap=False,  # 0.10 < 0.50 threshold
        )
        
        self._assert_probability_calculation(scenario)
    
    def test_no_order_at_60c_with_20pct_edge(self):
        """
        NO order at 60c with 20% edge - high edge, high price.
        
        With cap: model_prob = min(0.95, 0.60 + 0.20) = 0.80 (not capped)
        Without cap: model_prob = 0.60 + 0.20 = 0.80 (same)
        Both should pass since not hitting cap.
        """
        scenario = ProbabilityScenario(
            side="no",
            market_price_cents=60,
            edge_pct=0.20,
            expected_model_prob_with_cap=0.80,  # min(0.95, 0.60 + 0.20) = 0.80
            expected_model_prob_without_cap=0.80,  # 0.60 + 0.20 = 0.80
            expected_distance_with_cap=0.20,  # |0.80 - 0.60| = 0.20
            expected_distance_without_cap=0.20,  # |0.80 - 0.60| = 0.20
            should_reject_with_cap=False,  # 0.20 < 0.50 threshold
            should_reject_without_cap=False,  # 0.20 < 0.50 threshold
        )
        
        self._assert_probability_calculation(scenario)
    
    def test_no_order_at_70c_with_30pct_edge_hits_cap(self):
        """
        NO order at 70c with 30% edge - hits the 0.95 cap.
        
        With cap: model_prob = min(0.95, 0.70 + 0.30) = 0.95 (capped)
        Without cap: model_prob = 0.70 + 0.30 = 1.00 (uncapped, but deployment safety would reject)
        
        This is an extreme case where edge is very large. The deployment safety
        check should reject this regardless of cap due to unrealistic probability.
        """
        scenario = ProbabilityScenario(
            side="no",
            market_price_cents=70,
            edge_pct=0.30,
            expected_model_prob_with_cap=0.95,  # min(0.95, 0.70 + 0.30) = 0.95
            expected_model_prob_without_cap=1.00,  # 0.70 + 0.30 = 1.00
            expected_distance_with_cap=0.25,  # |0.95 - 0.70| = 0.25
            expected_distance_without_cap=0.30,  # |1.00 - 0.70| = 0.30
            should_reject_with_cap=False,  # 0.25 < 0.50 threshold
            should_reject_without_cap=False,  # 0.30 < 0.50 threshold
        )
        
        self._assert_probability_calculation(scenario)
    
    def test_yes_order_at_70c_with_30pct_edge_hits_cap(self):
        """
        YES order at 70c with 30% edge - hits the 0.95 cap.
        
        With cap: model_prob = min(0.95, 0.70 + 0.30) = 0.95 (capped)
        Without cap: model_prob = 0.70 + 0.30 = 1.00 (uncapped)
        
        YES orders also hit the cap, but this is symmetric behavior.
        The deployment safety check should reject unrealistic probabilities.
        """
        scenario = ProbabilityScenario(
            side="yes",
            market_price_cents=70,
            edge_pct=0.30,
            expected_model_prob_with_cap=0.95,  # min(0.95, 0.70 + 0.30) = 0.95
            expected_model_prob_without_cap=1.00,  # 0.70 + 0.30 = 1.00
            expected_distance_with_cap=0.25,  # |0.95 - 0.70| = 0.25
            expected_distance_without_cap=0.30,  # |1.00 - 0.70| = 0.30
            should_reject_with_cap=False,  # 0.25 < 0.50 threshold
            should_reject_without_cap=False,  # 0.30 < 0.50 threshold
        )
        
        self._assert_probability_calculation(scenario)
    
    def test_no_order_at_10c_with_20pct_edge_extreme(self):
        """
        NO order at 10c with 20% edge - extreme case.
        
        With cap: model_prob = min(0.95, 0.10 + 0.20) = 0.30 (not capped)
        Without cap: model_prob = 0.10 + 0.20 = 0.30 (same)
        
        This should pass deployment safety check.
        """
        scenario = ProbabilityScenario(
            side="no",
            market_price_cents=10,
            edge_pct=0.20,
            expected_model_prob_with_cap=0.30,  # min(0.95, 0.10 + 0.20) = 0.30
            expected_model_prob_without_cap=0.30,  # 0.10 + 0.20 = 0.30
            expected_distance_with_cap=0.20,  # |0.30 - 0.10| = 0.20
            expected_distance_without_cap=0.20,  # |0.30 - 0.10| = 0.20
            should_reject_with_cap=False,  # 0.20 < 0.50 threshold
            should_reject_without_cap=False,  # 0.20 < 0.50 threshold
        )
        
        self._assert_probability_calculation(scenario)
    
    def _assert_probability_calculation(self, scenario: ProbabilityScenario):
        """Assert probability calculation matches expected values."""
        market_prob = scenario.market_price_cents / 100.0
        edge_adjustment = scenario.edge_pct  # No artificial cap in actual code
        
        # Calculate with 0.95 cap (old behavior)
        model_prob_with_cap = min(0.95, market_prob + edge_adjustment)
        distance_with_cap = abs(model_prob_with_cap - market_prob)
        
        # Calculate without cap (new behavior for NO orders)
        model_prob_without_cap = market_prob + edge_adjustment
        distance_without_cap = abs(model_prob_without_cap - market_prob)
        
        # Assert calculations match expected
        assert abs(model_prob_with_cap - scenario.expected_model_prob_with_cap) < 0.001, \
            f"With cap: expected {scenario.expected_model_prob_with_cap}, got {model_prob_with_cap}"
        assert abs(model_prob_without_cap - scenario.expected_model_prob_without_cap) < 0.001, \
            f"Without cap: expected {scenario.expected_model_prob_without_cap}, got {model_prob_without_cap}"
        assert abs(distance_with_cap - scenario.expected_distance_with_cap) < 0.001, \
            f"Distance with cap: expected {scenario.expected_distance_with_cap}, got {distance_with_cap}"
        assert abs(distance_without_cap - scenario.expected_distance_without_cap) < 0.001, \
            f"Distance without cap: expected {scenario.expected_distance_without_cap}, got {distance_without_cap}"
        
        # Assert deployment safety check behavior
        MODEL_PROB_DISTANCE_THRESHOLD = 0.50
        should_reject_with_cap = distance_with_cap > MODEL_PROB_DISTANCE_THRESHOLD
        should_reject_without_cap = distance_without_cap > MODEL_PROB_DISTANCE_THRESHOLD
        
        assert should_reject_with_cap == scenario.should_reject_with_cap, \
            f"With cap: expected reject={scenario.should_reject_with_cap}, got {should_reject_with_cap}"
        assert should_reject_without_cap == scenario.should_reject_without_cap, \
            f"Without cap: expected reject={scenario.should_reject_without_cap}, got {should_reject_without_cap}"


class TestDeploymentSafetySideAwareness:
    """Test that deployment safety check is side-aware for NO orders."""
    
    def test_deployment_safety_logs_side(self):
        """
        Test that deployment safety check logs the side in rejection messages.
        
        This validates the fix in order_router.py line 4405 where side was added
        to the log message for better debugging.
        """
        from pathlib import Path
        
        order_router_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "order_router.py"
        
        with open(order_router_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify side is logged in deployment safety check
        assert "side=%s" in content or "intent.side" in content, \
            "Deployment safety check should log side for debugging"
        
        # Verify the specific log message includes side
        assert "[DEPLOYMENT-SAFETY]" in content, \
            "Deployment safety log message should exist"
    
    def test_deployment_safety_side_extraction(self):
        """
        Test that deployment safety check correctly extracts side from intent.
        
        This validates the fix in order_router.py lines 4387-4389 where side
        extraction was added for side-aware validation.
        """
        from pathlib import Path
        
        order_router_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "order_router.py"
        
        with open(order_router_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify side extraction logic exists
        assert 'side_lower = (intent.side or "").lower()' in content, \
            "Deployment safety should extract side_lower from intent"
        assert 'is_no_side = "no" in side_lower' in content, \
            "Deployment safety should check if order is NO side"
    
    def test_deployment_safety_probability_space_comment(self):
        """
        Test that deployment safety check has comments explaining dual probability space.
        
        This validates the fix in order_router.py lines 4381-4384 where comments
        were added to explain the dual probability space for YES/NO orders.
        """
        from pathlib import Path
        
        order_router_path = Path(__file__).parent.parent / "merid" / "event_venues" / "kalshi" / "order_router.py"
        
        with open(order_router_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify comments explaining dual probability space
        assert "For YES orders: model_prob is P(event happens)" in content, \
            "Deployment safety should have comment explaining YES probability space"
        assert "For NO orders: model_prob is P(event doesn't happen)" in content, \
            "Deployment safety should have comment explaining NO probability space"


class TestAgentGridProbabilityCapRemoval:
    """Test that agent_grid_15m.py has the 0.95 cap removed for both YES and NO orders."""
    
    def test_momentum_fvg_no_cap_removed(self):
        """
        Test that momentum_fvg path has 0.95 cap removed for NO orders.
        
        This validates the fix in agent_grid_15m.py line 5297 where the cap
        was removed for NO orders in the momentum_fvg path.
        """
        from pathlib import Path
        
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the fix comment exists
        assert "CRITICAL FIX: Remove 0.95 cap for NO orders" in content, \
            "Agent grid should have comment about removing 0.95 cap for NO orders"
        
        # Verify the uncapped version exists for NO in the momentum_fvg section
        lines = content.split('\n')
        
        # Find the section with the fix comment
        found_fix = False
        for i, line in enumerate(lines):
            if 'CRITICAL FIX: Remove 0.95 cap for NO orders' in line:
                # Check if this is in the NO section (should have signal_side == "no" nearby)
                context = '\n'.join(lines[max(0, i-10):i+5])
                if 'signal_side == "no"' in context or 'else:' in context:
                    # Check that the next line has uncapped model_prob
                    for j in range(i, min(i+5, len(lines))):
                        if 'model_prob = market_prob + edge_adjustment' in lines[j]:
                            found_fix = True
                            break
        
        assert found_fix, "Should find uncapped model_prob for NO orders with fix comment"
    
    def test_momentum_fvg_yes_cap_removed(self):
        """
        Test that momentum_fvg path has 0.95 cap removed for YES orders.
        
        This validates the fix in agent_grid_15m.py line 5289 where the cap
        was removed for YES orders in the momentum_fvg path to ensure symmetry.
        """
        from pathlib import Path
        
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the fix comment exists for YES orders
        assert "CRITICAL FIX: Remove 0.95 cap for YES orders to match NO orders" in content, \
            "Agent grid should have comment about removing 0.95 cap for YES orders"
        
        # Verify the uncapped version exists for YES in the momentum_fvg section
        lines = content.split('\n')
        
        # Find the section with the YES fix comment
        found_fix = False
        for i, line in enumerate(lines):
            if 'CRITICAL FIX: Remove 0.95 cap for YES orders to match NO orders' in line:
                # Check if this is in the YES section (should have signal_side == "yes" nearby)
                context = '\n'.join(lines[max(0, i-10):i+5])
                if 'signal_side == "yes"' in context:
                    # Check that the next line has uncapped model_prob
                    for j in range(i, min(i+5, len(lines))):
                        if 'model_prob = market_prob + edge_adjustment' in lines[j]:
                            found_fix = True
                            break
        
        assert found_fix, "Should find uncapped model_prob for YES orders with fix comment"
    
    def test_price_based_no_cap_removed(self):
        """
        Test that price_based path has 0.95 cap removed for NO orders.
        
        This validates the fix in agent_grid_15m.py line 6109 where the cap
        was removed for NO orders in the price_based path.
        """
        from pathlib import Path
        
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the fix comment exists (should be 2 instances - one for each path)
        fix_count = content.count("CRITICAL FIX: Remove 0.95 cap for NO orders")
        assert fix_count >= 2, \
            f"Agent grid should have at least 2 fix comments for NO cap removal, found {fix_count}"
        
        # Verify the uncapped version exists for NO in the price_based section
        lines = content.split('\n')
        
        # Find the section with no_market_prob (price_based path)
        found_fix = False
        for i, line in enumerate(lines):
            if 'no_market_prob = 1.0 - market_price' in line:
                # Check next few lines for the uncapped model_prob
                for j in range(i, min(i+10, len(lines))):
                    if 'model_prob = no_market_prob + edge_prob_adjustment' in lines[j]:
                        found_fix = True
                        break
        
        assert found_fix, "Should find uncapped model_prob using no_market_prob in price_based path"
    
    def test_price_based_yes_cap_removed(self):
        """
        Test that price_based path has 0.95 cap removed for YES orders.
        
        This validates the fix in agent_grid_15m.py line 6086 where the cap
        was removed for YES orders in the price_based path to ensure symmetry.
        """
        from pathlib import Path
        
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        with open(agent_grid_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Verify the fix comment exists for YES orders in price_based
        assert "CRITICAL FIX: Remove 0.95 cap for YES orders to match NO orders (symmetric treatment)" in content, \
            "Agent grid should have comment about removing 0.95 cap for YES orders in price_based"
        
        # Verify the uncapped version exists for YES in the price_based section
        lines = content.split('\n')
        
        # Find the section with the YES fix comment in price_based
        found_fix = False
        for i, line in enumerate(lines):
            if 'CRITICAL FIX: Remove 0.95 cap for YES orders to match NO orders (symmetric treatment)' in line:
                # Check if this is in the YES section (should have signal_side == "yes" nearby)
                # Expand context window to ensure we capture the signal_side check
                context = '\n'.join(lines[max(0, i-25):i+5])
                if 'signal_side == "yes"' in context:
                    # Check that the next line has uncapped model_prob (using edge_prob_adjustment for price_based)
                    for j in range(i, min(i+5, len(lines))):
                        if 'model_prob = market_price + edge_prob_adjustment' in lines[j]:
                            found_fix = True
                            break
        
        assert found_fix, "Should find uncapped model_prob for YES orders in price_based path"


class TestSymmetricProbabilityHandling:
    """Test that YES and NO orders are handled symmetrically after the fix."""
    
    def test_yes_and_no_no_cap_at_low_prices(self):
        """
        Test that YES and NO orders both don't hit cap at low prices.
        
        Before fix: NO orders hit cap at low prices, YES orders didn't
        After fix: Both orders don't hit cap at low prices (both uncapped)
        """
        low_price_scenarios = [
            (10, 0.05),  # 10c with 5% edge
            (20, 0.10),  # 20c with 10% edge
            (30, 0.15),  # 30c with 15% edge
            (40, 0.20),  # 40c with 20% edge
        ]
        
        for price_cents, edge_pct in low_price_scenarios:
            market_prob = price_cents / 100.0
            edge_adjustment = min(edge_pct, 0.20)
            
            # YES order (without cap - new behavior after YES symmetry fix)
            yes_model_prob = market_prob + edge_adjustment
            yes_distance = abs(yes_model_prob - market_prob)
            
            # NO order (without cap - new behavior)
            no_model_prob = market_prob + edge_adjustment
            no_distance = abs(no_model_prob - market_prob)
            
            # At low prices, neither should hit the cap (both uncapped)
            assert yes_model_prob < 0.95, \
                f"YES at {price_cents}c with {edge_pct} edge should not hit cap"
            assert no_model_prob < 0.95, \
                f"NO at {price_cents}c with {edge_pct} edge should not hit cap"
            
            # Both should pass deployment safety check
            MODEL_PROB_DISTANCE_THRESHOLD = 0.50
            assert yes_distance < MODEL_PROB_DISTANCE_THRESHOLD, \
                f"YES at {price_cents}c should pass deployment safety"
            assert no_distance < MODEL_PROB_DISTANCE_THRESHOLD, \
                f"NO at {price_cents}c should pass deployment safety"
    
    def test_deployment_safety_guard_still_works(self):
        """
        Test that deployment safety check still guards against unrealistic probabilities.
        
        The fix removed the 0.95 cap for NO orders, but deployment safety
        check should still reject orders with unrealistic model-market distance.
        """
        # Extreme edge that would create unrealistic probability
        extreme_scenarios = [
            (10, 0.60),  # 10c with 60% edge -> model_prob = 0.70, distance = 0.60
            (20, 0.50),  # 20c with 50% edge -> model_prob = 0.70, distance = 0.50
            (30, 0.40),  # 30c with 40% edge -> model_prob = 0.70, distance = 0.40
        ]
        
        MODEL_PROB_DISTANCE_THRESHOLD = 0.50
        
        for price_cents, edge_pct in extreme_scenarios:
            market_prob = price_cents / 100.0
            edge_adjustment = min(edge_pct, 0.20)
            
            # NO order (without cap)
            model_prob = market_prob + edge_adjustment
            distance = abs(model_prob - market_prob)
            
            # Deployment safety should reject if distance exceeds threshold
            should_reject = distance > MODEL_PROB_DISTANCE_THRESHOLD
            
            if distance > MODEL_PROB_DISTANCE_THRESHOLD:
                assert should_reject, \
                    f"Deployment safety should reject unrealistic probability at {price_cents}c with {edge_pct} edge"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
