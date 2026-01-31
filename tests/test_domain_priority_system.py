"""
Unit Tests for Domain Priority System.

Table-driven tests for priority resolution, access control, rate limiting,
and mode-aware behavior.
"""

import pytest
import time
from typing import Dict, List, Tuple

from core.domain_priority_manager import DomainPriorityManager, get_domain_priority_manager
from core.reality_registry import AssertionDomain, AssertionStatus
from core.reality_auditor import AuditorMode


class TestDomainPriorityResolution:
    """Test priority resolution and domain classification."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    @pytest.mark.parametrize("domain,expected_priority,expected_ops", [
        ("market", 1, ["read", "monitor", "query"]),
        ("onchain", 1, ["read", "monitor", "query"]),
        ("simulation", 2, ["read", "write", "execute"]),
        ("agent", 3, ["read", "propose", "recommend"]),
        ("execution", 4, []),  # No allowed operations
        ("governance", 4, []),
        ("treasury", 4, []),
        ("system", 4, []),
    ])
    def test_priority_resolution(self, priority_manager, domain, expected_priority, expected_ops):
        """Test that domains resolve to correct priority levels."""
        config = priority_manager.domain_configs[domain]
        assert config.priority == expected_priority, f"{domain} should have priority {expected_priority}"
        assert config.allowed_operations == expected_ops, f"{domain} should allow operations {expected_ops}"
    
    def test_unknown_domain_error(self, priority_manager):
        """Test that unknown domains raise explicit errors."""
        with pytest.raises(ValueError, match="Unknown domain: unknown_domain"):
            priority_manager.check_domain_access("unknown_domain", "read")
    
    @pytest.mark.parametrize("domain,operation,expected_allowed", [
        # Market/Onchain - read-only access
        ("market", "read", True),
        ("market", "monitor", True),
        ("market", "write", False),
        ("market", "execute", False),
        ("onchain", "read", True),
        ("onchain", "query", True),
        ("onchain", "write", False),
        
        # Simulation - full access
        ("simulation", "read", True),
        ("simulation", "write", True),
        ("simulation", "execute", True),
        
        # Agent - read + proposals only
        ("agent", "read", True),
        ("agent", "propose", True),
        ("agent", "recommend", True),
        ("agent", "execute", False),
        ("agent", "write", False),
        
        # Blocked domains - no access
        ("execution", "read", False),
        ("execution", "execute", False),
        ("execution", "write", False),
        ("governance", "read", False),
        ("governance", "propose", False),
        ("treasury", "read", False),
        ("treasury", "transfer", False),
        ("system", "read", False),
        ("system", "config", False),
    ])
    def test_access_control(self, priority_manager, domain, operation, expected_allowed):
        """Test access control rules for each domain."""
        allowed, reason = priority_manager.check_domain_access(domain, operation, "test_actor")
        assert allowed == expected_allowed, f"{domain}.{operation} should be {expected_allowed}, got {allowed}"
        
        if not expected_allowed:
            assert "priority" in reason.lower() or "blocked" in reason.lower()


class TestRateLimiting:
    """Test query rate limiting per domain."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    @pytest.mark.parametrize("domain,max_rate", [
        ("market", 1000),
        ("onchain", 500),
        ("simulation", 100),
        ("agent", 50),
        ("execution", 0),  # Blocked
        ("governance", 0),
        ("treasury", 0),
        ("system", 0),
    ])
    def test_rate_limits(self, priority_manager, domain, max_rate):
        """Test that rate limits are correctly configured."""
        config = priority_manager.domain_configs[domain]
        assert config.max_queries_per_minute == max_rate, f"{domain} should have rate limit {max_rate}"
    
    def test_rate_limit_enforcement(self, priority_manager):
        """Test that rate limits are enforced."""
        # Test market domain (1000/min limit)
        allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
        assert allowed, "First market query should be allowed"
        
        # Simulate hitting rate limit
        for _ in range(1005):  # Exceed limit
            priority_manager.check_domain_access("market", "read", "test_actor")
        
        # Next query should be blocked
        allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
        assert not allowed, "Market query should be blocked after rate limit exceeded"
        assert "rate limit" in reason.lower()


