"""Tests for single source of truth validation.

Verifies that kalshi_crypto_15m_v2.yaml is the only active config source
and that obsolete/deprecated sources are not used in production.
"""
from __future__ import annotations

import os
import pytest
from pathlib import Path


class TestSingleSourceOfTruth:
    """Verify single source of truth for risk configuration."""

    def test_profile_yaml_exists(self):
        """Verify the profile YAML exists and is the correct file."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        assert profile_path.exists(), f"Profile YAML must exist at {profile_path}"
        
        # Verify it has the single source of truth header
        content = profile_path.read_text(encoding="utf-8")
        assert "SINGLE SOURCE OF TRUTH" in content, "Profile YAML must have single source of truth header"
        assert "Industry best practices applied" in content, "Profile YAML must document industry best practices"

    def test_snapshot_directories_deleted(self):
        """Verify obsolete snapshot directories are deleted."""
        snapshots_path = Path(__file__).parent.parent / "web" / "snapshots"
        if snapshots_path.exists():
            # Check that no 15m_risk_* directories exist
            risk_snapshots = list(snapshots_path.glob("15m_risk_*"))
            assert len(risk_snapshots) == 0, f"Obsolete snapshot directories must be deleted: {risk_snapshots}"

    def test_allocator_tests_archived(self):
        """Verify allocator tests are archived (not in main tests directory)."""
        tests_path = Path(__file__).parent
        allocator_test = tests_path / "test_crypto15m_allocator.py"
        budget_test = tests_path / "test_kalshi_risk_15m_budget.py"
        
        # These should NOT exist in main tests directory
        assert not allocator_test.exists(), f"Allocator test must be archived: {allocator_test}"
        assert not budget_test.exists(), f"Budget test must be archived: {budget_test}"
        
        # They should exist in archive
        archive_path = Path(__file__).parent.parent / "archive" / "legacy" / "tests"
        assert (archive_path / "test_crypto15m_allocator.py").exists(), "Allocator test must be in archive"
        assert (archive_path / "test_kalshi_risk_15m_budget.py").exists(), "Budget test must be in archive"

    def test_deprecated_config_has_warning(self):
        """Verify deprecated config has deprecation warning."""
        config_path = Path(__file__).parent.parent / "config" / "kalshi_15m_crypto_config.py"
        content = config_path.read_text(encoding="utf-8")
        
        assert "DEPRECATION NOTICE" in content, "Deprecated config must have deprecation notice"
        assert "kalshi_crypto_15m_v2.yaml" in content, "Deprecated config must reference profile YAML"
        assert "DeprecationWarning" in content, "Deprecated config must use DeprecationWarning"

    def test_profile_has_no_conflicting_limits(self):
        """Verify profile YAML has no conflicting rate limits."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        content = profile_path.read_text(encoding="utf-8")
        
        # These conflicting limits should be removed (check for the value pattern, not just the key)
        assert "max_orders_per_minute:\n    value: 30" not in content, "Conflicting max_orders_per_minute should be removed"
        assert "max_orders_per_hour:\n    value: 300" not in content, "Conflicting max_orders_per_hour should be removed"
        assert "max_orders_per_cycle: 5" not in content, "Duplicate max_orders_per_cycle should be removed"
        
        # The primary limit should exist (updated to 12 per profile YAML 2026-07-07)
        assert "max_orders_per_15m_window: 12" in content, "Primary 15m window limit must exist (updated to 12)"
        assert "global_orders_limit: 30" in content, "Primary global rate limit must exist (updated to 30)"

    def test_production_code_path_uses_profile(self):
        """Verify production code path uses profile adapter."""
        main_15m_path = Path(__file__).parent.parent / "web" / "main_15m_lean.py"
        content = main_15m_path.read_text(encoding="utf-8")
        
        # Check for profile adapter usage (may be imported differently)
        assert "get_active_profile" in content or "Crypto15mProfileAdapter" in content, "Production code must use profile adapter"
        assert "kalshi_crypto_15m_v2" in content, "Production code must reference profile name"

    def test_profile_values_aligned_with_industry(self):
        """Verify profile values align with industry best practices."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        content = profile_path.read_text(encoding="utf-8")
        
        # Check industry-aligned values are documented
        assert "half-Kelly" in content, "Profile must document half-Kelly usage"
        assert "token bucket" in content, "Profile must document token bucket algorithm"
        assert "2%" in content or "0.02" in content, "Profile must document per-trade risk percentage"
        
        # Check conservative limits (per-asset max_contracts is set to 10 per 2026-07-07 fix)
        assert "max_contracts:\n      value: 10" in content, "Max contracts should be 10 (updated for multi-contract exits)"
        assert "drawdown_halt_pct" in content, "Drawdown halt should be defined"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
