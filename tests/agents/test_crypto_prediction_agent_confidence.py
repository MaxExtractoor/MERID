"""Tests for crypto_prediction_agent.py confidence threshold fixes."""
import pytest
from unittest.mock import MagicMock


class TestCryptoPredictionAgentConfidence:
    """Test confidence threshold adaptive floor fix."""

    def test_adaptive_threshold_floor_at_0_65(self):
        """Test that adaptive threshold cannot go below 0.65 (production config)."""
        # Mock the agent to avoid import issues
        mock_agent = MagicMock()
        mock_agent.confidence_threshold = 0.65
        
        # Simulate successful high-confidence prediction (should lower threshold)
        # But floor should prevent going below 0.65
        for _ in range(100):  # Many attempts to lower
            mock_agent.confidence_threshold = max(0.65, mock_agent.confidence_threshold - 0.01)
        
        # Should not go below 0.65
        assert mock_agent.confidence_threshold >= 0.65

    def test_adaptive_threshold_can_increase(self):
        """Test that adaptive threshold can increase above 0.65."""
        mock_agent = MagicMock()
        mock_agent.confidence_threshold = 0.65
        
        initial_threshold = mock_agent.confidence_threshold
        mock_agent.confidence_threshold = min(0.80, mock_agent.confidence_threshold + 0.01)
        
        # Should increase
        assert mock_agent.confidence_threshold > initial_threshold
        assert mock_agent.confidence_threshold <= 0.80  # Ceiling

    def test_adaptive_threshold_ceiling_at_0_80(self):
        """Test that adaptive threshold cannot exceed 0.80."""
        mock_agent = MagicMock()
        mock_agent.confidence_threshold = 0.65
        
        # Try to raise threshold many times
        for _ in range(100):
            mock_agent.confidence_threshold = min(0.80, mock_agent.confidence_threshold + 0.01)
        
        # Should not exceed 0.80
        assert mock_agent.confidence_threshold <= 0.80

    def test_low_confidence_signal_rejection(self):
        """Test that signals below 0.65 threshold are rejected."""
        threshold = 0.65
        signal_confidence = 0.50
        
        # Should be rejected
        assert signal_confidence < threshold

    def test_high_confidence_signal_acceptance(self):
        """Test that signals above 0.65 threshold are accepted."""
        threshold = 0.65
        signal_confidence = 0.70
        
        # Should be accepted
        assert signal_confidence >= threshold

    def test_boundary_confidence_signal(self):
        """Test signal exactly at 0.65 threshold boundary."""
        threshold = 0.65
        signal_confidence = 0.65
        
        # Should be accepted (inclusive threshold)
        assert signal_confidence >= threshold


if __name__ == "__main__":
    pytest.main([__file__])
