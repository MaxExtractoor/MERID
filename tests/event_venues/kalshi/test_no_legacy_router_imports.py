"""Test that legacy order_router_15m has been removed.

This test verifies that the legacy order_router_15m module was deleted
in the 2026-07-16 order router audit cleanup.
"""

import pytest
import os


class TestLegacyRouterRemoved:
    """Test that legacy order_router_15m has been removed."""

    def test_legacy_router_file_deleted(self):
        """Verify order_router_15m.py file has been deleted."""
        router_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "..",
            "..",
            "merid",
            "event_venues",
            "kalshi",
            "order_router_15m.py"
        )
        
        # File should not exist (deleted in 2026-07-16 audit cleanup)
        assert not os.path.exists(router_path), \
            "Legacy order_router_15m.py should have been deleted"

    def test_legacy_router_not_importable(self):
        """Verify order_router_15m module cannot be imported."""
        try:
            import merid.event_venues.kalshi.order_router_15m
            assert False, "Legacy order_router_15m module should not be importable"
        except ImportError:
            # Expected - module should not exist
            pass
