"""Tests for Sprint 41 — React.memo on Stateless Components."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
COMPONENTS_DIR = WEB_REACT / "components"

MEMO_COMPONENTS = [
    "AnimatedCard", "ChartCard", "ChartWrapper", "CodeQualityPanel",
    "ConsensusPill", "DataTable", "DevAgentRoster", "DevSwarmStats",
    "EmptyState", "ErrorAlert", "GovernanceDashboard", "LoadingState",
    "MarketsOverview", "MetricCard", "PortfolioChart", "PredictionEdgePill",
    "QuickActionsPanel", "Sidebar", "SkeletonLoader", "StatusIndicator",
    "StubBanner", "StubGate", "ThemeToggle", "Tooltip",
]


# ── 1. Components use React.memo ──────────────────────────────

class TestReactMemoWrapped:
    """Verify stateless components are wrapped with React.memo."""

    @pytest.mark.parametrize("name", MEMO_COMPONENTS)
    def test_component_uses_memo(self, name: str):
        fpath = COMPONENTS_DIR / f"{name}.tsx"
        assert fpath.exists(), f"{name}.tsx not found"
        text = fpath.read_text(encoding="utf-8")
        assert f"React.memo({name})" in text, f"{name} should be wrapped with React.memo"

    @pytest.mark.parametrize("name", MEMO_COMPONENTS)
    def test_component_exports_memo(self, name: str):
        fpath = COMPONENTS_DIR / f"{name}.tsx"
        text = fpath.read_text(encoding="utf-8")
        has_direct = f"export default React.memo({name})" in text
        has_named = f"export default Memoized{name}" in text
        assert has_direct or has_named, \
            f"{name} should export default via React.memo"


# ── 2. Components don't double-export ─────────────────────────

class TestNoDoubleExport:
    """Wrapped components should not have 'export default function'."""

    @pytest.mark.parametrize("name", MEMO_COMPONENTS)
    def test_no_export_default_function(self, name: str):
        fpath = COMPONENTS_DIR / f"{name}.tsx"
        text = fpath.read_text(encoding="utf-8")
        assert "export default function" not in text, \
            f"{name} should not have 'export default function' (use React.memo export)"


# ── 3. All stateless components are memoized ───────────────────

class TestAllStatelessMemoized:
    """All stateless components (no useState/useEffect) should use memo."""

    def test_no_unmemoized_stateless(self):
        unmemoized = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if 'React.memo' in text or 'memo(' in text:
                continue
            if 'useState' in text or 'useEffect' in text:
                continue
            if 'export default function' in text:
                unmemoized.append(f.name)
        assert len(unmemoized) == 0, f"Unmemoized stateless: {unmemoized}"
