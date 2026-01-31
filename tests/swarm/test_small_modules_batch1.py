"""Tests for small swarm modules batch 1."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from swarm.adaptive_model_selector import AdaptiveModelSelector
from swarm.adversarial_robustness import AdversarialRobustnessTester, AdversarialTestCase
from swarm.anomaly_detection_ml import MLAnomalyDetector
from swarm.cost_optimizer import ProviderCostOptimizer, ProviderCost
from swarm.privacy_preserving_inference import PrivacyPreservingInference
from swarm.proxy_health_checker import ProxyHealthChecker
from swarm.proxy_load_balancer import CrossRegionProxyLoadBalancer, ProxyEndpoint
from swarm.dynamic_network_policy import DynamicNetworkPolicyEngine


class TestAdaptiveModelSelector:
    def test_record_metrics(self):
        selector = AdaptiveModelSelector()
        selector.record_metrics("summarization", "gpt-4", 100.0, 0.01, 0.95)
        
        assert "summarization" in selector._metrics
        assert "gpt-4" in selector._metrics["summarization"]

    def test_best_model_returns_highest_score(self):
        selector = AdaptiveModelSelector()
        selector.record_metrics("task", "slow", 500.0, 0.005, 0.90)
        selector.record_metrics("task", "fast", 100.0, 0.01, 0.95)
        
        best = selector.best_model("task", max_latency_ms=600.0, max_cost_usd=0.02)
        assert best == "fast"

    def test_best_model_filters_by_constraints(self):
        selector = AdaptiveModelSelector()
        selector.record_metrics("task", "expensive", 100.0, 0.05, 0.99)
        selector.record_metrics("task", "cheap", 200.0, 0.01, 0.90)
        
        best = selector.best_model("task", max_latency_ms=300.0, max_cost_usd=0.02)
        assert best == "cheap"

    def test_best_model_empty_task(self):
        selector = AdaptiveModelSelector()
        best = selector.best_model("unknown", max_latency_ms=100.0, max_cost_usd=0.01)
        assert best == ""


class TestAdversarialRobustnessTester:
    def test_register_test(self):
        tester = AdversarialRobustnessTester()
        test = AdversarialTestCase(
            test_id="test-1",
            description="Prompt injection",
            perturbation_type="injection",
            payload={"prompt": "ignore instructions"},
        )
        tester.register_test(test)
        
        assert "test-1" in tester._tests

    def test_run_test_passes(self):
        tester = AdversarialRobustnessTester()
        test = AdversarialTestCase(
            test_id="test-1",
            description="Test",
            perturbation_type="noise",
            payload={},
        )
        tester.register_test(test)
        
        def evaluator(t):
            return True, []
        
        result = tester.run_test("test-1", evaluator)
        assert result.passed is True

    def test_run_test_fails(self):
        tester = AdversarialRobustnessTester()
        test = AdversarialTestCase(
            test_id="test-1",
            description="Test",
            perturbation_type="noise",
            payload={},
        )
        tester.register_test(test)
        
        def evaluator(t):
            return False, ["vulnerability found"]
        
        result = tester.run_test("test-1", evaluator)
        assert result.passed is False
        assert "vulnerability found" in result.findings

    def test_recent_failures(self):
        tester = AdversarialRobustnessTester()
        for i in range(10):
            test = AdversarialTestCase(f"test-{i}", "Test", "type", {})
            tester.register_test(test)
            tester.run_test(f"test-{i}", lambda t: (i % 2 == 0, []))
        
        failures = tester.recent_failures(limit=3)
        assert len(failures) == 3
        assert all(not f.passed for f in failures)


class TestMLAnomalyDetector:
    def test_record_normal_values(self):
        detector = MLAnomalyDetector(window_size=20, threshold=3.0)
        
        for i in range(15):
            is_anomaly = detector.record("latency", 100.0 + i)
        
        assert is_anomaly is False

    def test_detect_anomaly(self):
        detector = MLAnomalyDetector(window_size=20, threshold=2.0)
        
        for _ in range(15):
            detector.record("latency", 100.0)
        
        is_anomaly = detector.record("latency", 500.0)
        assert is_anomaly is True

    def test_insufficient_history(self):
        detector = MLAnomalyDetector()
        
        is_anomaly = detector.record("metric", 1000.0)
        assert is_anomaly is False


class TestProviderCostOptimizer:
    def test_record_cost(self):
        optimizer = ProviderCostOptimizer()
        cost = ProviderCost(
            provider_id="openai",
            avg_latency_ms=100.0,
            success_rate=0.95,
            cost_per_token_usd=0.00002,
            monthly_volume_tokens=1000000,
        )
        optimizer.record_cost(cost)
        
        assert "openai" in optimizer._costs
        assert cost.monthly_spend == 20.0

    def test_optimization_candidates(self):
        optimizer = ProviderCostOptimizer()
        optimizer.record_cost(ProviderCost("expensive", 100.0, 0.95, 0.0001, 1000000))
        optimizer.record_cost(ProviderCost("cheap", 120.0, 0.92, 0.00005, 1000000))
        
        candidates = optimizer.optimization_candidates(max_latency_increase_ms=50.0, min_success_rate=0.9)
        assert ("expensive", "cheap") in candidates

    def test_no_candidates_when_cheaper_too_slow(self):
        optimizer = ProviderCostOptimizer()
        optimizer.record_cost(ProviderCost("fast", 100.0, 0.95, 0.0001, 1000000))
        optimizer.record_cost(ProviderCost("slow", 200.0, 0.92, 0.00005, 1000000))
        
        candidates = optimizer.optimization_candidates(max_latency_increase_ms=10.0)
        assert len(candidates) == 0


class TestPrivacyPreservingInference:
    def test_encrypt_request(self):
        ppi = PrivacyPreservingInference()
        envelope = ppi.encrypt_request("session-1", "secret data", {"model": "gpt-4"})
        
        assert envelope.payload_hash is not None
        assert envelope.ciphertext is not None
        assert "session-1" in ppi._sessions

    def test_decrypt_response_valid(self):
        ppi = PrivacyPreservingInference()
        envelope = ppi.encrypt_request("session-1", "secret data", {})
        
        result = ppi.decrypt_response("session-1", envelope.ciphertext)
        assert result == envelope.payload_hash

    def test_decrypt_response_mismatch(self):
        ppi = PrivacyPreservingInference()
        ppi.encrypt_request("session-1", "secret data", {})
        
        with pytest.raises(ValueError, match="mismatch"):
            ppi.decrypt_response("session-1", b"wrong_ciphertext")


class TestProxyHealthChecker:
    def test_check_proxy(self):
        checker = ProxyHealthChecker()
        
        with patch("random.uniform", return_value=100.0):
            health = checker.check_proxy("proxy-1")
        
        assert health.proxy_id == "proxy-1"
        assert health.healthy is True
        assert health.last_latency_ms == 100.0

    def test_check_proxy_unhealthy(self):
        checker = ProxyHealthChecker()
        
        with patch("random.uniform", return_value=450.0):
            health = checker.check_proxy("proxy-1")
        
        assert health.healthy is False

    def test_get_health(self):
        checker = ProxyHealthChecker()
        
        assert checker.get_health("unknown") is None
        
        with patch("random.uniform", return_value=100.0):
            checker.check_proxy("proxy-1")
        
        health = checker.get_health("proxy-1")
        assert health is not None


class TestCrossRegionProxyLoadBalancer:
    def test_register_proxy(self):
        balancer = CrossRegionProxyLoadBalancer()
        proxy = ProxyEndpoint(
            endpoint_id="p1",
            region="us-east",
            url="http://proxy1.example.com",
            latency_ms=50.0,
            success_rate=0.99,
            last_checked=datetime.utcnow(),
        )
        balancer.register_proxy(proxy)
        
        assert "us-east" in balancer._proxies
        assert len(balancer._proxies["us-east"]) == 1

    def test_choose_proxy_from_region(self):
        balancer = CrossRegionProxyLoadBalancer()
        proxy = ProxyEndpoint("p1", "us-east", "http://p1", 50.0, 0.99, datetime.utcnow())
        balancer.register_proxy(proxy)
        
        chosen = balancer.choose_proxy("us-east")
        assert chosen.endpoint_id == "p1"

    def test_choose_proxy_fallback(self):
        balancer = CrossRegionProxyLoadBalancer()
        proxy = ProxyEndpoint("p1", "eu-west", "http://p1", 50.0, 0.99, datetime.utcnow())
        balancer.register_proxy(proxy)
        
        chosen = balancer.choose_proxy("us-east")
        assert chosen.endpoint_id == "p1"

    def test_choose_proxy_no_proxies(self):
        balancer = CrossRegionProxyLoadBalancer()
        
        with pytest.raises(ValueError, match="No proxies"):
            balancer.choose_proxy("us-east")


class TestDynamicNetworkPolicyEngine:
    def test_record_event_creates_policy(self):
        engine = DynamicNetworkPolicyEngine()
        policy = engine.record_event("agent-1", latency_ms=200.0, violations=0)
        
        assert policy.agent_id == "agent-1"
        assert policy.sensitivity == "PUBLIC"

    def test_record_event_increases_latency_cap(self):
        engine = DynamicNetworkPolicyEngine()
        engine.record_event("agent-1", latency_ms=200.0, violations=0)
        policy = engine.record_event("agent-1", latency_ms=1500.0, violations=0)
        
        assert policy.max_latency_ms == 1650

    def test_record_event_escalates_on_violations(self):
        engine = DynamicNetworkPolicyEngine()
        policy = engine.record_event("agent-1", latency_ms=200.0, violations=1)
        
        assert policy.sensitivity == "CRITICAL"
        assert policy.allowed_proxy_types == ["direct"]

    def test_get_policy(self):
        engine = DynamicNetworkPolicyEngine()
        
        assert engine.get_policy("unknown") is None
        
        engine.record_event("agent-1", latency_ms=100.0, violations=0)
        policy = engine.get_policy("agent-1")
        assert policy is not None
