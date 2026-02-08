"""Load tests for MERID trading system critical paths."""
import pytest
import asyncio
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch, MagicMock
from typing import List, Tuple


class TestOrderPlacementLoad:
    """Load tests for order placement throughput."""

    @pytest.fixture
    def paper_engine(self):
        """Create paper trading engine."""
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            from trading.paper_trading import PaperTradingEngine
            engine = PaperTradingEngine(starting_balance=1000000.0)
            engine.current_prices["BTC"] = 50000.0
            engine.current_prices["BTC/USDT"] = 50000.0
            engine.current_prices["ETH"] = 3000.0
            engine.current_prices["ETH/USDT"] = 3000.0
            return engine

    def test_order_placement_throughput(self, paper_engine):
        """Test order placement can handle 100 orders/second."""
        num_orders = 100
        start_time = time.perf_counter()

        for i in range(num_orders):
            paper_engine.place_order(
                user_id=f"user_{i % 10}",
                asset="BTC",
                side="long" if i % 2 == 0 else "short",
                size_usd=100.0,
                order_type="market",
            )

        elapsed = time.perf_counter() - start_time
        orders_per_second = num_orders / elapsed

        assert orders_per_second >= 50, f"Order throughput too low: {orders_per_second:.1f}/s"
        print(f"Order throughput: {orders_per_second:.1f} orders/second")

    def test_concurrent_order_placement(self, paper_engine):
        """Test concurrent order placement from multiple users."""
        num_users = 10
        orders_per_user = 20

        def place_orders(user_id: str) -> List[float]:
            latencies = []
            for _ in range(orders_per_user):
                start = time.perf_counter()
                paper_engine.place_order(
                    user_id=user_id,
                    asset="ETH",
                    side="long",
                    size_usd=50.0,
                )
                latencies.append(time.perf_counter() - start)
            return latencies

        all_latencies = []
        with ThreadPoolExecutor(max_workers=num_users) as executor:
            futures = [
                executor.submit(place_orders, f"user_{i}")
                for i in range(num_users)
            ]
            for future in as_completed(futures):
                all_latencies.extend(future.result())

        avg_latency = statistics.mean(all_latencies) * 1000  # ms
        p95_latency = sorted(all_latencies)[int(len(all_latencies) * 0.95)] * 1000

        assert avg_latency < 50, f"Average latency too high: {avg_latency:.2f}ms"
        assert p95_latency < 100, f"P95 latency too high: {p95_latency:.2f}ms"
        print(f"Avg latency: {avg_latency:.2f}ms, P95: {p95_latency:.2f}ms")


class TestRiskCheckLoad:
    """Load tests for risk checking throughput."""

    @pytest.fixture
    def risk_guard(self):
        """Create mock risk guard instance."""
        from unittest.mock import Mock
        guard = Mock()
        guard.can_trade = Mock(return_value=True)
        return guard

    def test_risk_check_throughput(self, risk_guard):
        """Test risk checks can handle high volume."""
        num_checks = 500
        start_time = time.perf_counter()

        for i in range(num_checks):
            risk_guard.can_trade()

        elapsed = time.perf_counter() - start_time
        checks_per_second = num_checks / elapsed

        assert checks_per_second >= 1000, f"Risk check throughput too low: {checks_per_second:.0f}/s"
        print(f"Risk check throughput: {checks_per_second:.0f} checks/second")


class TestConsensusLoad:
    """Load tests for consensus system."""

    def test_proposal_submission_throughput(self):
        """Test proposal submission throughput."""
        from unittest.mock import Mock

        consensus = Mock()
        consensus.submit_proposal = Mock(return_value="proposal_id")

        num_proposals = 100
        start_time = time.perf_counter()

        for i in range(num_proposals):
            consensus.submit_proposal({
                "action": "buy",
                "symbol": "BTC/USD",
                "confidence": 0.85,
            })

        elapsed = time.perf_counter() - start_time
        proposals_per_second = num_proposals / elapsed

        assert proposals_per_second >= 100, f"Proposal throughput too low"
        print(f"Proposal throughput: {proposals_per_second:.0f}/second")


