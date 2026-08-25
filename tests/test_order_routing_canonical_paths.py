"""Test order routing canonical paths (2026-07-16).

This test verifies that order routing follows canonical paths and that
deprecated components issue appropriate warnings.
"""

import pytest
import warnings
from pathlib import Path


class TestOrderRoutingCanonicalPaths:
    """Test that order routing follows canonical paths."""

    def test_canonical_order_intent_exists(self):
        """Verify canonical OrderIntent exists in order_router.py."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create a test intent
        intent = OrderIntent(
            ticker="KXBTC15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        assert intent.ticker == "KXBTC15M-TEST"
        assert intent.side == "yes"
        assert intent.action == "buy"
        assert intent.price_cents == 50
        assert intent.count == 1

    def test_canonical_order_intent_is_documented(self):
        """Verify canonical OrderIntent is documented as canonical."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Check docstring mentions canonical
        assert "CANONICAL" in OrderIntent.__doc__ or "canonical" in OrderIntent.__doc__.lower()

    def test_fills_ledger_order_intent_is_separate(self):
        """Verify fills_ledger.OrderIntent is documented as separate."""
        from merid.event_venues.kalshi.fills_ledger import OrderIntent as FillsLedgerOrderIntent
        
        # Check docstring mentions it's not a duplicate
        assert "NOT a duplicate" in FillsLedgerOrderIntent.__doc__ or "separate" in FillsLedgerOrderIntent.__doc__.lower()

    def test_route_order_async_exists(self):
        """Verify canonical async order routing function exists."""
        from merid.event_venues.kalshi.order_router import route_order_async
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create a test intent
        intent = OrderIntent(
            ticker="KXETH15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        # Function should exist (may fail in mock mode without proper setup)
        assert callable(route_order_async)

    def test_route_order_exists(self):
        """Verify synchronous order routing function exists."""
        from merid.event_venues.kalshi.order_router import route_order
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create a test intent
        intent = OrderIntent(
            ticker="KXSOL15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        # Function should exist
        assert callable(route_order)

    def test_unified_risk_manager_exists(self):
        """Verify UnifiedRiskManager exists as single source of truth."""
        from merid.risk.unified_risk_manager import UnifiedRiskManager, get_unified_risk_manager
        
        # Should be able to get instance
        risk_mgr = get_unified_risk_manager()
        assert risk_mgr is not None
        assert isinstance(risk_mgr, UnifiedRiskManager)

    def test_kalshi_risk_manager_deprecated(self):
        """Verify KalshiRiskManager is deprecated."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskManager, KalshiRiskConfig

        risk_mgr = KalshiRiskManager(config=KalshiRiskConfig())

        # The deprecation is now indicated in the class docstring, not via a
        # runtime warning (which would spam the test suite and production logs).
        assert risk_mgr is not None
        assert "DEPRECATED" in KalshiRiskManager.__doc__
        assert "UnifiedRiskManager" in KalshiRiskManager.__doc__

    def test_global_slot_allocator_exists(self):
        """Verify GlobalSlotAllocator exists for $2 exposure cap."""
        from merid.risk.global_slot_allocator import GlobalSlotAllocator
        
        # Should be able to create instance
        allocator = GlobalSlotAllocator()
        assert allocator is not None
        assert allocator.MAX_EXPOSURE_USD == 2.00

    def test_price_range_constants_exist(self):
        """Verify canonical price range constants exist."""
        from merid.event_venues.kalshi.risk_parameters import (
            CANONICAL_MIN_PRICE_CENTS,
            CANONICAL_MAX_PRICE_CENTS,
        )
        
        assert CANONICAL_MIN_PRICE_CENTS == 10
        assert CANONICAL_MAX_PRICE_CENTS == 75

    def test_legacy_order_router_15m_removed(self):
        """Verify legacy order_router_15m.py has been removed."""
        import sys
        
        try:
            from merid.event_venues.kalshi import order_router_15m
            assert False, "Legacy order_router_15m module should have been deleted"
        except ImportError:
            # Expected - module should not exist
            pass

    def test_canonical_risk_check_order_documented(self):
        """Verify canonical risk check order is documented."""
        doc_path = Path("docs/CANONICAL_RISK_CHECK_ORDER.md")
        assert doc_path.exists(), "Canonical risk check order documentation should exist"
        
        content = doc_path.read_text(encoding='utf-8')
        assert "Unified Risk Manager" in content
        assert "Single Source of Truth" in content

    def test_canonical_price_range_constants_documented(self):
        """Verify canonical price range constants are documented."""
        doc_path = Path("docs/CANONICAL_PRICE_RANGE_CONSTANTS.md")
        assert doc_path.exists(), "Canonical price range constants documentation should exist"
        
        content = doc_path.read_text(encoding='utf-8')
        assert "10-75c" in content
        assert "risk_parameters.py" in content

    def test_order_intent_required_fields(self):
        """Verify OrderIntent has all required fields."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create minimal intent
        intent = OrderIntent(
            ticker="KXXRP15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
        )
        
        # Verify required fields
        assert hasattr(intent, 'ticker')
        assert hasattr(intent, 'side')
        assert hasattr(intent, 'action')
        assert hasattr(intent, 'price_cents')
        assert hasattr(intent, 'count')
        assert hasattr(intent, 'intent_id')
        assert hasattr(intent, 'client_tag')
        assert hasattr(intent, 'snapshot_ts')

    def test_order_intent_optional_fields(self):
        """Verify OrderIntent has optional fields for risk checks."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        # Create intent with optional fields
        intent = OrderIntent(
            ticker="KXDOGE15M-TEST",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            edge_pct=0.05,
            source="test_agent",
            agent_id="agent_123",
            confidence=0.85,
        )
        
        # Verify optional fields
        assert intent.edge_pct == 0.05
        assert intent.source == "test_agent"
        assert intent.agent_id == "agent_123"
        assert intent.confidence == 0.85


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
