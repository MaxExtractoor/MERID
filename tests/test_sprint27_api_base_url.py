"""Tests for Sprint 27 — Replace API_BASE_URL with API_ENDPOINTS constants."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

# Files updated in Sprint 27
UPDATED_FILES = [
    "OperatorActivityStream.tsx",
    "OperatorControlPlane.tsx",
]

# New constants added
NEW_CONSTANTS = [
    "OPERATOR_ORDERS",
    "SYSTEM_DECISIONS",
    "OPERATOR_AUDIT_TRAIL",
    "DEV_SWARM_SHUTDOWN",
    "SYSTEM_STOP",
]


# ── 1. New constants exist ─────────────────────────────────────

class TestNewApiEndpointConstants:
    """New API endpoint constants were added."""

    @pytest.mark.parametrize("key", NEW_CONSTANTS)
    def test_constant_exists(self, key: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert key in text, f"Missing API_ENDPOINTS.{key}"


# ── 2. No API_BASE_URL in views ───────────────────────────────

class TestNoApiBaseUrlInViews:
    """Views should not use API_BASE_URL directly."""

    @pytest.mark.parametrize("filename", UPDATED_FILES)
    def test_no_api_base_url(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "API_BASE_URL" not in text, f"{filename} still uses API_BASE_URL"

    @pytest.mark.parametrize("filename", UPDATED_FILES)
    def test_uses_api_endpoints(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "API_ENDPOINTS" in text, f"{filename} missing API_ENDPOINTS import"

    def test_no_api_base_url_in_any_view(self):
        """No view should use API_BASE_URL directly."""
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "API_BASE_URL" in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Views still using API_BASE_URL: {violations}"


# ── 3. OperatorActivityStream uses constants ──────────────────

class TestOperatorActivityStreamConstants:
    """OperatorActivityStream uses API_ENDPOINTS for all fetch calls."""

    def test_uses_operator_orders(self):
        text = (VIEWS_DIR / "OperatorActivityStream.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.OPERATOR_ORDERS" in text

    def test_uses_system_decisions(self):
        text = (VIEWS_DIR / "OperatorActivityStream.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.SYSTEM_DECISIONS" in text

    def test_uses_audit_trail(self):
        text = (VIEWS_DIR / "OperatorActivityStream.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.OPERATOR_AUDIT_TRAIL" in text


# ── 4. OperatorControlPlane uses constants ────────────────────

class TestOperatorControlPlaneConstants:
    """OperatorControlPlane uses API_ENDPOINTS for all fetch calls."""

    def test_uses_dev_swarm_shutdown(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.DEV_SWARM_SHUTDOWN" in text

    def test_uses_system_stop(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "API_ENDPOINTS.SYSTEM_STOP" in text
