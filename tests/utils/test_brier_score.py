"""Tests for utils/brier_score.py."""
import pytest
import numpy as np
from utils.brier_score import (
    brier_score,
    brier_skill_score,
    decompose_brier_score,
    interpret_brier_score,
    BinaryOutcome,
)


class TestBinaryOutcome:
    """Test BinaryOutcome dataclass."""

    def test_creation(self):
        """Test BinaryOutcome creation."""
        outcome = BinaryOutcome(predicted_probability=0.8, actual_outcome=1)
        assert outcome.predicted_probability == 0.8
        assert outcome.actual_outcome == 1


class TestBrierScore:
    """Test brier_score function."""

    def test_perfect_prediction(self):
        """Test perfect prediction gives Brier score of 0."""
        y_true = [1, 0, 1, 0]
        y_prob = [1.0, 0.0, 1.0, 0.0]
        assert brier_score(y_true, y_prob) == 0.0

    def test_worst_prediction(self):
        """Test worst prediction gives Brier score of 1."""
        y_true = [1, 0, 1, 0]
        y_prob = [0.0, 1.0, 0.0, 1.0]
        assert brier_score(y_true, y_prob) == 1.0

    def test_example_calculation(self):
        """Test example from documentation."""
        y_true = [1, 1, 0, 1]
        y_prob = [0.27, 0.67, 0.83, 0.90]
        bs = brier_score(y_true, y_prob)
        expected = np.mean([
            (0.27 - 1)**2,
            (0.67 - 1)**2,
            (0.83 - 0)**2,
            (0.90 - 1)**2
        ])
        assert abs(bs - expected) < 1e-6

    def test_mismatched_lengths_raises(self):
        """Test mismatched lengths raises ValueError."""
        with pytest.raises(ValueError, match="same length"):
            brier_score([1, 0], [0.5])

    def test_empty_data_raises(self):
        """Test empty data raises ValueError."""
        with pytest.raises(ValueError, match="empty"):
            brier_score([], [])

    def test_invalid_true_values_raises(self):
        """Test invalid y_true values raises ValueError."""
        with pytest.raises(ValueError, match="0 or 1"):
            brier_score([1, 2, 0], [0.5, 0.5, 0.5])

    def test_invalid_prob_values_raises(self):
        """Test invalid probability values raises ValueError."""
        with pytest.raises(ValueError, match="probabilities"):
            brier_score([1, 0], [1.5, -0.1])


class TestBrierSkillScore:
    """Test brier_skill_score function."""

    def test_perfect_skill(self):
        """Test perfect model gives BSS of 1."""
        assert brier_skill_score(0.0, 0.5) == 1.0

    def test_no_skill(self):
        """Test model equal to reference gives BSS of 0."""
        assert brier_skill_score(0.5, 0.5) == 0.0

    def test_negative_skill(self):
        """Test worse model gives negative BSS."""
        assert brier_skill_score(0.6, 0.5) < 0

    def test_zero_reference_raises(self):
        """Test zero reference Brier score raises ValueError."""
        with pytest.raises(ValueError, match="cannot be zero"):
            brier_skill_score(0.5, 0.0)


class TestDecomposeBrierScore:
    """Test decompose_brier_score function."""

    def test_returns_dict_with_components(self):
        """Test returns dictionary with all components."""
        y_true = [1, 0, 1, 0, 1, 0]
        y_prob = [0.8, 0.2, 0.7, 0.3, 0.9, 0.1]
        result = decompose_brier_score(y_true, y_prob)
        
        assert "brier_score" in result
        assert "reliability" in result
        assert "resolution" in result
        assert "uncertainty" in result
        assert "decomposition_check" in result
        assert "base_rate" in result
        assert "n_bins" in result

    def test_mismatched_lengths_raises(self):
        """Test mismatched lengths raises ValueError."""
        with pytest.raises(ValueError, match="same length"):
            decompose_brier_score([1, 0], [0.5])


class TestInterpretBrierScore:
    """Test interpret_brier_score function."""

    def test_excellent_quality(self):
        """Test score < 0.1 is excellent."""
        result = interpret_brier_score(0.05)
        assert result["quality"] == "excellent"

    def test_good_quality(self):
        """Test score 0.1-0.2 is good."""
        result = interpret_brier_score(0.15)
        assert result["quality"] == "good"

    def test_fair_quality(self):
        """Test score 0.2-0.3 is fair."""
        result = interpret_brier_score(0.25)
        assert result["quality"] == "fair"

    def test_poor_quality(self):
        """Test score >= 0.3 is poor."""
        result = interpret_brier_score(0.35)
        assert result["quality"] == "poor"

    def test_with_reference_perfect_skill(self):
        """Test skill interpretation - perfect."""
        result = interpret_brier_score(0.0, reference_brier=0.5)
        assert result["skill_interpretation"] == "perfect"

    def test_with_reference_excellent_skill(self):
        """Test skill interpretation - excellent."""
        result = interpret_brier_score(0.1, reference_brier=0.5)
        assert result["skill_interpretation"] == "excellent"

    def test_with_reference_good_skill(self):
        """Test skill interpretation - good."""
        result = interpret_brier_score(0.3, reference_brier=0.5)
        assert result["skill_interpretation"] == "good"
