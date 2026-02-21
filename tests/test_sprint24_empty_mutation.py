"""Tests for Sprint 24 — Empty State UI + Mutation Feedback."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Views updated with empty state in Sprint 24
EMPTY_STATE_VIEWS = [
    "ApiDashboard.tsx",
    "Logs.tsx",
    "Risk.tsx",
]

# Views updated with mutation feedback in Sprint 24
MUTATION_FEEDBACK_VIEWS = [
    "Research.tsx",
    "Logs.tsx",
]


# ── 1. EmptyState component usage ──────────────────────────────

class TestEmptyStateImport:
    """Views import EmptyState component."""

    @pytest.mark.parametrize("filename", EMPTY_STATE_VIEWS)
    def test_imports_empty_state(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "EmptyState" in text, f"{filename} missing EmptyState import"


class TestEmptyStateGuard:
    """Views have empty state guard rendering EmptyState."""

    @pytest.mark.parametrize("filename", EMPTY_STATE_VIEWS)
    def test_has_empty_state_guard(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "<EmptyState" in text, f"{filename} missing <EmptyState render"

    @pytest.mark.parametrize("filename", EMPTY_STATE_VIEWS)
    def test_empty_guard_checks_length_or_null(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        has_check = (
            "length === 0" in text
            or "!riskMetrics && !alerts" in text
        )
        assert has_check, f"{filename} missing empty data check"


# ── 2. Mutation feedback ──────────────────────────────────────

class TestMutationFeedbackState:
    """Views with mutations have feedback state variables."""

    def test_research_has_backtest_status(self):
        text = (VIEWS_DIR / "Research.tsx").read_text(encoding="utf-8")
        assert "backtestStatus" in text

    def test_logs_has_clear_status(self):
        text = (VIEWS_DIR / "Logs.tsx").read_text(encoding="utf-8")
        assert "clearStatus" in text


class TestMutationFeedbackUI:
    """Views render mutation feedback to the user."""

    @pytest.mark.parametrize("filename", MUTATION_FEEDBACK_VIEWS)
    def test_renders_feedback_banner(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        has_feedback_ui = (
            "bg-emerald-900" in text
            and "bg-red-900" in text
        )
        assert has_feedback_ui, f"{filename} missing feedback banner UI"

    @pytest.mark.parametrize("filename", MUTATION_FEEDBACK_VIEWS)
    def test_has_success_message(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "'success'" in text or '"success"' in text, f"{filename} missing success state"

    @pytest.mark.parametrize("filename", MUTATION_FEEDBACK_VIEWS)
    def test_has_error_message(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "'error'" in text or '"error"' in text, f"{filename} missing error state"


class TestMutationFeedbackAutoHide:
    """Mutation feedback auto-hides after timeout."""

    @pytest.mark.parametrize("filename", MUTATION_FEEDBACK_VIEWS)
    def test_has_auto_hide_timeout(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "setTimeout" in text, f"{filename} missing auto-hide setTimeout"


# ── 3. No console.error in mutation handlers ───────────────────

class TestNoConsoleErrorInMutations:
    """Mutation handlers should use state feedback, not console.error."""

    def test_research_no_console_error_in_handler(self):
        text = (VIEWS_DIR / "Research.tsx").read_text(encoding="utf-8")
        # Find the handleRunBacktest function and check it doesn't use console.error
        match = re.search(r'handleRunBacktest.*?^\s*\};', text, re.DOTALL | re.MULTILINE)
        if match:
            handler = match.group(0)
            assert "console.error" not in handler, "handleRunBacktest still uses console.error"

    def test_logs_no_console_error_in_handler(self):
        text = (VIEWS_DIR / "Logs.tsx").read_text(encoding="utf-8")
        match = re.search(r'handleClearLogs.*?^\s*\};', text, re.DOTALL | re.MULTILINE)
        if match:
            handler = match.group(0)
            assert "console.error" not in handler, "handleClearLogs still uses console.error"
