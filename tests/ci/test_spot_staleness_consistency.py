"""CI Test: Spot Price Staleness Consistency

P0-001 Audit CI Test — Validates that all staleness checks use the unified
max_spot_age_seconds() helper rather than hardcoded constants.

This prevents inconsistency where different paths use 30s vs 120s defaults.

Run: pytest tests/ci/test_spot_staleness_consistency.py -v
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch

from merid.prediction.model import max_spot_age_seconds, MAX_PRICE_AGE_SECONDS
from merid.prediction.strategy import SNAPSHOT_STALE_SECONDS


class TestSpotStalenessConsistency:
    """Validate spot staleness configuration is consistent across all paths."""

    def test_max_spot_age_seconds_default(self) -> None:
        """max_spot_age_seconds() must return 120 by default."""
        # Ensure env var is not set
        with patch.dict(os.environ, {}, clear=False):
            # Remove env var if it exists
            env_copy = os.environ.copy()
            if "MERID_PM_MAX_SPOT_AGE_SECONDS" in env_copy:
                del os.environ["MERID_PM_MAX_SPOT_AGE_SECONDS"]

            result = max_spot_age_seconds()
            assert result == 120, f"Expected 120, got {result}"

    def test_max_spot_age_seconds_env_override(self) -> None:
        """max_spot_age_seconds() must respect MERID_PM_MAX_SPOT_AGE_SECONDS env var."""
        with patch.dict(os.environ, {"MERID_PM_MAX_SPOT_AGE_SECONDS": "60"}):
            result = max_spot_age_seconds()
            assert result == 60, f"Expected 60, got {result}"

    def test_max_spot_age_seconds_invalid_env_fallback(self) -> None:
        """max_spot_age_seconds() must fall back to default on invalid env var."""
        with patch.dict(os.environ, {"MERID_PM_MAX_SPOT_AGE_SECONDS": "invalid"}):
            result = max_spot_age_seconds()
            assert result == MAX_PRICE_AGE_SECONDS, f"Expected fallback to {MAX_PRICE_AGE_SECONDS}, got {result}"

    def test_snapshot_stale_seconds_uses_helper(self) -> None:
        """SNAPSHOT_STALE_SECONDS must be derived from max_spot_age_seconds()."""
        # SNAPSHOT_STALE_SECONDS is set at import time by calling max_spot_age_seconds()
        # We can't easily test dynamic env changes here, but we can verify the value
        # matches what we'd expect from the helper
        expected = max_spot_age_seconds()
        assert SNAPSHOT_STALE_SECONDS == expected, \
            f"SNAPSHOT_STALE_SECONDS ({SNAPSHOT_STALE_SECONDS}) != max_spot_age_seconds() ({expected})"

    def test_max_price_age_seconds_constant(self) -> None:
        """MAX_PRICE_AGE_SECONDS must be 120 (the unified default)."""
        assert MAX_PRICE_AGE_SECONDS == 120, \
            f"MAX_PRICE_AGE_SECONDS ({MAX_PRICE_AGE_SECONDS}) != 120"

    def test_no_hardcoded_staleness_literals_in_model(self) -> None:
        """Verify model.py doesn't have hardcoded staleness literals (except MAX_PRICE_AGE_SECONDS)."""
        import inspect
        from merid.prediction import model

        source = inspect.getsource(model)

        # Should not find hardcoded 30 (the old inconsistent default)
        # except in comments or the MAX_PRICE_AGE_SECONDS definition
        lines = source.split("\n")
        for i, line in enumerate(lines, 1):
            # Skip comments and the constant definition
            stripped = line.strip()
            if stripped.startswith("#") or "MAX_PRICE_AGE_SECONDS" in stripped:
                continue
            # Check for hardcoded 30 that might be a staleness value
            if "30" in stripped and ("age" in stripped.lower() or "stale" in stripped.lower() or "seconds" in stripped.lower()):
                pytest.fail(f"Potential hardcoded staleness value at line {i}: {line}")


class TestSpotAgeMetricsExist:
    """Validate that P0-001 metrics are registered."""

    def test_staleness_violation_counter_exists(self) -> None:
        """merid_pm_spot_staleness_violations_total counter must be registered."""
        from monitoring.metrics import get_metrics_registry

        registry = get_metrics_registry()
        counter = registry._metrics.get("merid_pm_spot_staleness_violations_total")
        assert counter is not None, "merid_pm_spot_staleness_violations_total counter not found"

        # Verify labels
        assert "asset" in counter.label_names, "Missing 'asset' label"
        assert "market_id" in counter.label_names, "Missing 'market_id' label"

    def test_spot_age_gauge_exists(self) -> None:
        """merid_pm_spot_age_seconds gauge must be registered."""
        from monitoring.metrics import get_metrics_registry

        registry = get_metrics_registry()
        gauge = registry._metrics.get("merid_pm_spot_age_seconds")
        assert gauge is not None, "merid_pm_spot_age_seconds gauge not found"

        # Verify labels
        assert "asset" in gauge.label_names, "Missing 'asset' label"

    def test_helper_functions_exist(self) -> None:
        """Metric helper functions must exist."""
        from monitoring.metrics import record_pm_spot_staleness_violation, update_pm_spot_age

        assert callable(record_pm_spot_staleness_violation)
        assert callable(update_pm_spot_age)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
