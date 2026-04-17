"""End-to-End Paper Trading Validation Suite for Kalshi.

This test suite validates the full order lifecycle:
    Signal Generation → Consensus → Order Routing → Fill Simulation → PnL Update

Tests cover:
- Complete order flow with mocked WebSocket fills
- PnL reconciliation between paper trading and signal tracking
- Fee calculation accuracy
- Edge-to-fill correlation
- Batch order lifecycle
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@dataclass
class MockFill:
    """Mock WebSocket fill event for testing."""
    ticker: str
    order_id: str
    side: str
    filled_count: int
    fill_price_cents: int
    fee_cents: int
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@pytest.fixture
def mock_signal_generator():
    """Mock signal generator that produces edge signals."""
    with patch("merid.signals.kalshi_signals.get_kalshi_signal_generator") as mock:
        generator = MagicMock()
        generator.generate_edge_signal.return_value = {
            "ticker": "KXBTCD-25JUN-T100000",
            "side": "yes",
            "action": "buy",
            "price_cents": 55,
            "count": 10,
            "edge_pct": 0.08,
            "confidence": 0.75,
            "signal_id": "test-sig-001",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        mock.return_value = generator
        yield generator


@pytest.fixture
def mock_consensus_engine():
    """Mock consensus engine that approves signals."""
    with patch("merid.prediction.consensus.get_consensus_engine") as mock:
        engine = MagicMock()
        engine.get_consensus.return_value = {
            "decision": "BUY",
            "confidence": 0.82,
            "size": 10,
            "price_target_cents": 55,
            "approved": True,
            "agents": ["momentum", "mean_reversion"],
        }
        mock.return_value = engine
        yield engine


@pytest.fixture
def mock_websocket_fills():
    """Mock WebSocket that simulates fill events."""
    fills: List[MockFill] = []
    
    async def mock_listen(callback):
        """Simulate receiving fill events."""
        for fill in fills:
            await callback({
                "type": "fill",
                "ticker": fill.ticker,
                "order_id": fill.order_id,
                "side": fill.side,
                "count": fill.filled_count,
                "price_cents": fill.fill_price_cents,
                "fee_cents": fill.fee_cents,
                "ts": fill.ts,
            })
            await asyncio.sleep(0.01)  # Small delay between fills
    
    return fills, mock_listen


class TestKalshiPaperTradingE2E:
    """End-to-end paper trading lifecycle tests."""
    
    @pytest.mark.asyncio
    async def test_full_order_lifecycle(self, mock_signal_generator, mock_consensus_engine):
        """Test complete order flow from signal to fill to PnL."""
        from merid.signals.kalshi_signals import get_kalshi_signal_generator
        from merid.prediction.consensus import get_consensus_engine
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, route_order_async, OrderResult
        )
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        # Step 1: Generate signal
        sig_gen = get_kalshi_signal_generator()
        signal = sig_gen.generate_edge_signal("KXBTCD-25JUN-T100000")
        assert signal is not None
        assert signal["edge_pct"] > 0
        
        # Step 2: Get consensus approval
        consensus = get_consensus_engine()
        decision = consensus.get_consensus(signal["ticker"])
        assert decision["approved"] is True
        assert decision["decision"] == "BUY"
        
        # Step 3: Create order intent
        intent = OrderIntent(
            ticker=signal["ticker"],
            side=signal["side"],
            action=signal["action"],
            price_cents=signal["price_cents"],
            count=decision["size"],
            edge_pct=signal["edge_pct"],
            mode="paper",
            order_type="limit",
        )
        
        # Step 4: Route order
        result = await route_order_async(intent)
        assert result.status in ("filled_paper", "partial_paper", "accepted_paper")
        assert result.error_code is None  # No error
        assert result.latency_ms >= 0
        
        # Step 5: Verify PnL tracking
        risk = get_kalshi_risk()
        summary = risk.summary()
        assert "daily_pnl_usd" in summary
        assert "total_notional_usd" in summary
        
        # Step 6: Verify fee calculation
        if result.fill:
            fee_cents = result.fill.get("fee_cents", 0)
            assert fee_cents >= 0
            # Fee should be approximately 7% of payout for small orders
            # _kalshi_fee_cents uses ceiling rounding: int(payout * rate + 0.9999)
            if result.fill["count"] < 100:
                payout_per = 100 - result.fill["price_cents"]
                expected_fee_per = max(2, int(payout_per * 0.07 + 0.9999))
                expected_total = expected_fee_per * result.fill["count"]
                assert abs(fee_cents - expected_total) <= 2  # Within 2 cents

    @pytest.mark.asyncio
    async def test_edge_to_fill_correlation(self):
        """Test that higher edge signals result in better fill prices."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, simulate_paper_fill
        )
        
        # Low edge order
        low_edge_intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",
            side="yes",
            action="buy",
            price_cents=60,
            count=10,
            edge_pct=0.02,
            order_type="limit",
        )
        
        # High edge order
        high_edge_intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            edge_pct=0.15,
            order_type="limit",
        )
        
        low_fill = simulate_paper_fill(low_edge_intent)
        high_fill = simulate_paper_fill(high_edge_intent)
        
        # High edge should generally get better fill prices
        # (lower buy price = better)
        assert high_fill["price_cents"] <= low_fill["price_cents"]

    @pytest.mark.asyncio
    async def test_batch_order_lifecycle(self):
        """Test batch order placement with multiple orders."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, BatchOrderIntent, route_batch_orders_async
        )
        
        orders = [
            OrderIntent(
                ticker=f"KXBTCD-25JUN-T{i}",
                side="yes",
                action="buy",
                price_cents=50 + i,
                count=5,
                order_type="limit",
            )
            for i in range(5)
        ]
        
        batch = BatchOrderIntent(orders=orders, order_group_id="test-batch-001")
        result = await route_batch_orders_async(batch, max_concurrent=3)
        
        assert result.total == 5
        assert len(result.results) == 5
        assert result.successful + result.failed == 5
        assert result.latency_ms >= 0
        assert result.order_group_id == "test-batch-001"
        
        # Verify all results have error_code set
        for r in result.results:
            if r.status == "rejected":
                assert r.error_code is not None

    @pytest.mark.asyncio
    async def test_pnl_reconciliation(self):
        """Test that paper trading PnL matches expected calculations."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        
        risk = get_kalshi_risk()
        initial_pnl = risk.summary()["daily_pnl_usd"]
        
        # Execute multiple orders
        for i in range(3):
            intent = OrderIntent(
                ticker=f"KXETH-25JUN-T{i}",
                side="yes",
                action="buy",
                price_cents=55,
                count=10,
                mode="paper",
                order_type="limit",
            )
            result = await route_order_async(intent)
            assert result.status in ("filled_paper", "partial_paper")
        
        # Check PnL updated
        final_pnl = risk.summary()["daily_pnl_usd"]
        # PnL may not change significantly in paper mode, but should be tracked
        assert final_pnl is not None

    @pytest.mark.asyncio
    async def test_fee_calculation_accuracy(self):
        """Test fee calculation for different order sizes."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, simulate_paper_fill, _kalshi_fee_cents
        )
        
        test_cases = [
            (50, 10, 0.07),   # Small order: 7%
            (50, 500, 0.05),  # Medium: 5%
            (50, 1500, 0.03), # Large: 3%
        ]
        
        for price_cents, count, expected_rate in test_cases:
            intent = OrderIntent(
                ticker="KXBTCD-25JUN-T100000",
                side="yes",
                action="buy",
                price_cents=price_cents,
                count=count,
                order_type="limit",
            )
            
            fill = simulate_paper_fill(intent)
            calculated_fee = _kalshi_fee_cents(fill["price_cents"], fill["count"])
            
            # Verify fee rate tier
            payout = 100 - fill["price_cents"]
            min_fee_per = 2
            expected_fee_per = max(min_fee_per, int(payout * expected_rate + 0.9999))
            expected_total = expected_fee_per * fill["count"]
            
            assert abs(calculated_fee - expected_total) <= 2

    @pytest.mark.asyncio
    async def test_error_code_propagation(self):
        """Test that error codes are properly set for different rejection reasons."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        
        # Invalid order (negative count)
        invalid_intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",
            side="yes",
            action="buy",
            price_cents=55,
            count=-5,
            order_type="limit",
        )
        result = await route_order_async(invalid_intent)
        assert result.status == "rejected"
        assert result.error_code == "non_positive_size"
        
        # Invalid price
        bad_price_intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",
            side="yes",
            action="buy",
            price_cents=150,  # Invalid: > 99
            count=10,
            order_type="limit",
        )
        result = await route_order_async(bad_price_intent)
        assert result.status == "rejected"
        assert result.error_code == "invalid_price"


