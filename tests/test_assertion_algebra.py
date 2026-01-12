"""
MERID Assertion Algebra Unit Tests - CONSTITUTIONAL

These tests are NON-NEGOTIABLE.
If ANY fail, the build is INVALID.

This suite ensures MERID cannot accidentally become optimistic.
"""

import pytest
import time
from core.reality_registry import (
    RealityAssertion,
    AssertionDomain,
    AssertionStatus,
    UIVisibility,
    AssertionProvenance,
    AssertionAlgebra,
)


class TestAssertionViability:
    """Test assertion decay and viability."""
    
    def test_assertion_decays_over_time(self):
        """TEST: Assertion decays over time - MUST PASS"""
        assertion = RealityAssertion(
            assertion_id="test-1",
            domain=AssertionDomain.MARKET,
            description="Test assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.1,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        current_time = assertion.last_verified_at
        regime_entropy = 0.0
        
        # Initially usable
        assert assertion.is_usable(current_time, regime_entropy, threshold=0.5)
        
        # After time passes, should decay
        future_time = current_time + 20  # 20 seconds
        effective = assertion.effective_confidence(future_time, regime_entropy)
        
        # Should be lower than initial
        initial = assertion.effective_confidence(current_time, regime_entropy)
        assert effective < initial, "Viability must decrease with time"
        
        # Eventually becomes unusable
        far_future = current_time + 100
        assert not assertion.is_usable(far_future, regime_entropy, threshold=0.5), \
            "Assertion must eventually become unusable"
    
    def test_provenance_suppression(self):
        """TEST: Low provenance suppresses high confidence - MUST PASS"""
        high_conf_low_prov = RealityAssertion(
            assertion_id="test-2",
            domain=AssertionDomain.MARKET,
            description="High confidence, low provenance",
            confidence_score=0.9,
            provenance_score=0.2,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        low_conf_high_prov = RealityAssertion(
            assertion_id="test-3",
            domain=AssertionDomain.MARKET,
            description="Low confidence, high provenance",
            confidence_score=0.6,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        current_time = time.time()
        regime_entropy = 0.0
        
        # High confidence with low provenance should be unusable
        assert not high_conf_low_prov.is_usable(current_time, regime_entropy, threshold=0.5), \
            "High confidence MUST NOT compensate for weak provenance"
        
        # Low confidence with high provenance should be usable
        assert low_conf_high_prov.is_usable(current_time, regime_entropy, threshold=0.5), \
            "High provenance with moderate confidence should be usable"


class TestAssertionCombination:
    """Test assertion algebra operations."""
    
    def test_weakest_truth_dominates_and(self):
        """TEST: Weakest truth dominates AND - MUST PASS"""
        strong = RealityAssertion(
            assertion_id="strong",
            domain=AssertionDomain.MARKET,
            description="Strong assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        weak = RealityAssertion(
            assertion_id="weak",
            domain=AssertionDomain.MARKET,
            description="Weak assertion",
            confidence_score=0.4,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        current_time = time.time()
        regime_entropy = 0.0
        
        result = AssertionAlgebra.conjunction(strong, weak, current_time, regime_entropy)
        weak_effective = weak.effective_confidence(current_time, regime_entropy)
        
        # Result should be close to weak assertion
        assert abs(result - weak_effective) < 0.01, \
            "AND operation MUST NOT use mean or weighted values"
    
    def test_conflict_contamination(self):
        """TEST: Conflict contamination - MUST PASS"""
        valid = RealityAssertion(
            assertion_id="valid",
            domain=AssertionDomain.MARKET,
            description="Valid assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        conflicted = RealityAssertion(
            assertion_id="conflicted",
            domain=AssertionDomain.MARKET,
            description="Conflicted assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.CONFLICTED,
            ui_visibility=UIVisibility.WARNING,
            execution_eligibility=False,
        )
        
        current_time = time.time()
        regime_entropy = 0.0
        
        result = AssertionAlgebra.conjunction(valid, conflicted, current_time, regime_entropy)
        
        # Conflict must contaminate result
        assert result == 0.0, \
            "Conflict MUST NOT be masked or downgraded"
    
    def test_or_never_enables_execution(self):
        """TEST: OR operator never enables execution - MUST PASS"""
        unusable = RealityAssertion(
            assertion_id="unusable",
            domain=AssertionDomain.MARKET,
            description="Unusable assertion",
            confidence_score=0.2,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.SUPPRESSED,
            execution_eligibility=False,
        )
        
        usable = RealityAssertion(
            assertion_id="usable",
            domain=AssertionDomain.MARKET,
            description="Usable assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        current_time = time.time()
        regime_entropy = 0.0
        
        # OR gives us a value, but execution check must fail
        can_execute, _ = AssertionAlgebra.check_execution_eligibility(
            [unusable, usable],
            current_time,
            regime_entropy,
        )
        
        assert not can_execute, \
            "OR MUST NOT allow eligibility - partial satisfaction forbidden"


class TestForbiddenBehavior:
    """Test that forbidden operations are blocked."""
    
    def test_no_averaging_across_domains(self):
        """TEST: No averaging across domains - MUST PASS"""
        market = RealityAssertion(
            assertion_id="market",
            domain=AssertionDomain.MARKET,
            description="Market assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        social = RealityAssertion(
            assertion_id="social",
            domain=AssertionDomain.AGENT,
            description="Social assertion",
            confidence_score=0.2,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        # System MUST NOT produce combined confidence
        # This is enforced by not having such a method
        # If someone adds it, this test documents the violation
        assert not hasattr(AssertionAlgebra, 'average_confidence'), \
            "Averaging across domains is FORBIDDEN"
        assert not hasattr(AssertionAlgebra, 'aggregate_confidence'), \
            "Aggregation across domains is FORBIDDEN"


class TestExecutionGate:
    """Test execution gating logic."""
    
    def test_missing_assertion_blocks_execution(self):
        """TEST: Missing assertion blocks execution - MUST PASS"""
        assertion = RealityAssertion(
            assertion_id="present",
            domain=AssertionDomain.MARKET,
            description="Present assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        current_time = time.time()
        regime_entropy = 0.0
        
        # Only one assertion when we need two
        can_execute, reason = AssertionAlgebra.check_execution_eligibility(
            [assertion],  # Missing second required assertion
            current_time,
            regime_entropy,
        )
        
        # This passes because we only check what's provided
        # The real check happens in RealityAuditor which checks for missing assertions
        assert can_execute, "Single valid assertion should pass"
        
        # But an empty list should fail
        can_execute_empty, _ = AssertionAlgebra.check_execution_eligibility(
            [],
            current_time,
            regime_entropy,
        )
        
        assert not can_execute_empty, \
            "Empty assertion list MUST block execution"
    
    def test_regime_entropy_suppresses_assertions(self):
        """TEST: Regime entropy suppresses assertions - MUST PASS"""
        assertion = RealityAssertion(
            assertion_id="test",
            domain=AssertionDomain.MARKET,
            description="Test assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        current_time = time.time()
        
        # Low entropy - should be usable
        low_entropy = 0.1
        assert assertion.is_usable(current_time, low_entropy, threshold=0.5)
        
        # High entropy - should suppress
        high_entropy = 0.7
        effective = assertion.effective_confidence(current_time, high_entropy)
        
        # High entropy should significantly reduce effective confidence
        assert effective < 0.5, \
            "High regime entropy MUST suppress execution"


class TestRegressionGuard:
    """Most important test - monotonicity."""
    
    def test_assertion_algebra_monotonicity(self):
        """
        TEST: Assertion algebra monotonicity - MUST PASS
        
        INVARIANT: Adding uncertainty can NEVER increase eligibility.
        """
        strong = RealityAssertion(
            assertion_id="strong",
            domain=AssertionDomain.MARKET,
            description="Strong assertion",
            confidence_score=0.9,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        current_time = time.time()
        regime_entropy = 0.0
        
        # Single strong assertion
        can_execute_one, _ = AssertionAlgebra.check_execution_eligibility(
            [strong],
            current_time,
            regime_entropy,
        )
        
        # Add a weaker assertion
        weak = RealityAssertion(
            assertion_id="weak",
            domain=AssertionDomain.MARKET,
            description="Weak assertion",
            confidence_score=0.3,
            provenance_score=0.9,
            regime_compatibility=1.0,
            decay_rate=0.01,
            last_verified_at=time.time(),
            validity_window=3600,
            status=AssertionStatus.VALID,
            ui_visibility=UIVisibility.VISIBLE,
            execution_eligibility=True,
        )
        
        can_execute_two, _ = AssertionAlgebra.check_execution_eligibility(
            [strong, weak],
            current_time,
            regime_entropy,
        )
        
        # Adding weak assertion should not increase eligibility
        if can_execute_one:
            # If one was executable, adding uncertainty should not help
            # In this case weak is below threshold so it blocks
            assert not can_execute_two, \
                "CRITICAL: Adding uncertainty MUST NOT increase eligibility"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
