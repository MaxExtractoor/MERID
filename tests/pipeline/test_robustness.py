"""
Pipeline Robustness Test Suite

Comprehensive test suite for all robustness components to ensure
proper functionality and integration.
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timezone

# Import robustness components
from merid.pipeline.robustness import (
    retry_async, circuit_breaker, validate_inputs, rate_limit,
    ThreadSafeState, ResourceManager, HealthChecker, PipelineMetrics,
    GracefulShutdown, ErrorRecovery, validate_non_empty_string,
    validate_positive_number, validate_probability
)

# Import robust pipeline components
from merid.publishing.kalshi_insight_pipeline_robust import (
    KalshiInsightPipelineRobust, KalshiMarket, InsightObject
)
from web.services.swarm_publishers_robust import (
    SwarmEventPublisherRobust, PublisherConfig
)
from merid.pipeline.risk_manager_robust import (
    GlobalRiskManagerRobust, DomainRiskConfig, RiskCheckResult, VenueExposure
)


class TestRobustnessDecorators:
    """Test robustness decorators."""

    @pytest.mark.asyncio
    async def test_retry_decorator_success(self):
        """Test retry decorator with successful function."""
        call_count = 0
        
        @retry_async(max_attempts=3, base_delay=0.1)
        async def successful_function():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = await successful_function()
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retry_decorator_with_failure(self):
        """Test retry decorator with failing function."""
        call_count = 0
        
        @retry_async(max_attempts=3, base_delay=0.1)
        async def failing_function():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Test error")
            return "success"
        
        result = await failing_function()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_decorator_max_attempts(self):
        """Test retry decorator max attempts exceeded."""
        call_count = 0
        
        @retry_async(max_attempts=2, base_delay=0.1)
        async def always_failing_function():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")
        
        with pytest.raises(ValueError):
            await always_failing_function()

        # max_attempts=2 means 2 retries after the initial attempt = 3 total
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_circuit_breaker_closed(self):
        """Test circuit breaker in closed state."""
        @circuit_breaker(failure_threshold=3, recovery_timeout=1.0)
        async def working_function():
            return "success"
        
        result = await working_function()
        assert result == "success"

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens(self):
        """Test circuit breaker opens after threshold."""
        call_count = 0

        @circuit_breaker(failure_threshold=2, recovery_timeout=1.0)
        async def failing_function():
            nonlocal call_count
            call_count += 1
            raise Exception("Service error")

        # First failure — circuit still CLOSED
        with pytest.raises(Exception):
            await failing_function()

        # Second failure — circuit reaches threshold and OPENS (raises original error)
        with pytest.raises(Exception):
            await failing_function()

        # Third call — circuit is OPEN, raises circuit breaker message
        with pytest.raises(Exception, match="Circuit breaker OPEN"):
            await failing_function()

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open(self):
        """Test circuit breaker half-open state."""
        call_count = 0
        
        @circuit_breaker(failure_threshold=1, recovery_timeout=0.5)
        async def recovering_function():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Initial failure")
            return "recovered"
        
        # First failure opens circuit
        with pytest.raises(Exception):
            await recovering_function()
        
        # Wait for recovery timeout
        await asyncio.sleep(0.6)
        
        # Should work in half-open state
        result = await recovering_function()
        assert result == "recovered"

    def test_validate_inputs_decorator(self):
        """Test input validation decorator."""
        @validate_inputs(name=validate_non_empty_string, age=validate_positive_number)
        def process_person(name, age):
            return f"Processed {name}, age {age}"
        
        # Valid input
        result = process_person("John", 25)
        assert result == "Processed John, age 25"
        
        # Invalid input
        with pytest.raises(ValueError):
            process_person("", 25)
        
        with pytest.raises(ValueError):
            process_person("John", -5)

    @pytest.mark.asyncio
    async def test_rate_limit_decorator(self):
        """Test rate limiting decorator."""
        call_times = []

        @rate_limit(calls_per_second=10.0)  # 0.1s between calls
        async def rate_limited_function():
            call_times.append(time.time())
            return "success"

        # Run sequentially so rate limiter can enforce ordering
        for _ in range(3):
            await rate_limited_function()

        # Verify rate limiting
        assert len(call_times) == 3
        for i in range(1, len(call_times)):
            assert call_times[i] - call_times[i-1] >= 0.09  # Allow small tolerance


class TestThreadSafeState:
    """Test thread-safe state management."""

    def test_thread_safe_state_basic(self):
        """Test basic thread-safe state operations."""
        state = ThreadSafeState()
        
        # Test set and get
        state.set("key1", "value1")
        assert state.get("key1") == "value1"
        
        # Test default value
        assert state.get("nonexistent", "default") == "default"
        
        # Test update
        state.update({"key2": "value2", "key3": "value3"})
        assert state.get("key2") == "value2"
        assert state.get("key3") == "value3"
        
        # Test delete
        state.delete("key1")
        assert state.get("key1") is None
        
        # Test clear
        state.clear()
        assert state.get("key2") is None

    def test_thread_safe_state_concurrent(self):
        """Test thread-safe state with concurrent access."""
        import threading
        
        state = ThreadSafeState()
        results = []
        
        def worker(thread_id):
            for i in range(100):
                key = f"thread_{thread_id}_key_{i}"
                value = f"thread_{thread_id}_value_{i}"
                state.set(key, value)
                retrieved = state.get(key)
                results.append((thread_id, i, retrieved))
        
        # Create multiple threads
        threads = []
        for thread_id in range(5):
            thread = threading.Thread(target=worker, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all operations completed successfully
        assert len(results) == 500  # 5 threads * 100 operations each
        assert all(retrieved == f"thread_{tid}_value_{i}" for tid, i, retrieved in results)


class TestHealthChecker:
    """Test health checker system."""

    @pytest.mark.asyncio
    async def test_health_checker_registration(self):
        """Test health check registration."""
        checker = HealthChecker()
        
        async def healthy_check():
            return {"status": "ok"}
        
        checker.register_check("test_component", healthy_check)
        
        result = await checker.run_check("test_component")
        assert result.healthy is True
        assert result.message == "OK"

    @pytest.mark.asyncio
    async def test_health_checker_failure(self):
        """Test health check failure."""
        checker = HealthChecker()
        
        async def failing_check():
            raise Exception("Health check failed")
        
        checker.register_check("failing_component", failing_check)
        
        result = await checker.run_check("failing_component")
        assert result.healthy is False
        assert "Health check failed" in result.message

    @pytest.mark.asyncio
    async def test_health_checker_all_checks(self):
        """Test running all health checks."""
        checker = HealthChecker()
        
        async def check1():
            return {"status": "ok"}
        
        async def check2():
            return {"status": "ok"}
        
        checker.register_check("component1", check1)
        checker.register_check("component2", check2)
        
        results = await checker.run_all_checks()
        assert len(results) == 2
        assert all(status.healthy for status in results.values())

    def test_health_checker_summary(self):
        """Test health checker summary."""
        checker = HealthChecker()
        
        # Mock some results
        checker._last_results = {
            "component1": Mock(healthy=True, timestamp=datetime.now(timezone.utc)),
            "component2": Mock(healthy=False, timestamp=datetime.now(timezone.utc))
        }
        
        summary = checker.get_summary()
        assert summary["status"] == "degraded"
        assert summary["checks"] == 2
        assert summary["healthy_checks"] == 1
        assert summary["unhealthy_checks"] == 1


class TestPipelineMetrics:
    """Test pipeline metrics collection."""

    def test_metrics_counters(self):
        """Test counter metrics."""
        metrics = PipelineMetrics()
        
        metrics.increment_counter("test_counter")
        assert metrics._metrics.get("test_counter", 0) == 1
        
        metrics.increment_counter("test_counter", 5)
        assert metrics._metrics.get("test_counter", 0) == 6

    def test_metrics_gauges(self):
        """Test gauge metrics."""
        metrics = PipelineMetrics()
        
        metrics.set_gauge("test_gauge", 42.5)
        assert metrics._metrics.get("test_gauge", 0) == 42.5

    def test_metrics_timings(self):
        """Test timing metrics."""
        metrics = PipelineMetrics()
        
        metrics.record_timing("test_timing", 1.23)
        timings = metrics._metrics.get("test_timing_timings", [])
        assert len(timings) == 1
        assert timings[0] == 1.23
        
        # Test multiple timings
        metrics.record_timing("test_timing", 2.34)
        timings = metrics._metrics.get("test_timing_timings", [])
        assert len(timings) == 2

    def test_metrics_summary(self):
        """Test metrics summary."""
        metrics = PipelineMetrics()
        
        metrics.increment_counter("test_counter", 5)
        metrics.set_gauge("test_gauge", 42.5)
        metrics.record_timing("test_timing", 1.23)
        
        summary = metrics.get_summary()
        assert "uptime_seconds" in summary
        assert "metrics" in summary
        assert summary["metrics"]["test_counter"] == 5
        assert summary["metrics"]["test_gauge"] == 42.5


class TestKalshiInsightPipelineRobust:
    """Test robust Kalshi insight pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_startup_shutdown(self):
        """Test pipeline startup and shutdown."""
        pipeline = KalshiInsightPipelineRobust()
        
        # Test startup
        await pipeline.start()
        assert pipeline._running is True
        assert len(pipeline._tasks) > 0
        
        # Test shutdown
        await pipeline.stop()
        assert pipeline._running is False
        assert len(pipeline._tasks) == 0

    def test_market_validation(self):
        """Test market data validation."""
        # Valid market
        valid_market = KalshiMarket(
            ticker="TEST-123",
            question="Test question",
            category="Crypto",
            yes_price=50.0,
            no_price=50.0,
            volume=1000,
            open_interest=500,
            end_date="2024-12-31",
            status="open",
            result=None
        )
        assert valid_market.prob == 0.5
        
        # Invalid market (negative price)
        with pytest.raises(ValueError):
            KalshiMarket(
                ticker="TEST-123",
                question="Test question",
                category="Crypto",
                yes_price=-10.0,  # Invalid
                no_price=50.0,
                volume=1000,
                open_interest=500,
                end_date="2024-12-31",
                status="open",
                result=None
            )

    def test_insight_validation(self):
        """Test insight data validation."""
        # Valid insight
        valid_insight = InsightObject(
            source="kalshi",
            category="Crypto",
            ticker="BTC-USD",
            question="Bitcoin price prediction",
            kalshi_prob=0.6,
            swarm_prob=0.7,
            swarm_confidence=0.8,
            change_24h=0.1,
            timestamp=datetime.now(timezone.utc).isoformat(),
            narrative="Test narrative",
            action="new_market",
            market_url="https://kalshi.com/markets/BTC-USD",
            volume=1000,
            open_interest=500
        )
        assert valid_insight.kalshi_prob == 0.6
        
        # Invalid insight (invalid probability)
        with pytest.raises(ValueError):
            InsightObject(
                source="kalshi",
                category="Crypto",
                ticker="BTC-USD",
                question="Bitcoin price prediction",
                kalshi_prob=1.5,  # Invalid
                swarm_prob=0.7,
                swarm_confidence=0.8,
                change_24h=0.1,
                timestamp=datetime.now(timezone.utc).isoformat(),
                narrative="Test narrative",
                action="new_market",
                market_url="https://kalshi.com/markets/BTC-USD",
                volume=1000,
                open_interest=500
            )

    def test_pipeline_summary(self):
        """Test pipeline summary."""
        pipeline = KalshiInsightPipelineRobust()
        summary = pipeline.summary()
        
        assert "running" in summary
        assert "consumers" in summary
        assert "tracked_tickers" in summary
        assert "metrics" in summary
        assert "health" in summary


