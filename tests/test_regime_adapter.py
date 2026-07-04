"""Tests for regime adapter that bridges simple detectors to canonical ops.regime_detection.

This tests the compatibility layer that allows agent_grid_15m.py to continue using
its existing detector while benefiting from canonical risk controls.
"""

import pytest
from unittest.mock import Mock, patch


class TestRegimeMapping:
    """Test regime mapping between different detector implementations."""
    
    def test_map_prediction_detector_bull(self):
        """Test mapping prediction detector BULL to canonical TRENDING_BULL."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_prediction_regime("bull")
        assert canonical == "trending_bull"
    
    def test_map_prediction_detector_choppy(self):
        """Test mapping prediction detector CHOPPY to canonical MEAN_REVERTING."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_prediction_regime("choppy")
        assert canonical == "mean_reverting"
    
    def test_map_prediction_detector_bear(self):
        """Test mapping prediction detector BEAR to canonical TRENDING_BEAR."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_prediction_regime("bear")
        assert canonical == "trending_bear"
    
    def test_map_prediction_detector_unknown(self):
        """Test mapping unknown regime to canonical UNKNOWN."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_prediction_regime("unknown")
        assert canonical == "unknown"
    
    def test_map_strategies_detector_trending_up(self):
        """Test mapping strategies detector TRENDING_UP to canonical TRENDING_BULL."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_strategies_regime("trending_up")
        assert canonical == "trending_bull"
    
    def test_map_strategies_detector_trending_down(self):
        """Test mapping strategies detector TRENDING_DOWN to canonical TRENDING_BEAR."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_strategies_regime("trending_down")
        assert canonical == "trending_bear"
    
    def test_map_strategies_detector_ranging(self):
        """Test mapping strategies detector RANGING to canonical MEAN_REVERTING."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_strategies_regime("ranging")
        assert canonical == "mean_reverting"
    
    def test_map_strategies_detector_volatile(self):
        """Test mapping strategies detector VOLATILE to canonical HIGH_VOLATILITY."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_strategies_regime("volatile")
        assert canonical == "high_volatility"
    
    def test_map_strategies_detector_quiet(self):
        """Test mapping strategies detector QUIET to canonical TRENDING_BULL."""
        from ops.regime_adapter import RegimeMapping
        canonical = RegimeMapping.map_strategies_regime("quiet")
        assert canonical == "trending_bull"


class TestRegimeAdapter:
    """Test RegimeAdapter functionality."""
    
    def test_adapter_initialization(self):
        """Test adapter initializes with no state."""
        from ops.regime_adapter import RegimeAdapter
        adapter = RegimeAdapter()
        assert adapter.get_state() is None
        assert adapter.get_canonical_regime() is None
    
    def test_update_from_prediction_detector(self):
        """Test updating adapter from prediction detector."""
        from ops.regime_adapter import RegimeAdapter
        adapter = RegimeAdapter()
        
        state = adapter.update_from_prediction_detector("bull", confidence=0.8)
        
        assert state.source_regime == "bull"
        assert state.canonical_regime == "trending_bull"
        assert state.confidence == 0.8
        assert state.source == "prediction_detector"
        assert adapter.get_canonical_regime() == "trending_bull"
    
    def test_update_from_strategies_detector(self):
        """Test updating adapter from strategies detector."""
        from ops.regime_adapter import RegimeAdapter
        adapter = RegimeAdapter()
        
        state = adapter.update_from_strategies_detector("ranging", confidence=0.7)
        
        assert state.source_regime == "ranging"
        assert state.canonical_regime == "mean_reverting"
        assert state.confidence == 0.7
        assert state.source == "strategies_detector"
        assert adapter.get_canonical_regime() == "mean_reverting"
    
    def test_adapter_state_persistence(self):
        """Test that adapter state persists between updates."""
        from ops.regime_adapter import RegimeAdapter
        adapter = RegimeAdapter()
        
        adapter.update_from_prediction_detector("bull", confidence=0.8)
        assert adapter.get_canonical_regime() == "trending_bull"
        
        adapter.update_from_prediction_detector("bear", confidence=0.9)
        assert adapter.get_canonical_regime() == "trending_bear"
    
    @patch('ops.regime_detection.get_regime_detector')
    def test_adapter_updates_canonical_detector(self, mock_get_detector):
        """Test that adapter updates canonical detector when available."""
        from ops.regime_adapter import RegimeAdapter
        
        # Mock canonical detector
        mock_detector = Mock()
        mock_get_detector.return_value = mock_detector
        
        adapter = RegimeAdapter()
        adapter.update_from_prediction_detector("bull", confidence=0.8)
        
        # Verify canonical detector was updated
        mock_detector.update_from_adapter.assert_called_once_with("trending_bull", 0.8)
    
    @patch('ops.regime_detection.get_regime_detector')
    def test_adapter_handles_canonical_detector_error(self, mock_get_detector):
        """Test that adapter handles canonical detector errors gracefully."""
        from ops.regime_adapter import RegimeAdapter
        
        # Mock canonical detector to raise error
        mock_detector = Mock()
        mock_detector.update_from_adapter.side_effect = Exception("Detector error")
        mock_get_detector.return_value = mock_detector
        
        adapter = RegimeAdapter()
        # Should not raise exception
        state = adapter.update_from_prediction_detector("bull", confidence=0.8)
        
        # State should still be updated
        assert state.canonical_regime == "trending_bull"


