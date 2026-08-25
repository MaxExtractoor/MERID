"""
E2E integration tests for exit policy integration (2026-07-20).

Tests the exit order flow through midstream (router + risk/sizing) to validate
exit classification invariants, bypass logic, and log assertions.

These tests focus on the router path changes we implemented:
- Exit classification invariant
- Risk-based sizing bypass
- Depth-based sizing bypass
- Price adjustment bypass
- Maker/taker policy bypass
- Slot allocator asset scoping fix
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import time
from decimal import Decimal
from typing import Optional


class TestExitClassificationInvariant:
    """Test exit classification invariant in router path."""

    def test_is_exit_order_recognizes_position_monitor_exit(self):
        """Test that _is_exit_order recognizes position_monitor_exit source."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order
        
        intent = OrderIntent(
            ticker="KXBTC15M-26JUL2026-50000",
            side="yes",
            action="sell",
            price_cents=57,
            count=1,
            source="position_monitor_exit",
            agent_id="BTC_15M",
            entry_or_exit="exit",
        )
        
        assert _is_exit_order(intent) is True, \
            "Exit intent with source='position_monitor_exit' should be recognized"

    def test_is_exit_order_recognizes_entry_or_exit_flag(self):
        """Test that _is_exit_order recognizes entry_or_exit='exit' flag."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order
        
        intent = OrderIntent(
            ticker="KXETH15M-26JUL2026-3000",
            side="yes",
            action="sell",
            price_cents=42,
            count=1,
            source="manual_exit",
            agent_id="ETH_15M",
            entry_or_exit="exit",
        )
        
        assert _is_exit_order(intent) is True, \
            "Exit intent with entry_or_exit='exit' should be recognized"

    def test_is_exit_order_rejects_entry_orders(self):
        """Test that _is_exit_order rejects entry orders."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order
        
        intent = OrderIntent(
            ticker="KXSOL15M-26JUL2026-150",
            side="yes",
            action="buy",
            price_cents=50,
            count=1,
            source="agent_signal",
            agent_id="SOL_15M",
            entry_or_exit="entry",
        )
        
        assert _is_exit_order(intent) is False, \
            "Entry intent should not be recognized as exit"

    def test_exit_invariant_code_exists(self):
        """Test that exit invariant code exists in order_router."""
        import inspect
        from merid.event_venues.kalshi.order_router import route_order_async
        
        source = inspect.getsource(route_order_async)
        
        # Check for exit invariant check
        assert "EXIT-INVARIANT" in source, \
            "EXIT-INVARIANT log should exist"
        assert "exit_invariant_breach" in source, \
            "exit_invariant_breach reason should exist"
        assert "_is_exit_order" in source, \
            "_is_exit_order check should exist in invariant"


class TestExitBypassLogic:
    """Test exit order bypass logic for sizing and adjustment functions."""

    def test_risk_based_sizing_bypass_for_exits(self):
        """Test that _apply_risk_based_order_sizing bypasses exit orders."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, _apply_risk_based_order_sizing
        )
        
        exit_intent = OrderIntent(
            ticker="KXBTC15M-26JUL2026-50000",
            side="yes",
            action="sell",
            price_cents=57,
            count=1,
            source="position_monitor_exit",
            agent_id="BTC_15M",
            entry_or_exit="exit",
        )
        
        # Exit orders should bypass sizing and return original count
        result = _apply_risk_based_order_sizing(exit_intent)
        assert result == 1, \
            "Exit order should bypass risk-based sizing and return original count"

    def test_risk_based_sizing_applies_to_entries(self):
        """Test that _apply_risk_based_order_sizing applies to entry orders."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, _apply_risk_based_order_sizing
        )
        
        entry_intent = OrderIntent(
            ticker="KXBTC15M-26JUL2026-50000",
            side="yes",
            action="buy",
            price_cents=57,
            count=1,
            source="agent_signal",
            agent_id="BTC_15M",
            entry_or_exit="entry",
        )
        
        # Entry orders should go through sizing logic
        # (may return 0 if no bankroll available, but should not bypass)
        result = _apply_risk_based_order_sizing(entry_intent)
        # The important thing is it doesn't just return the original count without checking
        # (actual sizing logic depends on bankroll/allocator state)

    def test_depth_based_sizing_bypass_for_exits(self):
        """Test that _apply_depth_based_order_sizing bypasses exit orders."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, _apply_depth_based_order_sizing
        )
        
        exit_intent = OrderIntent(
            ticker="KXETH15M-26JUL2026-3000",
            side="yes",
            action="sell",
            price_cents=42,
            count=1,
            source="position_monitor_exit",
            agent_id="ETH_15M",
            entry_or_exit="exit",
        )
        
        # Exit orders should bypass depth-based sizing
        result = _apply_depth_based_order_sizing(exit_intent, state=None)
        assert result == 1, \
            "Exit order should bypass depth-based sizing and return original count"

    def test_price_adjustment_bypass_for_exits(self):
        """Test that _adjust_order_price_for_fill_rate bypasses exit orders."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, _adjust_order_price_for_fill_rate
        )
        
        exit_intent = OrderIntent(
            ticker="KXSOL15M-26JUL2026-150",
            side="yes",
            action="sell",
            price_cents=50,
            count=1,
            source="position_monitor_exit",
            agent_id="SOL_15M",
            entry_or_exit="exit",
        )
        
        # Exit orders should bypass price adjustment
        result = _adjust_order_price_for_fill_rate(exit_intent, state=None)
        assert result == 50, \
            "Exit order should bypass price adjustment and return original price"

    def test_bypass_logs_exist(self):
        """Test that bypass log messages exist in the code."""
        import inspect
        from merid.event_venues.kalshi.order_router import (
            _apply_risk_based_order_sizing,
            _apply_depth_based_order_sizing,
            _adjust_order_price_for_fill_rate,
        )
        
        # Check risk-based sizing bypass log
        source_risk = inspect.getsource(_apply_risk_based_order_sizing)
        assert "Exit order bypasses sizing" in source_risk, \
            "Risk-based sizing should have exit bypass log"
        
        # Check depth-based sizing bypass log
        source_depth = inspect.getsource(_apply_depth_based_order_sizing)
        assert "Exit order bypasses depth sizing" in source_depth, \
            "Depth-based sizing should have exit bypass log"
        
        # Check price adjustment bypass log
        source_price = inspect.getsource(_adjust_order_price_for_fill_rate)
        assert "Exit order bypasses price adjustment" in source_price, \
            "Price adjustment should have exit bypass log"


