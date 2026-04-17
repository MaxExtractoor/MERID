"""Kill Switch Error Audit — Regression tests for BUG-KS1 through BUG-KS5

These tests validate the fixes for the 50 errors/hour kill switch trigger issue.

Bugs Fixed:
- BUG-KS1: Stop-loss escalation unconditionally counted errors without filtering
- BUG-KS2: Missing policy prefixes in should_count_toward_error_threshold
- BUG-KS3: Stop-loss failures didn't distinguish policy vs infrastructure errors
- BUG-KS4: Error deduplication window issues (documented, config-based)
- BUG-KS5: Stop-loss close failures always counted toward error threshold

Test Coverage:
- Stop-loss error classification (policy vs incident)
- Policy prefix matching for all known rejection types
- Gate blocked substring matching
- Integration with risk_controller.record_error()
"""

from __future__ import annotations

import os
import sys
import time
import pytest
from typing import Optional
from unittest.mock import MagicMock, patch

# Ensure merid is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ─────────────────────────────────────────────────────────────────────────────
# Test Data: Policy prefixes that should NOT count toward error threshold
# ─────────────────────────────────────────────────────────────────────────────

POLICY_REJECTION_REASONS = [
    # Market condition rejections (A5 checks)
    ("market_condition:price_too_low:5", False, "A5 price too low"),
    ("market_condition:price_too_high:95", False, "A5 price too high"),
    ("market_condition:spread_too_wide:15", False, "A5 spread too wide"),
    ("market_condition:volume_too_low:100", False, "A5 volume too low"),
    
    # Category and exposure caps
    ("category_cap_exceeded:crypto:1000", False, "Category cap exceeded"),
    ("category_cap_check_error:RuntimeError", False, "Category check error"),
    ("corr_stack_cap_exceeded:500", False, "Correlation stack cap"),
    
    # Execution gate blocks
    ("execution_gate_blocked:kill switch engaged", False, "Gate blocked - kill switch"),
    ("execution_gate_error:connection failed", False, "Execution gate error"),
    ("execution gate blocked:reconciliation pending", False, "Gate blocked - reconciliation"),
    
    # Risk checks
    ("risk_check:daily_loss_limit", False, "Risk check - daily loss"),
    ("risk_check:position_limit", False, "Risk check - position limit"),
    ("pre_validation_failed:insufficient_funds", False, "Pre-validation failed"),
    
    # Order group issues
    ("order_group_not_found:group_123", False, "Order group not found"),
    ("order_group_not_active:group_123:status=expired", False, "Order group not active"),
    ("order_group_limit_exceeded:group_123", False, "Order group limit exceeded"),
    
    # Authorization and leasing
    ("unauthorized_caller:malicious_module", False, "Unauthorized caller"),
    ("lease_conflict:KXBTC-15M:yes", False, "Lease conflict"),
    ("live_requires_async_route_order", False, "Live requires async"),
    
    # Configuration and mode issues
    ("live_not_enabled", False, "Live not enabled"),
    ("kalshi config mismatch", False, "Config mismatch"),
    ("paper/mock=true but using live url", False, "Paper/live URL mismatch"),
    
    # Rate limiting and circuit breakers
    # NOTE: rate_limit is HIGH severity and SHOULD count toward threshold (not exempt)
    ("circuit_breaker_open:kalshi", False, "Circuit breaker open"),
    ("concurrent_order_limit:10", False, "Concurrent order limit"),
    
    # Market not found (expired/delisted)
    ("client error: 404:market not found", False, "404 market not found"),
    ("gate:duplicate:order_exists", False, "Duplicate order"),
    
    # Maintenance and venue issues
    ("maintenance_mode:scheduled", False, "Maintenance mode"),
    ("venue_unavailable:kalshi", False, "Venue unavailable"),
    ("insufficient_margin:50<100", False, "Insufficient margin"),
    ("position_limit_exceeded:100>50", False, "Position limit exceeded"),
]

# Errors that SHOULD count toward threshold (infrastructure/incident grade)
INCIDENT_ERROR_REASONS = [
    ("sanity_check_error:division by zero", True, "Sanity check internal error"),
    ("live_execution_error:connection timeout", True, "Live execution failure"),
    ("routing_exception:network error", True, "Routing exception"),
    ("unknown_error:something bad happened", True, "Unknown error (default to count)"),
    ("auth_error:401 unauthorized", True, "Auth error"),
    ("exchange_error:503 service unavailable", True, "Exchange error"),
    ("timeout:read operation timed out", True, "Timeout error"),
]


