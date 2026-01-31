"""
Unit Tests for Domain Priority Conflict Resolution.

Tests deterministic conflict resolution when multiple rules or callers disagree.
Implements precedence order: global_safety > domain_priority > caller_role > default.
"""

import pytest
from typing import Dict, List, Tuple, Any
from enum import Enum

from core.domain_priority_manager import DomainPriorityManager, get_domain_priority_manager
from core.reality_auditor import AuditorMode


class CallerKind(Enum):
    """Types of callers for conflict resolution testing."""
    AGENT = "agent"
    HUMAN = "human"
    SYSTEM_MAINTENANCE = "system_maintenance"
    SAFETY_OVERRIDE = "safety_override"
    GOVERNANCE = "governance"
    RISK_MANAGER = "risk_manager"


class TestConflictResolutionPrecedence:
    """Test that conflict resolution follows the correct precedence order."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    @pytest.mark.parametrize("domain,operation,caller_kind,mode,expected_decision", [
        # Global safety override always wins
        ("execution", "execute", CallerKind.AGENT, "SIGHTED_DEGRADED", "BLOCK"),
        ("execution", "execute", CallerKind.SAFETY_OVERRIDE, "SIGHTED_DEGRADED", "ALLOW"),
        ("treasury", "transfer", CallerKind.SAFETY_OVERRIDE, "SIGHTED_DEGRADED", "ALLOW"),
        
        # Domain priority wins over caller role
        ("execution", "execute", CallerKind.HUMAN, "SIGHTED_DEGRADED", "BLOCK"),
        ("execution", "execute", CallerKind.SYSTEM_MAINTENANCE, "SIGHTED_DEGRADED", "BLOCK"),
        ("execution", "execute", CallerKind.GOVERNANCE, "SIGHTED_DEGRADED", "BLOCK"),
        
        # Core domains allow read operations regardless of caller
        ("market", "read", CallerKind.AGENT, "SIGHTED_DEGRADED", "ALLOW"),
        ("market", "read", CallerKind.HUMAN, "SIGHTED_DEGRADED", "ALLOW"),
        ("onchain", "read", CallerKind.SYSTEM_MAINTENANCE, "SIGHTED_DEGRADED", "ALLOW"),
        
        # Simulation allows write for trusted callers
        ("simulation", "write", CallerKind.HUMAN, "SIGHTED_DEGRADED", "ALLOW"),
        ("simulation", "write", CallerKind.RISK_MANAGER, "SIGHTED_DEGRADED", "ALLOW"),
        ("simulation", "execute", CallerKind.AGENT, "SIGHTED_DEGRADED", "ALLOW"),
        
        # Agent domain allows proposals but not execution
        ("agent", "propose", CallerKind.AGENT, "SIGHTED_DEGRADED", "ALLOW"),
        ("agent", "propose", CallerKind.HUMAN, "SIGHTED_DEGRADED", "ALLOW"),
        ("agent", "execute", CallerKind.AGENT, "SIGHTED_DEGRADED", "BLOCK"),
        ("agent", "execute", CallerKind.SYSTEM_MAINTENANCE, "SIGHTED_DEGRADED", "BLOCK"),
        
        # Blocked domains remain blocked even for privileged callers
        ("governance", "write", CallerKind.GOVERNANCE, "SIGHTED_DEGRADED", "BLOCK"),
        ("governance", "read", CallerKind.SAFETY_OVERRIDE, "SIGHTED_DEGRADED", "ALLOW"),
        ("treasury", "transfer", CallerKind.HUMAN, "SIGHTED_DEGRADED", "BLOCK"),
        ("treasury", "transfer", CallerKind.SAFETY_OVERRIDE, "SIGHTED_DEGRADED", "ALLOW"),
    ])
    def test_precedence_order(self, priority_manager, domain, operation, caller_kind, mode, expected_decision):
        """Test that conflict resolution follows precedence order."""
        
        priority_manager.set_mode(mode)
        
        # Simulate caller role and priority hints
        context = {
            "caller_kind": caller_kind.value,
            "priority_hint": "high" if caller_kind in [CallerKind.SAFETY_OVERRIDE, CallerKind.GOVERNANCE] else "normal"
        }
        
        # Check access with context
        allowed, reason = priority_manager.check_domain_access(
            domain, operation, f"test_{caller_kind.value}", context
        )
        
        decision = "ALLOW" if allowed else "BLOCK"
        assert decision == expected_decision, f"Expected {expected_decision} for {domain}.{operation} by {caller_kind.value} in {mode}, got {decision}"
    
    def test_global_safety_override_wins(self, priority_manager):
        """Test that global safety override always wins over domain rules."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Even with safety override, some operations should still be blocked
        test_cases = [
            ("execution", "execute", CallerKind.SAFETY_OVERRIDE, "ALLOW"),  # Safety override allows
            ("treasury", "transfer", CallerKind.SAFETY_OVERRIDE, "ALLOW"),  # Safety override allows
            ("system", "config", CallerKind.SAFETY_OVERRIDE, "ALLOW"),  # Safety override allows
        ]
        
        for domain, operation, caller_kind, expected in test_cases:
            context = {"caller_kind": caller_kind.value, "priority_hint": "safety_override"}
            allowed, reason = priority_manager.check_domain_access(domain, operation, f"test_{caller_kind.value}", context)
            
            decision = "ALLOW" if allowed else "BLOCK"
            assert decision == expected, f"Safety override should {expected} {domain}.{operation}"
    
    def test_domain_priority_over_caller_role(self, priority_manager):
        """Test that domain priority wins over caller role."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Even privileged callers should be blocked by domain rules
        test_cases = [
            ("execution", "execute", CallerKind.GOVERNANCE, "BLOCK"),
            ("execution", "execute", CallerKind.RISK_MANAGER, "BLOCK"),
            ("treasury", "transfer", CallerKind.HUMAN, "BLOCK"),
            ("governance", "write", CallerKind.GOVERNANCE, "BLOCK"),
        ]
        
        for domain, operation, caller_kind, expected in test_cases:
            context = {"caller_kind": caller_kind.value, "priority_hint": "high"}
            allowed, reason = priority_manager.check_domain_access(domain, operation, f"test_{caller_kind.value}", context)
            
            decision = "ALLOW" if allowed else "BLOCK"
            assert decision == expected, f"Domain priority should {expected} {domain}.{operation} for {caller_kind.value}"
    
    def test_conflicting_rules_resolution(self, priority_manager):
        """Test resolution when rules conflict."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Scenario: caller has high priority hint but domain is blocked
        context = {
            "caller_kind": CallerKind.HUMAN.value,
            "priority_hint": "high",  # Caller claims high priority
            "justification": "urgent_maintenance"
        }
        
        # Domain rule should win
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_human", context)
        assert not allowed, "Domain rule should win over caller priority hint"
        assert "priority" in reason.lower() or "blocked" in reason.lower()
    
    def test_idempotency(self, priority_manager):
        """Test that repeated evaluations yield the same decision."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        test_cases = [
            ("market", "read", CallerKind.AGENT),
            ("execution", "execute", CallerKind.HUMAN),
            ("simulation", "write", CallerKind.RISK_MANAGER),
            ("agent", "propose", CallerKind.GOVERNANCE),
        ]
        
        for domain, operation, caller_kind in test_cases:
            context = {"caller_kind": caller_kind.value}
            
            # Evaluate multiple times
            results = []
            for i in range(5):
                allowed, reason = priority_manager.check_domain_access(domain, operation, f"test_{caller_kind.value}_{i}", context)
                results.append(allowed)
            
            # All results should be identical
            assert all(r == results[0] for r in results), f"Results for {domain}.{operation} should be idempotent"


class TestConflictResolutionMatrix:
    """Table-driven tests for comprehensive conflict resolution."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_comprehensive_conflict_matrix(self, priority_manager):
        """Comprehensive table-driven test for conflict resolution."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Test matrix: (domain, operation, caller_kind) -> expected decision
        test_matrix = [
            # Core domains - read allowed for all callers
            ("market", "read", CallerKind.AGENT, "ALLOW"),
            ("market", "read", CallerKind.HUMAN, "ALLOW"),
            ("market", "read", CallerKind.SYSTEM_MAINTENANCE, "ALLOW"),
            ("market", "read", CallerKind.GOVERNANCE, "ALLOW"),
            ("market", "read", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            
            ("onchain", "read", CallerKind.AGENT, "ALLOW"),
            ("onchain", "read", CallerKind.HUMAN, "ALLOW"),
            ("onchain", "read", CallerKind.SYSTEM_MAINTENANCE, "ALLOW"),
            ("onchain", "read", CallerKind.GOVERNANCE, "ALLOW"),
            ("onchain", "read", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            
            # Core domains - write blocked for all callers
            ("market", "write", CallerKind.AGENT, "BLOCK"),
            ("market", "write", CallerKind.HUMAN, "BLOCK"),
            ("market", "write", CallerKind.SYSTEM_MAINTENANCE, "BLOCK"),
            ("market", "write", CallerKind.GOVERNANCE, "BLOCK"),
            ("market", "write", CallerKind.SAFETY_OVERRIDE, "BLOCK"),
            
            ("onchain", "write", CallerKind.AGENT, "BLOCK"),
            ("onchain", "write", CallerKind.HUMAN, "BLOCK"),
            ("onchain", "write", CallerKind.SYSTEM_MAINTENANCE, "BLOCK"),
            ("onchain", "write", CallerKind.GOVERNANCE, "BLOCK"),
            ("onchain", "write", CallerKind.SAFETY_OVERRIDE, "BLOCK"),
            
            # Simulation - write allowed for trusted callers
            ("simulation", "write", CallerKind.HUMAN, "ALLOW"),
            ("simulation", "write", CallerKind.RISK_MANAGER, "ALLOW"),
            ("simulation", "write", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            ("simulation", "write", CallerKind.AGENT, "ALLOW"),
            ("simulation", "write", CallerKind.SYSTEM_MAINTENANCE, "ALLOW"),
            
            # Agent domain - proposals allowed, execution blocked
            ("agent", "propose", CallerKind.AGENT, "ALLOW"),
            ("agent", "propose", CallerKind.HUMAN, "ALLOW"),
            ("agent", "propose", CallerKind.GOVERNANCE, "ALLOW"),
            ("agent", "propose", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            
            ("agent", "execute", CallerKind.AGENT, "BLOCK"),
            ("agent", "execute", CallerKind.HUMAN, "BLOCK"),
            ("agent", "execute", CallerKind.GOVERNANCE, "BLOCK"),
            ("agent", "execute", CallerKind.SAFETY_OVERRIDE, "ALLOW"),  # Safety override allows
            
            # Blocked domains - all operations blocked unless safety override
            ("execution", "read", CallerKind.AGENT, "BLOCK"),
            ("execution", "read", CallerKind.HUMAN, "BLOCK"),
            ("execution", "read", CallerKind.GOVERNANCE, "BLOCK"),
            ("execution", "read", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            
            ("execution", "execute", CallerKind.AGENT, "BLOCK"),
            ("execution", "execute", CallerKind.HUMAN, "BLOCK"),
            ("execution", "execute", CallerKind.GOVERNANCE, "BLOCK"),
            ("execution", "execute", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            
            ("governance", "read", CallerKind.AGENT, "BLOCK"),
            ("governance", "read", CallerKind.HUMAN, "BLOCK"),
            ("governance", "read", CallerKind.GOVERNANCE, "BLOCK"),
            ("governance", "read", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            
            ("treasury", "read", CallerKind.AGENT, "BLOCK"),
            ("treasury", "read", CallerKind.HUMAN, "BLOCK"),
            ("treasury", "read", CallerKind.GOVERNANCE, "BLOCK"),
            ("treasury", "read", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
            
            ("system", "read", CallerKind.AGENT, "BLOCK"),
            ("system", "read", CallerKind.HUMAN, "BLOCK"),
            ("system", "read", CallerKind.GOVERNANCE, "BLOCK"),
            ("system", "read", CallerKind.SAFETY_OVERRIDE, "ALLOW"),
        ]
        
        failed_tests = []
        
        for domain, operation, caller_kind, expected in test_matrix:
            context = {"caller_kind": caller_kind.value}
            
            if caller_kind == CallerKind.SAFETY_OVERRIDE:
                context["priority_hint"] = "safety_override"
            
            allowed, reason = priority_manager.check_domain_access(domain, operation, f"test_{caller_kind.value}", context)
            
            decision = "ALLOW" if allowed else "BLOCK"
            
            if decision != expected:
                failed_tests.append(f"{domain}.{operation} by {caller_kind.value}: expected {expected}, got {decision}")
        
        if failed_tests:
            pytest.fail(f"Conflict resolution matrix tests failed:\n" + "\n".join(failed_tests))
    
    def test_precedence_order_implementation(self, priority_manager):
        """Test that the precedence order is correctly implemented."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Define test case with conflicting rules
        domain = "execution"
        operation = "execute"
        
        # 1. Default: should be blocked
        allowed, reason = priority_manager.check_domain_access(domain, operation, "test_default")
        assert not allowed, "Default should block execution"
        
        # 2. Add caller role (should still be blocked)
        context = {"caller_kind": CallerKind.HUMAN.value}
        allowed, reason = priority_manager.check_domain_access(domain, operation, "test_human", context)
        assert not allowed, "Human caller should still be blocked"
        
        # 3. Add safety override (should be allowed)
        context["priority_hint"] = "safety_override"
        allowed, reason = priority_manager.check_domain_access(domain, operation, "test_safety", context)
        assert allowed, "Safety override should allow execution"
        
        # 4. Remove safety override, should be blocked again
        context = {"caller_kind": CallerKind.HUMAN.value}
        allowed, reason = priority_manager.check_domain_access(domain, operation, "test_human_2", context)
        assert not allowed, "Without safety override should be blocked"