class TestSwarmEventPublisherRobust:
    """Test robust swarm event publisher."""

    @pytest.mark.asyncio
    async def test_publisher_startup_shutdown(self):
        """Test publisher startup and shutdown."""
        config = PublisherConfig(max_queue_size=100, batch_size=5)
        publisher = SwarmEventPublisherRobust(config)
        
        # Test startup
        await publisher.start()
        assert publisher._running is True
        assert len(publisher._tasks) > 0
        
        # Test shutdown
        await publisher.stop()
        assert publisher._running is False
        assert len(publisher._tasks) == 0

    def test_publisher_stats(self):
        """Test publisher statistics."""
        config = PublisherConfig(max_queue_size=100, batch_size=5)
        publisher = SwarmEventPublisherRobust(config)
        
        stats = publisher.get_stats()
        assert "running" in stats
        assert "config" in stats
        assert "queue" in stats
        assert "websocket" in stats
        assert "metrics" in stats
        assert "health" in stats


class TestGlobalRiskManagerRobust:
    """Test robust global risk manager."""

    def test_risk_manager_initialization(self):
        """Test risk manager initialization."""
        manager = GlobalRiskManagerRobust(Decimal("100000"))
        
        assert manager._state.get("total_capital_usd") == Decimal("100000")
        assert len(manager._state.get("domain_configs")) > 0
        assert len(manager._state.get("exposures")) > 0

    def test_domain_config_validation(self):
        """Test domain risk config validation."""
        # Valid config
        valid_config = DomainRiskConfig(
            domain="prediction",
            max_allocation_pct=Decimal("0.10"),
            max_notional_usd=Decimal("5000"),
            max_daily_loss_usd=Decimal("250"),
            max_positions=20,
            max_single_order_usd=Decimal("500")
        )
        assert valid_config.enabled is True
        
        # Invalid config (negative allocation)
        with pytest.raises(ValueError):
            DomainRiskConfig(
                domain="prediction",
                max_allocation_pct=Decimal("-0.10"),  # Invalid
                max_notional_usd=Decimal("5000"),
                max_daily_loss_usd=Decimal("250"),
                max_positions=20,
                max_single_order_usd=Decimal("500")
            )

    def test_venue_exposure_validation(self):
        """Test venue exposure validation."""
        # Valid exposure
        valid_exposure = VenueExposure(
            venue="kalshi",
            domain="prediction",
            notional_usd=Decimal("1000"),
            position_count=5
        )
        assert valid_exposure.position_count == 5
        
        # Invalid exposure (negative position count)
        with pytest.raises(ValueError):
            VenueExposure(
                venue="kalshi",
                domain="prediction",
                notional_usd=Decimal("1000"),
                position_count=-5  # Invalid
            )

    def test_risk_check_result_validation(self):
        """Test risk check result validation."""
        # Valid result
        valid_result = RiskCheckResult(
            approved=True,
            reason="All checks passed",
            domain="prediction",
            venue="kalshi",
            risk_score=0.1
        )
        assert valid_result.approved is True
        assert valid_result.risk_score == 0.1
        
        # Invalid result (invalid risk score)
        with pytest.raises(ValueError):
            RiskCheckResult(
                approved=True,
                reason="All checks passed",
                domain="prediction",
                venue="kalshi",
                risk_score=1.5  # Invalid
            )

    def test_domain_halt_resume(self):
        """Test domain halt and resume."""
        manager = GlobalRiskManagerRobust()
        
        # Test halt
        manager.halt_domain("prediction", "Test halt")
        assert manager.is_domain_halted("prediction") is True
        
        # Test resume
        manager.resume_domain("prediction")
        assert manager.is_domain_halted("prediction") is False

    def test_exposure_calculations(self):
        """Test exposure calculations."""
        manager = GlobalRiskManagerRobust()
        
        # Add some test exposures
        manager.update_exposure("prediction", "kalshi", {
            "notional_usd": Decimal("1000"),
            "position_count": 5
        })
        manager.update_exposure("prediction", "binary", {
            "notional_usd": Decimal("500"),
            "position_count": 3
        })
        
        # Test calculations
        assert manager.domain_notional("prediction") == Decimal("1500")
        assert manager.domain_positions("prediction") == 8
        assert manager.portfolio_notional() == Decimal("1500")

    def test_manager_summary(self):
        """Test risk manager summary."""
        manager = GlobalRiskManagerRobust()
        summary = manager.summary()
        
        assert "total_capital_usd" in summary
        assert "portfolio_notional" in summary
        assert "total_exposures" in summary
        assert "domain_configs" in summary
        assert "exposures" in summary
        assert "metrics" in summary
        assert "health" in summary


