"""Tests for Sprint 29 — AUTH_TOKEN_KEY Constant + localStorage Cleanup."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

UPDATED_FILES = ["Logs.tsx", "Research.tsx", "Settings.tsx"]


# ── 1. AUTH_TOKEN_KEY constant exists ──────────────────────────

class TestAuthTokenKeyConstant:
    """AUTH_TOKEN_KEY constant exists in constants.ts."""

    def test_constant_exists(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "AUTH_TOKEN_KEY" in text

    def test_constant_value(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert '"merid-access"' in text


# ── 2. No hardcoded 'merid-access' in views ───────────────────

class TestNoHardcodedAuthKey:
    """Views should use AUTH_TOKEN_KEY instead of hardcoded string."""

    @pytest.mark.parametrize("filename", UPDATED_FILES)
    def test_no_hardcoded_merid_access(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        # Should not have the hardcoded string in localStorage calls
        hardcoded = re.findall(r'localStorage\.\w+\(\s*["\']merid-access["\']', text)
        assert len(hardcoded) == 0, f"{filename} still has hardcoded 'merid-access'"

    @pytest.mark.parametrize("filename", UPDATED_FILES)
    def test_uses_auth_token_key(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "AUTH_TOKEN_KEY" in text, f"{filename} missing AUTH_TOKEN_KEY"

    def test_no_hardcoded_in_any_view(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if re.search(r'localStorage\.\w+\(\s*["\']merid-access["\']', text):
                violations.append(f.name)
        assert len(violations) == 0, f"Views with hardcoded 'merid-access': {violations}"


# ── 3. Updated files import AUTH_TOKEN_KEY ─────────────────────

class TestImportsAuthTokenKey:
    """Updated files import AUTH_TOKEN_KEY from constants."""

    @pytest.mark.parametrize("filename", UPDATED_FILES)
    def test_imports_auth_token_key(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "AUTH_TOKEN_KEY" in text
        # Verify it's in an import statement
        assert re.search(r"import\s*\{[^}]*AUTH_TOKEN_KEY[^}]*\}", text), (
            f"{filename} does not import AUTH_TOKEN_KEY"
        )
