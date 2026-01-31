"""
Tests for security fixes implemented in audit remediation.

Validates:
- Credential loading from environment variables
- Safe expression evaluation in compliance checker
- No hardcoded secrets
"""

import logging
import os
import sys

import pytest
from unittest.mock import patch, MagicMock

# Mock Neo4j to avoid connection requirement
sys.modules['neo4j'] = MagicMock()
sys.modules['db.neo4j'] = MagicMock()

from core.xstocks_adapters import TokenizedEquityAdapter
from notifications.channels import EmailChannel
from security.automated_compliance_checker import AutomatedComplianceChecker, ComplianceRule


class TestCredentialSecurity:
    """Test credential security improvements."""
    
    def test_tokenized_equity_loads_from_env(self):
        """Test TokenizedEquityAdapter loads credentials from environment."""
        with patch.dict(os.environ, {
            'TOKENIZED_EQUITY_API_KEY': 'test_key_123',
            'TOKENIZED_EQUITY_API_BASE': 'https://test.api.com'
        }):
            adapter = TokenizedEquityAdapter()
            assert adapter._api_key == 'test_key_123'
            assert adapter._api_base == 'https://test.api.com'
    
    def test_tokenized_equity_warns_on_missing_key(self, caplog):
        """Test warning when API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            logger = logging.getLogger("core.xstocks_adapters")
            original_propagate = logger.propagate
            logger.propagate = True
            try:
                with caplog.at_level("WARNING", logger="core.xstocks_adapters"):
                    adapter = TokenizedEquityAdapter()
                    assert adapter._api_key == ''
                    assert 'TOKENIZED_EQUITY_API_KEY not set' in caplog.text
            finally:
                logger.propagate = original_propagate
    
    def test_email_channel_loads_from_env(self):
        """Test EmailChannel loads SMTP credentials from environment."""
        with patch.dict(os.environ, {
            'SMTP_HOST': 'smtp.test.com',
            'SMTP_PORT': '465',
            'SMTP_USER': 'test@test.com',
            'SMTP_PASSWORD': 'test_pass',
            'SMTP_FROM_ADDRESS': 'noreply@test.com',
            'SMTP_USE_TLS': 'false'
        }):
            channel = EmailChannel()
            assert channel.smtp_host == 'smtp.test.com'
            assert channel.smtp_port == 465
            assert channel.smtp_user == 'test@test.com'
            assert channel.smtp_password == 'test_pass'
            assert channel.from_address == 'noreply@test.com'
            assert channel.use_tls is False
    
    def test_email_channel_warns_on_missing_config(self, caplog):
        """Test warning when SMTP config is missing."""
        with patch.dict(os.environ, {}, clear=True):
            logger = logging.getLogger("notifications.channels")
            original_propagate = logger.propagate
            logger.propagate = True
            try:
                with caplog.at_level("WARNING", logger="notifications.channels"):
                    channel = EmailChannel()
                    assert 'SMTP credentials not configured' in caplog.text
            finally:
                logger.propagate = original_propagate


class TestSafeComplianceEvaluation:
    """Test safe compliance rule evaluation without eval()."""
    
    def test_safe_evaluate_simple_comparison(self):
        """Test safe evaluation of simple comparison."""
        checker = AutomatedComplianceChecker()
        rule = ComplianceRule(
            rule_id="test_1",
            expression="payload['amount'] > 1000",
            severity="high",
            description="Test rule"
        )
        checker.register_rule(rule)
        
        findings = checker.evaluate({"amount": 1500})
        assert len(findings) == 1
        assert findings[0]["rule_id"] == "test_1"
        
        findings = checker.evaluate({"amount": 500})
        assert len(findings) == 0
    
    def test_safe_evaluate_equality(self):
        """Test safe evaluation of equality check."""
        checker = AutomatedComplianceChecker()
        rule = ComplianceRule(
            rule_id="test_2",
            expression="payload['status'] == 'active'",
            severity="medium",
            description="Status check"
        )
        checker.register_rule(rule)
        
        findings = checker.evaluate({"status": "active"})
        assert len(findings) == 1
        
        findings = checker.evaluate({"status": "inactive"})
        assert len(findings) == 0
    
    def test_safe_evaluate_boolean_logic(self):
        """Test safe evaluation of boolean logic."""
        checker = AutomatedComplianceChecker()
        rule = ComplianceRule(
            rule_id="test_3",
            expression="payload['amount'] > 1000 and payload['status'] == 'pending'",
            severity="high",
            description="Combined check"
        )
        checker.register_rule(rule)
        
        findings = checker.evaluate({"amount": 1500, "status": "pending"})
        assert len(findings) == 1
        
        findings = checker.evaluate({"amount": 1500, "status": "active"})
        assert len(findings) == 0
        
        findings = checker.evaluate({"amount": 500, "status": "pending"})
        assert len(findings) == 0
    
    def test_safe_evaluate_in_operator(self):
        """Test safe evaluation of 'in' operator."""
        checker = AutomatedComplianceChecker()
        rule = ComplianceRule(
            rule_id="test_4",
            expression="payload['country'] in ['US', 'UK', 'EU']",
            severity="medium",
            description="Country check"
        )
        checker.register_rule(rule)
        
        findings = checker.evaluate({"country": "US"})
        assert len(findings) == 1
        
        findings = checker.evaluate({"country": "CN"})
        assert len(findings) == 0
    
    def test_safe_evaluate_rejects_unsafe_operations(self):
        """Test that unsafe operations are rejected."""
        checker = AutomatedComplianceChecker()
        
        # These should fail gracefully without executing dangerous code
        unsafe_expressions = [
            "__import__('os').system('ls')",
            "eval('1+1')",
            "exec('print(1)')",
        ]
        
        for expr in unsafe_expressions:
            rule = ComplianceRule(
                rule_id=f"unsafe_{expr[:10]}",
                expression=expr,
                severity="high",
                description="Unsafe rule"
            )
            checker.register_rule(rule)
        
        # Should not crash, should return empty findings
        findings = checker.evaluate({"test": "value"})
        assert len(findings) == 0
    
    def test_safe_evaluate_handles_missing_keys(self):
        """Test safe handling of missing payload keys."""
        checker = AutomatedComplianceChecker()
        rule = ComplianceRule(
            rule_id="test_5",
            expression="payload['nonexistent'] > 100",
            severity="low",
            description="Missing key test"
        )
        checker.register_rule(rule)
        
        # Should not crash on missing key
        findings = checker.evaluate({"other_key": 50})
        assert len(findings) == 0
    
    def test_safe_evaluate_not_operator(self):
        """Test safe evaluation of 'not' operator."""
        checker = AutomatedComplianceChecker()
        rule = ComplianceRule(
            rule_id="test_6",
            expression="not payload['approved']",
            severity="medium",
            description="Not approved check"
        )
        checker.register_rule(rule)
        
        findings = checker.evaluate({"approved": False})
        assert len(findings) == 1
        
        findings = checker.evaluate({"approved": True})
        assert len(findings) == 0


class TestNoHardcodedSecrets:
    """Test that no secrets are hardcoded."""
    
    def test_no_hardcoded_api_keys_in_adapters(self):
        """Verify no hardcoded API keys in adapters."""
        with patch.dict(os.environ, {}, clear=True):
            adapter = TokenizedEquityAdapter()
            # Should be empty string, not a real key
            assert adapter._api_key == ''
            assert not adapter._api_key or len(adapter._api_key) < 10
    
    def test_no_hardcoded_smtp_credentials(self):
        """Verify no hardcoded SMTP credentials."""
        with patch.dict(os.environ, {}, clear=True):
            channel = EmailChannel()
            # Should be empty strings, not real credentials
            assert channel.smtp_host == ''
            assert channel.smtp_user == ''
            assert channel.smtp_password == ''


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
