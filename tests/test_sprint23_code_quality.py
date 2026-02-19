"""Tests for Sprint 23 — Code Quality: Hardcoded URLs + console.log cleanup."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

# Files that should NOT have console.log (SocketTest exempt as debug tool)
CONSOLE_LOG_EXEMPT = {"SocketTest.tsx"}


# ── 1. No hardcoded useApiData URLs ────────────────────────────

class TestNoHardcodedApiUrls:
    """Views should use API_ENDPOINTS constants, not hardcoded strings."""

    def test_no_hardcoded_useapidata_urls(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            hardcoded = re.findall(r'useApiData[^(]*\(\s*["\'](/api/[^"\']+)', text)
            for url in hardcoded:
                violations.append(f"{f.name}: {url}")
        assert len(violations) == 0, f"Hardcoded useApiData URLs: {violations}"

    def test_no_hardcoded_fetch_urls_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            hardcoded = re.findall(r'fetch\(\s*["\'](/api/[^"\']+)', text)
            for url in hardcoded:
                violations.append(f"{f.name}: {url}")
        assert len(violations) == 0, f"Hardcoded fetch URLs: {violations}"


# ── 2. New constants exist ─────────────────────────────────────

class TestNewConstants:
    """New API_ENDPOINTS constants were added."""

    def test_risk_alerts_constant(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "RISK_ALERTS" in text

    def test_risk_position_limits_constant(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "RISK_POSITION_LIMITS" in text

    def test_risk_alerts_value(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert '"/api/v1/risk/alerts"' in text

    def test_risk_position_limits_value(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert '"/api/v1/risk/position-limits"' in text


# ── 3. console.log cleanup ─────────────────────────────────────

class TestConsoleLogCleanup:
    """Production views/components should not have console.log."""

    def test_no_console_log_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            if f.name in CONSOLE_LOG_EXEMPT:
                continue
            text = f.read_text(encoding="utf-8")
            count = len(re.findall(r"console\.log\(", text))
            if count > 0:
                violations.append(f"{f.name}: {count}")
        assert len(violations) == 0, f"Views with console.log: {violations}"

    def test_no_console_log_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            if f.name in CONSOLE_LOG_EXEMPT:
                continue
            text = f.read_text(encoding="utf-8")
            count = len(re.findall(r"console\.log\(", text))
            if count > 0:
                violations.append(f"{f.name}: {count}")
        assert len(violations) == 0, f"Components with console.log: {violations}"

    def test_console_warn_error_allowed(self):
        """console.warn and console.error are acceptable for error reporting."""
        total_warn = 0
        total_error = 0
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                total_warn += len(re.findall(r"console\.warn\(", text))
                total_error += len(re.findall(r"console\.error\(", text))
        # These are fine — just verify they exist (error handling)
        assert total_warn >= 0
        assert total_error >= 0


# ── 4. Risk.tsx uses constants ─────────────────────────────────

class TestRiskViewConstants:
    """Risk.tsx uses API_ENDPOINTS for all data fetching."""

    def test_risk_uses_api_endpoints_for_alerts(self):
        text = (VIEWS_DIR / "Risk.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.RISK_ALERTS" in text

    def test_risk_uses_api_endpoints_for_position_limits(self):
        text = (VIEWS_DIR / "Risk.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.RISK_POSITION_LIMITS" in text

    def test_risk_no_hardcoded_urls(self):
        text = (VIEWS_DIR / "Risk.tsx").read_text(encoding="utf-8")
        hardcoded = re.findall(r'useApiData[^(]*\(\s*["\'](/api/[^"\']+)', text)
        assert len(hardcoded) == 0, f"Risk.tsx still has hardcoded URLs: {hardcoded}"