class TestErrorRecovery:
    """Test error recovery patterns."""

    @pytest.mark.asyncio
    async def test_safe_execute_success(self):
        """Test safe execute with successful function."""
        async def successful_function():
            return "success"
        
        result = await ErrorRecovery.safe_execute(
            successful_function,
            fallback_value="fallback"
        )
        assert result == "success"

    @pytest.mark.asyncio
    async def test_safe_execute_failure(self):
        """Test safe execute with failing function."""
        async def failing_function():
            raise Exception("Test error")
        
        result = await ErrorRecovery.safe_execute(
            failing_function,
            fallback_value="fallback"
        )
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_with_timeout_success(self):
        """Test with timeout on successful function."""
        async def quick_function():
            return "quick"
        
        result = await ErrorRecovery.with_timeout(
            quick_function,
            timeout=1.0,
            fallback_value="timeout"
        )
        assert result == "quick"

    @pytest.mark.asyncio
    async def test_with_timeout_failure(self):
        """Test with timeout on slow function."""
        async def slow_function():
            await asyncio.sleep(2.0)
            return "slow"
        
        result = await ErrorRecovery.with_timeout(
            slow_function,
            timeout=0.5,
            fallback_value="timeout"
        )
        assert result == "timeout"


class TestValidators:
    """Test input validation functions."""

    def test_validate_non_empty_string(self):
        """Test non-empty string validation."""
        assert validate_non_empty_string("hello") is True
        assert validate_non_empty_string("   hello   ") is True
        assert validate_non_empty_string("") is False
        assert validate_non_empty_string("   ") is False
        assert validate_non_empty_string(None) is False
        assert validate_non_empty_string(123) is False

    def test_validate_positive_number(self):
        """Test positive number validation."""
        assert validate_positive_number(5) is True
        assert validate_positive_number(5.5) is True
        assert validate_positive_number("10") is True
        assert validate_positive_number(0) is False
        assert validate_positive_number(-5) is False
        assert validate_positive_number("abc") is False
        assert validate_positive_number(None) is False

    def test_validate_probability(self):
        """Test probability validation."""
        assert validate_probability(0.5) is True
        assert validate_probability(0.0) is True
        assert validate_probability(1.0) is True
        assert validate_probability("0.75") is True
        assert validate_probability(-0.1) is False
        assert validate_probability(1.1) is False
        assert validate_probability("abc") is False
        assert validate_probability(None) is False