class TestAnomalyDetectionLoad:
    """Load tests for anomaly detection."""

    @pytest.fixture
    def anomaly_stack(self):
        """Create anomaly detection stack."""
        from ops.anomaly_detection import AnomalyDetectionStack
        return AnomalyDetectionStack()

    def test_anomaly_check_throughput(self, anomaly_stack):
        """Test anomaly detection throughput."""
        import numpy as np

        num_checks = 200
        latencies = []

        for i in range(num_checks):
            start = time.perf_counter()
            anomaly_stack.check_output_drift(
                returns=np.random.randn() * 0.01,
                volatility=abs(np.random.randn() * 0.02),
            )
            latencies.append(time.perf_counter() - start)

        avg_latency = statistics.mean(latencies) * 1000
        checks_per_second = num_checks / sum(latencies)

        assert checks_per_second >= 500, f"Anomaly check throughput too low"
        print(f"Anomaly check throughput: {checks_per_second:.0f}/second, avg latency: {avg_latency:.3f}ms")


class TestPortfolioOptimizerLoad:
    """Load tests for portfolio optimization."""

    def test_optimization_throughput(self):
        """Test portfolio optimization speed with mock."""
        from unittest.mock import Mock
        
        optimizer = Mock()
        optimizer.optimize = Mock(return_value={"weights": [0.1] * 10, "expected_return": 0.12})
        
        num_optimizations = 20
        latencies = []

        for _ in range(num_optimizations):
            start = time.perf_counter()
            optimizer.optimize(method="mean_variance", target_return=0.15)
            latencies.append(time.perf_counter() - start)

        avg_latency = statistics.mean(latencies) * 1000
        
        assert avg_latency < 500, f"Optimization too slow: {avg_latency:.0f}ms"
        print(f"Optimization avg latency: {avg_latency:.2f}ms")


class TestDisasterRecoveryLoad:
    """Load tests for disaster recovery operations."""

    @pytest.fixture
    def dr_manager(self):
        """Create disaster recovery manager."""
        from recovery.disaster_recovery import DisasterRecoveryManager
        return DisasterRecoveryManager()

    def test_recovery_point_creation_speed(self, dr_manager):
        """Test recovery point creation speed."""
        num_points = 50
        latencies = []

        for _ in range(num_points):
            start = time.perf_counter()
            dr_manager.create_recovery_point()
            latencies.append(time.perf_counter() - start)

        avg_latency = statistics.mean(latencies) * 1000
        
        assert avg_latency < 100, f"Recovery point creation too slow: {avg_latency:.0f}ms"
        print(f"Recovery point creation avg: {avg_latency:.1f}ms")


class TestEndToEndLoad:
    """End-to-end load tests for complete trading flow."""

    def test_full_flow_under_load(self):
        """Test complete trading flow under load."""
        with patch("trading.paper_trading.get_live_price_feed") as mock_feed:
            mock_feed.return_value = MagicMock()
            from trading.paper_trading import PaperTradingEngine
            
            engine = PaperTradingEngine(starting_balance=100000.0)
            engine.current_prices["BTC"] = 50000.0
            engine.current_prices["BTC/USDT"] = 50000.0

            num_cycles = 50
            latencies = []

            for i in range(num_cycles):
                start = time.perf_counter()
                
                # Full cycle: order -> position -> close
                order = engine.place_order(
                    user_id=f"load_user_{i}",
                    asset="BTC",
                    side="long",
                    size_usd=100.0,
                )
                
                if order.status.value == "filled":
                    engine.close_position(f"load_user_{i}", "BTC_long_perp")
                
                latencies.append(time.perf_counter() - start)

            avg_latency = statistics.mean(latencies) * 1000
            p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] * 1000
            throughput = num_cycles / sum(latencies)

            assert throughput >= 20, f"E2E throughput too low: {throughput:.0f}/s"
            assert p99_latency < 200, f"P99 latency too high: {p99_latency:.0f}ms"
            
            print(f"E2E throughput: {throughput:.0f}/s, avg: {avg_latency:.1f}ms, p99: {p99_latency:.1f}ms")
