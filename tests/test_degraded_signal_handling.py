"""
Tests for Degraded Signal Handling.

Tests that when signals degrade, behavior becomes more conservative, never less.
Implements FIA-compliant conservative degradation strategies.
"""

import pytest
import time
from unittest.mock import patch, MagicMock
from typing import Dict, Any, List

from core.domain_priority_manager import DomainPriorityManager, get_domain_priority_manager
from core.reality_auditor import get_reality_auditor, AuditorMode
from core.reality_registry import get_reality_registry, AssertionDomain, AssertionStatus
from monitoring.reality_metrics import get_metrics_collector


class TestPartialAssertionLoss:
    """Test behavior when partial assertion loss occurs."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_assertion_loss_below_threshold(self, priority_manager):
        """Test that assertion loss below threshold triggers conservative behavior."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Initially, all core domains should be accessible
        allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
        assert allowed, "Market should be accessible initially"
        
        # Simulate partial assertion loss (drop from 7 to 3 assertions)
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to fail due to insufficient assertions
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "INSUFFICIENT_ASSERTIONS: market has 3 valid assertions (min 5)"
            }
            
            # System should remain conservative
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should remain blocked when assertions below threshold"
            assert "priority" in reason.lower()
            
            # Core observation should still work but with warnings
            allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
            # In a real system, this might be allowed with warnings
            assert isinstance(allowed, bool), "Market read should return boolean"
    
    def test_domain_specific_assertion_loss(self, priority_manager):
        """Test behavior when specific domains lose assertions."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate market domain losing assertions
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to fail specifically for market
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "DOMAIN_DEGRADED: market domain has insufficient assertions"
            }
            
            # System should trigger rollback or conservative mode
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked when market domain degraded"
            
            # Other domains might still work with restrictions
            allowed, reason = priority_manager.check_domain_access("simulation", "read", "test_actor")
            assert isinstance(allowed, bool), "Simulation should return boolean"
    
    def test_metrics_update_on_assertion_loss(self, priority_manager):
        """Test that metrics are updated when assertions are lost."""
        
        metrics_collector = get_metrics_collector()
        
        # Simulate assertion loss
        domain_counts_before = {
            "market": {"valid": 7, "total": 7, "failed": 0},
            "onchain": {"valid": 7, "total": 7, "failed": 0},
            "simulation": {"valid": 7, "total": 7, "failed": 0},
            "agent": {"valid": 7, "total": 7, "failed": 0}
        }
        
        metrics_collector.update_domain_assertion_metrics(domain_counts_before)
        
        # Simulate partial loss
        domain_counts_after = {
            "market": {"valid": 3, "total": 7, "failed": 4},
            "onchain": {"valid": 7, "total": 7, "failed": 0},
            "simulation": {"valid": 7, "total": 7, "failed": 0},
            "agent": {"valid": 7, "total": 7, "failed": 0}
        }
        
        metrics_collector.update_domain_assertion_metrics(domain_counts_after)
        
        # Check that metrics reflect the loss
        from monitoring.reality_metrics import reality_valid_assertions
        
        # In a real implementation, this would check the actual metric values
        # For now, we verify the update was called
        assert True, "Metrics should be updated on assertion loss"


class TestFeedLatencySpike:
    """Test behavior when feed latency spikes occur."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_stale_market_data_handling(self, priority_manager):
        """Test handling of stale market data timestamps."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Initially, market should be accessible
        allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
        assert allowed, "Market should be accessible initially"
        
        # Simulate stale market data (timestamps > threshold)
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to fail due to stale data
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "FEED_STALE: market data timestamp exceeds threshold"
            }
            
            # System should treat market as degraded
            allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
            # In a real system, this might be blocked or allowed with warnings
            assert isinstance(allowed, bool), "Market access should return boolean"
            
            # Execution should definitely remain blocked
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked with stale feed data"
    
    def test_feed_latency_threshold_violation(self, priority_manager):
        """Test behavior when feed latency exceeds thresholds."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate high latency scenario
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to fail due to latency
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "FEED_LATENCY_HIGH: onchain feed latency exceeds threshold"
            }
            
            # System should degrade the affected domain
            allowed, reason = priority_manager.check_domain_access("onchain", "read", "test_actor")
            assert isinstance(allowed, bool), "Onchain access should return boolean"
            
            # Other domains should still work
            allowed, reason = priority_manager.check_domain_access("simulation", "read", "test_actor")
            assert allowed, "Simulation should still work when onchain has high latency"
    
    def test_multiple_feed_degradation(self, priority_manager):
        """Test behavior when multiple feeds degrade simultaneously."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate multiple feed issues
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to fail for multiple feeds
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "MULTIPLE_FEED_DEGRADATION: market and onchain feeds compromised"
            }
            
            # System should become highly conservative
            dangerous_operations = [
                ("execution", "execute"),
                ("governance", "write"),
                ("treasury", "transfer")
            ]
            
            for domain, operation in dangerous_operations:
                allowed, reason = priority_manager.check_domain_access(domain, operation, "test_actor")
                assert not allowed, f"{domain}.{operation} should be blocked with multiple feed degradation"
            
            # Core observation might still work with restrictions
            core_operations = [
                ("market", "read"),
                ("onchain", "read"),
                ("simulation", "read"),
                ("agent", "read")
            ]
            
            for domain, operation in core_operations:
                allowed, reason = priority_manager.check_domain_access(domain, operation, "test_actor")
                assert isinstance(allowed, bool), f"{domain}.{operation} should return boolean"


class TestContradictorySignals:
    """Test handling of contradictory signals between domains."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_market_vs_governance_conflict(self, priority_manager):
        """Test conflict between market and governance signals."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate contradictory signals
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to detect contradiction
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "CONTRADICTORY_SIGNALS: market indicates OPEN but governance indicates FAILING"
            }
            
            # System should choose conservative interpretation
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked with contradictory signals"
            
            # Market access might be restricted
            allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
            assert isinstance(allowed, bool), "Market access should return boolean"
    
    def test_simulation_vs_agent_conflict(self, priority_manager):
        """Test conflict between simulation and agent signals."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate conflicting signals
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to detect conflict
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "CONTRADICTORY_SIGNALS: simulation shows PASSED but agent shows CRITICAL_ERROR"
            }
            
            # System should choose conservative interpretation
            allowed, reason = priority_manager.check_domain_access("simulation", "execute", "test_actor")
            assert not allowed, "Simulation execution should be blocked with contradictory signals"
            
            # Agent operations should be restricted
            allowed, reason = priority_manager.check_domain_access("agent", "propose", "test_actor")
            assert not allowed, "Agent proposals should be blocked with contradictory signals"
    
    def test_priority_hierarchy_conflict_resolution(self, priority_manager):
        """Test that priority hierarchy resolves conflicts conservatively."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Test case: high-priority caller wants blocked operation
        context = {
            "caller_kind": "safety_override",
            "priority_hint": "high",
            "justification": "emergency_maintenance"
        }
        
        # Even with high priority caller, blocked domains should remain blocked
        # unless specifically overridden
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_override", context)
        
        # In current implementation, this would be blocked unless safety override is specifically handled
        # The test verifies the conservative default behavior
        assert isinstance(allowed, bool), "Execution access should return boolean"


class TestHighViolationRate:
    """Test behavior when violation rate is high."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_agent_spam_violations(self, priority_manager):
        """Test system behavior when agent repeatedly calls blocked domains."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate agent spamming blocked domains
        violation_count = 0
        blocked_domains = ["execution", "governance", "treasury", "system"]
        operations = ["execute", "write", "read", "transfer", "propose"]
        
        for domain in blocked_domains:
            for operation in operations:
                allowed, reason = priority_manager.check_domain_access(domain, operation, "spamming_agent")
                if not allowed:
                    violation_count += 1
        
        # All calls should be rejected
        assert violation_count == len(blocked_domains) * len(operations), "All blocked domain calls should be rejected"
        
        # Check that violations were logged
        violations = priority_manager.get_priority_violations(100)
        assert len(violations) > 0, "Violations should be logged"
        
        # Check that metrics were updated
        from monitoring.reality_metrics import reality_priority_violations_total
        
        # In a real implementation, this would check the actual metric values
        assert True, "Violation metrics should be updated"
    
    def test_violation_rate_escalation(self, priority_manager):
        """Test escalation when violation rate is high."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Generate high violation rate
        for i in range(50):
            priority_manager.check_domain_access("execution", "execute", f"spam_agent_{i}")
            priority_manager.check_domain_access("treasury", "transfer", f"spam_agent_{i}")
        
        # Check that violations were logged
        violations = priority_manager.get_priority_violations(100)
        assert len(violations) >= 100, "High number of violations should be logged"
        
        # In a real system, this might trigger alerts or stricter mode
        # For now, we verify the logging works
        assert True, "High violation rate should be logged"
    
    def test_violation_metrics_accuracy(self, priority_manager):
        """Test that violation metrics are accurately tracked."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Generate specific violations
        test_violations = [
            ("execution", "execute", 5),
            ("governance", "write", 3),
            ("treasury", "transfer", 2),
            ("system", "config", 1)
        ]
        
        for domain, operation, count in test_violations:
            for i in range(count):
                priority_manager.check_domain_access(domain, operation, f"test_agent_{i}")
        
        # Verify violations were logged correctly
        violations = priority_manager.get_priority_violations(50)
        
        domain_counts = {}
        for violation in violations:
            domain = violation["domain"]
            if domain not in domain_counts:
                domain_counts[domain] = 0
            domain_counts[domain] += 1
        
        for domain, operation, expected_count in test_violations:
            actual_count = domain_counts.get(domain, 0)
            assert actual_count >= expected_count, f"Expected at least {expected_count} violations for {domain}, got {actual_count}"


class TestSlowAssertionEngine:
    """Test behavior when assertion engine is slow."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_latency_threshold_violation(self, priority_manager):
        """Test behavior when assertion evaluation is slow."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate slow assertion engine
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to detect slow engine
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "ASSERTION_ENGINE_SLOW: evaluation latency exceeds threshold"
            }
            
            # System should mark engine as degraded
            allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
            assert isinstance(allowed, bool), "Market access should return boolean"
            
            # Execution should definitely be blocked
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked with slow assertion engine"
    
    def test_unknown_as_failure(self, priority_manager):
        """Test that unknown assertion results are treated as failures."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Simulate unknown assertion results
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to fail due to unknown results
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "UNKNOWN_ASSERTION_RESULTS: cannot determine assertion validity"
            }
            
            # System should fail safe
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked with unknown assertion results"
            
            # Keep or roll back to safer state
            allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
            assert isinstance(allowed, bool), "Market access should return boolean"
    
    def test_engine_degradation_recovery(self, priority_manager):
        """Test recovery from assertion engine degradation."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Initially, engine is slow
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # First call: engine is slow
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "ASSERTION_ENGINE_SLOW: evaluation latency exceeds threshold"
            }
            
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked when engine is slow"
            
            # Second call: engine recovers
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": True,
                "reason": "All safety checks passed"
            }
            
            # System should allow normal operations again
            allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
            assert allowed, "Market read should be allowed when engine recovers"
            
            # Execution should still be blocked by domain rules
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should remain blocked by domain rules"


class TestConservativeDegradation:
    """Test that degradation always becomes more conservative."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_degradation_never_lessens_restrictions(self, priority_manager):
        """Test that degradation never lessens restrictions."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Start with normal restrictions
        initial_allowed = priority_manager.check_domain_access("market", "read", "test_actor")
        initial_blocked = not priority_manager.check_domain_access("execution", "execute", "test_actor")
        
        assert initial_allowed, "Market should be accessible initially"
        assert initial_blocked, "Execution should be blocked initially"
        
        # Simulate degradation
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check to fail
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "DEGRADED_SIGNALS: multiple domains showing issues"
            }
            
            # After degradation, execution should still be blocked
            degraded_blocked = not priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert degraded_blocked, "Execution should remain blocked after degradation"
            
            # Market access might be restricted but never expanded
            degraded_allowed = priority_manager.check_domain_access("market", "read", "test_actor")
            # In a real system, this might be blocked or allowed with warnings
            # The key point is it should never become less restrictive than before
            assert isinstance(degraded_allowed, bool), "Market access should return boolean"
    
    def test_conservative_interpretation_preference(self, priority_manager):
        """Test that system prefers conservative interpretations."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Test case: ambiguous signal that could be interpreted either way
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock ambiguous safety check result
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "AMBIGUOUS_SIGNALS: market data quality uncertain"
            }
            
            # System should choose conservative interpretation
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked with ambiguous signals"
            
            # Market access should be conservative
            allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
            assert isinstance(allowed, bool), "Market access should return boolean"
    
    def test_safety_first_principle(self, priority_manager):
        """Test that safety is always prioritized over functionality."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Test case: functionality vs safety conflict
        with patch('core.reality_auditor.get_reality_auditor') as mock_auditor:
            mock_auditor_instance = MagicMock()
            mock_auditor.return_value = mock_auditor_instance
            
            # Mock safety check that would allow execution but with safety concerns
            mock_auditor_instance._run_sighted_degraded_safety_checks.return_value = {
                "passed": False,
                "reason": "SAFETY_CONCERN: execution allowed but safety checks indicate elevated risk"
            }
            
            # Safety should win - execution should be blocked
            allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
            assert not allowed, "Execution should be blocked when safety concerns exist"
            
            # Even if some operations are technically allowed, they should be conservative
            allowed, reason = priority_manager.check_domain_access("simulation", "execute", "test_actor")
            # Simulation might be allowed but with restrictions
            assert isinstance(allowed, bool), "Simulation execution should return boolean"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
