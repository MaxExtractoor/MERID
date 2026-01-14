"""
Unit tests for OutcomeValidator layer.

Tests:
- Consensus validation
- Market validation
- On-chain validation
- Reality gap calculation
- Anomaly detection
"""

import pytest
from agents.reflection.validator import (
    OutcomeValidator, ValidationResult, ValidationMethod
)


class TestOutcomeValidator:
    """Test suite for OutcomeValidator."""
    
    def test_validate_consensus_perfect_match(self):
        """Test perfect consensus match."""
        validator = OutcomeValidator()
        
        result = validator.validate_consensus_outcome(
            prediction="accept",
            actual_consensus="accept",
            consensus_confidence=0.9,
            vote_distribution={"accept": 8, "reject": 1, "abstain": 1}
        )
        
        assert result.validated is True
        assert result.reality_gap == 0.0
        assert result.validation_score > 0.8
        assert result.method == ValidationMethod.CONSENSUS
    
    def test_validate_consensus_complete_mismatch(self):
        """Test complete consensus mismatch."""
        validator = OutcomeValidator()
        
        result = validator.validate_consensus_outcome(
            prediction="accept",
            actual_consensus="reject",
            consensus_confidence=0.85,
            vote_distribution={"accept": 2, "reject": 7, "abstain": 1}
        )
        
        assert result.validated is False
        assert result.reality_gap == 1.0
        assert result.method == ValidationMethod.CONSENSUS
    
    def test_validate_consensus_abstain_prediction(self):
        """Test abstain prediction when should have voted."""
        validator = OutcomeValidator()
        
        result = validator.validate_consensus_outcome(
            prediction="abstain",
            actual_consensus="accept",
            consensus_confidence=0.8,
            vote_distribution={"accept": 6, "reject": 2, "abstain": 2}
        )
        
        assert result.validated is False
        assert result.reality_gap == 0.5
    
    def test_validate_market_bullish_correct(self):
        """Test correct bullish market prediction."""
        validator = OutcomeValidator()
        
        result = validator.validate_market_outcome(
            predicted_direction="bullish",
            actual_price_change=5.2,  # +5.2%
            confidence=0.75,
            timeframe_hours=24.0
        )
        
        assert result.validated is True
        assert result.reality_gap < 1.0
        assert result.method == ValidationMethod.MARKET
    
    def test_validate_market_bearish_correct(self):
        """Test correct bearish market prediction."""
        validator = OutcomeValidator()
        
        result = validator.validate_market_outcome(
            predicted_direction="bearish",
            actual_price_change=-3.8,  # -3.8%
            confidence=0.7,
            timeframe_hours=24.0
        )
        
        assert result.validated is True
        assert result.reality_gap < 1.0
    
    def test_validate_market_wrong_direction(self):
        """Test wrong market direction prediction."""
        validator = OutcomeValidator()
        
        result = validator.validate_market_outcome(
            predicted_direction="bullish",
            actual_price_change=-5.0,  # Predicted up, went down
            confidence=0.8,
            timeframe_hours=24.0
        )
        
        assert result.validated is False
        assert result.reality_gap == 1.0
    
    def test_validate_market_neutral_small_move(self):
        """Test neutral prediction with small price move."""
        validator = OutcomeValidator()
        
        result = validator.validate_market_outcome(
            predicted_direction="neutral",
            actual_price_change=0.3,  # Small move
            confidence=0.6,
            timeframe_hours=24.0
        )
        
        assert result.validated is True
        assert result.reality_gap < 0.5
    
    def test_validate_onchain_match(self):
        """Test on-chain validation match."""
        validator = OutcomeValidator()
        
        prediction = {"outcome": "executed", "value": 100}
        actual_data = {"outcome": "executed", "value": 100}
        
        result = validator.validate_onchain_outcome(
            prediction=prediction,
            actual_onchain_data=actual_data,
            verification_method="block_explorer"
        )
        
        assert result.validated is True
        assert result.reality_gap == 0.0
        assert result.validation_score == 0.95
        assert result.method == ValidationMethod.ONCHAIN
    
    def test_validate_onchain_mismatch(self):
        """Test on-chain validation mismatch."""
        validator = OutcomeValidator()
        
        prediction = {"outcome": "executed"}
        actual_data = {"outcome": "failed"}
        
        result = validator.validate_onchain_outcome(
            prediction=prediction,
            actual_onchain_data=actual_data,
            verification_method="node"
        )
        
        assert result.validated is False
        assert result.reality_gap == 0.8
    
    def test_validate_timeout(self):
        """Test timeout validation."""
        validator = OutcomeValidator()
        
        result = validator.validate_timeout(
            age_seconds=4000.0,
            timeout_threshold=3600.0
        )
        
        assert result.validated is False
        assert result.reality_gap == 0.5
        assert result.validation_score == 0.3
        assert result.method == ValidationMethod.TIMEOUT
    
    def test_calculate_aggregate_reality_gap(self):
        """Test aggregate reality gap calculation."""
        validator = OutcomeValidator()
        
        # Create multiple validations
        validations = [
            ValidationResult(
                validated=True,
                reality_gap=0.1,
                validation_score=0.9,
                method=ValidationMethod.CONSENSUS,
                evidence={},
                timestamp=0.0
            ),
            ValidationResult(
                validated=True,
                reality_gap=0.2,
                validation_score=0.8,
                method=ValidationMethod.MARKET,
                evidence={},
                timestamp=0.0
            ),
            ValidationResult(
                validated=False,
                reality_gap=0.8,
                validation_score=0.5,
                method=ValidationMethod.ONCHAIN,
                evidence={},
                timestamp=0.0
            )
        ]
        
        aggregate_gap = validator.calculate_aggregate_reality_gap(validations)
        
        # Should be weighted average
        # (0.1*0.9 + 0.2*0.8 + 0.8*0.5) / (0.9 + 0.8 + 0.5)
        expected = (0.09 + 0.16 + 0.4) / 2.2
        assert abs(aggregate_gap - expected) < 0.01
    
    def test_detect_anomalies_conflicting(self):
        """Test anomaly detection for conflicting validations."""
        validator = OutcomeValidator()
        
        validations = [
            ValidationResult(
                validated=True,
                reality_gap=0.1,
                validation_score=0.9,
                method=ValidationMethod.CONSENSUS,
                evidence={},
                timestamp=0.0
            ),
            ValidationResult(
                validated=False,
                reality_gap=0.9,
                validation_score=0.8,
                method=ValidationMethod.MARKET,
                evidence={},
                timestamp=0.0
            )
        ]
        
        anomalies = validator.detect_anomalies(validations)
        
        assert len(anomalies) > 0
        assert any("Conflicting" in a for a in anomalies)
    
    def test_detect_anomalies_low_confidence(self):
        """Test anomaly detection for low validation confidence."""
        validator = OutcomeValidator()
        
        validations = [
            ValidationResult(
                validated=True,
                reality_gap=0.5,
                validation_score=0.3,
                method=ValidationMethod.TIMEOUT,
                evidence={},
                timestamp=0.0
            ),
            ValidationResult(
                validated=False,
                reality_gap=0.6,
                validation_score=0.4,
                method=ValidationMethod.TIMEOUT,
                evidence={},
                timestamp=0.0
            )
        ]
        
        anomalies = validator.detect_anomalies(validations)
        
        assert len(anomalies) > 0
        assert any("Low validation confidence" in a for a in anomalies)
    
    def test_get_stats(self):
        """Test statistics reporting."""
        validator = OutcomeValidator()
        
        # Perform various validations
        validator.validate_consensus_outcome(
            "accept", "accept", 0.9, {"accept": 8, "reject": 2}
        )
        validator.validate_market_outcome(
            "bullish", 5.0, 0.8, 24.0
        )
        validator.validate_timeout(3700.0, 3600.0)
        
        stats = validator.get_stats()
        
        assert stats["total_validations"] == 3
        assert stats["validations_by_method"]["consensus"] == 1
        assert stats["validations_by_method"]["market"] == 1
        assert stats["validations_by_method"]["timeout"] == 1
        assert "performance" in stats


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
