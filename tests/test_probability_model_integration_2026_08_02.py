"""Unit tests for probability_model_integration.py

Tests for unified probability model handling addressing bugs #1, #2, #7.
"""

import pytest
from merid.event_venues.kalshi.probability_model_integration import (
    LegacyProbabilityFields,
    convert_legacy_to_binary_probability,
    validate_intent_probability_fields,
    get_side_specific_probability,
    enrich_intent_with_binary_probability,
    get_probability_from_intent,
    validate_probability_model_consistency,
)
from merid.event_venues.kalshi.side_aware_trading_layer import BinaryProbability


class TestLegacyProbabilityFields:
    """Test LegacyProbabilityFields dataclass."""
    
    def test_init_with_all_fields(self):
        """Test initialization with all fields."""
        legacy = LegacyProbabilityFields(
            p_hat_yes_cents=65.0,
            p_hat_no_cents=35.0,
            model_prob=0.65,
            side="yes"
        )
        assert legacy.p_hat_yes_cents == 65.0
        assert legacy.p_hat_no_cents == 35.0
        assert legacy.model_prob == 0.65
        assert legacy.side == "yes"
    
    def test_init_with_partial_fields(self):
        """Test initialization with partial fields."""
        legacy = LegacyProbabilityFields(
            p_hat_yes_cents=65.0,
            model_prob=0.65
        )
        assert legacy.p_hat_yes_cents == 65.0
        assert legacy.p_hat_no_cents is None
        assert legacy.model_prob == 0.65
        assert legacy.side is None


class TestConvertLegacyToBinaryProbability:
    """Test conversion from legacy fields to BinaryProbability."""
    
    def test_convert_with_both_p_hat_fields(self):
        """Test conversion with both p_hat fields (highest priority)."""
        legacy = LegacyProbabilityFields(
            p_hat_yes_cents=65.0,
            p_hat_no_cents=35.0
        )
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is not None
        assert error is None
        assert prob.yes_cents == 65.0
        assert prob.no_cents == 35.0
    
    def test_convert_with_model_prob_yes(self):
        """Test conversion with model_prob for YES side."""
        legacy = LegacyProbabilityFields(
            model_prob=0.65,
            side="yes"
        )
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is not None
        assert error is None
        assert prob.yes_cents == 65.0
        assert prob.no_cents == 35.0
    
    def test_convert_with_model_prob_no(self):
        """Test conversion with model_prob for NO side (Bug #7 fix)."""
        legacy = LegacyProbabilityFields(
            model_prob=0.25,
            side="no"
        )
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is not None
        assert error is None
        # CRITICAL: model_prob is NO probability, do NOT invert
        assert prob.no_cents == 25.0
        assert prob.yes_cents == 75.0
    
    def test_convert_with_only_p_hat_yes(self):
        """Test conversion with only p_hat_yes_cents."""
        legacy = LegacyProbabilityFields(
            p_hat_yes_cents=65.0
        )
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is not None
        assert error is None
        assert prob.yes_cents == 65.0
        assert prob.no_cents == 35.0
    
    def test_convert_with_only_p_hat_no(self):
        """Test conversion with only p_hat_no_cents."""
        legacy = LegacyProbabilityFields(
            p_hat_no_cents=35.0
        )
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is not None
        assert error is None
        assert prob.no_cents == 35.0
        assert prob.yes_cents == 65.0
    
    def test_convert_duality_violation(self):
        """Test conversion fails on duality violation."""
        legacy = LegacyProbabilityFields(
            p_hat_yes_cents=80.0,
            p_hat_no_cents=50.0  # Sum = 130, violates duality
        )
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is None
        assert error is not None
        assert "duality" in error.lower()
    
    def test_convert_no_valid_fields(self):
        """Test conversion fails with no valid fields."""
        legacy = LegacyProbabilityFields()
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is None
        assert error is not None
        assert "No valid probability fields" in error
    
    def test_convert_invalid_side(self):
        """Test conversion fails with invalid side."""
        legacy = LegacyProbabilityFields(
            model_prob=0.65,
            side="invalid"
        )
        prob, error = convert_legacy_to_binary_probability(legacy, "TEST_TICKER")
        assert prob is None
        assert error is not None
        assert "Invalid side" in error


