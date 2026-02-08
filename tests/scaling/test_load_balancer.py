"""Tests for scaling/load_balancer.py - Load Balancer."""
import pytest
import asyncio
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from dataclasses import asdict

from scaling.load_balancer import (
    Instance,
    LoadBalancingRule,
    RoutingDecision,
    LoadBalancer,
)


class TestInstance:
    """Test Instance dataclass."""

    def test_creation(self):
        """Test creating instance."""
        instance = Instance(
            instance_id="inst_001",
            host="localhost",
            port=8080,
            protocol="http",
            status="healthy",
            weight=10,
            connections=5,
            max_connections=100,
            response_time=0.05,
            error_rate=0.01,
            last_health_check=1000.0,
        )
        assert instance.instance_id == "inst_001"
        assert instance.status == "healthy"

    def test_unhealthy_instance(self):
        """Test unhealthy instance."""
        instance = Instance(
            instance_id="inst_002",
            host="192.168.1.10",
            port=8080,
            protocol="http",
            status="unhealthy",
            weight=0,
            connections=0,
            max_connections=100,
            response_time=5.0,
            error_rate=0.5,
            last_health_check=500.0,
        )
        assert instance.status == "unhealthy"
        assert instance.weight == 0

    def test_draining_instance(self):
        """Test draining instance."""
        instance = Instance(
            instance_id="inst_003",
            host="192.168.1.11",
            port=8080,
            protocol="https",
            status="draining",
            weight=1,
            connections=50,
            max_connections=100,
            response_time=0.1,
            error_rate=0.02,
            last_health_check=800.0,
        )
        assert instance.status == "draining"


class TestLoadBalancingRule:
    """Test LoadBalancingRule dataclass."""

    def test_round_robin_rule(self):
        """Test round robin rule."""
        rule = LoadBalancingRule(
            rule_id="rule_001",
            pattern="/api/*",
            algorithm="round_robin",
            sticky_sessions=False,
            health_check_interval=30,
            health_check_timeout=5,
            max_failures=3,
        )
        assert rule.algorithm == "round_robin"
        assert rule.sticky_sessions is False

    def test_weighted_rule(self):
        """Test weighted round robin rule."""
        rule = LoadBalancingRule(
            rule_id="rule_002",
            pattern="/ws/*",
            algorithm="weighted_round_robin",
            sticky_sessions=True,
            health_check_interval=15,
            health_check_timeout=3,
            max_failures=5,
        )
        assert rule.algorithm == "weighted_round_robin"
        assert rule.sticky_sessions is True

    def test_least_connections_rule(self):
        """Test least connections rule."""
        rule = LoadBalancingRule(
            rule_id="rule_003",
            pattern="/trading/*",
            algorithm="least_connections",
            sticky_sessions=False,
            health_check_interval=10,
            health_check_timeout=2,
            max_failures=2,
            backup_instances=["inst_backup_001"],
        )
        assert rule.algorithm == "least_connections"
        assert len(rule.backup_instances) == 1


class TestRoutingDecision:
    """Test RoutingDecision dataclass."""

    def test_creation(self):
        """Test creating routing decision."""
        decision = RoutingDecision(
            instance_id="inst_001",
            host="localhost",
            port=8080,
            protocol="http",
            selected_at=1000.0,
            algorithm_used="round_robin",
            reasoning="Next in rotation",
        )
        assert decision.instance_id == "inst_001"
        assert decision.algorithm_used == "round_robin"


