"""Tests for security.automated_compliance_checker sandbox behavior."""

from __future__ import annotations

import pytest

import security.automated_compliance_checker as compliance_module
from security.automated_compliance_checker import AutomatedComplianceChecker, ComplianceRule


class LoggerStub:
    def __init__(self) -> None:
        self.errors = []

    def error(self, message: str) -> None:  # pragma: no cover - minimal stub
        self.errors.append(message)


@pytest.fixture
def checker(monkeypatch):
    logger_stub = LoggerStub()
    monkeypatch.setattr(compliance_module, "logger", logger_stub, raising=False)
    return AutomatedComplianceChecker(), logger_stub


def test_malicious_expressions_rejected_by_sandbox(checker):
    compliance_checker, logger_stub = checker
    compliance_checker.register_rule(
        ComplianceRule(
            rule_id="malicious",
            description="attempt to escape sandbox",
            severity="critical",
            expression="__import__('os').system('rm -rf /')",
        )
    )

    findings = compliance_checker.evaluate({})

    assert findings == []
    assert any("__import__" in msg for msg in logger_stub.errors)


def test_complex_rule_combinations_evaluate_correctly(checker):
    compliance_checker, _ = checker
    compliance_checker.register_rule(
        ComplianceRule(
            rule_id="combo",
            description="exposure and geography check",
            severity="high",
            expression="(payload['exposure'] > 100 and payload['region'] in ['US', 'EU']) or payload['tier'] == 'critical'",
        )
    )

    payload = {"exposure": 120, "region": "US", "tier": "normal"}
    findings = compliance_checker.evaluate(payload)
    assert len(findings) == 1

    payload = {"exposure": 50, "region": "APAC", "tier": "critical"}
    findings = compliance_checker.evaluate(payload)
    assert len(findings) == 1

    payload = {"exposure": 20, "region": "APAC", "tier": "normal"}
    findings = compliance_checker.evaluate(payload)
    assert findings == []


def test_error_reporting_preserves_rule_metadata(monkeypatch, checker):
    compliance_checker, logger_stub = checker

    def boom(self, expression, payload):
        raise RuntimeError("sandbox unavailable")

    monkeypatch.setattr(AutomatedComplianceChecker, "_safe_evaluate", boom)

    compliance_checker.register_rule(
        ComplianceRule(
            rule_id="rule_error",
            description="broken rule",
            severity="medium",
            expression="payload['amount'] > 0",
        )
    )

    findings = compliance_checker.evaluate({"amount": 10})

    assert findings == []
    assert any("rule_error" in msg for msg in logger_stub.errors)
