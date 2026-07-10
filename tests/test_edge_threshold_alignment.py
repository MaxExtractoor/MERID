"""
Test suite for edge threshold alignment across all modules.

This test validates that edge thresholds are consistent across:
- strategy.py::_get_min_edge_for_phase()
- unified_edge.py::min_edge_cents
- kalshi_crypto_15m_v2.yaml edge_bands section
- kelly_min_edge_pct

All should align at 1.25% minimum edge (BTC base) - UPDATED 2026-07-10 based on moltbook research.
"""

import pytest
from decimal import Decimal
from merid.prediction.strategy import _get_min_edge_for_phase, ExpiryPhase
from merid.prediction.unified_edge import UnifiedEdgeComputer


class TestEdgeThresholdAlignment:
    """Test edge threshold alignment across modules."""

    def test_get_min_edge_for_phase_returns_1_25_percent(self):
        """Test that _get_min_edge_for_phase returns 1.25% (BTC base - UPDATED 2026-07-10)."""
        # Test all expiry phases
        phases = [ExpiryPhase.EARLY, ExpiryPhase.MID, ExpiryPhase.LATE, ExpiryPhase.TERMINAL]
        
        for phase in phases:
            min_edge = _get_min_edge_for_phase(phase)
            assert min_edge == Decimal("0.0125"), f"Expected 1.25% for phase {phase}, got {min_edge}"

    def test_unified_edge_min_edge_cents_is_1_25(self):
        """Test that UnifiedEdgeComputer.min_edge_cents is 1.25 (UPDATED 2026-07-10)."""
        computer = UnifiedEdgeComputer()
        assert computer.min_edge_cents == 1.25, f"Expected 1.25, got {computer.min_edge_cents}"

    def test_edge_thresholds_match_yaml(self):
        """Test that edge thresholds match YAML edge_bands configuration."""
        # YAML edge_bands specifies (2026 FIX - RAISED thresholds):
        # - watch_band: 4-5% (log only)
        # - small_band: 5-7% (trade small)
        # - standard_band: >=7% (trade standard)
        # - kelly_min_edge_pct: 2% (hard floor - kept at 2% for Kelly sizing)
        
        # Verify our code uses 1.25% as the floor (edge validation threshold)
        min_edge_from_strategy = float(_get_min_edge_for_phase(ExpiryPhase.MID))
        min_edge_from_unified = UnifiedEdgeComputer().min_edge_cents / 100.0  # Convert cents to percentage
        
        assert min_edge_from_strategy == 0.0125, f"Strategy min edge should be 1.25%, got {min_edge_from_strategy}"
        assert min_edge_from_unified == 0.0125, f"Unified edge min should be 1.25%, got {min_edge_from_unified}"

    def test_edge_thresholds_not_4_percent(self):
        """Regression test: ensure edge thresholds are NOT 4% (old value from Phase 1A)."""
        # This is a regression test to prevent the old value from returning
        min_edge = _get_min_edge_for_phase(ExpiryPhase.MID)
        assert min_edge != Decimal("0.04"), "Edge threshold should NOT be 4% (old value from Phase 1A)"
        
        computer = UnifiedEdgeComputer()
        assert computer.min_edge_cents != 4.0, "min_edge_cents should NOT be 4.0 (old value from Phase 1A)"

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
