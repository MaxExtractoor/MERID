"""Tests for Sprint 21 — Error State + ErrorAlert/EmptyState Components."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Views updated with error handling in Sprint 21
ERROR_HANDLED_VIEWS = [
    "Agents.tsx",
    "ApiDashboard.tsx",
    "Logs.tsx",
    "Research.tsx",
    "Risk.tsx",
    "Settings.tsx",
]


# ── 1. Reusable components exist ───────────────────────────────

class TestErrorAlertComponent:
    """ErrorAlert component exists and has correct structure."""

    def test_file_exists(self):
        assert (COMPONENTS_DIR / "ErrorAlert.tsx").exists()

    def test_has_message_prop(self):
        text = (COMPONENTS_DIR / "ErrorAlert.tsx").read_text(encoding="utf-8")
        assert "message" in text

    def test_has_retry_prop(self):
        text = (COMPONENTS_DIR / "ErrorAlert.tsx").read_text(encoding="utf-8")
        assert "onRetry" in text

    def test_has_alert_icon(self):
        text = (COMPONENTS_DIR / "ErrorAlert.tsx").read_text(encoding="utf-8")
        assert "AlertTriangle" in text

    def test_has_retry_button(self):
        text = (COMPONENTS_DIR / "ErrorAlert.tsx").read_text(encoding="utf-8")
        assert "Retry" in text

    def test_default_export(self):
        text = (COMPONENTS_DIR / "ErrorAlert.tsx").read_text(encoding="utf-8")
        assert "export default" in text

    def test_has_title_attribute(self):
        text = (COMPONENTS_DIR / "ErrorAlert.tsx").read_text(encoding="utf-8")
        assert 'title=' in text


class TestEmptyStateComponent:
    """EmptyState component exists and has correct structure."""

    def test_file_exists(self):
        assert (COMPONENTS_DIR / "EmptyState.tsx").exists()

    def test_has_title_prop(self):
        text = (COMPONENTS_DIR / "EmptyState.tsx").read_text(encoding="utf-8")
        assert "title" in text

    def test_has_message_prop(self):
        text = (COMPONENTS_DIR / "EmptyState.tsx").read_text(encoding="utf-8")
        assert "message" in text

    def test_has_default_text(self):
        text = (COMPONENTS_DIR / "EmptyState.tsx").read_text(encoding="utf-8")
        assert "No data available" in text

    def test_has_inbox_icon(self):
        text = (COMPONENTS_DIR / "EmptyState.tsx").read_text(encoding="utf-8")
        assert "Inbox" in text

    def test_default_export(self):
        text = (COMPONENTS_DIR / "EmptyState.tsx").read_text(encoding="utf-8")
        assert "export default" in text


# ── 2. Views import and use ErrorAlert ─────────────────────────

class TestViewsImportErrorAlert:
    """Each updated view imports ErrorAlert."""

    @pytest.mark.parametrize("filename", ERROR_HANDLED_VIEWS)
    def test_imports_error_alert(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "ErrorAlert" in text, f"{filename} missing ErrorAlert import"


class TestViewsDestructureError:
    """Each updated view destructures error from useApiData."""

    @pytest.mark.parametrize("filename", ERROR_HANDLED_VIEWS)
    def test_destructures_error(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "error:" in text, f"{filename} missing error destructuring"


class TestViewsHaveErrorGuard:
    """Each updated view has an error guard with ErrorAlert."""

    @pytest.mark.parametrize("filename", ERROR_HANDLED_VIEWS)
    def test_has_error_guard(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        has_guard = bool(re.search(r'if\s*\(\s*\w*[Ee]rror\s*&&', text))
        assert has_guard, f"{filename} missing error guard pattern"

    @pytest.mark.parametrize("filename", ERROR_HANDLED_VIEWS)
    def test_renders_error_alert(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "<ErrorAlert" in text, f"{filename} missing <ErrorAlert render"


class TestViewsHaveRetry:
    """Each updated view passes onRetry to ErrorAlert."""

    @pytest.mark.parametrize("filename", ERROR_HANDLED_VIEWS)
    def test_has_retry_callback(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "onRetry=" in text, f"{filename} missing onRetry prop"


# ── 3. Comprehensive coverage check ───────────────────────────

class TestAllUseApiDataViewsHaveError:
    """Every view using useApiData destructures error."""

    def test_no_views_without_error_destructuring(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "useApiData" not in text:
                continue
            lines = len(text.splitlines())
            if lines < 80:
                continue
            has_error = "error:" in text or "error," in text or "error }" in text
            if not has_error:
                violations.append(f.name)
        assert len(violations) == 0, (
            f"Views using useApiData without error destructuring: {violations}"
        )
