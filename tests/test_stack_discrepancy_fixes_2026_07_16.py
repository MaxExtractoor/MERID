"""
Test suite for stack-wide discrepancy fixes (2026-07-16).

This test suite verifies that all legacy references have been updated to match
the current production configuration:
- 10-75c canonical price range (expanded from 10-50c)
- Fixed $1 exposure model (percentage-based caps DISABLED)
- 42.5c midpoint calculations (updated from 50c)
"""

import pytest
from pathlib import Path


class TestPriceRange75cAlignment:
    """Test that all components use 10-75c canonical range."""

    def test_market_filter_default_config_75c(self):
        """Test that DEFAULT_FILTER_CONFIG uses 75c max price."""
        from merid.event_venues.kalshi.market_filter import DEFAULT_FILTER_CONFIG
        
        assert DEFAULT_FILTER_CONFIG.min_price_cents == 10, \
            f"Expected min_price_cents=10, got {DEFAULT_FILTER_CONFIG.min_price_cents}"
        assert DEFAULT_FILTER_CONFIG.max_price_cents == 75, \
            f"Expected max_price_cents=75, got {DEFAULT_FILTER_CONFIG.max_price_cents}"

    def test_strategy_midpoint_42_5c(self):
        """Test that strategy.py uses 42.5c midpoint for 10-75c range."""
        # Check that comments reference 42.5c midpoint
        strategy_path = Path(__file__).parent.parent / "merid" / "prediction" / "strategy.py"
        with open(strategy_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Should have 42.5c midpoint references, not 50c
        assert "42.5c" in content or "42c" in content, \
            "strategy.py should reference 42.5c midpoint for 10-75c range"
        
        # Should not have "50c price - canonical range midpoint" (old reference)
        assert "50c price - canonical range midpoint" not in content, \
            "strategy.py should not reference 50c as canonical range midpoint"

    def test_deep_trading_blocker_audit_75c(self):
        """Test that deep_trading_blocker_audit.py expects 75c."""
        audit_path = Path(__file__).parent.parent / "scripts" / "deep_trading_blocker_audit.py"
        with open(audit_path, 'r') as f:
            content = f.read()
        
        # Should recommend 75c, not 50c
        assert "max_price_cents=75" in content, \
            "deep_trading_blocker_audit.py should recommend max_price_cents=75"
        assert "expected 75c" in content, \
            "deep_trading_blocker_audit.py should expect 75c"

    def test_diagnose_order_path_75c(self):
        """Test that diagnose_order_path.py checks for 10-75c range."""
        diag_path = Path(__file__).parent.parent / "scripts" / "diagnose_order_path.py"
        with open(diag_path, 'r') as f:
            content = f.read()
        
        # Should check for 10-75c range
        assert "10-75c" in content, \
            "diagnose_order_path.py should check for 10-75c range"
        assert "max_price_cents = 75" in content, \
            "diagnose_order_path.py should check for max_price_cents=75"


class TestPercentageCapsDisabled:
    """Test that percentage-based allocation caps are DISABLED (0.0)."""

    def test_risk_limits_yaml_percentage_caps_disabled(self):
        """Test that risk_limits.yaml has percentage caps set to 0.0."""
        import yaml
        
        risk_limits_path = Path(__file__).parent.parent / "config" / "risk_limits.yaml"
        with open(risk_limits_path, 'r') as f:
            risk_limits = yaml.safe_load(f)
        
        # Check that percentage-based caps are DISABLED (0.0)
        assert risk_limits['bankroll']['max_cycle_risk_pct'] == 0.0, \
            f"Expected max_cycle_risk_pct=0.0 (DISABLED), got {risk_limits['bankroll']['max_cycle_risk_pct']}"
        assert risk_limits['bankroll']['max_total_risk_pct'] == 0.0, \
            f"Expected max_total_risk_pct=0.0 (DISABLED), got {risk_limits['bankroll']['max_total_risk_pct']}"
        assert risk_limits['per_trade']['max_notional_pct'] == 0.0, \
            f"Expected max_notional_pct=0.0 (DISABLED), got {risk_limits['per_trade']['max_notional_pct']}"
        assert risk_limits['categories']['crypto']['max_notional_pct'] == 0.0, \
            f"Expected crypto max_notional_pct=0.0 (DISABLED), got {risk_limits['categories']['crypto']['max_notional_pct']}"
        
        # Fixed exposure cap should be $1.00
        assert risk_limits['fixed_exposure_cap_usd'] == 1.00, \
            f"Expected fixed_exposure_cap_usd=1.00, got {risk_limits['fixed_exposure_cap_usd']}"

    def test_unified_risk_enforcement_legacy_comments(self):
        """Test that unified_risk_enforcement.py has legacy comments for percentage caps."""
        from merid.config.unified_risk_enforcement import ABSOLUTE_MAX_RISK_PER_TRADE_PCT
        
        # This is a legacy ceiling (DISABLED for 15m)
        assert ABSOLUTE_MAX_RISK_PER_TRADE_PCT == 0.03, \
            f"Expected 0.03 (legacy ceiling, DISABLED for 15m), got {ABSOLUTE_MAX_RISK_PER_TRADE_PCT}"


class TestMidpointCalculations:
    """Test that midpoint calculations use 42.5c for 10-75c range."""

    def test_deep_spread_edge_audit_42_5c(self):
        """Test that deep_spread_edge_audit.py uses 42.5c midpoint."""
        audit_path = Path(__file__).parent.parent / "scripts" / "deep_spread_edge_audit.py"
        with open(audit_path, 'r') as f:
            content = f.read()
        
        # Should reference 42.5c midpoint
        assert "42.5c" in content or "42c" in content, \
            "deep_spread_edge_audit.py should reference 42.5c midpoint for 10-75c range"
        
        # Should not reference 50c as midpoint
        assert "50c midpoint = 0.50 probability" not in content, \
            "deep_spread_edge_audit.py should not reference 50c as midpoint"

    def test_deep_trading_blocker_audit_42c_fallback(self):
        """Test that deep_trading_blocker_audit.py references 42c fallback."""
        audit_path = Path(__file__).parent.parent / "scripts" / "deep_trading_blocker_audit.py"
        with open(audit_path, 'r') as f:
            content = f.read()
        
        # Should reference 42c midpoint in fallback pattern
        assert "42c midpoint" in content, \
            "deep_trading_blocker_audit.py should reference 42c midpoint for 10-75c range"


class TestTestFilesUpdated:
    """Test that test files have been updated to match production config."""

    def test_market_filter_test_75c(self):
        """Test that test_kalshi_market_filter.py expects 75c."""
        test_path = Path(__file__).parent / "event_venues" / "kalshi" / "test_kalshi_market_filter.py"
        with open(test_path, 'r') as f:
            content = f.read()
        
        # Should test for 75c max price
        assert "max_price_cents == 75" in content, \
            "test_kalshi_market_filter.py should test for max_price_cents=75"
        assert "10-75c" in content, \
            "test_kalshi_market_filter.py should reference 10-75c range"

    def test_risk_limits_yaml_consistency_0_0(self):
        """Test that test_risk_limits_yaml_consistency.py expects 0.0 for percentage caps."""
        test_path = Path(__file__).parent / "test_risk_limits_yaml_consistency.py"
        with open(test_path, 'r') as f:
            content = f.read()
        
        # Should expect 0.0 for DISABLED percentage caps
        assert "== 0.0" in content, \
            "test_risk_limits_yaml_consistency.py should expect 0.0 for DISABLED percentage caps"
        assert "DISABLED for 15m" in content, \
            "test_risk_limits_yaml_consistency.py should mention DISABLED for 15m"

    def test_risk_threshold_fixes_legacy_comments(self):
        """Test that test_risk_threshold_fixes.py has legacy comments."""
        test_path = Path(__file__).parent / "test_risk_threshold_fixes.py"
        with open(test_path, 'r') as f:
            content = f.read()
        
        # Should have legacy comments explaining these are DISABLED for 15m
        assert "legacy default" in content, \
            "test_risk_threshold_fixes.py should have legacy default comments"
        assert "DISABLED for 15m" in content, \
            "test_risk_threshold_fixes.py should mention DISABLED for 15m"


class TestNoLegacy50cReferences:
    """Test that legacy 50c references have been updated."""

    def test_no_50c_canonical_range_references(self):
        """Test that no files reference 50c as canonical range upper bound."""
        import re
        
        # Check key files for legacy 50c canonical range references
        files_to_check = [
            "merid/prediction/strategy.py",
            "merid/prediction/agent_grid_15m.py",
            "merid/event_venues/kalshi/market_filter.py",
            "merid/risk/profiles/crypto_15m_profile.py",
        ]
        
        project_root = Path(__file__).parent.parent
        for file_rel in files_to_check:
            file_path = project_root / file_rel
            if not file_path.exists():
                continue
            
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Check for "10-50c" or "10c-50c" patterns (legacy canonical range)
            # Allow "50c" in other contexts (e.g., crisis regime, legacy comments)
            # But reject explicit canonical range references
            legacy_patterns = [
                r'canonical.*range.*10.*50',
                r'10c.*50c.*canonical',
                r'max_price_cents.*=.*50.*#.*canonical',
            ]
            
            for pattern in legacy_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                assert not matches, \
                    f"{file_rel} has legacy canonical range reference: {matches}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
