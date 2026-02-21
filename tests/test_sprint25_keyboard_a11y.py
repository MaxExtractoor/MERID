"""Tests for Sprint 25 — Keyboard Accessibility + Mutation Feedback."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Files fixed with role/tabIndex/onKeyDown in Sprint 25
KEYBOARD_FIXED_FILES_VIEWS = [
    "CognitiveView.tsx",
    "FlowRadarView.tsx",
    "ObservabilityView.tsx",
    "Predictions.tsx",
    "SignalLayerView.tsx",
    "Social.tsx",
    "SportsLiveView.tsx",
]

KEYBOARD_FIXED_FILES_COMPONENTS = [
    "AgentStatusPanel.tsx",
    "CommandPalette.tsx",
    "DevProposalBoard.tsx",
    "DevSwarmTaskList.tsx",
    "ExplainabilityPanel.tsx",
    "ExplainabilityTimeline.tsx",
    "HITLApprovalQueue.tsx",
    "LiveNotifications.tsx",
    "OrchestratorPanel.tsx",
    "RiskProtectionsPanel.tsx",
    "SwarmPanel.tsx",
]


# ── 1. Fixed files now have keyboard a11y attributes ──────────

class TestKeyboardA11yViews:
    """Views fixed in Sprint 25 now contain role=button and onKeyDown."""

    @pytest.mark.parametrize("filename", KEYBOARD_FIXED_FILES_VIEWS)
    def test_has_role_button(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert 'role="button"' in text, f"{filename} missing role=button"

    @pytest.mark.parametrize("filename", KEYBOARD_FIXED_FILES_VIEWS)
    def test_has_onkeydown(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert 'onKeyDown' in text, f"{filename} missing onKeyDown"

    @pytest.mark.parametrize("filename", KEYBOARD_FIXED_FILES_VIEWS)
    def test_has_tabindex(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert 'tabIndex' in text, f"{filename} missing tabIndex"


class TestKeyboardA11yComponents:
    """Components fixed in Sprint 25 now contain role=button and onKeyDown."""

    @pytest.mark.parametrize("filename", KEYBOARD_FIXED_FILES_COMPONENTS)
    def test_has_role_button(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        assert 'role="button"' in text, f"{filename} missing role=button"

    @pytest.mark.parametrize("filename", KEYBOARD_FIXED_FILES_COMPONENTS)
    def test_has_onkeydown(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        assert 'onKeyDown' in text, f"{filename} missing onKeyDown"

    @pytest.mark.parametrize("filename", KEYBOARD_FIXED_FILES_COMPONENTS)
    def test_has_tabindex(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        assert 'tabIndex' in text, f"{filename} missing tabIndex"


# ── 3. OperatorControlPlane mutation feedback ──────────────────

class TestOperatorControlPlaneFeedback:
    """OperatorControlPlane has mutation feedback."""

    def test_has_action_status_state(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "actionStatus" in text

    def test_has_success_feedback(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "'success'" in text or '"success"' in text

    def test_has_error_feedback(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "'error'" in text or '"error"' in text

    def test_has_feedback_banner(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "bg-emerald-900" in text and "bg-red-900" in text

    def test_has_auto_hide(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "setTimeout" in text

    def test_no_console_error_in_handlers(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "console.error" not in text
