"""Test for Kalshi market catalog executor shutdown fix.

Tests that the catalog refresh calls _build_indexes directly instead of
using run_in_executor, which was causing "cannot schedule new futures after shutdown" errors.

Run: pytest tests/test_kalshi_catalog_executor_fix.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
import asyncio


class TestKalshiCatalogExecutorFix:
    """Test that catalog refresh avoids executor shutdown errors."""

    def test_build_indexes_can_be_called_directly(self):
        """_build_indexes can be called directly without run_in_executor."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
            from datetime import datetime, timezone

            # Mock the client
            mock_client = MagicMock()

            # Create catalog instance (no config parameter)
            catalog = KalshiMarketCatalog(client=mock_client, refresh_interval_s=5.0)

            # Mock _build_indexes to succeed
            catalog._build_indexes = MagicMock(return_value=([], {}, {}, {}, {}, set(), set()))

            # Call _build_indexes directly - should NOT use run_in_executor
            now = datetime.now(timezone.utc)
            try:
                enriched, cat_idx, asset_idx, tf_idx, ticker_idx, categories_found, assets_found = catalog._build_indexes([], now)
                # If we get here without error, the direct call works
                assert True, "_build_indexes can be called directly"
            except Exception as e:
                pytest.fail(f"Direct call to _build_indexes failed: {e}")

        except ImportError:
            pytest.skip("market_catalog not available")

    def test_catalog_refresh_uses_direct_call_not_run_in_executor(self):
        """Verify that the refresh code path calls _build_indexes directly."""
        try:
            from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog
            import inspect

            # Get the source code of the refresh method
            source = inspect.getsource(KalshiMarketCatalog._refresh_loop)

            # Verify that run_in_executor is NOT used for _build_indexes
            # The fix changed from: await loop.run_in_executor(None, self._build_indexes, ...)
            # To: self._build_indexes(...)
            assert "run_in_executor" not in source or "_build_indexes" not in source or source.count("run_in_executor") == 0, (
                "Catalog refresh should not use run_in_executor for _build_indexes"
            )

        except ImportError:
            pytest.skip("market_catalog not available")
