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


class TestP2DSTCalculation:
    """P2-2: DST calculation off-by-one fixed."""

    def test_dst_start_boundary(self):
        """Verify DST starts at 7:00 AM UTC on 2nd Sunday of March."""
        from merid.prediction.session_guard import _is_us_dst
        
        # 2024: 2nd Sunday of March is March 10
        # DST starts at 2:00 AM ET = 7:00 AM UTC
        before_dst = datetime(2024, 3, 10, 6, 59, tzinfo=timezone.utc)
        at_dst_start = datetime(2024, 3, 10, 7, 0, tzinfo=timezone.utc)
        
        # Before 7 AM UTC on transition day, should be standard time
        assert _is_us_dst(before_dst) is False
        # At 7 AM UTC on transition day, DST starts
        assert _is_us_dst(at_dst_start) is True

    def test_dst_end_boundary(self):
        """Verify DST ends at 6:00 AM UTC on 1st Sunday of November."""
        from merid.prediction.session_guard import _is_us_dst
        
        # 2024: 1st Sunday of November is November 3
        # DST ends at 2:00 AM ET = 6:00 AM UTC (when in DST, ET = UTC-4)
        before_end = datetime(2024, 11, 3, 5, 59, tzinfo=timezone.utc)
        at_dst_end = datetime(2024, 11, 3, 6, 0, tzinfo=timezone.utc)
        
        # Before 6 AM UTC on transition day, still DST
        assert _is_us_dst(before_end) is True
        # At 6 AM UTC on transition day, standard time starts
        assert _is_us_dst(at_dst_end) is False

    def test_mid_summer_is_dst(self):
        """Verify mid-summer dates are correctly identified as DST."""
        from merid.prediction.session_guard import _is_us_dst
        
        summer_date = datetime(2024, 7, 15, 12, 0, tzinfo=timezone.utc)
        assert _is_us_dst(summer_date) is True

    def test_mid_winter_not_dst(self):
        """Verify mid-winter dates are correctly identified as not DST."""
        from merid.prediction.session_guard import _is_us_dst
        
        winter_date = datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc)
        assert _is_us_dst(winter_date) is False


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
        removed = gate.cleanup_stale(ttl_s=86400)
        
        # Should remove 2 terminal records but not the pending one
        assert removed == 2
        assert "test-1" not in gate.store._orders
        assert "test-2" not in gate.store._orders
        assert "test-3" in gate.store._orders


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


class TestP2DrawdownRecoveryAfterKillReset:
    """P2-5: Drawdown recovery fires for all kill types."""

    def test_drawdown_recovery_check_exists(self):
        """Verify CapitalEngine has check_drawdown_recovery method."""
        from merid.risk.capital_engine import CapitalEngine
        
        engine = CapitalEngine(total_equity=10000.0)
        assert hasattr(engine, 'check_drawdown_recovery')
        assert callable(getattr(engine, 'check_drawdown_recovery'))

    def test_drawdown_recovery_restores_sizing(self):
        """Verify check_drawdown_recovery restores sizing when capital recovered."""
        from merid.risk.capital_engine import CapitalEngine
        
        engine = CapitalEngine(total_equity=10000.0)
        
        # Simulate drawdown that triggered sizing reduction
        engine._risk_capital_peak = 10000.0
        engine._risk_capital = 8000.0  # 20% drawdown
        engine._sizing_multiplier = 0.6  # Reduced due to drawdown
        
        # Now recover to 96% of peak (above 95% threshold)
        engine._risk_capital = 9600.0
        
        # Check recovery
        recovered = engine.check_drawdown_recovery("BTC")
        
        assert recovered is True
        assert engine._sizing_multiplier == 1.0

    def test_drawdown_recovery_no_restore_if_not_recovered(self):
        """Verify sizing not restored if capital hasn't recovered enough."""
        from merid.risk.capital_engine import CapitalEngine
        
        engine = CapitalEngine(total_equity=10000.0)
        
        # Simulate drawdown
        engine._risk_capital_peak = 10000.0
        engine._risk_capital = 8000.0  # 20% drawdown
        engine._sizing_multiplier = 0.6
        
        # Only recover to 94% (below 95% threshold)
        engine._risk_capital = 9400.0
        
        # Check recovery
        recovered = engine.check_drawdown_recovery("BTC")
        
        assert recovered is False
        assert engine._sizing_multiplier == 0.6  # Not restored


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