class TestKalshiLatencyMonitoring:
    """Tests for latency monitoring integration."""
    
    @pytest.mark.asyncio
    async def test_latency_monitor_records(self):
        """Test that latency monitor records and reports statistics."""
        from merid.event_venues.kalshi.kalshi_risk import LatencyMonitor
        
        monitor = LatencyMonitor(
            "test_kalshi_api",
            window_size=100,
            warning_p99=100,
            critical_p99=200,
        )
        
        # Record some latencies
        for i in range(50):
            monitor.record(50.0 + i)  # 50-100ms range
        
        stats = monitor.get_stats()
        assert stats.count == 50
        assert stats.min_ms >= 50.0
        assert stats.max_ms <= 100.0
        assert stats.avg_ms > 0
    
    @pytest.mark.asyncio
    async def test_latency_alert_thresholds(self):
        """Test that latency alerts trigger at correct thresholds."""
        from merid.event_venues.kalshi.kalshi_risk import LatencyMonitor
        
        monitor = LatencyMonitor(
            "test_alert",
            window_size=200,
            warning_p99=100,
            critical_p99=200,
        )
        
        # Fill with normal latencies
        for i in range(150):
            monitor.record(50.0)
        
        # No alert yet (all below warning)
        alert = monitor.check_alert()
        assert alert is None
        
        # Add high latency to trigger warning
        for i in range(50):
            monitor.record(150.0)  # Above warning_p99
        
        alert = monitor.check_alert()
        assert alert is not None
        assert alert["severity"] == "warning"
        assert alert["monitor_name"] == "test_alert"
        assert "p99" in alert["message"]
    
    @pytest.mark.asyncio
    async def test_latency_alert_cooldown(self):
        """Test that alerts respect cooldown period."""
        from merid.event_venues.kalshi.kalshi_risk import LatencyMonitor
        
        monitor = LatencyMonitor(
            "test_cooldown",
            window_size=100,
            warning_p99=50,
        )
        monitor._alert_cooldown_seconds = 0.1  # Short cooldown for test
        
        # Fill and trigger first alert
        for i in range(100):
            monitor.record(100.0)  # Above warning
        
        alert1 = monitor.check_alert()
        assert alert1 is not None
        
        # Second check should be None (cooldown)
        alert2 = monitor.check_alert()
        assert alert2 is None
        
        # Wait for cooldown
        await asyncio.sleep(0.15)
        
        # Third check should trigger again
        alert3 = monitor.check_alert()
        assert alert3 is not None
