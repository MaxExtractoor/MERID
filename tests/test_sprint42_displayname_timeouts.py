"""Tests for Sprint 42 — displayName on React.memo + Hardcoded Timeout Constants."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

MEMO_COMPONENTS = [
    "AnimatedCard", "ChartCard", "ChartWrapper", "CodeQualityPanel",
    "ConsensusPill", "DataTable", "DevAgentRoster", "DevSwarmStats",
    "EmptyState", "ErrorAlert", "GovernanceDashboard", "LoadingState",
    "MarketsOverview", "MetricCard", "PortfolioChart", "PredictionEdgePill",
    "QuickActionsPanel", "Sidebar", "SkeletonLoader", "StatusIndicator",
    "StubBanner", "StubGate", "ThemeToggle", "Tooltip",
]


# ── 1. displayName on React.memo components ───────────────────

class TestDisplayName:
    """All React.memo components should have displayName set."""

    @pytest.mark.parametrize("name", MEMO_COMPONENTS)
    def test_has_display_name(self, name: str):
        fpath = COMPONENTS_DIR / f"{name}.tsx"
        text = fpath.read_text(encoding="utf-8")
        assert ".displayName" in text, f"{name} should have displayName"

    @pytest.mark.parametrize("name", MEMO_COMPONENTS)
    def test_display_name_matches(self, name: str):
        fpath = COMPONENTS_DIR / f"{name}.tsx"
        text = fpath.read_text(encoding="utf-8")
        assert f"= '{name}'" in text, f"{name} displayName should be '{name}'"

    def test_no_memo_without_displayname(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if 'React.memo(' in text and '.displayName' not in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Missing displayName: {violations}"


# ── 2. DEFAULTS.TIMEOUTS constants exist ───────────────────────

class TestTimeoutConstants:
    """Verify DEFAULTS.TIMEOUTS constants exist."""

    def test_timeouts_section_exists(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "TIMEOUTS:" in text

    @pytest.mark.parametrize("name", ["DEBOUNCE", "UI_FEEDBACK", "TOAST", "STATUS_RESET"])
    def test_timeout_constant_exists(self, name: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert f"{name}:" in text, f"Missing DEFAULTS.TIMEOUTS.{name}"


# ── 3. No hardcoded setTimeout values ─────────────────────────

class TestNoHardcodedTimeouts:
    """setTimeout should use DEFAULTS constants, not magic numbers."""

    def test_no_hardcoded_timeouts_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            lines = text.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                if re.search(r'setTimeout\([^,]+,\s*\d+\)', line) and 'DEFAULTS' not in line:
                    violations.append(f"{f.name}:{i}")
        assert len(violations) == 0, f"Hardcoded timeouts: {violations}"

    def test_no_hardcoded_timeouts_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            lines = text.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                if re.search(r'setTimeout\([^,]+,\s*\d+\)', line) and 'DEFAULTS' not in line:
                    violations.append(f"{f.name}:{i}")
        assert len(violations) == 0, f"Hardcoded timeouts: {violations}"