class TestOrderErrorThresholdPolicyPrefixes:
    """BUG-KS2: Test that policy prefixes correctly filter expected rejections."""
    
    def test_policy_prefixes_do_not_count(self):
        """All policy rejection reasons should return False (not counted)."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        for reason, should_count, description in POLICY_REJECTION_REASONS:
            result = should_count_toward_error_threshold(reason)
            assert result is False, (
                f"Policy rejection '{description}' (reason='{reason}') should NOT count, "
                f"but got should_count={result}"
            )
    
    def test_incident_errors_do_count(self):
        """Infrastructure/incident errors should return True (counted)."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        for reason, should_count, description in INCIDENT_ERROR_REASONS:
            result = should_count_toward_error_threshold(reason)
            assert result is True, (
                f"Incident error '{description}' (reason='{reason}') SHOULD count, "
                f"but got should_count={result}"
            )
    
    def test_empty_reason_counts(self):
        """Empty reason defaults to counting (fail-safe)."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        assert should_count_toward_error_threshold("") is True
        assert should_count_toward_error_threshold(None) is True
    
    def test_case_insensitive_matching(self):
        """Gate blocked matching is case-insensitive."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        # Various casings should all be blocked
        assert should_count_toward_error_threshold("KILL SWITCH ENGAGED") is False
        assert should_count_toward_error_threshold("Execution Gate Blocked") is False
        assert should_count_toward_error_threshold("Market_Condition:Price_TOO_Low") is False


class TestStopLossErrorClassification:
    """BUG-KS1 & BUG-KS5: Stop-loss failures use should_count_toward_error_threshold."""
    
    @pytest.fixture
    def mock_risk_controller(self):
        """Create a mock risk controller for testing."""
        mock = MagicMock()
        mock.record_error = MagicMock()
        return mock
    
    @pytest.fixture  
    def mock_sl_result(self):
        """Create a mock stop-loss result."""
        mock = MagicMock()
        mock.status = "rejected"
        return mock
    
    def test_stop_loss_policy_rejection_not_counted(self, mock_sl_result):
        """Stop-loss close blocked by execution gate should NOT count."""
        mock_sl_result.reason = "execution_gate_blocked:kill switch engaged"
        
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        result = should_count_toward_error_threshold(mock_sl_result.reason)
        assert result is False, (
            "Stop-loss failure due to kill switch should NOT count toward threshold"
        )
    
    def test_stop_loss_market_condition_not_counted(self, mock_sl_result):
        """Stop-loss close blocked by market conditions should NOT count."""
        mock_sl_result.reason = "market_condition:spread_too_wide:20"
        
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        result = should_count_toward_error_threshold(mock_sl_result.reason)
        assert result is False, (
            "Stop-loss failure due to market conditions should NOT count"
        )
    
    def test_stop_loss_infrastructure_error_counted(self, mock_sl_result):
        """Stop-loss close failing due to infrastructure SHOULD count."""
        mock_sl_result.reason = "live_execution_error:connection timeout"
        
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        result = should_count_toward_error_threshold(mock_sl_result.reason)
        assert result is True, (
            "Stop-loss failure due to infrastructure errors SHOULD count"
        )


class TestGateBlockedSubstrings:
    """BUG-KS2: Gate blocked substring matching covers multi-leg messages."""
    
    def test_multi_leg_message_blocked(self):
        """Multi-leg rejection messages should be detected."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        # Multi-leg format with embedded gate block
        multi_leg = "YES: execution gate blocked: kill switch engaged; NO: some other reason"
        
        result = should_count_toward_error_threshold(multi_leg)
        assert result is False, (
            "Multi-leg message with embedded gate block should NOT count"
        )
    
    def test_various_gate_blocked_formats(self):
        """Different gate blocked formats should all be recognized."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        blocked_reasons = [
            "execution_gate_blocked:reconciliation pending",
            "Execution Gate Blocked: daily loss limit",
            "kill switch is engaged - trading halted",
            "KILL SWITCH ENGAGED",
            "market_condition: price_too_low: 3",
            "spread_too_wide detected",
            "circuit_breaker_open for venue kalshi",
        ]
        
        for reason in blocked_reasons:
            result = should_count_toward_error_threshold(reason)
            assert result is False, f"Reason should be blocked: {reason}"


