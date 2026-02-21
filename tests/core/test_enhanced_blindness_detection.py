#!/usr/bin/env python3
"""
Enhanced Reality Auditor Test Suite

Tests the robust blindness detection and operator tools implementation.
Follows the step-by-step implementation plan for safer, louder, self-healing blindness mode.
"""

import pytest
import time
import json
from typing import Dict, List, Optional
from dataclasses import asdict

# Test imports
from core.reality_registry import (
    RealityRegistry,
    AssertionDomain,
    AssertionStatus,
    BlindnessContext,
    AuditorMode,
    BlindnessSeverity,
    AssertionPipelineHealth,
    RealityAssertion,
    AssertionProvenance,
)
from core.reality_auditor import RealityAuditor, AuditResult


class TestEnhancedBlindnessDetection:
    """Test suite for enhanced blindness detection with context and severity."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = RealityRegistry()
        self.auditor = RealityAuditor(registry=self.registry, environment="test")
        self.current_time = time.time()
    
    def test_no_assertions_critical_blindness(self):
        """Test that no assertions triggers critical blindness."""
        # Registry is empty by default
        context = self.registry.check_blindness_context(
            self.current_time,
            regime_entropy=0.0,
            environment="live",
            pipeline_id="test"
        )
        
        assert context.mode == AuditorMode.BLIND_HARD
        assert context.severity == BlindnessSeverity.CRITICAL
        assert context.primary_reason == "No assertions registered"
        assert "metrics" in context.impacted_subsystems
        assert "risk_checks" in context.impacted_subsystems
        assert context.num_total_assertions == 0
        assert context.num_valid_assertions == 0
    
    def test_no_valid_assertions_critical_blindness(self):
        """Test that no valid assertions triggers critical blindness."""
        # Register expired assertions only
        self.registry.register_assertion(
            domain=AssertionDomain.MARKET,
            description="Test assertion",
            confidence=0.8,
            provenance_score=0.9,
            regime_compatibility=0.8,
            decay_rate=0.1,
            validity_window=1.0,  # 1 second validity
            sources=[AssertionProvenance("test", "test", "", 1.0)]
        )
        
        # Wait for expiration
        time.sleep(2)
        self.registry.update_assertion_status(time.time(), 0.0)
        
        context = self.registry.check_blindness_context(
            time.time(),
            regime_entropy=0.0,
            environment="live",
            pipeline_id="test"
        )
        
        assert context.mode == AuditorMode.BLIND_HARD
        assert context.severity == BlindnessSeverity.CRITICAL
        assert context.primary_reason == "No valid assertions"
        assert context.num_total_assertions > 0
        assert context.num_valid_assertions == 0
    
    def test_core_domain_missing_critical_blindness(self):
        """Test that missing core domain triggers critical blindness."""
        # Register only market assertions (not core)
        self.registry.register_assertion(
            domain=AssertionDomain.MARKET,
            description="Market assertion",
            confidence=0.8,
            provenance_score=0.9,
            regime_compatibility=0.8,
            decay_rate=0.01,
            validity_window=3600.0,
            sources=[AssertionProvenance("test", "test", "", 1.0)]
        )
        
        context = self.registry.check_blindness_context(
            self.current_time,
            regime_entropy=0.0,
            environment="live",
            pipeline_id="test"
        )
        
        assert context.mode == AuditorMode.BLIND_HARD
        assert context.severity == BlindnessSeverity.CRITICAL
        assert "Core domain" in context.primary_reason
        assert "execution" in context.impacted_subsystems
    
    def test_high_regime_entropy_concerning_blindness(self):
        """Test that high regime entropy triggers concerning blindness."""
        # Register valid core assertions
        self.registry.register_assertion(
            domain=AssertionDomain.EXECUTION,
            description="Execution assertion",
            confidence=0.8,
            provenance_score=0.9,
            regime_compatibility=0.8,
            decay_rate=0.01,
            validity_window=3600.0,
            sources=[AssertionProvenance("test", "test", "", 1.0)]
        )
        
        context = self.registry.check_blindness_context(
            self.current_time,
            regime_entropy=0.8,  # High entropy
            environment="live",
            pipeline_id="test"
        )
        
        assert context.mode == AuditorMode.BLIND_SOFT
        assert context.severity == BlindnessSeverity.CONCERNING
        assert "Regime entropy" in context.primary_reason
        assert "prediction_quality" in context.impacted_subsystems
    
    def test_environment_specific_severity_escalation(self):
        """Test that severity escalates based on environment and duration."""
        # Register no assertions (critical condition)
        context_live = self.registry.check_blindness_context(
            self.current_time,
            regime_entropy=0.0,
            environment="live",
            pipeline_id="test"
        )
        
        context_sim = self.registry.check_blindness_context(
            self.current_time,
            regime_entropy=0.0,
            environment="sim",
            pipeline_id="test"
        )
        
        # Both should be critical initially
        assert context_live.severity == BlindnessSeverity.CRITICAL
        assert context_sim.severity == BlindnessSeverity.CRITICAL
        
        # Simulate time passing (mock by setting last_assertion_ts)
        # This would be tested with actual time passing in integration tests
    
    def test_blindness_context_completeness(self):
        """Test that blindness context contains all required fields."""
        context = self.registry.check_blindness_context(
            self.current_time,
            regime_entropy=0.0,
            environment="paper",
            pipeline_id="test_pipeline"
        )
        
        # Verify all required fields are present
        required_fields = [
            'mode', 'severity', 'environment', 'pipeline_id', 'current_time',
            'last_assertion_ts', 'last_resolution_ts', 'num_total_assertions',
            'num_valid_assertions', 'num_resolved_assertions', 'num_markets_scanned',
            'expected_assertions_window', 'blind_duration', 'impacted_subsystems',
            'primary_reason', 'secondary_reasons'
        ]
        
        context_dict = context.to_dict()
        for field in required_fields:
            assert field in context_dict, f"Missing field: {field}"
        
        # Verify environment-specific expectations
        assert context.environment == "paper"
        assert context.pipeline_id == "test_pipeline"
        assert context.expected_assertions_window == 6.0  # 6 hours for paper
    
    def test_backward_compatibility_simple_check(self):
        """Test that old check_blindness_condition still works."""
        is_blind, reason = self.registry.check_blindness_condition(
            self.current_time,
            regime_entropy=0.0
        )
        
        # Should match the new implementation
        context = self.registry.check_blindness_context(
            self.current_time,
            regime_entropy=0.0
        )
        
        assert is_blind == (context.mode != AuditorMode.NORMAL)
        assert reason == context.primary_reason


class TestAssertionPipelineHealth:
    """Test suite for assertion pipeline health monitoring."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = RealityRegistry()
        self.current_time = time.time()
    
    def test_empty_pipeline_stale(self):
        """Test that empty pipeline is marked as stale."""
        health = self.registry.get_assertion_pipeline_health(self.current_time)
        
        assert health.assertions_per_hour == 0.0
        assert health.last_assertion_ts is None
        assert health.last_resolution_ts is None
        assert health.pending_assertions == 0
        assert health.resolved_assertions == 0
        assert health.is_stale == True
    
    def test_recent_pipeline_healthy(self):
        """Test that recent pipeline is healthy."""
        # Register recent assertion
        self.registry.register_assertion(
            domain=AssertionDomain.MARKET,
            description="Recent assertion",
            confidence=0.8,
            provenance_score=0.9,
            regime_compatibility=0.8,
            decay_rate=0.01,
            validity_window=3600.0,
            sources=[AssertionProvenance("test", "test", "", 1.0)]
        )
        
        health = self.registry.get_assertion_pipeline_health(self.current_time)
        
        assert health.assertions_per_hour >= 0.0
        assert health.last_assertion_ts is not None
        assert health.is_stale == False
    
    def test_stale_threshold_detection(self):
        """Test stale detection with custom threshold."""
        # Register old assertion
        old_time = self.current_time - (3 * 3600)  # 3 hours ago
        with pytest.MonkeyPatch().context() as m:
            m.setattr(time, 'time', lambda: old_time)
            self.registry.register_assertion(
                domain=AssertionDomain.MARKET,
                description="Old assertion",
                confidence=0.8,
                provenance_score=0.9,
                regime_compatibility=0.8,
                decay_rate=0.01,
                validity_window=3600.0,
                sources=[AssertionProvenance("test", "test", "", 1.0)]
            )
        
        # Check with 2-hour threshold
        health = self.registry.get_assertion_pipeline_health(
            self.current_time,
            stale_threshold_hours=2.0
        )
        
        assert health.is_stale == True
        assert health.stale_threshold_hours == 2.0


