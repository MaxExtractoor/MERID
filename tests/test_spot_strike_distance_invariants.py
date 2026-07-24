"""
Tests for spot_strike_distance_invariants.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest

from merid.validation.spot_strike_distance_invariants import (
    SpotStrikeDistanceInvariantChecker,
    SpotStrikeDistanceViolation,
    SpotStrikeDistanceCheckResult,
    check_spot_strike_distance,
    check_deep_otm_block,
    check_contract_selection_consistency,
    generate_synthetic_spot_strike_distance_test_cases,
)


class TestSpotStrikeDistanceInvariants:
    """Test suite for spot-strike distance invariants."""
    
    @pytest.fixture
    def checker(self):
        """Fixture for SpotStrikeDistanceInvariantChecker."""
        return SpotStrikeDistanceInvariantChecker(
            max_distance_delta=0.1,
            extreme_edge_threshold=0.15,
            deep_otm_threshold_cents=10,
        )
    
    def test_allowed_distance_window_accepts_contract(self, checker):
        """
        |δ| < allowed window, edge moderate, expect no violation.
        """
        # Valid case: δ = 0 (spot equals strike)
        result = checker.check_spot_strike_distance(
            spot_price=65000.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert result.is_valid
        assert result.context["delta"] == 0.0
        
        # Valid case: δ = 0.0077 (within 0.1 window)
        result = checker.check_spot_strike_distance(
            spot_price=65000.0,
            strike_price=65500.0,
            trade_emitted=True,
        )
        assert result.is_valid
        assert abs(result.context["delta"]) < 0.1
    
    def test_outside_distance_window_blocks_contract(self, checker):
        """
        |δ| > window, edge normal, expect DISTANCE_EXCEEDED violation and no trade.
        """
        # Invalid case: δ = 0.107 (exceeds 0.1 window)
        result = checker.check_spot_strike_distance(
            spot_price=65000.0,
            strike_price=72000.0,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == SpotStrikeDistanceViolation.DISTANCE_EXCEEDED
        assert abs(result.context["delta"]) > 0.1
        
        # Valid case: δ > window but no trade emitted
        result = checker.check_spot_strike_distance(
            spot_price=65000.0,
            strike_price=72000.0,
            trade_emitted=False,
        )
        assert result.is_valid
    
    def test_deep_otm_requires_extreme_edge(self, checker):
        """
        Deep OTM contract with moderate edge → DEEP_OTM_WITHOUT_EXTREME_EDGE.
        Deep OTM with extreme edge and strategy_allow_deep_otm=True → passes.
        """
        # Invalid case: deep OTM (8c) with moderate edge (10%)
        result = checker.check_deep_otm_block(
            contract_price_cents=8,
            edge=0.10,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == SpotStrikeDistanceViolation.DEEP_OTM_WITHOUT_EXTREME_EDGE
        assert result.context["is_deep_otm"] is True
        
        # Valid case: deep OTM (8c) with extreme edge (20%)
        result = checker.check_deep_otm_block(
            contract_price_cents=8,
            edge=0.20,
            trade_emitted=True,
        )
        assert result.is_valid
        
        # Valid case: not deep OTM (50c) with moderate edge
        result = checker.check_deep_otm_block(
            contract_price_cents=50,
            edge=0.10,
            trade_emitted=True,
        )
        assert result.is_valid
        assert result.context["is_deep_otm"] is False
    
    def test_contract_selection_consistent_with_intent_mapping(self, checker):
        """
        Provided TA/intent fixture mapping to contract set; assert invariant detects mismatches.
        """
        # Valid case: bullish intent → YES contract
        result = checker.check_contract_selection_consistency(
            ta_intent="bullish",
            selected_contract_type="yes",
            spot_price=65000.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert result.is_valid
        
        # Valid case: bearish intent → NO contract
        result = checker.check_contract_selection_consistency(
            ta_intent="bearish",
            selected_contract_type="no",
            spot_price=65000.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert result.is_valid
        
        # Invalid case: bullish intent → NO contract
        result = checker.check_contract_selection_consistency(
            ta_intent="bullish",
            selected_contract_type="no",
            spot_price=65000.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == SpotStrikeDistanceViolation.CONTRACT_SELECTION_MISMATCH
        
        # Invalid case: bearish intent → YES contract
        result = checker.check_contract_selection_consistency(
            ta_intent="bearish",
            selected_contract_type="yes",
            spot_price=65000.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == SpotStrikeDistanceViolation.CONTRACT_SELECTION_MISMATCH
    
    def test_invalid_spot_price(self, checker):
        """Test that invalid spot prices are caught."""
        # Invalid: spot price <= 0
        result = checker.check_spot_strike_distance(
            spot_price=0.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == SpotStrikeDistanceViolation.INVALID_SPOT_PRICE
        
        # Invalid: spot price < 0
        result = checker.check_spot_strike_distance(
            spot_price=-100.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == SpotStrikeDistanceViolation.INVALID_SPOT_PRICE
    
    def test_invalid_strike_price(self, checker):
        """Test that invalid strike prices are caught."""
        # Invalid: strike price <= 0
        result = checker.check_spot_strike_distance(
            spot_price=65000.0,
            strike_price=0.0,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == SpotStrikeDistanceViolation.INVALID_STRIKE_PRICE
    
    def test_calculate_normalized_distance(self, checker):
        """Test normalized distance calculation."""
        # δ = 0 when spot equals strike
        delta = checker.calculate_normalized_distance(65000.0, 65000.0)
        assert delta == 0.0
        
        # δ positive when strike > spot
        delta = checker.calculate_normalized_distance(65000.0, 65500.0)
        assert delta > 0
        assert abs(delta - 0.00769) < 0.0001  # (65500-65000)/65000 ≈ 0.00769
        
        # δ negative when strike < spot
        delta = checker.calculate_normalized_distance(65000.0, 64500.0)
        assert delta < 0
        assert abs(delta + 0.00769) < 0.0001  # (64500-65000)/65000 ≈ -0.00769
    
    def test_check_all_invariants(self, checker):
        """Test running all spot-strike distance invariants together."""
        results = checker.check_all_invariants(
            spot_price=65000.0,
            strike_price=65000.0,
            contract_price_cents=50,
            edge=0.10,
            ta_intent="bullish",
            selected_contract_type="yes",
            trade_emitted=True,
        )
        
        assert len(results) == 3  # Three invariants checked
        assert all(r.is_valid for r in results)
    
    def test_check_all_invariants_with_violations(self, checker):
        """Test running all invariants with violations."""
        results = checker.check_all_invariants(
            spot_price=65000.0,
            strike_price=72000.0,  # Distance exceeds window
            contract_price_cents=8,  # Deep OTM
            edge=0.10,  # Moderate edge (insufficient for deep OTM)
            ta_intent="bullish",
            selected_contract_type="no",  # Wrong contract type
            trade_emitted=True,
        )
        
        assert len(results) == 3
        assert not all(r.is_valid for r in results)
        # At least one should be invalid
        assert sum(1 for r in results if not r.is_valid) >= 1


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    def test_check_spot_strike_distance(self):
        """Test convenience function for spot-strike distance."""
        result = check_spot_strike_distance(
            spot_price=65000.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_check_deep_otm_block(self):
        """Test convenience function for deep OTM block."""
        result = check_deep_otm_block(
            contract_price_cents=50,
            edge=0.10,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_check_contract_selection_consistency(self):
        """Test convenience function for contract selection consistency."""
        result = check_contract_selection_consistency(
            ta_intent="bullish",
            selected_contract_type="yes",
            spot_price=65000.0,
            strike_price=65000.0,
            trade_emitted=True,
        )
        assert result.is_valid


class TestSyntheticTestCases:
    """Test synthetic test case generator."""
    
    def test_generate_synthetic_spot_strike_distance_test_cases(self):
        """Test that synthetic test cases are generated correctly."""
        test_cases = generate_synthetic_spot_strike_distance_test_cases()
        
        assert len(test_cases) > 0
        assert all("spot_price" in tc for tc in test_cases)
        assert all("strike_price" in tc for tc in test_cases)
        assert all("contract_price_cents" in tc for tc in test_cases)
        assert all("edge" in tc for tc in test_cases)
        assert all("ta_intent" in tc for tc in test_cases)
        assert all("selected_contract_type" in tc for tc in test_cases)
        assert all("expected_valid" in tc for tc in test_cases)
    
    def test_synthetic_test_cases_valid_and_invalid(self):
        """Test that synthetic test cases include both valid and invalid cases."""
        test_cases = generate_synthetic_spot_strike_distance_test_cases()
        
        valid_cases = [tc for tc in test_cases if tc["expected_valid"]]
        invalid_cases = [tc for tc in test_cases if not tc["expected_valid"]]
        
        assert len(valid_cases) > 0
        assert len(invalid_cases) > 0


class TestSpotStrikeDistanceCheckResult:
    """Test SpotStrikeDistanceCheckResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = SpotStrikeDistanceCheckResult(
            is_valid=True,
            violation_type=None,
            message="Test message",
            context={"key": "value"},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is True
        assert result_dict["violation_type"] is None
        assert result_dict["message"] == "Test message"
        assert result_dict["context"] == {"key": "value"}
    
    def test_to_dict_with_violation(self):
        """Test conversion to dictionary with violation."""
        result = SpotStrikeDistanceCheckResult(
            is_valid=False,
            violation_type=SpotStrikeDistanceViolation.DISTANCE_EXCEEDED,
            message="Test violation",
            context={},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is False
        assert result_dict["violation_type"] == "distance_exceeded"
