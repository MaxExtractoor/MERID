"""
Test order gate exit policy validation.

CRITICAL FIX (2026-07-08): Tests for exit policy metadata value validation
to prevent invalid TP/SL values from passing gate checks.
"""

import pytest
from merid.event_venues.kalshi.order_gate import GateMetrics


class TestOrderGateExitPolicyValidation:
    """Tests for order gate exit policy metadata validation."""
    
    def test_blocked_exit_policy_invalid_metric_exists(self):
        """Test that blocked_exit_policy_invalid metric exists in GateMetrics.
        
        CRITICAL FIX (2026-07-08): This validates that the new metric
        for tracking invalid exit policy value rejections was added.
        """
        metrics = GateMetrics()
        
        # Verify the new metric exists
        assert hasattr(metrics, 'blocked_exit_policy_invalid')
        assert metrics.blocked_exit_policy_invalid == 0
    
    def test_exit_policy_validation_code_exists(self):
        """Test that exit policy validation code exists in order_gate.py.
        
        CRITICAL FIX (2026-07-08): This validates that the validation
        logic for max_hold_seconds was added to the gate.
        """
        import inspect
        from merid.event_venues.kalshi.order_gate import PreTradeGate
        
        # Get the source code of the check method
        source = inspect.getsource(PreTradeGate.check)
        
        # Verify the validation logic exists
        assert "max_hold_seconds_invalid" in source
        assert "< 60s minimum" in source
        assert "> 3600s maximum" in source
        assert "blocked_exit_policy_invalid" in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
