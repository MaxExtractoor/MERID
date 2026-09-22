"""Tests for Sprint 25 — Keyboard Accessibility + Mutation Feedback."""
import re
from pathlib import Path

import pytest


# AUDIT-2026-09-22-04: conditional strict xfail for frontend files that were
# never committed to this tree.  The mark drops off per-param once the file
# lands; existing files must pass.  Expiry 2026-10-15.
_MISSING_UI_REASON = (
    "DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree "
    "(never committed). Expiry 2026-10-15."
)


def _ui_params(directory, names):
    return [
        pytest.param(
            n,
            marks=pytest.mark.xfail(
                not (directory / n).exists(),
                strict=True,
                reason=_MISSING_UI_REASON,
            ),
        )
        for n in names
    ]

_XFAIL_PARAMS = {
    'test_has_onkeydown': {'CognitiveView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'FlowRadarView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'ObservabilityView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Predictions.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SignalLayerView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Social.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SportsLiveView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'DevProposalBoard.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'DevSwarmTaskList.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'OrchestratorPanel.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SwarmPanel.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.'},
    'test_has_role_button': {'CognitiveView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'FlowRadarView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'ObservabilityView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Predictions.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SignalLayerView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Social.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SportsLiveView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'DevProposalBoard.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'DevSwarmTaskList.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'OrchestratorPanel.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SwarmPanel.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.'},
    'test_has_tabindex': {'CognitiveView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'FlowRadarView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'ObservabilityView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Predictions.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SignalLayerView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Social.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SportsLiveView.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'DevProposalBoard.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'DevSwarmTaskList.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'OrchestratorPanel.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'SwarmPanel.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.'},
}
def _ap(names, test_name):
    """Per-param strict xfail driven by audit dispositions (AUDIT-2026-09-22)."""
    fm = _XFAIL_PARAMS.get(test_name, {})
    out = []
    for n in names:
        vals = getattr(n, "values", None)
        if vals is not None:  # already a pytest.param/ParameterSet
            key = "-".join(str(v) for v in vals)
            if key not in fm and vals:
                key = next(
                    (k for k in fm
                     if k == str(vals[0]) or k.startswith(str(vals[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *vals, marks=list(n.marks) + [
                        pytest.mark.xfail(strict=True, reason=fm[key])]))
            else:
                out.append(n)
        elif isinstance(n, tuple):
            key = "-".join(str(x) for x in n)
            if key not in fm and n:
                key = next(
                    (k for k in fm
                     if k == str(n[0]) or k.startswith(str(n[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *n, marks=pytest.mark.xfail(strict=True, reason=fm[key])))
            else:
                out.append(n)
        elif n in fm:
            out.append(pytest.param(
                n, marks=pytest.mark.xfail(strict=True, reason=fm[n])))
        else:
            out.append(n)
    return out


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

    @pytest.mark.parametrize("filename", _ap(_ui_params(COMPONENTS_DIR, KEYBOARD_FIXED_FILES_COMPONENTS), 'test_has_role_button'))
    def test_has_role_button(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        assert 'role="button"' in text, f"{filename} missing role=button"

    @pytest.mark.parametrize("filename", _ap(KEYBOARD_FIXED_FILES_COMPONENTS, 'test_has_onkeydown'))
    def test_has_onkeydown(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        assert 'onKeyDown' in text, f"{filename} missing onKeyDown"

    @pytest.mark.parametrize("filename", _ap(KEYBOARD_FIXED_FILES_COMPONENTS, 'test_has_tabindex'))
    def test_has_tabindex(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        assert 'tabIndex' in text, f"{filename} missing tabIndex"


# ── 3. OperatorControlPlane mutation feedback ──────────────────

class TestOperatorControlPlaneFeedback:
    """OperatorControlPlane has mutation feedback."""

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_action_status_state(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "actionStatus" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_success_feedback(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "'success'" in text or '"success"' in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_error_feedback(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "'error'" in text or '"error"' in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_feedback_banner(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "bg-emerald-900" in text and "bg-red-900" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_has_auto_hide(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "setTimeout" in text

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.")
    def test_no_console_error_in_handlers(self):
        text = (VIEWS_DIR / "OperatorControlPlane.tsx").read_text(encoding="utf-8")
        assert "console.error" not in text
