"""
Tests for edge_probability_invariants.py

Pure unit tests with synthetic inputs, no I/O, fully deterministic.
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from merid.validation.edge_probability_invariants import (
    EdgeProbabilityInvariantChecker,
    EdgeProbabilityViolation,
    EdgeProbabilityCheckResult,
    check_edge_probability_consistency,
    check_confidence_monotonicity,
    check_edge_threshold_consistency,
    generate_synthetic_edge_probability_test_cases,
)


class TestEdgeProbabilityInvariants:
    """Test suite for edge-probability consistency invariants."""
    
    @pytest.fixture
    def checker(self):
        """Fixture for EdgeProbabilityInvariantChecker."""
        return EdgeProbabilityInvariantChecker(
            min_edge_threshold=0.01,
            min_confidence_threshold=0.5,
        )
    
    @pytest.fixture
    def mock_error_taxonomy(self):
        """Mock error taxonomy for testing."""
        with patch('merid.validation.edge_probability_invariants.logger') as mock_logger:
            yield mock_logger
    
    def test_bullish_edge_forces_long_yes_not_long_no(self, checker):
        """
        Given p_model=0.7, p_market=0.55 → edge>0, side=UP, contract=YES.
        Assert invariant passes.
        Flip to contract=NO or position=short YES and assert invariant reports violation.
        """
        # Valid case: bullish edge with long YES
        result = checker.check_edge_sign_consistency(
            p_model=0.7,
            edge=0.15,
            chosen_side="yes",
        )
        assert result.is_valid
        assert result.violation_type is None
        
        # Invalid case: bullish edge but chosen side is NO
        result = checker.check_edge_sign_consistency(
            p_model=0.7,
            edge=0.15,
            chosen_side="no",
        )
        assert not result.is_valid
        assert result.violation_type == EdgeProbabilityViolation.SIDE_PROBABILITY_MISMATCH
        assert "bullish" in result.message.lower() or "0.7" in result.message
    
    def test_bearish_edge_forces_long_no_not_long_yes(self, checker):
        """
        Similarly with p_model=0.3, edge<0.
        """
        # Valid case: bearish edge with long NO
        result = checker.check_edge_sign_consistency(
            p_model=0.3,
            edge=-0.15,
            chosen_side="no",
        )
        assert result.is_valid
        assert result.violation_type is None
        
        # Invalid case: bearish edge but chosen side is YES
        result = checker.check_edge_sign_consistency(
            p_model=0.3,
            edge=-0.15,
            chosen_side="yes",
        )
        assert not result.is_valid
        assert result.violation_type == EdgeProbabilityViolation.SIDE_PROBABILITY_MISMATCH
    
    def test_confidence_monotonic_in_edge_magnitude(self, checker):
        """
        Build two scenarios with identical symbols but different edges: edge_small, edge_big.
        Assert confidence(edge_big) ≥ confidence(edge_small).
        Inject a bad case and assert violation.
        """
        # Valid case: higher edge with higher confidence
        result = checker.check_confidence_monotonicity(
            p_model=0.7,
            edge=0.15,
            confidence=0.85,
        )
        assert result.is_valid
        
        # Valid case: lower edge with lower confidence
        result = checker.check_confidence_monotonicity(
            p_model=0.55,
            edge=0.05,
            confidence=0.60,
        )
        assert result.is_valid
        
        # Invalid case: low edge but high confidence
        result = checker.check_confidence_monotonicity(
            p_model=0.52,
            edge=0.005,
            confidence=0.90,
        )
        assert not result.is_valid
        assert result.violation_type == EdgeProbabilityViolation.CONFIDENCE_NOT_MONOTONIC
    
    def test_no_trade_when_edge_below_threshold(self, checker):
        """
        Scenario: edge=0.001, threshold=0.01, trade_emitted=True.
        Assert invariant flags LOW_EDGE_HIGH_CONFIDENCE and trade_invalid.
        """
        # Invalid case: trade emitted with edge below threshold
        result = checker.check_edge_threshold_consistency(
            edge=0.001,
            confidence=0.80,
            trade_emitted=True,
        )
        assert not result.is_valid
        assert result.violation_type == EdgeProbabilityViolation.LOW_EDGE_HIGH_CONFIDENCE
        assert "0.001" in result.message
        
        # Valid case: no trade emitted with edge below threshold
        result = checker.check_edge_threshold_consistency(
            edge=0.001,
            confidence=0.80,
            trade_emitted=False,
        )
        assert result.is_valid
        
        # Valid case: trade emitted with edge above threshold
        result = checker.check_edge_threshold_consistency(
            edge=0.05,
            confidence=0.80,
            trade_emitted=True,
        )
        assert result.is_valid
    
    def test_invalid_probability_range(self, checker):
        """Test that invalid probability ranges are caught."""
        # Invalid: p_model > 1.0
        result = checker.check_edge_sign_consistency(
            p_model=1.5,
            edge=0.15,
            chosen_side="yes",
        )
        assert not result.is_valid
        assert result.violation_type == EdgeProbabilityViolation.INVALID_PROBABILITY_RANGE
        
        # Invalid: p_model < 0.0
        result = checker.check_edge_sign_consistency(
            p_model=-0.1,
            edge=0.15,
            chosen_side="yes",
        )
        assert not result.is_valid
        assert result.violation_type == EdgeProbabilityViolation.INVALID_PROBABILITY_RANGE
    
    def test_check_all_invariants(self, checker):
        """Test running all invariants together."""
        results = checker.check_all_invariants(
            p_model=0.7,
            edge=0.15,
            confidence=0.85,
            chosen_side="yes",
            trade_emitted=True,
        )
        
        assert len(results) == 3  # Three invariants checked
        assert all(r.is_valid for r in results)
    
    def test_check_all_invariants_with_violations(self, checker):
        """Test running all invariants with violations."""
        results = checker.check_all_invariants(
            p_model=0.7,
            edge=0.001,  # Below threshold
            confidence=0.90,  # Too high for low edge
            chosen_side="no",  # Wrong side for bullish
            trade_emitted=True,  # Trade emitted despite low edge
        )
        
        assert len(results) == 3
        assert not all(r.is_valid for r in results)
        # At least one should be invalid
        assert sum(1 for r in results if not r.is_valid) >= 1


class TestConvenienceFunctions:
    """Test convenience functions for direct use."""
    
    def test_check_edge_probability_consistency(self):
        """Test convenience function for edge-probability consistency."""
        result = check_edge_probability_consistency(
            p_model=0.7,
            edge=0.15,
            chosen_side="yes",
        )
        assert result.is_valid
    
    def test_check_confidence_monotonicity(self):
        """Test convenience function for confidence monotonicity."""
        result = check_confidence_monotonicity(
            p_model=0.7,
            edge=0.15,
            confidence=0.85,
        )
        assert result.is_valid
    
    def test_check_edge_threshold_consistency(self):
        """Test convenience function for edge threshold consistency."""
        result = check_edge_threshold_consistency(
            edge=0.05,
            confidence=0.80,
            trade_emitted=True,
        )
        assert result.is_valid


class TestSyntheticTestCases:
    """Test synthetic test case generator."""
    
    def test_generate_synthetic_edge_probability_test_cases(self):
        """Test that synthetic test cases are generated correctly."""
        test_cases = generate_synthetic_edge_probability_test_cases()
        
        assert len(test_cases) > 0
        assert all("p_model" in tc for tc in test_cases)
        assert all("edge" in tc for tc in test_cases)
        assert all("confidence" in tc for tc in test_cases)
        assert all("chosen_side" in tc for tc in test_cases)
        assert all("expected_valid" in tc for tc in test_cases)
    
    def test_synthetic_test_cases_valid_and_invalid(self):
        """Test that synthetic test cases include both valid and invalid cases."""
        test_cases = generate_synthetic_edge_probability_test_cases()
        
        valid_cases = [tc for tc in test_cases if tc["expected_valid"]]
        invalid_cases = [tc for tc in test_cases if not tc["expected_valid"]]
        
        assert len(valid_cases) > 0
        assert len(invalid_cases) > 0


class TestEdgeProbabilityCheckResult:
    """Test EdgeProbabilityCheckResult dataclass."""
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = EdgeProbabilityCheckResult(
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
        result = EdgeProbabilityCheckResult(
            is_valid=False,
            violation_type=EdgeProbabilityViolation.EDGE_SIGN_MISMATCH,
            message="Test violation",
            context={},
        )
        
        result_dict = result.to_dict()
        assert result_dict["is_valid"] is False
        assert result_dict["violation_type"] == "edge_sign_mismatch"
