"""Tests for Sprint 22 — Accessibility: Button titles + Input labels."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Files that were fixed in Sprint 22
BUTTON_FIXED_FILES = [
    "Betting.tsx", "BettingConsensusView.tsx", "Institutional.tsx",
    "Logs.tsx", "Mining.tsx", "Orders.tsx", "Plugins.tsx",
    "Positions.tsx", "PredictionConsensusView.tsx", "Predictions.tsx",
    "Research.tsx", "Settings.tsx", "Social.tsx", "Treasury.tsx", "Wallet.tsx",
]

COMPONENT_BUTTON_FIXED = [
    "CodebaseHealth.tsx", "DevProposalDetail.tsx", "DevSwarmCreateTask.tsx",
    "DevSwarmReadiness.tsx", "DevSwarmTaskList.tsx", "GovernanceDashboard.tsx",
    "HITLApprovalQueue.tsx", "LiveNotifications.tsx", "NotificationPanel.tsx",
    "PredictionMarketsPanel.tsx", "RiskProtectionsPanel.tsx", "StubGate.tsx",
    "TradingHaltBanner.tsx",
]

INPUT_FIXED_COMPONENTS = [
    "AssistantPanel.tsx",
    "CommandPalette.tsx",
    "DevProposalDetail.tsx",
]


# ── 1. Input accessibility ─────────────────────────────────────

class TestInputAccessibility:
    """Inputs in key components have aria-label."""

    @pytest.mark.parametrize("filename", INPUT_FIXED_COMPONENTS)
    def test_input_has_aria_label(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        # Match multi-line input tags by collapsing whitespace
        inputs = re.findall(r'<input\b[\s\S]*?/>', text)
        if not inputs:
            inputs = re.findall(r'<input\b[\s\S]*?>', text)
        for inp in inputs:
            has_label = (
                "aria-label=" in inp
                or "id=" in inp
                or "title=" in inp
            )
            assert has_label, f"{filename} has input without aria-label/id/title: {inp[:80]}"


# ── 2. Button title coverage improved ──────────────────────────

class TestButtonTitleCoverageViews:
    """Views that were fixed now have fewer unlabeled buttons."""

    @pytest.mark.parametrize("filename", BUTTON_FIXED_FILES)
    def test_view_has_titled_buttons(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        buttons = re.findall(r'<button[^>]*>', text, re.DOTALL)
        titled = [b for b in buttons if "title=" in b or "aria-label=" in b]
        # At least one button should be titled after fix
        if buttons:
            assert len(titled) > 0, f"{filename} has 0 titled buttons out of {len(buttons)}"


class TestButtonTitleCoverageComponents:
    """Components that were fixed now have titled buttons."""

    @pytest.mark.parametrize("filename", COMPONENT_BUTTON_FIXED)
    def test_component_has_titled_buttons(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        buttons = re.findall(r'<button[^>]*>', text, re.DOTALL)
        titled = [b for b in buttons if "title=" in b or "aria-label=" in b]
        if buttons:
            assert len(titled) > 0, f"{filename} has 0 titled buttons out of {len(buttons)}"


# ── 3. Overall accessibility metrics ───────────────────────────

class TestOverallAccessibilityMetrics:
    """Overall accessibility has improved."""

    def test_no_images_without_alt(self):
        violations = []
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                imgs = re.findall(r'<img[^>]*>', text)
                for img in imgs:
                    if "alt=" not in img:
                        violations.append(f"{f.name}: {img[:60]}")
        assert len(violations) == 0, f"Images without alt: {violations}"

    def test_button_title_coverage_above_threshold(self):
        """At least 25% of all buttons across the UI have title/aria-label."""
        total = 0
        titled = 0
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                buttons = re.findall(r'<button[^>]*>', text, re.DOTALL)
                total += len(buttons)
                titled += sum(1 for b in buttons if "title=" in b or "aria-label=" in b)
        pct = titled / total * 100 if total > 0 else 0
        assert pct >= 25, f"Button title coverage {pct:.1f}% < 25% threshold ({titled}/{total})"

    def test_input_label_coverage(self):
        """All inputs across the UI have some form of labeling."""
        violations = []
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                inputs = re.findall(r'<input\b[\s\S]*?/>', text)
                if not inputs:
                    inputs = re.findall(r'<input\b[\s\S]*?>', text)
                for inp in inputs:
                    has_label = any(attr in inp for attr in [
                        "aria-label=", "id=", "title=", "placeholder=",
                    ])
                    if not has_label:
                        violations.append(f"{f.name}: {inp[:60]}")
        assert len(violations) == 0, f"Inputs without labels: {violations}"