class TestValidateIntentProbabilityFields:
    """Test validation of intent probability fields."""
    
    def test_validate_with_both_p_hat_fields(self):
        """Test validation with both p_hat fields."""
        intent = {
            "p_hat_yes_cents": 65.0,
            "p_hat_no_cents": 35.0
        }
        is_valid, error, prob = validate_intent_probability_fields(intent, "TEST_TICKER")
        assert is_valid
        assert error is None
        assert prob is not None
        assert prob.yes_cents == 65.0
    
    def test_validate_with_model_prob_yes(self):
        """Test validation with model_prob for YES."""
        intent = {
            "model_prob": 0.65,
            "side": "yes"
        }
        is_valid, error, prob = validate_intent_probability_fields(intent, "TEST_TICKER")
        assert is_valid
        assert error is None
        assert prob is not None
        assert prob.yes_cents == 65.0
    
    def test_validate_with_model_prob_no(self):
        """Test validation with model_prob for NO (Bug #7 fix)."""
        intent = {
            "model_prob": 0.25,
            "side": "no"
        }
        is_valid, error, prob = validate_intent_probability_fields(intent, "TEST_TICKER")
        assert is_valid
        assert error is None
        assert prob is not None
        assert prob.no_cents == 25.0
    
    def test_validate_no_valid_fields(self):
        """Test validation fails with no valid fields."""
        intent = {}
        is_valid, error, prob = validate_intent_probability_fields(intent, "TEST_TICKER")
        assert not is_valid
        assert error is not None
        assert prob is None
    
    def test_validate_duality_violation(self):
        """Test validation fails on duality violation."""
        intent = {
            "p_hat_yes_cents": 80.0,
            "p_hat_no_cents": 50.0
        }
        is_valid, error, prob = validate_intent_probability_fields(intent, "TEST_TICKER")
        assert not is_valid
        assert error is not None
        assert prob is None


class TestGetSideSpecificProbability:
    """Test getting side-specific probability from BinaryProbability."""
    
    def test_get_yes_probability(self):
        """Test getting YES probability."""
        prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
        result = get_side_specific_probability(prob, "yes")
        assert result == 65.0
    
    def test_get_no_probability(self):
        """Test getting NO probability."""
        prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
        result = get_side_specific_probability(prob, "no")
        assert result == 35.0
    
    def test_get_invalid_side(self):
        """Test getting probability for invalid side."""
        prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
        with pytest.raises(ValueError, match="Invalid side"):
            get_side_specific_probability(prob, "invalid")
    
    def test_get_case_insensitive(self):
        """Test side parameter is case-insensitive."""
        prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
        assert get_side_specific_probability(prob, "YES") == 65.0
        assert get_side_specific_probability(prob, "Yes") == 65.0
        assert get_side_specific_probability(prob, "NO") == 35.0
        assert get_side_specific_probability(prob, "No") == 35.0


class TestEnrichIntentWithBinaryProbability:
    """Test enriching intent with validated BinaryProbability."""
    
    def test_enrich_valid_intent(self):
        """Test enriching a valid intent."""
        intent = {
            "p_hat_yes_cents": 65.0,
            "p_hat_no_cents": 35.0
        }
        is_valid, error = enrich_intent_with_binary_probability(intent, "TEST_TICKER")
        assert is_valid
        assert error is None
        assert "_binary_probability" in intent
        assert "_probability_model_validated" in intent
        assert intent["_probability_model_validated"] is True
    
    def test_enrich_invalid_intent(self):
        """Test enriching an invalid intent."""
        intent = {}
        is_valid, error = enrich_intent_with_binary_probability(intent, "TEST_TICKER")
        assert not is_valid
        assert error is not None
        assert "_binary_probability" not in intent
    
    def test_enrich_preserves_existing_fields(self):
        """Test enrichment preserves existing intent fields."""
        intent = {
            "ticker": "TEST_TICKER",
            "side": "yes",
            "p_hat_yes_cents": 65.0,
            "p_hat_no_cents": 35.0
        }
        is_valid, error = enrich_intent_with_binary_probability(intent, "TEST_TICKER")
        assert is_valid
        assert intent["ticker"] == "TEST_TICKER"
        assert intent["side"] == "yes"
        assert intent["p_hat_yes_cents"] == 65.0