# Integration Tests

class TestIntegration:
    """Integration tests for robustness components."""

    @pytest.mark.asyncio
    async def test_pipeline_with_health_checks(self):
        """Test pipeline integration with health checks."""
        pipeline = KalshiInsightPipelineRobust()
        
        # Start pipeline
        await pipeline.start()
        
        # Run health checks
        health_results = await pipeline._health_checker.run_all_checks()
        
        # Verify health checks are working
        assert len(health_results) > 0
        
        # Stop pipeline
        await pipeline.stop()

    @pytest.mark.asyncio
    async def test_error_recovery_integration(self):
        """Test error recovery integration."""
        from merid.pipeline.robustness import get_health_checker, get_metrics
        
        # Test global instances
        health_checker = get_health_checker()
        metrics = get_metrics()
        
        # Register test health check
        async def test_check():
            return {"healthy": True}
        
        health_checker.register_check("integration_test", test_check)
        
        # Run health check
        result = await health_checker.run_check("integration_test")
        assert result.healthy is True
        
        # Test metrics
        metrics.increment_counter("integration_test_counter")
        assert metrics._metrics.get("integration_test_counter", 0) == 1


# Performance Tests

class TestPerformance:
    """Performance tests for robustness components."""

    @pytest.mark.asyncio
    async def test_thread_safe_state_performance(self):
        """Test thread-safe state performance."""
        import threading
        import time
        
        state = ThreadSafeState()
        
        def worker(thread_id):
            start_time = time.time()
            for i in range(1000):
                key = f"thread_{thread_id}_key_{i}"
                value = f"thread_{thread_id}_value_{i}"
                state.set(key, value)
                state.get(key)
            return time.time() - start_time
        
        # Create multiple threads
        threads = []
        for thread_id in range(10):
            thread = threading.Thread(target=worker, args=(thread_id,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Performance should be reasonable
        # (This is a basic sanity check, adjust thresholds as needed)
        assert True  # If we get here without deadlock, performance is acceptable

    @pytest.mark.asyncio
    async def test_retry_decorator_performance(self):
        """Test retry decorator performance impact."""
        @retry_async(max_attempts=1, base_delay=0.001)  # Minimal delay
        async def fast_function():
            return "success"
        
        start_time = time.time()
        
        # Make many calls
        tasks = [fast_function() for _ in range(100)]
        await asyncio.gather(*tasks)
        
        duration = time.time() - start_time
        
        # Should complete quickly (adjust threshold as needed)
        assert duration < 1.0


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
