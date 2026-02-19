"""Tests for Sprint 43 — Status String Constants."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"


# ── 1. Status constants exist ──────────────────────────────────

class TestStatusConstants:
    """Verify domain-specific status constants exist."""

    @pytest.mark.parametrize("const_name", [
        "ARB_STATUS", "COMPLIANCE_STATUS", "PROPOSAL_STATUS", "READINESS_STATUS",
    ])
    def test_constant_exported(self, const_name: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert f"export const {const_name}" in text

    @pytest.mark.parametrize("const_name,values", [
        ("ARB_STATUS", ["LIVE", "FILLED", "SUBMITTED", "FAILED"]),
        ("COMPLIANCE_STATUS", ["ALLOWED", "RESTRICTED", "PROHIBITED"]),
        ("PROPOSAL_STATUS", ["DRAFT", "IN_REVIEW", "APPROVED", "SCHEDULED", "EXECUTING", "EXECUTED"]),
        ("READINESS_STATUS", ["OK", "DRIFTED", "MISSING"]),
    ])
    def test_constant_values(self, const_name: str, values: list):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        for v in values:
            assert f"{v}:" in text, f"Missing {const_name}.{v}"


# ── 2. Files use constants instead of magic strings ────────────

class TestFilesUseConstants:
    """Files should use status constants, not hardcoded strings."""

    def test_arb_scanner_uses_constants(self):
        text = (COMPONENTS_DIR / "ArbScannerPanel.tsx").read_text(encoding="utf-8")
        assert "ARB_STATUS." in text
        # No hardcoded status strings
        violations = re.findall(r"status\s*===\s*'(live|filled|submitted|failed)'", text)
        assert len(violations) == 0, f"Hardcoded: {violations}"

    def test_compliance_uses_constants(self):
        text = (COMPONENTS_DIR / "CompliancePanel.tsx").read_text(encoding="utf-8")
        assert "COMPLIANCE_STATUS." in text
        violations = re.findall(r"status\s*===\s*'(ALLOWED|RESTRICTED|PROHIBITED)'", text)
        assert len(violations) == 0, f"Hardcoded: {violations}"

    def test_dev_proposal_uses_constants(self):
        text = (COMPONENTS_DIR / "DevProposalDetail.tsx").read_text(encoding="utf-8")
        assert "PROPOSAL_STATUS." in text
        violations = re.findall(r"status\s*===\s*'(draft|in_review|approved|scheduled|executing|executed)'", text)
        assert len(violations) == 0, f"Hardcoded: {violations}"

    def test_swarm_readiness_uses_constants(self):
        text = (COMPONENTS_DIR / "DevSwarmReadiness.tsx").read_text(encoding="utf-8")
        assert "READINESS_STATUS." in text
        violations = re.findall(r"status\s*===\s*'(OK|DRIFTED|MISSING)'", text)
        assert len(violations) == 0, f"Hardcoded: {violations}"


# ── 3. No remaining hardcoded status checks ────────────────────

class TestNoHardcodedStatusChecks:
    """No file should have 3+ unique hardcoded status string checks."""

    def test_no_excessive_status_strings(self):
        violations = []
        views = WEB_REACT / "views"
        for d in [views, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                statuses = re.findall(r"status\s*===?\s*['\"](\w+)['\"]", text)
                if len(statuses) > 3:
                    unique = set(statuses)
                    if len(unique) >= 3:
                        violations.append(f"{f.name}: {len(statuses)} checks")
        assert len(violations) == 0, f"Hardcoded status checks: {violations}"