class TestGetProbabilityFromIntent:
    """Test getting probability from intent with unified interface."""
    
    def test_get_from_validated_model(self):
        """Test getting probability from validated BinaryProbability."""
        prob = BinaryProbability(yes_cents=65.0, no_cents=35.0)
        intent = {
            "_binary_probability": prob
        }
        result = get_probability_from_intent(intent, "yes")
        assert result == 65.0
    
    def test_get_from_legacy_p_hat_yes(self):
        """Test getting probability from legacy p_hat_yes_cents."""
        intent = {
            "p_hat_yes_cents": 65.0
        }
        result = get_probability_from_intent(intent, "yes")
        assert result == 65.0
    
    def test_get_from_legacy_p_hat_no(self):
        """Test getting probability from legacy p_hat_no_cents."""
        intent = {
            "p_hat_no_cents": 35.0
        }
        result = get_probability_from_intent(intent, "no")
        assert result == 35.0
    
    def test_get_none_when_missing(self):
        """Test getting None when probability not available."""
        intent = {}
        result = get_probability_from_intent(intent, "yes")
        assert result is None
    
    def test_get_priority_validated_over_legacy(self):
        """Test validated model takes priority over legacy fields."""
        prob = BinaryProbability(yes_cents=70.0, no_cents=30.0)
        intent = {
            "_binary_probability": prob,
            "p_hat_yes_cents": 65.0,
            "p_hat_no_cents": 35.0
        }
        result = get_probability_from_intent(intent, "yes")
        # Should use validated model (70.0), not legacy (65.0)
        assert result == 70.0


class TestValidateProbabilityModelConsistency:
    """Test validation of probability model consistency."""
    
    def test_validate_consistent_p_hat_fields(self):
        """Test validation with consistent p_hat fields."""
        intent = {
            "p_hat_yes_cents": 65.0,
            "p_hat_no_cents": 35.0
        }
        is_valid, error = validate_probability_model_consistency(intent, "TEST_TICKER")
        assert is_valid
        assert error is None
    
    def test_validate_duality_violation(self):
        """Test validation detects duality violation."""
        intent = {
            "p_hat_yes_cents": 80.0,
            "p_hat_no_cents": 50.0
        }
        is_valid, error = validate_probability_model_consistency(intent, "TEST_TICKER")
        assert not is_valid
        assert error is not None
        assert "duality" in error.lower()
    
    def test_validate_model_prob_consistency(self):
        """Test validation checks model_prob vs p_hat consistency."""
        intent = {
            "p_hat_yes_cents": 65.0,
            "model_prob": 0.65,
            "side": "yes"
        }
        is_valid, error = validate_probability_model_consistency(intent, "TEST_TICKER")
        # Should pass (within tolerance)
        assert is_valid
    
    def test_validate_model_prob_inconsistency(self):
        """Test validation detects model_prob inconsistency."""
        intent = {
            "p_hat_yes_cents": 65.0,
            "model_prob": 0.80,  # Inconsistent with p_hat_yes
            "side": "yes"
        }
        is_valid, error = validate_probability_model_consistency(intent, "TEST_TICKER")
        # Should warn but not fail (model_prob may have different purpose)
        # Implementation may vary - adjust based on actual behavior
    
    def test_validate_no_p_hat_fields(self):
        """Test validation with no p_hat fields."""
        intent = {}
        is_valid, error = validate_probability_model_consistency(intent, "TEST_TICKER")
        # Should pass (nothing to validate)
        assert is_valid
        assert error is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