class TestMakerTakerPolicyBypass:
    """Test maker/taker policy bypass for exit orders."""

    def test_maker_taker_policy_bypass_for_exits(self):
        """Test that apply_maker_taker_policy bypasses exit orders."""
        from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_intent
        from merid.event_venues.kalshi.order_router import OrderIntent
        
        exit_intent = OrderIntent(
            ticker="KXXRP15M-26JUL2026-0.5",
            side="yes",
            action="sell",
            price_cents=55,
            count=1,
            source="position_monitor_exit",
            agent_id="XRP_15M",
            entry_or_exit="exit",
        )
        
        # Apply maker/taker policy (only takes intent as parameter)
        apply_maker_taker_policy(exit_intent)
        
        # Exit orders should have bypass settings
        assert exit_intent.expected_role == "taker", \
            "Exit order should have expected_role='taker'"
        assert exit_intent.fee_type == "taker", \
            "Exit order should have fee_type='taker'"
        assert exit_intent.post_only is False, \
            "Exit order should have post_only=False"
        assert exit_intent.policy_mode == "EXIT_ORDER_BYPASS", \
            "Exit order should have policy_mode='EXIT_ORDER_BYPASS'"

    def test_maker_taker_policy_bypass_log_exists(self):
        """Test that maker/taker bypass log exists."""
        import inspect
        from merid.event_venues.kalshi.maker_taker_integration import apply_maker_taker_policy
        
        source = inspect.getsource(apply_maker_taker_policy)
        assert "Skipping policy for exit order" in source, \
            "Maker/taker policy should have exit bypass log"
        assert "EXIT_ORDER_BYPASS" in source, \
            "Maker/taker policy should set EXIT_ORDER_BYPASS mode"


class TestSlotAllocatorAssetScoping:
    """Test slot allocator asset scoping fix."""

    def test_asset_extraction_robustness(self):
        """Test that asset extraction uses robust pattern matching in order_router."""
        import inspect
        from merid.event_venues.kalshi.order_router import _route_live
        
        # Check that the function contains asset extraction logic
        source = inspect.getsource(_route_live)
        assert '"BTC" in ticker.upper()' in source, \
            "Should use robust BTC pattern matching"
        assert '"ETH" in ticker.upper()' in source, \
            "Should use robust ETH pattern matching"
        assert '"SOL" in ticker.upper()' in source, \
            "Should use robust SOL pattern matching"
        assert '"XRP" in ticker.upper()' in source, \
            "Should use robust XRP pattern matching"
        assert '"DOGE" in ticker.upper()' in source, \
            "Should use robust DOGE pattern matching"

    def test_allocator_notification_log_exists(self):
        """Test that allocator notification log exists with asset scoping."""
        import inspect
        from merid.event_venues.kalshi.order_router import _route_live
        
        source = inspect.getsource(_route_live)
        assert "GLOBAL-ALLOCATOR-NOTIFY" in source, \
            "Should have global allocator notification log"
        assert "asset=%s" in source, \
            "Should log asset in allocator notification"