class TestConflictResolutionEdgeCases:
    """Test edge cases and boundary conditions for conflict resolution."""
    
    @pytest.fixture
    def priority_manager(self):
        """Fresh priority manager for each test."""
        return DomainPriorityManager()
    
    def test_unknown_caller_kind(self, priority_manager):
        """Test behavior with unknown caller kinds."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Unknown caller should be treated as normal priority
        context = {"caller_kind": "unknown_caller"}
        allowed, reason = priority_manager.check_domain_access("market", "read", "test_unknown", context)
        
        # Market read should be allowed regardless of caller
        assert allowed, "Unknown caller should be allowed for market read"
        
        # Execution should be blocked regardless of caller
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_unknown", context)
        assert not allowed, "Unknown caller should be blocked for execution"
    
    def test_empty_context(self, priority_manager):
        """Test behavior with empty context."""
        
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        # Empty context should use default behavior
        allowed, reason = priority_manager.check_domain_access("market", "read", "test_empty", {})
        assert allowed, "Empty context should allow market read"
        
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_empty", {})
        assert not allowed, "Empty context should block execution"
    
    def test_mode_aware_conflict_resolution(self, priority_manager):
        """Test that conflict resolution respects system mode."""
        
        # In BLIND mode, priority manager should be inactive
        priority_manager.set_mode("BLIND")
        
        context = {"caller_kind": CallerKind.SAFETY_OVERRIDE.value, "priority_hint": "safety_override"}
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_blind", context)
        
        assert allowed, "In BLIND mode, all operations should be allowed (priority manager inactive)"
        assert "inactive" in reason.lower()
        
        # In SIGHTED_DEGRADED mode, priority manager should be active
        priority_manager.set_mode("SIGHTED_DEGRADED")
        
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_degraded", context)
        assert allowed, "Safety override should allow execution in SIGHTED_DEGRADED"
        
        # Remove safety override
        context = {"caller_kind": CallerKind.HUMAN.value}
        allowed, reason = priority_manager.check_domain_access("execution", "execute", "test_degraded_2", context)
        assert not allowed, "Without safety override, execution should be blocked in SIGHTED_DEGRADED"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