class TestStripOrderRejectedPrefix:
    """Test prefix stripping for order rejection normalization."""
    
    def test_strip_order_rejected_prefix(self):
        """Order rejected prefix should be stripped."""
        from merid.prediction.order_error_threshold import strip_order_rejected_prefix
        
        assert strip_order_rejected_prefix("Order rejected: live_not_enabled") == "live_not_enabled"
        assert strip_order_rejected_prefix("order rejected: market_condition:price_low") == "market_condition:price_low"
        assert strip_order_rejected_prefix("ORDER REJECTED: risk_check:limit") == "risk_check:limit"
        assert strip_order_rejected_prefix("live_not_enabled") == "live_not_enabled"  # No prefix


class TestIntegrationWithRiskController:
    """Integration tests with risk_controller.record_error()."""
    
    @pytest.fixture
    def temp_kill_switch_file(self, tmp_path):
        """Create a temporary kill switch file."""
        ks_file = tmp_path / "test_kill_switch.json"
        ks_file.write_text('{"active": false, "reason": null, "details": null, "activated_at": null}')
        return str(ks_file)
    
    def test_record_error_called_for_incident(self, temp_kill_switch_file):
        """Incident errors should trigger record_error()."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        from merid.risk.kill_switches import RiskController
        
        # Create controller with temp file
        with patch('merid.risk.kill_switches._KILL_SWITCH_FILE', temp_kill_switch_file):
            controller = RiskController(error_threshold=10)
            
            # Simulate an incident error
            reason = "live_execution_error:connection failed"
            if should_count_toward_error_threshold(reason):
                controller.record_error()
            
            assert controller._error_count >= 1, "Error count should increment for incident"
    
    def test_record_error_not_called_for_policy(self, temp_kill_switch_file):
        """Policy rejections should NOT trigger record_error()."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        from merid.risk.kill_switches import RiskController
        
        with patch('merid.risk.kill_switches._KILL_SWITCH_FILE', temp_kill_switch_file):
            controller = RiskController(error_threshold=10)
            initial_count = controller._error_count
            
            # Simulate a policy rejection
            reason = "execution_gate_blocked:kill switch engaged"
            if should_count_toward_error_threshold(reason):
                controller.record_error()
            
            assert controller._error_count == initial_count, (
                "Error count should NOT increment for policy rejection"
            )


class TestNewPolicyPrefixesCoverage:
    """BUG-KS2: Verify all new policy prefixes are correctly handled."""
    
    def test_all_new_prefixes_return_false(self):
        """All new policy prefixes should return False."""
        from merid.prediction.order_error_threshold import should_count_toward_error_threshold
        
        new_prefixes = [
            ("market_condition:price_too_low:5", "market condition"),
            ("category_cap_check_error:exception", "category cap check error"),
            ("execution_gate_error:failed", "execution gate error"),
            ("execution_gate_blocked:reason", "execution gate blocked"),
            ("unauthorized_caller:test", "unauthorized caller"),
            ("lease_conflict:ticker:side", "lease conflict"),
            ("live_requires_async_route_order", "live requires async"),
            ("insufficient_margin:50<100", "insufficient margin"),
            ("position_limit_exceeded:100>50", "position limit"),
            ("concurrent_order_limit:10", "concurrent order limit"),
            ("circuit_breaker_open:venue", "circuit breaker"),
            ("venue_unavailable:kalshi", "venue unavailable"),
            ("maintenance_mode:scheduled", "maintenance mode"),
            # NOTE: rate_limit is intentionally omitted - it counts toward threshold
        ]
        
        for reason, description in new_prefixes:
            result = should_count_toward_error_threshold(reason)
            assert result is False, (
                f"New prefix '{description}' (reason='{reason}') should NOT count"
            )


# ─────────────────────────────────────────────────────────────────────────────
# Error Budget Integration Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestErrorBudgetIntegration:
    """Test integration with error budget and classification system."""
    
    def test_error_classification_counts_toward_budget(self):
        """Error classification should correctly identify budget-counting errors."""
        from merid.risk.error_classification import classify_error, should_count_error
        
        # Critical errors should count
        classification = classify_error("auth_failed", context="kalshi_api")
        should_count, _ = should_count_error("auth_failed", context="kalshi_api")
        
        assert classification.counts_toward_budget is True
        assert classification.severity.value == "critical"
    
    def test_error_classification_exempt_errors(self):
        """Low severity errors should be exempt from budget."""
        from merid.risk.error_classification import classify_error
        
        # Gate blocked is exempt
        classification = classify_error("gate_blocked", context="execution")
        assert classification.counts_toward_budget is False
        
        # Duplicate order is exempt
        classification = classify_error("duplicate_order", context="order_router")
        assert classification.counts_toward_budget is False


# ─────────────────────────────────────────────────────────────────────────────
# Run tests if executed directly
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
