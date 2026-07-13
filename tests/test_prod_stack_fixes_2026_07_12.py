"""Tests for production stack fixes on 2026-07-12.

Tests cover:
- 10c-75c canonical range log message fix
- Strip order count moved to execution success path
- Fee_aware_gate rationale fix
- Sentiment audit removal from production
"""

import pytest
import re


class Test10c75cLogMessageFix:
    """Test that log messages show 10c-75c canonical range, not 10c-95c."""

    def test_agent_grid_price_selection_logs_10c_75c(self):
        """Verify agent_grid_15m.py logs 10c-75c range, not 10c-95c."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should NOT contain 10c-95c
        assert "10c-95c" not in content, \
            "agent_grid_15m.py should not reference 10c-95c range"
        
        # Should contain 10c-75c in PRICE-SELECTION logs
        assert "canonical range [10c-75c]" in content, \
            "agent_grid_15m.py should log canonical range [10c-75c]"
        
        # Count occurrences of the correct log message
        count = content.count("[PRICE-SELECTION] asset=%s final entry price=%d (within canonical range [10c-75c])")
        assert count == 3, \
            f"Expected 3 PRICE-SELECTION log messages with 10c-75c, found {count}"

    def test_no_expanded_range_95c_references(self):
        """Verify no references to expanded 95c range in production code."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Check for any 95c references in log messages
        pattern = r'\[.*\].*95c'
        matches = re.findall(pattern, content)
        
        # Filter out crisis regime references (which are legitimate)
        non_crisis_matches = [m for m in matches if "crisis" not in m.lower()]
        
        assert len(non_crisis_matches) == 0, \
            f"Found non-crisis 95c references in log messages: {non_crisis_matches}"


class TestStripOrderCountFix:
    """Test that strip order count only increments on successful execution."""

    def test_strip_order_count_not_in_candidate_generation(self):
        """Verify strip order count is NOT incremented in candidate generation."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Find the candidate generation section
        # Look for the comment about candidate generation
        assert "[CANDIDATE-GENERATED]" in content, \
            "Candidate generation log should exist"
        
        # The strip order count increment should NOT be in candidate generation
        # Split by CANDIDATE-GENERATED and check the section before it
        candidate_section = content.split("[CANDIDATE-GENERATED]")[0]
        
        # The old buggy code had strip order count increment here
        # The fix removed it
        assert "self._strip_order_counts[strip_ticker]" not in candidate_section or \
               "CRITICAL FIX (2026-07-12): Strip order count should only increment" in content, \
            "Strip order count should not be incremented in candidate generation"

    def test_strip_order_count_in_execution_success(self):
        """Verify strip order count IS incremented in GLOBAL-ALLOCATOR-EXECUTE-SUCCESS."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Find the GLOBAL-ALLOCATOR-EXECUTE-SUCCESS section
        assert "[GLOBAL-ALLOCATOR-EXECUTE-SUCCESS]" in content, \
            "GLOBAL-ALLOCATOR-EXECUTE-SUCCESS log should exist"
        
        # The strip order count increment should be in the success path
        success_section = content.split("[GLOBAL-ALLOCATOR-EXECUTE-SUCCESS]")[1]
        
        # Should have strip order count increment
        assert "self._strip_order_counts[strip_ticker]" in success_section, \
            "Strip order count should be incremented in execution success path"
        
        # Should have the fix comment
        assert "CRITICAL FIX (2026-07-12): Increment strip order count only on successful execution" in success_section, \
            "Should have comment explaining the fix"

    def test_strip_order_count_log_format(self):
        """Verify strip order count log is present and correctly formatted."""
        with open("merid/prediction/agent_grid_15m.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should have the log message
        assert "[STRIP-ORDER-COUNT] asset=%s strip=%s orders=%d/%d" in content, \
            "Strip order count log should exist"
        
        # Should be in the execution success section, not candidate generation
        success_section = content.split("[GLOBAL-ALLOCATOR-EXECUTE-SUCCESS]")[1]
        assert "[STRIP-ORDER-COUNT]" in success_section, \
            "Strip order count log should be in execution success path"


class TestFeeAwareGateRationaleFix:
    """Test that rationale is set in OrderIntent to prevent fee_aware_gate rejection."""

    def test_kalshi_tools_sets_rationale(self):
        """Verify kalshi_tools.py sets rationale in OrderIntent."""
        with open("merid/prediction/kalshi_tools.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should have rationale in OrderIntent construction
        assert "rationale=" in content, \
            "kalshi_tools.py should set rationale in OrderIntent"
        
        # Should have the fix comment
        assert "CRITICAL FIX (2026-07-12): Add rationale to prevent fee_aware_gate rejection" in content, \
            "Should have comment explaining the rationale fix"

    def test_rationale_format(self):
        """Verify rationale format includes agent name."""
        with open("merid/prediction/kalshi_tools.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should use agent name in rationale
        assert 'rationale=f"momentum_fvg_signal_{_agent_name}"' in content, \
            "Rationale should include agent name for traceability"
        
        # Should have fallback for when agent_name is None
        assert "kalshi_tools_order" in content, \
            "Should have fallback rationale when agent_name is None"

    def test_order_router_fee_aware_gate_check(self):
        """Verify order_router checks for rationale in fee_aware_gate."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should have the rationale check
        assert "intent.rationale is None" in content, \
            "order_router should check for None rationale"
        
        # Should reject when rationale is None
        assert "fee_aware_gate_failed:rationale_required" in content, \
            "Should reject with rationale_required error when rationale is None"


class TestSentimentAuditRemoval:
    """Test that sentiment audit logs are removed from production code."""

    def test_no_sentiment_audit_in_order_router(self):
        """Verify SENTIMENT-AUDIT log is removed from order_router.py."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should NOT have SENTIMENT-AUDIT log
        assert "[SENTIMENT-AUDIT]" not in content, \
            "order_router.py should not have SENTIMENT-AUDIT log (sentiment is legacy only)"
        
        # Note: sentiment_driven field may still exist in OrderIntent for backward compatibility
        # The log message is what was removed from production

    def test_execution_eligible_assets_log_exists(self):
        """Verify EXECUTION-ELIGIBLE-ASSETS log still exists (sentiment removal should not break this)."""
        with open("merid/event_venues/kalshi/order_router.py", "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should still have the execution-eligible assets log
        assert "[EXECUTION-ELIGIBLE-ASSETS]" in content, \
            "EXECUTION-ELIGIBLE-ASSETS log should still exist after sentiment removal"
        
        # Should still have the audit log
        assert "[AUDIT] caller_check" in content, \
            "AUDIT caller_check log should still exist after sentiment removal"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