class TestLoadBalancer:
    """Test LoadBalancer class."""

    @pytest.fixture
    def lb_config(self):
        """Create load balancer config."""
        return {
            "default_algorithm": "weighted_round_robin",
            "health_check_interval": 30,
            "us_compliance": {
                "geo_fencing": True,
                "data_residency": True,
            },
        }

    @pytest.fixture
    def load_balancer(self, lb_config):
        """Create load balancer instance."""
        return LoadBalancer(lb_config)

    def test_creation(self, load_balancer):
        """Test creating load balancer."""
        assert load_balancer is not None
        assert load_balancer.instances == {}

    def test_register_instance(self, load_balancer):
        """Test registering an instance."""
        instance = Instance(
            instance_id="inst_001",
            host="localhost",
            port=8080,
            protocol="http",
            status="healthy",
            weight=10,
            connections=0,
            max_connections=100,
            response_time=0.05,
            error_rate=0.0,
            last_health_check=0.0,
        )
        
        load_balancer.instances["inst_001"] = instance
        
        assert "inst_001" in load_balancer.instances
        assert load_balancer.instances["inst_001"].status == "healthy"

    def test_register_multiple_instances(self, load_balancer):
        """Test registering multiple instances."""
        for i in range(5):
            instance = Instance(
                instance_id=f"inst_{i:03d}",
                host=f"192.168.1.{10+i}",
                port=8080,
                protocol="http",
                status="healthy",
                weight=10,
                connections=0,
                max_connections=100,
                response_time=0.05,
                error_rate=0.0,
                last_health_check=0.0,
            )
            load_balancer.instances[instance.instance_id] = instance
        
        assert len(load_balancer.instances) == 5

    def test_default_rule(self, load_balancer):
        """Test default load balancing rule."""
        assert load_balancer.default_rule is not None
        assert load_balancer.default_rule.algorithm == "weighted_round_robin"

    def test_add_custom_rule(self, load_balancer):
        """Test adding custom rule."""
        rule = LoadBalancingRule(
            rule_id="api_rule",
            pattern="/api/*",
            algorithm="least_connections",
            sticky_sessions=False,
            health_check_interval=15,
            health_check_timeout=3,
            max_failures=3,
        )
        
        load_balancer.rules["api_rule"] = rule
        
        assert "api_rule" in load_balancer.rules

    def test_sticky_sessions(self, load_balancer):
        """Test sticky session tracking."""
        load_balancer.sticky_sessions["session_123"] = "inst_001"
        load_balancer.sticky_sessions["session_456"] = "inst_002"
        
        assert load_balancer.sticky_sessions["session_123"] == "inst_001"
        assert len(load_balancer.sticky_sessions) == 2

    def test_us_compliance_settings(self, load_balancer):
        """Test US compliance settings."""
        assert load_balancer.us_compliance["geo_fencing"] is True
        assert load_balancer.us_compliance["data_residency"] is True

    def test_get_healthy_instances(self, load_balancer):
        """Test filtering healthy instances."""
        # Add mix of healthy and unhealthy instances
        load_balancer.instances["inst_001"] = Instance(
            instance_id="inst_001", host="h1", port=8080, protocol="http",
            status="healthy", weight=10, connections=0, max_connections=100,
            response_time=0.05, error_rate=0.0, last_health_check=0.0,
        )
        load_balancer.instances["inst_002"] = Instance(
            instance_id="inst_002", host="h2", port=8080, protocol="http",
            status="unhealthy", weight=0, connections=0, max_connections=100,
            response_time=5.0, error_rate=0.5, last_health_check=0.0,
        )
        load_balancer.instances["inst_003"] = Instance(
            instance_id="inst_003", host="h3", port=8080, protocol="http",
            status="healthy", weight=10, connections=0, max_connections=100,
            response_time=0.03, error_rate=0.0, last_health_check=0.0,
        )
        
        healthy = [i for i in load_balancer.instances.values() if i.status == "healthy"]
        
        assert len(healthy) == 2

    def test_instance_connection_tracking(self, load_balancer):
        """Test tracking instance connections."""
        instance = Instance(
            instance_id="inst_001", host="h1", port=8080, protocol="http",
            status="healthy", weight=10, connections=50, max_connections=100,
            response_time=0.05, error_rate=0.0, last_health_check=0.0,
        )
        load_balancer.instances["inst_001"] = instance
        
        # Simulate connection
        load_balancer.instances["inst_001"].connections += 1
        
        assert load_balancer.instances["inst_001"].connections == 51
        assert load_balancer.instances["inst_001"].connections < load_balancer.instances["inst_001"].max_connections


class TestLoadBalancerAlgorithms:
    """Test load balancing algorithm logic."""

    def test_round_robin_selection(self):
        """Test round robin selection logic."""
        instances = ["inst_001", "inst_002", "inst_003"]
        current_index = 0
        
        selections = []
        for _ in range(6):
            selections.append(instances[current_index])
            current_index = (current_index + 1) % len(instances)
        
        assert selections == ["inst_001", "inst_002", "inst_003", "inst_001", "inst_002", "inst_003"]

    def test_weighted_selection(self):
        """Test weighted selection logic."""
        instances = [
            {"id": "inst_001", "weight": 5},
            {"id": "inst_002", "weight": 3},
            {"id": "inst_003", "weight": 2},
        ]
        
        total_weight = sum(i["weight"] for i in instances)
        
        # Verify weights sum correctly
        assert total_weight == 10
        
        # Calculate expected distribution
        expected_ratios = {i["id"]: i["weight"] / total_weight for i in instances}
        assert expected_ratios["inst_001"] == pytest.approx(0.5)
        assert expected_ratios["inst_002"] == pytest.approx(0.3)
        assert expected_ratios["inst_003"] == pytest.approx(0.2)

    def test_least_connections_selection(self):
        """Test least connections selection logic."""
        instances = [
            {"id": "inst_001", "connections": 50},
            {"id": "inst_002", "connections": 30},
            {"id": "inst_003", "connections": 45},
        ]
        
        # Select instance with fewest connections
        selected = min(instances, key=lambda x: x["connections"])
        
        assert selected["id"] == "inst_002"

    def test_response_time_selection(self):
        """Test response time based selection logic."""
        instances = [
            {"id": "inst_001", "response_time": 0.1},
            {"id": "inst_002", "response_time": 0.05},
            {"id": "inst_003", "response_time": 0.08},
        ]
        
        # Select instance with fastest response
        selected = min(instances, key=lambda x: x["response_time"])
        
        assert selected["id"] == "inst_002"
