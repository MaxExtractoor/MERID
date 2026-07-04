"""
Tests for price clamping and max_contracts validation fixes in kalshi_tools.py

This test suite validates the critical fixes to prevent:
1. Purchases at $0.99 (price clamping to [15, 70] range)
2. Overspending (max_contracts validation to per-asset limits)

Run with: pytest tests/test_kalshi_tools_price_and_contracts_fixes.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
from decimal import Decimal


class TestPriceClampingFixes:
    """Test that price clamping uses [50, 70] range instead of [1, 99]."""

    def test_build_live_route_order_intent_clamps_price(self):
        """Test that build_live_route_order_intent clamps price to [50, 70] range."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        # Test price above 70c should be clamped to 70c
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=99,  # Should be clamped to 70
            count=1,
        )
        assert intent.price_cents == 70, f"Expected 70c, got {intent.price_cents}c"
        
        # Test price below 50c should be clamped to 50c
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=5,  # Should be clamped to 50
            count=1,
        )
        assert intent.price_cents == 50, f"Expected 50c, got {intent.price_cents}c"
        
        # Test price within range should not be clamped
        intent = build_live_route_order_intent(
            ticker="KXBTC15M-26APR191645-45",
            side="yes",
            action="buy",
            price_cents=65,  # Should remain 65
            count=1,
        )
        assert intent.price_cents == 65, f"Expected 65c, got {intent.price_cents}c"


class TestMaxContractsValidation:
    """Test that max_contracts validation respects per-asset limits."""

    def test_build_live_route_order_intent_clamps_count_to_asset_limit(self):
        """Test that build_live_route_order_intent clamps count to per-asset max_contracts (2)."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        # Mock profile with max_contracts=2 for BTC
        mock_profile = MagicMock()
        mock_profile.assets = {
            "BTC": MagicMock(max_contracts=2),
            "ETH": MagicMock(max_contracts=2),
            "SOL": MagicMock(max_contracts=2),
            "XRP": MagicMock(max_contracts=2),
            "DOGE": MagicMock(max_contracts=2),
        }
        mock_adapter = MagicMock()
        mock_adapter.profile = mock_profile
        
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=mock_adapter):
            # Test count above asset limit should be clamped to 2
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,  # Should be clamped to 2
            )
            assert intent.count == 2, f"Expected 2 contracts, got {intent.count}"
            
            # Test count within limit should not be clamped
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=1,  # Should remain 1
            )
            assert intent.count == 1, f"Expected 1 contract, got {intent.count}"

    def test_build_live_route_order_intent_uses_default_limit_when_profile_unavailable(self):
        """Test that build_live_route_order_intent uses default limit (2) when profile unavailable."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=None):
            # Test count above default limit should be clamped to 2
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,  # Should be clamped to 2 (default)
            )
            assert intent.count == 2, f"Expected 2 contracts (default), got {intent.count}"

    def test_build_live_route_order_intent_respects_different_asset_limits(self):
        """Test that build_live_route_order_intent respects different per-asset limits."""
        from merid.prediction.kalshi_tools import build_live_route_order_intent
        
        # Mock profile with different max_contracts per asset
        mock_profile = MagicMock()
        mock_profile.assets = {
            "BTC": MagicMock(max_contracts=2),
            "ETH": MagicMock(max_contracts=2),
            "SOL": MagicMock(max_contracts=2),
            "XRP": MagicMock(max_contracts=2),
            "DOGE": MagicMock(max_contracts=2),
        }
        mock_adapter = MagicMock()
        mock_adapter.profile = mock_profile
        
        with patch('merid.risk.profiles.crypto_15m_profile.get_active_profile', return_value=mock_adapter):
            # Test BTC limit
            intent = build_live_route_order_intent(
                ticker="KXBTC15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for BTC, got {intent.count}"
            
            # Test ETH limit
            intent = build_live_route_order_intent(
                ticker="KXETH15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for ETH, got {intent.count}"
            
            # Test SOL limit
            intent = build_live_route_order_intent(
                ticker="KXSOL15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for SOL, got {intent.count}"
            
            # Test XRP limit
            intent = build_live_route_order_intent(
                ticker="KXXRP15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for XRP, got {intent.count}"
            
            # Test DOGE limit
            intent = build_live_route_order_intent(
                ticker="KXDOGE15M-26APR191645-45",
                side="yes",
                action="buy",
                price_cents=50,
                count=5,
            )
            assert intent.count == 2, f"Expected 2 contracts for DOGE, got {intent.count}"
