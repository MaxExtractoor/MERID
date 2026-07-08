"""Tests for PROFILE-GATED comments added to configuration modules.

These tests verify that PROFILE-GATED comments exist in the modified files
to alert developers about profile-specific behavior for kalshi_crypto_15m_v2.
"""

import pytest
from pathlib import Path


class TestProfileGatingComments:
    """Tests for PROFILE-GATED comments in modified modules."""

    def test_risk_profile_has_profile_gated_comment(self):
        """Verify merid/risk/risk_profile.py has PROFILE-GATED comment for edge thresholds."""
        file_path = Path(__file__).parent.parent / "merid" / "risk" / "risk_profile.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "PROFILE-GATED" in content, "PROFILE-GATED comment missing in risk_profile.py"
        assert "kalshi_crypto_15m_v2" in content, "Profile name missing in risk_profile.py"
        assert "4-7%" in content, "Profile edge bands not documented in risk_profile.py"

    def test_swarm_orchestrator_has_profile_gated_comment(self):
        """Verify merid/swarm/orchestrator.py has PROFILE-GATED comment for MIN_EDGE_BPS."""
        file_path = Path(__file__).parent.parent / "merid" / "swarm" / "orchestrator.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "PROFILE-GATED" in content, "PROFILE-GATED comment missing in orchestrator.py"
        assert "kalshi_crypto_15m_v2" in content, "Profile name missing in orchestrator.py"
        assert "400-700 bps" in content, "Profile edge bands in bps not documented in orchestrator.py"

    def test_top3_edge_allocator_has_profile_gated_comment(self):
        """Verify merid/trading/top3_edge_allocator.py has PROFILE-GATED comment for min_edge1_pct."""
        file_path = Path(__file__).parent.parent / "merid" / "trading" / "top3_edge_allocator.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "PROFILE-GATED" in content, "PROFILE-GATED comment missing in top3_edge_allocator.py"
        assert "kalshi_crypto_15m_v2" in content, "Profile name missing in top3_edge_allocator.py"
        assert "4-7%" in content, "Profile edge bands not documented in top3_edge_allocator.py"
        # CRITICAL FIX (2026-07-07): Verify cycle_risk_cap_pct comment is 5% (not 3%)
        assert "cycle_risk_cap_pct = 0.05" in content or "5% - aligned" in content, \
            "cycle_risk_cap_pct comment should reference 5% (aligned with profile), not 3%"

    def test_unified_risk_manager_has_doge_note(self):
        """Verify merid/risk/unified_risk_manager.py has NOTE about DOGE contract limit."""
        file_path = Path(__file__).parent.parent / "merid" / "risk" / "unified_risk_manager.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "DOGE" in content, "DOGE reference missing in unified_risk_manager.py"
        assert "max_contracts=1" in content, "DOGE max_contracts not documented in unified_risk_manager.py"
        assert "kalshi_crypto_15m_v2" in content, "Profile name missing in unified_risk_manager.py"

    def test_kalshi_15m_crypto_config_has_canonical_note(self):
        """Verify config/kalshi_15m_crypto_config.py clarifies series tickers are canonical."""
        file_path = Path(__file__).parent.parent / "config" / "kalshi_15m_crypto_config.py"
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        assert "CANONICAL" in content, "CANONICAL note missing in kalshi_15m_crypto_config.py"
        assert "NOT deprecated" in content, "Clarification about series tickers missing"
        assert "KALSHI_15M_SERIES_TICKERS" in content, "Series tickers reference missing"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
