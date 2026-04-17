"""Historical Stress Scenarios for Kalshi E2E Testing.

Adds known high-volatility and edge-case scenarios to validate:
- Circuit breaker behavior under sustained load
- Order rejection handling during market halts  
- Latency monitoring during congestion
- Regime detection during volatility spikes
- Kill switch activation during drawdowns

Scenarios are based on real historical events or synthetic stress patterns.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest


@dataclass
class StressScenario:
    """Definition of a stress test scenario."""
    name: str
    description: str
    duration_seconds: float
    market_conditions: Dict[str, Any]
    expected_behavior: Dict[str, Any]


# ── Historical Scenarios ─────────────────────────────────────────────────

SCENARIO_BTC_FLASH_CRASH = StressScenario(
    name="BTC_Flash_Crash_2024_03",
    description="Bitcoin flash crash scenario - 15% drop in 2 minutes",
    duration_seconds=120,
    market_conditions={
        "price_volatility_annualized": 0.85,
        "spread_cents": 15,
        "volume_spike_factor": 3.5,
        "correlation_btc_eth": 0.92,
    },
    expected_behavior={
        "circuit_breaker_may_trip": True,
        "position_sizing_reduced": True,
        "kill_switch_standby": True,
    },
)

SCENARIO_FOMC_ANNOUNCEMENT = StressScenario(
    name="FOMC_Announcement_Volatility",
    description="Fed rate decision - extreme volatility in macro markets",
    duration_seconds=300,
    market_conditions={
        "price_volatility_annualized": 1.20,
        "spread_cents": 25,
        "market_halts_probable": True,
        "latency_ms": 800,
    },
    expected_behavior={
        "orders_rejected_during_halt": True,
        "regime_detection_high_vol": True,
        "correlation_spike": True,
    },
)

SCENARIO_API_DEGRADATION = StressScenario(
    name="Kalshi_API_Degradation",
    description="Simulated Kalshi API slowdown and intermittent failures",
    duration_seconds=180,
    market_conditions={
        "api_latency_p99_ms": 2500,
        "api_error_rate": 0.15,
        "circuit_breaker_should_open": True,
    },
    expected_behavior={
        "circuit_breaker_opens": True,
        "fallback_to_paper": False,  # Live orders blocked
        "alerts_fired": True,
    },
)

SCENARIO_CORRELATION_BREAKDOWN = StressScenario(
    name="Crypto_Correlation_Breakdown",
    description="All crypto assets suddenly move together (contagion)",
    duration_seconds=600,
    market_conditions={
        "correlation_matrix": {
            "BTC-ETH": 0.95,
            "BTC-SOL": 0.93,
            "ETH-SOL": 0.94,
            "BTC-XRP": 0.88,
        },
        "exposure_reduction_triggered": True,
    },
    expected_behavior={
        "correlation_alerts_fired": True,
        "position_limits_reduced": True,
        "risk_events_emitted": True,
    },
)

SCENARIO_KILL_SWITCH_DRAWDOWN = StressScenario(
    name="Daily_Drawdown_Kill_Switch",
    description="Simulated daily loss approaching limit triggering kill switch",
    duration_seconds=60,
    market_conditions={
        "daily_pnl_usd": -450,  # Near $500 limit
        "drawdown_pct": 0.08,
        "consecutive_losses": 8,
    },
    expected_behavior={
        "kill_switch_activates": True,
        "all_live_orders_blocked": True,
        "telegram_alert_sent": True,
    },
)


class TestKalshiStressScenarios:
    """End-to-end stress tests using historical scenarios."""
    
    @pytest.mark.asyncio
    async def test_flash_crash_circuit_breaker(self):
        """Test circuit breaker trips during flash crash conditions."""
        from merid.circuit_breaker import get_circuit_breaker, CircuitState
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        
        scenario = SCENARIO_BTC_FLASH_CRASH
        breaker = get_circuit_breaker("kalshi_api_stress_test")
        
        # Simulate rapid failures (API timeouts during vol)
        for i in range(10):
            try:
                # Fast-fail to simulate API degradation
                raise TimeoutError("Kalshi API timeout")
            except TimeoutError:
                breaker._on_failure()
        
        # Verify circuit breaker opened
        assert breaker.state == CircuitState.OPEN
        
        # Verify subsequent orders are rejected
        intent = OrderIntent(
            ticker="KXBTCD-25JUN-T100000",
            side="yes",
            action="buy",
            price_cents=50,
            count=10,
            mode="live",
        )
        
        result = await route_order_async(intent)
        assert result.status == "rejected"
        assert "circuit" in result.reason.lower() or result.error_code == "circuit_breaker"
    
    @pytest.mark.asyncio  
    async def test_fomc_announcement_volatility_regime(self):
        """Test regime detection during FOMC announcement."""
        from merid.event_venues.kalshi.regime_detection import (
            get_regime_detector, MarketRegime, RegimeChangeEvent
        )
        
        scenario = SCENARIO_FOMC_ANNOUNCEMENT
        detector = get_regime_detector()
        
        events: List[RegimeChangeEvent] = []
        detector.register_listener(events.append)

        # Prime the detector with a low-vol regime first so the next call is a transition
        detector.update_regime(
            asset="BTC_FOMC_TEST",
            regime=MarketRegime.LOW_VOLATILITY,
            confidence=0.90,
            features={},
        )

        # Simulate regime transition to high volatility
        detector.update_regime(
            asset="BTC_FOMC_TEST",
            regime=MarketRegime.HIGH_VOLATILITY,
            confidence=0.85,
            features={
                "volatility_regime": 1.2,
                "vix_proxy": 45,
                "spread_widening": 2.5,
            }
        )

        # Verify event was emitted
        assert len(events) == 1
        assert events[0].new_regime == MarketRegime.HIGH_VOLATILITY
        detector.unregister_listener(events.append)
        assert events[0].confidence > 0.70
    
    @pytest.mark.asyncio
    async def test_api_degradation_latency_alerts(self):
        """Test latency monitoring fires alerts during API degradation."""
        from merid.event_venues.kalshi.kalshi_risk import LatencyMonitor
        
        scenario = SCENARIO_API_DEGRADATION
        monitor = LatencyMonitor(
            "kalshi_api_stress",
            window_size=100,
            warning_p99=500,
            critical_p99=1000,
        )
        
        # Simulate degraded latencies
        for i in range(50):
            monitor.record(1500.0)  # 1.5s latency - above critical
        
        # Check alert fired
        alert = monitor.check_alert()
        assert alert is not None
        assert alert["severity"] == "critical"
        assert alert["metric"] == "p99"
    
    @pytest.mark.asyncio
    async def test_correlation_breakdown_exposure_reduction(self):
        """Test correlation risk triggers exposure reduction."""
        from merid.risk.correlation import get_correlation_tracker
        from merid.event_venues.kalshi.category_exposure import get_category_exposure_tracker
        
        scenario = SCENARIO_CORRELATION_BREAKDOWN
        tracker = get_correlation_tracker()
        
        # Record returns that create high correlation
        for i in range(50):
            # Both assets move together (correlated)
            tracker.record_return("BTC", 0.02 + (i * 0.001))
            tracker.record_return("ETH", 0.018 + (i * 0.001))
        
        corr = tracker.get_correlation("BTC", "ETH")
        assert corr > 0.85  # High correlation
        
        # Verify exposure reduction factor is low (restrictive)
        reduction = tracker.exposure_reduction_factor("BTC", "ETH")
        assert reduction < 0.5  # Reduced to <50% of normal cap
    
    @pytest.mark.asyncio
    async def test_kill_switch_drawdown_activation(self):
        """Test kill switch activates during simulated drawdown."""
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        from merid.risk.kill_switches import risk_controller
        
        scenario = SCENARIO_KILL_SWITCH_DRAWDOWN
        risk = get_kalshi_risk()
        
        # Simulate losses approaching limit
        risk.record_pnl(-200, 50, is_realized=True)  # First loss
        risk.record_pnl(-150, 45, is_realized=True)  # Second loss  
        risk.record_pnl(-100, 40, is_realized=True)  # Third loss
        
        summary = risk.summary()
        assert summary["daily_pnl_usd"] < -400  # Near limit
        
        # One more loss should trigger kill switch
        risk.record_pnl(-150, 35, is_realized=True)
        
        # Verify kill switch activated or warning logged
        assert summary["kill_switch_active"] or risk._state.kill_switch_active
    
    @pytest.mark.asyncio
    async def test_order_rejection_rate_metrics(self):
        """Test order rejection rate metrics are recorded correctly."""
        from monitoring.kalshi_metrics import get_kalshi_metrics_collector
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        
        collector = get_kalshi_metrics_collector()
        
        # Record multiple rejected orders with different error codes
        error_codes = ["invalid_price", "category_cap_exceeded", "risk_check"]
        
        for code in error_codes:
            collector.record_order(
                mode="live",
                status="rejected",
                count=10,
                latency_ms=50.0,
                error_code=code,
            )
        
        # Verify metrics collected
        metrics = collector.collect()
        rejected_metrics = [m for m in metrics if "rejected" in m.name]
        assert len(rejected_metrics) > 0
    
    @pytest.mark.asyncio
    async def test_full_stress_scenario_compound(self):
        """Test compound stress: high vol + API degradation + correlation spike."""
        from merid.circuit_breaker import get_circuit_breaker, CircuitState
        from merid.event_venues.kalshi.kalshi_risk import LatencyMonitor, get_kalshi_risk
        from merid.risk.correlation import get_correlation_tracker
        
        # Initialize all monitors
        cb = get_circuit_breaker("compound_stress_test")
        latency = LatencyMonitor("compound", warning_p99=300, critical_p99=800)
        corr = get_correlation_tracker()
        
        # Phase 1: High volatility regime
        for i in range(30):
            latency.record(600.0)  # Elevated latency
            corr.record_return("BTC", (i % 5 - 2) * 0.05)  # Volatile
            corr.record_return("ETH", (i % 5 - 2) * 0.045)  # Correlated volatile
        
        # Phase 2: API degradation
        for i in range(10):
            latency.record(2500.0)  # Critical latency
            cb._on_failure()  # Force failures
        
        # Verify all systems responded
        assert latency.check_alert() is not None
        assert cb.state == CircuitState.OPEN
        assert corr.get_correlation("BTC", "ETH") > 0.5


# ── Performance Benchmarks ────────────────────────────────────────────────

class TestKalshiPerformanceBenchmarks:
    """Performance benchmarks for critical paths."""
    
    @pytest.mark.asyncio
    async def test_order_routing_latency_benchmark(self):
        """Benchmark order routing latency under load."""
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order
        
        latencies: List[float] = []
        
        for i in range(100):
            intent = OrderIntent(
                ticker=f"KXBTCD-25JUN-T{i}",
                side="yes",
                action="buy", 
                price_cents=55,
                count=5,
                mode="paper",
            )
            
            result = route_order(intent)
            latencies.append(result.latency_ms)
        
        # Calculate percentiles
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p99 = latencies[int(len(latencies) * 0.99)]
        
        # Assert SLO compliance (p99 < 100ms for paper orders)
        assert p99 < 100.0, f"p99 latency {p99}ms exceeds 100ms SLO"
        print(f"Order routing latency - p50: {p50:.2f}ms, p99: {p99:.2f}ms")
    
    @pytest.mark.asyncio
    async def test_batch_order_throughput(self):
        """Test batch order placement throughput."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, BatchOrderIntent, route_batch_orders_async
        )
        
        orders = [
            OrderIntent(
                ticker=f"KXETH-25JUN-T{i}",
                side="yes",
                action="buy",
                price_cents=50 + (i % 10),
                count=5,
            )
            for i in range(50)
        ]
        
        batch = BatchOrderIntent(orders=orders)
        
        t0 = asyncio.get_running_loop().time()
        result = await route_batch_orders_async(batch, max_concurrent=10)
        elapsed_ms = (asyncio.get_running_loop().time() - t0) * 1000
        
        # Calculate throughput (min 1ms to avoid ZeroDivisionError on fast machines)
        throughput = result.total / max(elapsed_ms / 1000, 0.001)  # orders/sec
        
        # Assert reasonable throughput (>10 orders/sec)
        assert throughput > 10.0, f"Batch throughput {throughput:.1f} orders/sec too low"
        print(f"Batch throughput: {throughput:.1f} orders/sec ({elapsed_ms:.1f}ms for {result.total} orders)")