class TestRegimeDetectorAdapterIntegration:
    """Test integration between adapter and canonical detector."""
    
    @patch('ops.regime_detection.get_regime_detector')
    def test_adapter_updates_detector_state(self, mock_get_detector):
        """Test that adapter updates canonical detector state correctly."""
        from ops.regime_adapter import get_regime_adapter
        from ops.regime_detection import MarketRegime, RegimeState
        
        # Mock canonical detector
        mock_detector = Mock()
        mock_get_detector.return_value = mock_detector
        
        adapter = get_regime_adapter()
        adapter.update_from_prediction_detector("bull", confidence=0.8)
        
        # Verify detector was called with correct parameters
        mock_detector.update_from_adapter.assert_called_once_with("trending_bull", 0.8)
    
    @patch('ops.regime_detection.get_regime_detector')
    def test_multiple_regime_transitions(self, mock_get_detector):
        """Test that adapter handles multiple regime transitions."""
        from ops.regime_adapter import get_regime_adapter
        
        # Mock canonical detector
        mock_detector = Mock()
        mock_get_detector.return_value = mock_detector
        
        adapter = get_regime_adapter()
        
        # Simulate regime transitions
        adapter.update_from_prediction_detector("bull", confidence=0.8)
        adapter.update_from_prediction_detector("choppy", confidence=0.7)
        adapter.update_from_prediction_detector("bear", confidence=0.9)
        
        # Verify detector was updated for each transition
        assert mock_detector.update_from_adapter.call_count == 3
        
        # Verify correct canonical regimes were passed
        calls = mock_detector.update_from_adapter.call_args_list
        assert calls[0][0][0] == "trending_bull"
        assert calls[1][0][0] == "mean_reverting"
        assert calls[2][0][0] == "trending_bear"


class TestRegimeDetectorUpdateFromAdapter:
    """Test RegimeDetector.update_from_adapter method."""
    
    def test_update_from_adapter_creates_state(self):
        """Test that update_from_adapter creates correct regime state."""
        from ops.regime_detection import RegimeDetector, MarketRegime
        
        detector = RegimeDetector()
        
        # Update from adapter
        detector.update_from_adapter("trending_bull", confidence=0.8)
        
        state = detector.get_current_state()
        assert state is not None
        assert state.current_regime == MarketRegime.TRENDING_BULL
        assert state.confidence == 0.8
        assert state.stability_score == 0.8
        assert state.observations_in_regime == 1
    
    def test_update_from_adapter_invalid_regime(self):
        """Test that update_from_adapter handles invalid regime gracefully."""
        from ops.regime_detection import RegimeDetector, MarketRegime
        
        detector = RegimeDetector()
        
        # Update with invalid regime
        detector.update_from_adapter("invalid_regime", confidence=0.8)
        
        state = detector.get_current_state()
        assert state is not None
        assert state.current_regime == MarketRegime.UNKNOWN
    
    def test_update_from_adapter_observations_increment(self):
        """Test that observations increment on each update."""
        from ops.regime_detection import RegimeDetector, MarketRegime
        
        detector = RegimeDetector()
        
        # First update
        detector.update_from_adapter("trending_bull", confidence=0.8)
        state1 = detector.get_current_state()
        assert state1.observations_in_regime == 1
        
        # Second update (same regime)
        detector.update_from_adapter("trending_bull", confidence=0.9)
        state2 = detector.get_current_state()
        assert state2.observations_in_regime == 2
        
        # Third update (different regime)
        detector.update_from_adapter("mean_reverting", confidence=0.7)
        state3 = detector.get_current_state()
        assert state3.observations_in_regime == 3
    
    def test_update_from_adapter_constraints(self):
        """Test that update_from_adapter sets correct constraints."""
        from ops.regime_detection import RegimeDetector, MarketRegime, REGIME_CONSTRAINTS
        
        detector = RegimeDetector()
        
        # Update to bear regime
        detector.update_from_adapter("trending_bear", confidence=0.8)
        
        state = detector.get_current_state()
        assert state.constraints == REGIME_CONSTRAINTS[MarketRegime.TRENDING_BEAR]
        assert state.constraints.position_size_multiplier == 0.7
        assert state.constraints.leverage_multiplier == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
