"""Tests for phantom detection crypto threshold adjustment (P3 FIX)."""

import pytest
from datetime import datetime, timezone

from merid.reconciliation.phantom_detection import (
    PhantomDetector,
    PhantomDetectionConfig,
    PhantomPosition,
    ResolutionAction
)


class TestCryptoThresholdAdjustment:
    """Test phantom detection threshold adjustment for crypto markets."""
    
    def test_default_latency_threshold_increased(self):
        """Test that default latency threshold is increased to 120s for crypto."""
        config = PhantomDetectionConfig()
        
        # P3 FIX: Threshold increased from 60s to 120s
        assert config.LATENCY_THRESHOLD_SECONDS == 120
    
    def test_phantom_classification_with_new_threshold(self):
        """Test phantom classification uses the new 120s threshold."""
        detector = PhantomDetector()
        
        # Create a phantom position with recent fill (within 120s)
        fill_time = datetime.now(timezone.utc)
        # 90 seconds ago - should be classified as LATENCY with new threshold
        fill_time = datetime.fromtimestamp(fill_time.timestamp() - 90, timezone.utc)
        
        phantom = detector.detect_phantom(
            market_id="KXBTCD-25JUN-T100000",
            internal_yes_qty=10,
            internal_no_qty=0,
            external_yes_qty=0,
            external_no_qty=0,
            fill_timestamp=fill_time
        )
        
        # Should be detected as phantom
        assert phantom is not None
        
        # Should be classified as LATENCY (within 120s threshold)
        assert phantom.resolution_action == ResolutionAction.WAIT
    
    def test_phantom_classification_beyond_threshold(self):
        """Test phantom classification beyond 120s threshold."""
        detector = PhantomDetector()
        
        # Create a phantom position with old fill (beyond 120s)
        fill_time = datetime.now(timezone.utc)
        # 150 seconds ago - should NOT be classified as LATENCY with new threshold
        fill_time = datetime.fromtimestamp(fill_time.timestamp() - 150, timezone.utc)
        
        phantom = detector.detect_phantom(
            market_id="KXBTCD-25JUN-T100000",
            internal_yes_qty=10,
            internal_no_qty=0,
            external_yes_qty=0,
            external_no_qty=0,
            fill_timestamp=fill_time
        )
        
        # Should be detected as phantom
        assert phantom is not None
        
        # Should NOT be classified as LATENCY (beyond 120s threshold)
        assert phantom.resolution_action != ResolutionAction.WAIT
    
    def test_custom_config_override(self):
        """Test that custom config can override default threshold."""
        custom_config = PhantomDetectionConfig(LATENCY_THRESHOLD_SECONDS=60)
        detector = PhantomDetector(config=custom_config)
        
        # Custom config should override default
        assert detector.config.LATENCY_THRESHOLD_SECONDS == 60
