"""Tests for CTExecutionAdapter — Shadow Mode Router Integration.

Phase 1: Shadow mode parity logging
Phase 2: Canary flip to live router calls
Phase 3: Direct HTTP removal
"""

import pytest

from merid.trading.ct_execution_adapter import (
    CTExecutionAdapter,
    ParityLogEntry,
    get_ct_execution_adapter,
)


class TestCTExecutionAdapter:
    """Test CT → Router adapter functionality."""

    def test_adapter_singleton(self):
        """get_ct_execution_adapter returns singleton instance."""
        adapter1 = get_ct_execution_adapter()
        adapter2 = get_ct_execution_adapter()
        assert adapter1 is adapter2

    def test_order_dict_to_intent_conversion(self):
        """CT order dict is correctly converted to OrderIntent."""
        adapter = CTExecutionAdapter()

        order_data = {
            "ticker": "KXBTC-15M-100000",
            "side": "yes",
            "action": "buy",
            "count": 5,
            "yes_price": 55,
            "client_order_id": "test-123",
            "group_id": "ct_btc",
        }

        intent = adapter._order_dict_to_intent(order_data)

        assert intent.ticker == "KXBTC-15M-100000"
        assert intent.side == "yes"
        assert intent.action == "buy"
        assert intent.count == 5
        assert intent.price_cents == 55
        assert intent.client_tag == "test-123"
        assert intent.group_id == "ct_btc"
        assert intent.source == "ct_execution_adapter"
        assert intent.agent_id == "kalshi_ct"

    def test_parity_log_entry_structure(self):
        """ParityLogEntry captures all comparison fields."""
        entry = ParityLogEntry(
            ticker="KXBTC-15M-100000",
            side="yes",
            count=5,
            price_cents=55,
            http_status="filled",
            router_status="filled_paper",
            http_latency_ms=150.0,
            router_latency_ms=45.0,
            fill_count_http=5,
            fill_count_router=5,
            parity_match=True,
            ts=1234567890.0,
        )

        assert entry.parity_match is True
        assert entry.fill_count_http == 5

    def test_get_stats_initial_state(self):
        """Stats start at zero."""
        adapter = CTExecutionAdapter()
        stats = adapter.get_stats()

        assert stats["shadow_calls"] == 0
        assert stats["parity_matches"] == 0
        assert stats["parity_mismatches"] == 0
        assert stats["parity_rate"] == 0.0


class TestCTExecutionAdapterIntegration:
    """Integration tests with actual router calls (mock mode)."""

    @pytest.mark.asyncio
    async def test_shadow_mode_returns_result(self):
        """Shadow mode calls router and returns OrderResult."""
        from merid.event_venues.kalshi.order_router import OrderResult, TradingMode

        adapter = CTExecutionAdapter()
        order_data = {
            "ticker": "KXBTC-TEST-12345",
            "side": "yes",
            "action": "buy",
            "count": 1,
            "yes_price": 50,
        }

        # Shadow mode call (uses mock/paper mode by default)
        result = await adapter.execute_shadow(order_data)

        # Should return OrderResult
        assert result is not None
        assert isinstance(result, OrderResult)
        # In mock/paper mode, should be filled
        assert "filled" in result.status or result.status == "rejected"

    @pytest.mark.asyncio
    async def test_shadow_mode_logs_parity(self):
        """Shadow mode logs parity when HTTP result provided."""
        adapter = CTExecutionAdapter()
        order_data = {
            "ticker": "KXBTC-TEST-12345",
            "side": "yes",
            "action": "buy",
            "count": 1,
            "yes_price": 50,
        }
        http_result = {
            "status": "filled",
            "filled_count": 1,
        }

        initial_stats = adapter.get_stats()
        initial_calls = initial_stats["shadow_calls"]

        await adapter.execute_shadow(order_data, http_result=http_result)

        final_stats = adapter.get_stats()
        # Should have incremented shadow_calls
        assert final_stats["shadow_calls"] == initial_calls + 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