class TestModeAwareBehavior:
    """Test behavior changes based on system mode."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_blind_mode_inactive(self, priority_manager):
        """Test that priority manager is inactive in BLIND mode."""
        priority_manager.set_mode("BLIND")
        
        # All domains should be allowed in BLIND mode (safe default)
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
        assert allowed, "In BLIND mode, all domains should be allowed (safe default)"
        assert "inactive" in reason.lower()
    
    def test_sighted_degraded_mode_active(self, priority_manager):
        """Test that priority manager is active in SIGHTED_DEGRADED mode."""
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Blocked domains should be rejected
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
        assert not allowed, "In SIGHTED_DEGRADED mode, execution should be blocked"
        assert "priority" in reason.lower()
        
        # Core domains should be allowed
        allowed, reason = priority_manager.check_domain_access("market", "read", "test_actor")
        assert allowed, "In SIGHTED_DEGRADED mode, market read should be allowed"


class TestPropertyBasedTests:
    """Lightweight property-based tests."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_blocked_domains_never_succeed(self, priority_manager):
        """Property: blocked domains never succeed in SIGHTED_DEGRADED mode."""
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        blocked_domains = ["execution", "governance", "treasury", "system"]
        operations = ["read", "write", "execute", "propose", "transfer"]
        
        for domain in blocked_domains:
            for operation in operations:
                allowed, reason = priority_manager.check_domain_access(domain, operation, "test_actor")
                assert not allowed, f"Blocked domain {domain} should never allow {operation}"
    
    def test_core_domains_always_have_access(self, priority_manager):
        """Property: core domains always have some access in SIGHTED_DEGRADED mode."""
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        core_domains = {"market": ["read", "monitor"], "onchain": ["read", "monitor"]}
        
        for domain, allowed_ops in core_domains.items():
            for operation in allowed_ops:
                allowed, reason = priority_manager.check_domain_access(domain, operation, "test_actor")
                assert allowed, f"Core domain {domain} should always allow {operation}"


class TestViolationLogging:
    """Test that violations are properly logged and tracked."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_violation_logging(self, priority_manager):
        """Test that priority violations are logged."""
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Generate a violation
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_actor")
        assert not allowed
        
        # Check that violation was logged
        violations = priority_manager.get_priority_violations(10)
        assert len(violations) > 0, "Violation should be logged"
        
        # Check violation structure
        latest_violation = violations[0]
        assert latest_violation["domain"] == "execution"
        assert latest_violation["operation"] == "execute"
        assert latest_violation["actor_id"] == "test_actor"
        assert latest_violation["severity"] in ["error", "warning"]
    
    def test_violation_clearing(self, priority_manager):
        """Test that violations can be cleared."""
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Generate a violation
        priority_manager.check_domain_access("execution", "execute", "test_actor")
        
        # Clear violations
        priority_manager.clear_violations()
        
        # Check that violations are cleared
        violations = priority_manager.get_priority_violations(10)
        assert len(violations) == 0, "Violations should be cleared"


class TestSafetyChecks:
    """Test safety check functionality."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_safety_checks_pass(self, priority_manager):
        """Test that safety checks pass when system is healthy."""
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Run safety checks
        results = priority_manager._run_safety_checks()
        
        # All checks should pass initially
        assert all(results.values()), "All safety checks should pass initially"
    
    def test_safety_checks_detect_violations(self, priority_manager):
        """Test that safety checks detect priority violations."""
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Generate violations
        priority_manager.check_domain_access("execution", "execute", "test_actor")
        priority_manager.check_domain_access("governance", "write", "test_actor")
        
        # Run safety checks
        results = priority_manager._run_safety_checks()
        
        # Should detect priority violations
        assert not results["priority_violations"], "Safety checks should detect priority violations"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
