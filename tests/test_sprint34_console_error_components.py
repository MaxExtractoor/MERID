"""Tests for Sprint 34 — console.error Removal from Components."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# ErrorBoundary is the only component allowed to keep console.error
ALLOWED_CONSOLE_ERROR = {"ErrorBoundary.tsx"}

CLEANED_COMPONENTS = [
    "AgentActivityPanel.tsx",
    "AgentPerformanceTable.tsx",
    "AgentReasoningPanel.tsx",
    "AgentStatusPanel.tsx",
    "ArbitragePanel.tsx",
    "ConsensusBoard.tsx",
    "DebateTimeline.tsx",
    "DomainControlPanel.tsx",
    "DrawdownChart.tsx",
    "NotificationPanel.tsx",
    "PaperTradingPanel.tsx",
    "PredictionMarketsPanel.tsx",
    "SharpeRatioTile.tsx",
    "SimulationControlPanel.tsx",
    "VenueHealthGrid.tsx",
]


# ── 1. No console.error in cleaned components ─────────────────

class TestNoConsoleErrorComponents:
    """Cleaned components should not use console.error."""

    @pytest.mark.parametrize("filename", CLEANED_COMPONENTS)
    def test_no_console_error(self, filename: str):
        text = (COMPONENTS_DIR / filename).read_text(encoding="utf-8")
        errors = re.findall(r"console\.error\(", text)
        assert len(errors) == 0, f"{filename} still has {len(errors)} console.error calls"

    def test_only_error_boundary_has_console_error(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            if f.name in ALLOWED_CONSOLE_ERROR:
                continue
            text = f.read_text(encoding="utf-8")
            if "console.error(" in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Components with console.error: {violations}"


# ── 2. ErrorBoundary still has its logging ─────────────────────

class TestErrorBoundaryPreserved:
    """ErrorBoundary should retain its error logging (logUiError or console.error)."""

    def test_error_boundary_has_console_error(self):
        text = (COMPONENTS_DIR / "ErrorBoundary.tsx").read_text(encoding="utf-8")
        assert "console.error" in text or "logUiError" in text, "ErrorBoundary should keep error logging"


# ── 3. Full codebase sanity: no console.warn or console.error in views ──

class TestViewsSanity:
    """Views should have zero console.error and console.warn."""

    def test_no_console_error_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "console.error(" in text:
                violations.append(f.name)
        assert len(violations) == 0

    def test_no_console_warn_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "console.warn(" in text:
                violations.append(f.name)
        assert len(violations) == 0