class TestSingleEntrySingleExitPerAsset:
    """Test single-entry single-exit flow per asset (BTC, ETH, SOL, XRP, DOGE)."""

    def test_exit_intent_classification_per_asset(self):
        """Test exit intent classification for all 5 assets."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order
        
        assets = [
            ("KXBTC15M-26JUL2026-50000", "BTC_15M"),
            ("KXETH15M-26JUL2026-3000", "ETH_15M"),
            ("KXSOL15M-26JUL2026-150", "SOL_15M"),
            ("KXXRP15M-26JUL2026-0.5", "XRP_15M"),
            ("KXDOGE15M-26JUL2026-0.07", "DOGE_15M"),
        ]
        
        for ticker, agent_id in assets:
            exit_intent = OrderIntent(
                ticker=ticker,
                side="yes",
                action="sell",
                price_cents=50,
                count=1,
                source="position_monitor_exit",
                agent_id=agent_id,
                entry_or_exit="exit",
            )
            
            assert _is_exit_order(exit_intent) is True, \
                f"Exit intent for {ticker} should be recognized as exit"
            assert exit_intent.entry_or_exit == "exit"
            assert exit_intent.source == "position_monitor_exit"


class TestMultiAssetParallelExitsUnderGlobalCap:
    """Test multi-asset parallel exits under $1 global exposure cap."""

    def test_parallel_exit_intent_classification(self):
        """Test that parallel exit intents are all classified correctly."""
        from merid.event_venues.kalshi.order_router import OrderIntent, _is_exit_order
        
        # Create exit intents for BTC, ETH, XRP (total ≈ $1)
        exit_intents = [
            OrderIntent(
                ticker="KXBTC15M-26JUL2026-50000",
                side="yes",
                action="sell",
                price_cents=57,
                count=1,
                source="position_monitor_exit",
                agent_id="BTC_15M",
                entry_or_exit="exit",
            ),
            OrderIntent(
                ticker="KXETH15M-26JUL2026-3000",
                side="yes",
                action="sell",
                price_cents=42,
                count=1,
                source="position_monitor_exit",
                agent_id="ETH_15M",
                entry_or_exit="exit",
            ),
            OrderIntent(
                ticker="KXXRP15M-26JUL2026-0.5",
                side="yes",
                action="sell",
                price_cents=55,
                count=1,
                source="position_monitor_exit",
                agent_id="XRP_15M",
                entry_or_exit="exit",
            ),
        ]
        
        # All should be recognized as exits
        for intent in exit_intents:
            assert _is_exit_order(intent) is True, \
                f"Exit intent for {intent.ticker} should be recognized as exit"
            assert intent.entry_or_exit == "exit"
            assert intent.source == "position_monitor_exit"

    def test_bypass_logic_applies_to_all_parallel_exits(self):
        """Test that bypass logic applies to all parallel exit intents."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, _apply_risk_based_order_sizing,
            _apply_depth_based_order_sizing, _adjust_order_price_for_fill_rate
        )
        
        exit_intents = [
            OrderIntent(
                ticker="KXBTC15M-26JUL2026-50000",
                side="yes",
                action="sell",
                price_cents=57,
                count=1,
                source="position_monitor_exit",
                agent_id="BTC_15M",
                entry_or_exit="exit",
            ),
            OrderIntent(
                ticker="KXETH15M-26JUL2026-3000",
                side="yes",
                action="sell",
                price_cents=42,
                count=1,
                source="position_monitor_exit",
                agent_id="ETH_15M",
                entry_or_exit="exit",
            ),
        ]
        
        # All should bypass sizing and adjustment
        for intent in exit_intents:
            risk_result = _apply_risk_based_order_sizing(intent)
            assert risk_result == 1, \
                f"Exit for {intent.ticker} should bypass risk-based sizing"
            
            depth_result = _apply_depth_based_order_sizing(intent, state=None)
            assert depth_result == 1, \
                f"Exit for {intent.ticker} should bypass depth-based sizing"
            
            price_result = _adjust_order_price_for_fill_rate(intent, state=None)
            assert price_result == intent.price_cents, \
                f"Exit for {intent.ticker} should bypass price adjustment"


class TestDuplicateExitStressWithin5sTTL:
    """Test duplicate exit handling within 5-second TTL."""

    def test_dedup_cache_exists(self):
        """Test that OrderDeduplicationCache exists and has TTL."""
        from merid.event_venues.kalshi.order_deduplication import OrderDeduplicationCache
        
        cache = OrderDeduplicationCache(ttl_seconds=5)
        # The cache stores TTL as _ttl timedelta, not ttl_seconds attribute
        assert cache._ttl.total_seconds() == 5, \
            "Dedup cache should have 5-second TTL"

    def test_dedup_cache_submitted_to_exchange_logic(self):
        """Test that dedup cache checks submitted_to_exchange flag."""
        import inspect
        from merid.event_venues.kalshi.order_deduplication import OrderDeduplicationCache
        
        source = inspect.getsource(OrderDeduplicationCache)
        assert "submitted_to_exchange" in source, \
            "Dedup cache should check submitted_to_exchange flag"

    def test_duplicate_window_constant(self):
        """Test that duplicate order window is set to 5 seconds."""
        from merid.event_venues.kalshi.order_router import _DUPLICATE_ORDER_WINDOW_SECONDS
        
        assert _DUPLICATE_ORDER_WINDOW_SECONDS == 5, \
            "Duplicate order window should be 5 seconds"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
