"""Tests for swarm.contract_scanner."""

from __future__ import annotations

from datetime import datetime

import pytest

from swarm import contract_scanner as cs


@pytest.fixture()
def scanner():
    # Fresh scanner per test to avoid global state interference.
    return cs.ContractExploitScanner()


def test_register_exploit_pattern(scanner):
    pattern = scanner.register_exploit_pattern(
        pattern_id="custom_pattern",
        pattern_name="Custom",
        exploit_type=cs.ExploitType.BACKDOOR,
        severity=cs.ExploitSeverity.HIGH,
        function_signatures=["function custom()"],
        auto_block=False,
    )

    assert scanner._exploit_patterns["custom_pattern"] is pattern
    assert pattern.auto_block is False


def test_scan_unverified_requires_governance(scanner):
    analysis = scanner.scan_contract(
        contract_address="0xdeadbeef",
        is_verified=False,
        audit_completed=False,
    )

    assert analysis.contract_address == "0xdeadbeef"
    assert any(e.exploit_type is cs.ExploitType.UNVERIFIED_CODE for e in analysis.exploits)
    assert analysis.requires_governance_approval is True
    assert analysis.approved_for_use is False
    assert analysis.risk_score == pytest.approx(0.8, rel=1e-3)


def test_scan_contract_detects_blocked_pattern(scanner):
    source_code = """
    contract Evil {
        function emergencyWithdraw() external {}
    }
    """
    analysis = scanner.scan_contract(
        contract_address="0x123",
        contract_name="Evil",
        source_code=source_code,
        is_verified=True,
        audit_completed=True,
    )

    exploits = {exploit.exploit_type for exploit in analysis.exploits}
    assert cs.ExploitType.BACKDOOR in exploits
    assert analysis.approved_for_use is False
    assert "0x123" in scanner.get_blocked_contracts()
    assert scanner.is_contract_safe("0x123") is False


def test_approve_contract_overrides_block(scanner):
    scanner.block_contract("0xabc", reason="manual block")
    assert scanner.is_contract_safe("0xabc") is False

    scanner.approve_contract("0xabc", governance_approved=True)
    assert scanner.is_contract_safe("0xabc") is True


def test_block_contract_updates_sets(scanner):
    scanner.approve_contract("0xbeef", governance_approved=True)
    assert scanner.is_contract_safe("0xbeef") is True

    scanner.block_contract("0xbeef", reason="issue")
    assert "0xbeef" in scanner.get_blocked_contracts()
    assert scanner.is_contract_safe("0xbeef") is False


def test_get_contract_analysis_returns_cached(scanner):
    scanner.scan_contract("0x999", source_code="contract A {}", is_verified=True, audit_completed=True)
    first = scanner.get_contract_analysis("0x999")

    # Second scan should return cached object
    second = scanner.scan_contract("0x999")
    assert first is second


def test_global_scanner_singleton():
    first = cs.get_contract_exploit_scanner()
    second = cs.get_contract_exploit_scanner()
    assert first is second