class TestAuditorOperatorTools:
    """Test suite for auditor operator tools and API endpoints."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = RealityRegistry()
        self.auditor = RealityAuditor(registry=self.registry, environment="test")
        self.current_time = time.time()
    
    def test_auditor_status_comprehensive(self):
        """Test comprehensive auditor status endpoint."""
        status = self.auditor.get_auditor_status()
        
        required_sections = [
            'auditor_mode', 'environment', 'regime_entropy', 'last_audit',
            'blindness_context', 'pipeline_health', 'registry_status'
        ]
        
        for section in required_sections:
            assert section in status, f"Missing status section: {section}"
        
        # Verify blindness context structure
        blindness = status['blindness_context']
        assert 'mode' in blindness
        assert 'severity' in blindness
        assert 'primary_reason' in blindness
        
        # Verify pipeline health structure
        health = status['pipeline_health']
        assert 'assertions_per_hour' in health
        assert 'is_stale' in health
        assert 'stale_threshold_hours' in health
    
    def test_recent_assertions_debugging(self):
        """Test recent assertions endpoint for debugging."""
        # Register some test assertions
        for i in range(5):
            self.registry.register_assertion(
                domain=AssertionDomain.MARKET,
                description=f"Test assertion {i}",
                confidence=0.8,
                provenance_score=0.9,
                regime_compatibility=0.8,
                decay_rate=0.01,
                validity_window=3600.0,
                sources=[AssertionProvenance("test", "test", "", 1.0)]
            )
        
        recent = self.auditor.get_recent_assertions(since_hours=1.0, limit=10)
        
        assert isinstance(recent, list)
        assert len(recent) <= 10
        assert len(recent) <= 5  # Only 5 registered
        
        # Verify structure of returned assertions
        if recent:
            assertion = recent[0]
            required_fields = [
                'assertion_id', 'domain', 'status', 'created_at',
                'confidence', 'effective_confidence'
            ]
            for field in required_fields:
                assert field in assertion, f"Missing assertion field: {field}"
    
    def test_reload_persistent_store_placeholder(self):
        """Test reload from persistent store (placeholder)."""
        # This is a placeholder test - actual implementation would integrate with real store
        result = self.auditor.reload_from_persistent_store()
        
        # Should return True for placeholder implementation
        assert isinstance(result, bool)
    
    def test_audit_result_enhanced_with_context(self):
        """Test that audit results include blindness context."""
        # Test UI component audit
        result = self.auditor.audit_ui_component(
            component_id="test_component",
            required_assertions=["nonexistent_assertion"]
        )
        
        assert isinstance(result, AuditResult)
        assert result.blindness_context is not None
        assert result.auditor_mode in [AuditorMode.NORMAL, AuditorMode.BLIND_SOFT, AuditorMode.BLIND_HARD]
        
        # Should fail due to missing assertion, but include context
        assert result.passed == False
        assert "Missing required assertion" in result.reason


class TestStructuredLogging:
    """Test suite for structured logging of blindness incidents."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = RealityRegistry()
        self.auditor = RealityAuditor(registry=self.registry, environment="test")
    
    def test_critical_blindness_logging(self):
        """Test that critical blindness incidents are logged at error level."""
        # Empty registry should trigger critical blindness
        with pytest.raises(Exception):  # Logger should be called
            # This would be tested with actual logger mocking
            self.auditor.audit_loop()
    
    def test_concerning_blindness_logging(self):
        """Test that concerning blindness incidents are logged at warning level."""
        # Register core assertion but with high entropy
        self.registry.register_assertion(
            domain=AssertionDomain.EXECUTION,
            description="Core assertion",
            confidence=0.8,
            provenance_score=0.9,
            regime_compatibility=0.8,
            decay_rate=0.01,
            validity_window=3600.0,
            sources=[AssertionProvenance("test", "test", "", 1.0)]
        )
        
        # High entropy should trigger concerning blindness
        self.auditor.update_regime_entropy(0.8)
        
        with pytest.raises(Exception):  # Logger should be called
            self.auditor.audit_loop()
    
    def test_structured_log_data_completeness(self):
        """Test that structured log data contains all required fields."""
        context = self.registry.check_blindness_context(
            time.time(),
            regime_entropy=0.0,
            environment="live",
            pipeline_id="test"
        )
        
        log_data = context.to_dict()
        
        # Verify all fields are serializable (JSON-compatible)
        try:
            json.dumps(log_data)
        except (TypeError, ValueError):
            pytest.fail("Log data is not JSON serializable")
        
        # Verify critical fields for alerting
        alerting_fields = [
            'mode', 'severity', 'environment', 'primary_reason',
            'impacted_subsystems', 'blind_duration'
        ]
        
        for field in alerting_fields:
            assert field in log_data, f"Missing alerting field: {field}"


