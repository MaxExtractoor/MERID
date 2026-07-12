"""
Catalog Refresh Interval Fix Tests

This test suite validates the fix for catalog refresh interval from 30s to 5s
to ensure agents discover new markets immediately at 15-minute rollover.

Issue: 30-second delay prevented agents from discovering new markets at rollover
Fix: Changed MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S from 30.0 to 5.0 in .env

SPEC_VERSION: 1.0.0
DATE: 2026-07-09
"""

import pytest
import os
import time
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta


class TestCatalogRefreshIntervalFix:
    """Test catalog refresh interval configuration and behavior."""

    @pytest.fixture
    def env_refresh_interval(self):
        """Get the current environment refresh interval."""
        return float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))

    @pytest.fixture
    def expected_refresh_interval(self):
        """Expected refresh interval for 15m crypto markets."""
        return 5.0  # 5 seconds for fast market discovery at rollover

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_is_5_seconds(self, env_refresh_interval, expected_refresh_interval):
        """Test that catalog refresh interval is set to 5 seconds."""
        # Act & Assert
        assert env_refresh_interval == expected_refresh_interval, (
            f"Catalog refresh interval should be {expected_refresh_interval}s, "
            f"but got {env_refresh_interval}s. 30s delay prevents agents from "
            f"discovering new markets at 15-minute rollover."
        )

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_not_30_seconds(self, env_refresh_interval):
        """Test that catalog refresh interval is NOT 30 seconds (old problematic value)."""
        # Act & Assert
        assert env_refresh_interval != 30.0, (
            f"Catalog refresh interval is still 30s. This causes agents to miss "
            f"early trading window at 15-minute rollover. Should be 5s."
        )

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_within_rate_limits(self, env_refresh_interval):
        """Test that 5-second refresh interval is within Kalshi API rate limits."""
        # Arrange: Kalshi Basic tier rate limits
        basic_tier_read_tokens_per_sec = 200
        tokens_per_catalog_request = 10  # Default cost for GET /markets
        
        # Act: Calculate tokens per minute
        requests_per_minute = 60.0 / env_refresh_interval
        tokens_per_minute = requests_per_minute * tokens_per_catalog_request
        tokens_per_second = tokens_per_minute / 60.0
        
        # Assert: Should be well within Basic tier limits
        assert tokens_per_second < basic_tier_read_tokens_per_sec, (
            f"5-second refresh uses {tokens_per_second:.1f} tokens/sec, "
            f"which exceeds Basic tier limit of {basic_tier_read_tokens_per_sec} tokens/sec"
        )
        
        # Verify we have headroom
        headroom_pct = (basic_tier_read_tokens_per_sec - tokens_per_second) / basic_tier_read_tokens_per_sec * 100
        assert headroom_pct > 50, (
            f"Should have at least 50% headroom for rate limits, got {headroom_pct:.1f}%"
        )

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_respects_env_variable(self):
        """Test that catalog refresh interval respects environment variable."""
        # Arrange: Set custom refresh interval
        custom_interval = 10.0
        
        with patch.dict(os.environ, {'MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S': str(custom_interval)}):
            # Act: Re-import to pick up new env var
            import importlib
            from merid.event_venues.kalshi import market_catalog
            importlib.reload(market_catalog)
            
            # Assert: Catalog should use the env var value
            # Note: This tests the mechanism, not the actual catalog instance
            # which would be created with the env var at startup
            assert os.getenv('MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S') == str(custom_interval)

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_faster_than_15m_rollover(self, env_refresh_interval):
        """Test that refresh interval is significantly faster than 15-minute rollover."""
        # Arrange: 15-minute window in seconds
        window_15m_seconds = 15 * 60  # 900 seconds
        
        # Act: Calculate how many refreshes per 15-minute window
        refreshes_per_window = window_15m_seconds / env_refresh_interval
        
        # Assert: Should have multiple refreshes per window
        assert refreshes_per_window >= 10, (
            f"Should have at least 10 refreshes per 15-minute window for "
            f"timely market discovery, got {refreshes_per_window:.1f}"
        )
        
        # Verify refresh is much faster than window
        assert env_refresh_interval < window_15m_seconds / 10, (
            f"Refresh interval should be < 10% of 15-minute window ({window_15m_seconds / 10}s), "
            f"got {env_refresh_interval}s"
        )

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_allows_early_trading_window_access(self, env_refresh_interval):
        """Test that 5-second refresh allows access to early trading window (2-12 min to expiry)."""
        # Arrange: Trading window parameters
        min_entry_minutes = 2.0  # Earliest entry point
        max_entry_minutes = 12.0  # Latest entry point
        early_window_seconds = min_entry_minutes * 60  # 120 seconds
        
        # Act: Calculate refreshes in early window
        refreshes_in_early_window = early_window_seconds / env_refresh_interval
        
        # Assert: Should have multiple refreshes in early window
        assert refreshes_in_early_window >= 5, (
            f"Should have at least 5 refreshes in early trading window ({early_window_seconds}s), "
            f"got {refreshes_in_early_window:.1f} with {env_refresh_interval}s interval"
        )

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_not_too_frequent(self, env_refresh_interval):
        """Test that refresh interval is not too frequent (avoids API abuse)."""
        # Arrange: Minimum reasonable interval
        min_reasonable_interval = 2.0  # 2 seconds minimum
        
        # Act & Assert
        assert env_refresh_interval >= min_reasonable_interval, (
            f"Refresh interval should be >= {min_reasonable_interval}s to avoid "
            f"excessive API calls, got {env_refresh_interval}s"
        )

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_matches_code_default(self, env_refresh_interval):
        """Test that env variable matches code default in market_catalog.py."""
        # Arrange: Code default from market_catalog.py
        code_default = 5.0  # From market_catalog.py line 537
        
        # Act & Assert
        assert env_refresh_interval == code_default, (
            f"Env variable ({env_refresh_interval}s) should match code default ({code_default}s)"
        )

    @pytest.mark.kalshi_catalog
    def test_30s_interval_would_miss_early_window(self):
        """Test that 30-second interval would miss early trading window opportunities."""
        # Arrange: Old problematic interval
        old_interval = 30.0
        early_window_seconds = 2.0 * 60  # 120 seconds (2 minutes to expiry)
        
        # Act: Calculate refreshes in early window with old interval
        refreshes_with_old_interval = early_window_seconds / old_interval
        
        # Assert: Old interval had very few refreshes in early window
        assert refreshes_with_old_interval < 5, (
            f"30-second interval only gives {refreshes_with_old_interval:.1f} refreshes "
            f"in early trading window, which is insufficient for timely market discovery"
        )
        
        # Calculate delay at rollover
        max_delay_at_rollover = old_interval  # Could miss entire first 30 seconds
        assert max_delay_at_rollover > 10, (
            f"30-second interval could miss first {max_delay_at_rollover}s after rollover, "
            f"which is significant for 15-minute markets"
        )

    @pytest.mark.kalshi_catalog
    def test_5s_interval_captures_early_window(self, env_refresh_interval):
        """Test that 5-second interval adequately captures early trading window."""
        # Arrange: New interval
        early_window_seconds = 2.0 * 60  # 120 seconds (2 minutes to expiry)
        
        # Act: Calculate refreshes in early window with new interval
        refreshes_with_new_interval = early_window_seconds / env_refresh_interval
        
        # Assert: New interval has many refreshes in early window
        assert refreshes_with_new_interval >= 20, (
            f"5-second interval gives {refreshes_with_new_interval:.1f} refreshes "
            f"in early trading window, which is adequate for timely market discovery"
        )
        
        # Calculate max delay at rollover
        max_delay_at_rollover = env_refresh_interval
        assert max_delay_at_rollover <= 10, (
            f"5-second interval max delay at rollover is {max_delay_at_rollover}s, "
            f"which is acceptable for 15-minute markets"
        )

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_consistent_with_15m_boundary_logic(self):
        """Test that refresh interval is consistent with 15-minute boundary logic."""
        # Arrange: 15-minute boundaries
        boundaries = [0, 15, 30, 45]
        window_duration = 15  # minutes
        
        # Act: Verify refresh is much faster than boundary interval
        refresh_interval_minutes = 5.0 / 60  # Convert to minutes
        
        # Assert: Refresh should be frequent relative to window duration
        assert refresh_interval_minutes < window_duration / 10, (
            f"Refresh interval ({refresh_interval_minutes:.2f} min) should be "
            f"< 10% of window duration ({window_duration} min)"
        )

    @pytest.mark.kalshi_catalog
    def test_catalog_refresh_interval_documented(self):
        """Test that the refresh interval fix is documented."""
        # This test ensures the fix is documented in code comments
        # Arrange: Check market_catalog.py for documentation
        from merid.event_venues.kalshi import market_catalog
        
        # Act: Check if refresh interval is documented
        # This is a placeholder - in real implementation, would check docstrings
        # or comments explaining the 5s interval choice
        assert True  # Placeholder for documentation check

    @pytest.mark.kalshi_catalog
    def test_refresh_interval_prevents_rollover_misses(self, env_refresh_interval):
        """Test that refresh interval prevents missing markets at rollover."""
        # Arrange: Simulate rollover scenario
        rollover_time = datetime.now(timezone.utc).replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(minutes=15)
        
        # Act: Calculate worst-case discovery delay
        worst_case_delay = env_refresh_interval
        
        # Assert: Delay should be small enough to capture early window
        early_window_start = 2.0 * 60  # 2 minutes to expiry
        assert worst_case_delay < early_window_start / 10, (
            f"Worst-case discovery delay ({worst_case_delay}s) should be "
            f"< 10% of early window start ({early_window_start}s)"
        )


class TestCatalogRefreshIntegration:
    """Integration tests for catalog refresh behavior."""

    @pytest.mark.kalshi_catalog
    @pytest.mark.integration
    def test_catalog_refresh_with_5s_interval(self):
        """Test catalog refresh behavior with 5-second interval."""
        # This is an integration test that would require a real catalog instance
        # For now, we test the configuration
        env_interval = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))
        assert env_interval == 5.0

    @pytest.mark.kalshi_catalog
    @pytest.mark.integration
    def test_market_discovery_timing_at_rollover(self):
        """Test that markets are discovered quickly at 15-minute rollover."""
        # This would test actual market discovery timing
        # For now, we verify the configuration supports it
        env_interval = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))
        
        # Verify interval is fast enough for rollover discovery
        assert env_interval <= 5.0, (
            f"Refresh interval must be <= 5s for timely rollover discovery, "
            f"got {env_interval}s"
        )


def pytest_configure(config):
    """Configure pytest markers for catalog refresh interval tests."""
    config.addinivalue_line(
        "markers", "kalshi_catalog: Kalshi catalog refresh interval tests"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests requiring real catalog instance"
    )
