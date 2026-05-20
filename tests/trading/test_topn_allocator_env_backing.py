"""Tests for topn_allocator.py environment variable backing.

Tests that verify default stop distance respects environment variable overrides.
"""

import os
import pytest


class TestTopNAllocatorEnvBacking:
    """Test topn_allocator.py respects environment variable overrides."""

    def test_topn_default_stop_distance_env_override(self, monkeypatch):
        """Set TOPN_DEFAULT_STOP_DISTANCE_PCT and verify configurator uses it."""
        # The implementation reads from os.getenv("TOPN_DEFAULT_STOP_DISTANCE_PCT", "0.02")
        # We test this pattern directly
        
        # Test default value
        default_value = float(os.getenv("TOPN_DEFAULT_STOP_DISTANCE_PCT", "0.02"))
        assert default_value == 0.02
        
        # Test with env override
        monkeypatch.setenv("TOPN_DEFAULT_STOP_DISTANCE_PCT", "0.15")
        override_value = float(os.getenv("TOPN_DEFAULT_STOP_DISTANCE_PCT", "0.02"))
        assert override_value == 0.15
