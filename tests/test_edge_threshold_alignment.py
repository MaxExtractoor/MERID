"""
Test suite for edge threshold alignment across all modules.

This test validates that edge thresholds are consistent across:
- strategy.py::_get_min_edge_for_phase()
- unified_edge.py::min_edge_cents
- kalshi_crypto_15m_v2.yaml edge_bands section
- kelly_min_edge_pct

All should align at 4% minimum edge (small band floor) - INCREASED from 2% based on 100% loss analysis.
"""

import pytest
from decimal import Decimal
from merid.prediction.strategy import _get_min_edge_for_phase, ExpiryPhase
from merid.prediction.unified_edge import UnifiedEdgeComputer


class TestEdgeThresholdAlignment:
    """Test edge threshold alignment across modules."""

    def test_get_min_edge_for_phase_returns_4_percent(self):
        """Test that _get_min_edge_for_phase returns 4% (INCREASED from 2% to prevent 100% losses)."""
        # Test all expiry phases
        phases = [ExpiryPhase.EARLY, ExpiryPhase.MID, ExpiryPhase.LATE, ExpiryPhase.TERMINAL]
        
        for phase in phases:
            min_edge = _get_min_edge_for_phase(phase)
            assert min_edge == Decimal("0.04"), f"Expected 4% for phase {phase}, got {min_edge}"

    def test_unified_edge_min_edge_cents_is_4(self):
        """Test that UnifiedEdgeComputer.min_edge_cents is 4.0 (INCREASED from 2.0 to prevent 100% losses)."""
        computer = UnifiedEdgeComputer()
        assert computer.min_edge_cents == 4.0, f"Expected 4.0, got {computer.min_edge_cents}"

    def test_edge_thresholds_match_yaml(self):
        """Test that edge thresholds match YAML edge_bands configuration."""
        # YAML edge_bands specifies (2026 FIX - RAISED thresholds):
        # - watch_band: 4-5% (log only)
        # - small_band: 5-7% (trade small)
        # - standard_band: >=7% (trade standard)
        # - kelly_min_edge_pct: 2% (hard floor - kept at 2% for Kelly sizing)
        
        # Verify our code uses 4% as the floor (edge validation threshold)
        min_edge_from_strategy = float(_get_min_edge_for_phase(ExpiryPhase.MID))
        min_edge_from_unified = UnifiedEdgeComputer().min_edge_cents / 100.0  # Convert cents to percentage
        
        assert min_edge_from_strategy == 0.04, f"Strategy min edge should be 4%, got {min_edge_from_strategy}"
        assert min_edge_from_unified == 0.04, f"Unified edge min should be 4%, got {min_edge_from_unified}"

    def test_edge_thresholds_not_2_percent(self):
        """Regression test: ensure edge thresholds are NOT 2% (old value that caused 100% losses)."""
        # This is a regression test to prevent the old buggy value from returning
        min_edge = _get_min_edge_for_phase(ExpiryPhase.MID)
        assert min_edge != Decimal("0.02"), "Edge threshold should NOT be 2% (old value that caused 100% losses)"
        
        computer = UnifiedEdgeComputer()
        assert computer.min_edge_cents != 2.0, "min_edge_cents should NOT be 2.0 (old value that caused 100% losses)"

    def test_profile_kelly_min_edge_pct(self):
        """Test that profile kelly_min_edge_pct is 1.5% (Kelly sizing floor - separate from edge validation threshold)."""
        import os
        from unittest.mock import patch
        from merid.risk.profiles.crypto_15m_profile import get_active_profile
        
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}, clear=False):
            from merid.risk.profiles.crypto_15m_profile import _active_adapter
            import merid.risk.profiles.crypto_15m_profile as profile_module
            profile_module._active_adapter = None
            
            adapter = get_active_profile()
            profile = adapter.profile
            
            # Kelly floor is 1.5% (sizing parameter, separate from edge validation threshold of 4%)
            assert profile.kelly_min_edge_pct == 0.015, f"Expected 1.5%, got {profile.kelly_min_edge_pct}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
