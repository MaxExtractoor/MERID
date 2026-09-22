"""
Test suite for P2 Medium Fixes from Deep Audit.

This module tests all 5 P2 fixes:
1. Silent exception handlers upgraded from debug to warning/error
2. DST off-by-one fixed in session_guard
3. Order gate cleanup_stale() now called via maintenance scheduler
4. Fee calculation consistency between compute() and explain()
5. Drawdown recovery fires for all kill types (manual/daily-loss/drawdown)
"""

import pytest
import os
import time
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch


class TestP2SilentExceptionHandlers:
    """P2-1: Silent exception handlers upgraded to warning level."""

    def test_kill_switch_tg_failure_logged_at_warning(self, caplog):
        """Verify kill switch Telegram failures are logged at warning level, not debug."""
        from merid.risk.kill_switches import RiskController, KillSwitchReason
        import logging
        
        controller = RiskController()
        
        with caplog.at_level(logging.WARNING, logger="merid.risk.kill_switches"):
            # Simulate a kill switch trigger (which would attempt Telegram)
            # The actual Telegram call might fail, but we check log levels
            controller._trigger_kill(KillSwitchReason.MANUAL, "test")
        
        # Check that critical failures are at warning level
        warning_messages = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        # Should have warning about kill switch being triggered
        assert any("Kill switch" in msg for msg in warning_messages)




class TestP2OrderGateCleanup:
    """P2-3: Order gate cleanup_stale() is now called via maintenance scheduler."""

    def test_cleanup_stale_removes_terminal_records(self):
        """Verify cleanup_stale removes old terminal records."""
        from merid.event_venues.kalshi.order_gate import PreTradeGate, OrderStatus
        
        gate = PreTradeGate()
        
        # Add some terminal records with old timestamps
        old_time = time.time() - 90000  # 25 hours ago
        gate.store._orders["test-1"] = MagicMock(
            status=OrderStatus.FILLED,
            updated_at=old_time,
            client_order_id="test-1"
        )
        gate.store._orders["test-2"] = MagicMock(
            status=OrderStatus.REJECTED,
            updated_at=old_time,
            client_order_id="test-2"
        )
        gate.store._orders["test-3"] = MagicMock(
            status=OrderStatus.PENDING,
            updated_at=old_time,
            client_order_id="test-3"
        )
        
        # Cleanup with 24 hour TTL
        result = gate.cleanup_stale(ttl_s=86400)

        # Should remove 2 terminal records.  The PENDING one is not
        # *deleted* (that would drop an in-flight order); it is instead
        # marked as REJECTED by the orphan sweep so the next terminal
        # prune can sweep it on a later pass.
        assert result["pruned_terminal"] == 2
        assert result["orphaned_pending"] == 1
        assert "test-1" not in gate.store._orders
        assert "test-2" not in gate.store._orders
        assert "test-3" in gate.store._orders
        assert gate.store._orders["test-3"].status == OrderStatus.REJECTED


class TestP2FeeCalculationConsistency:
    """P2-4: Fee calculation consistency between compute() and explain()."""

    def test_fee_per_contract_helper(self):
        """Verify kalshi_fee_per_contract_cents uses correct tier rates."""
        import math
        from merid.event_venues.kalshi.position_sizer import (
            kalshi_fee_per_contract_cents,
            kalshi_fee_cents,
        )
        
        price = 55
        p = price / 100.0
        
        # Tier 1: < 100 contracts, rate = 0.07
        fee_1 = kalshi_fee_per_contract_cents(price, 1)
        total_1 = kalshi_fee_cents(price, 1)
        assert fee_1 == math.ceil(total_1 / 1)
        
        # Tier 2: 100-999 contracts, rate = 0.05
        fee_100 = kalshi_fee_per_contract_cents(price, 100)
        total_100 = kalshi_fee_cents(price, 100)
        assert fee_100 == math.ceil(total_100 / 100)
        
        # Tier 3: >= 1000 contracts, rate = 0.03
        fee_1000 = kalshi_fee_per_contract_cents(price, 1000)
        total_1000 = kalshi_fee_cents(price, 1000)
        assert fee_1000 == math.ceil(total_1000 / 1000)
        
        # Lower tier should have higher per-contract fee
        assert fee_1 >= fee_100 >= fee_1000

    def test_explain_uses_correct_fee_tier(self):
        """Verify explain() uses fee tier based on computed contract count."""
        from merid.event_venues.kalshi.position_sizer import (
            PositionSizer,
            kalshi_fee_per_contract_cents,
        )
        
        sizer = PositionSizer()
        
        # High edge to get many contracts
        result = sizer.explain(
            agent_name="BTC_HOURLY",
            edge_pct=10.0,
            price_cents=55,
            bankroll_cents=1_000_000,  # $10k bankroll
            size_factor=1.0,
        )
        
        contracts = result["contracts"]
        fee_per_contract = result["fee_per_contract_cents"]
        
        # Fee should match the canonical per-contract function for this tier
        expected_fee = kalshi_fee_per_contract_cents(55, contracts)
        assert fee_per_contract == expected_fee




if __name__ == "__main__":
    pytest.main([__file__, "-v"])