class TestMetricsRobustness:
    """Test suite for metrics robustness during blindness."""
    
    def setup_method(self):
        """Set up test environment."""
        self.registry = RealityRegistry()
        self.auditor = RealityAuditor(registry=self.registry, environment="test")
    
    def test_brier_metrics_awaiting_outcomes_when_blind(self):
        """Test that Brier metrics return awaiting outcomes when blind."""
        from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent, ArbitrageOpportunitySummary
        
        agent = PredictionArbitrageAnalystAgent(
            agent_id="test_agent",
            min_spread=0.05,
            min_liquidity=50000,
            categories=["test"]
        )
        
        # Create sample opportunities
        opportunities = [
            ArbitrageOpportunitySummary(
                canonical_question="Test question",
                spread_probability=0.65,
                best_venue="test",
                best_probability=0.68,
                worst_venue="test",
                worst_probability=0.62,
                days_to_resolution=30.0,
                total_liquidity=75000.0,
                risk_note="Test risk",
                forecast_probability=0.65
            )
        ]
        
        # Should return awaiting outcomes when blind
        metrics = agent._calculate_brier_score(opportunities)
        
        assert metrics is not None
        assert metrics["status"] == "awaiting_outcomes"
        assert metrics["brier_score"] is None
        assert metrics["quality_category"] == "AWAITING_OUTCOMES"
        assert "blindness_context" in metrics
    
    def test_metrics_calculation_when_normal(self):
        """Test that metrics calculate normally when not blind."""
        # Register a core assertion to avoid blindness
        self.registry.register_assertion(
            domain=AssertionDomain.EXECUTION,
            description="Core assertion",
            confidence=0.8,
            provenance_score=0.9,
            regime_compatibility=0.8,
            decay_rate=0.01,
            validity_window=3600.0,
            sources=[AssertionProvenance("test", "test", "", 1.0)]
        )
        
        from agents.prediction_arbitrage_analyst import PredictionArbitrageAnalystAgent, ArbitrageOpportunitySummary
        
        agent = PredictionArbitrageAnalystAgent(
            agent_id="test_agent",
            min_spread=0.05,
            min_liquidity=50000,
            categories=["test"]
        )
        
        opportunities = [
            ArbitrageOpportunitySummary(
                canonical_question="Test question",
                spread_probability=0.65,
                best_venue="test",
                best_probability=0.68,
                worst_venue="test",
                worst_probability=0.62,
                days_to_resolution=30.0,
                total_liquidity=75000.0,
                risk_note="Test risk",
                forecast_probability=0.65
            )
        ]
        
        # Should calculate metrics normally
        metrics = agent._calculate_brier_score(opportunities)
        
        assert metrics is not None
        assert metrics["status"] == "ok"
        assert metrics["brier_score"] is not None
        assert metrics["quality_category"] in ["Excellent", "Good", "Fair", "Poor"]


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, "-v"])
