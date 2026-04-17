"""Tests for Sprint 20 — Loading State Coverage for Views."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"

# Views that were updated with loading states in Sprint 20
LOADING_STATE_VIEWS = [
    "ApiDashboard.tsx",
    "Logs.tsx",
    "Research.tsx",
    "Risk.tsx",
    "Settings.tsx",
    "TradeFloor.tsx",
]

# Views exempt from loading state requirement:
# - OperatorStatusBar.tsx: presentational component (receives data via props)
# - Small views (<50 lines) or purely static views
EXEMPT_VIEWS = [
    "OperatorStatusBar.tsx",
]


# ── 1. Loading state pattern present ───────────────────────────

class TestLoadingStatePresent:
    """Each targeted view has a loading indicator pattern."""

    @pytest.mark.parametrize("filename", LOADING_STATE_VIEWS)
    def test_view_has_loading_indicator(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        has_loading = (
            "isLoading" in text
            or "isInitialLoad" in text
            or "loading:" in text
            or "Loading" in text
        )
        assert has_loading, f"{filename} missing loading state"

    @pytest.mark.parametrize("filename", LOADING_STATE_VIEWS)
    def test_view_has_spinner_or_skeleton(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        has_spinner = (
            "animate-spin" in text
            or "Skeleton" in text
            or "RefreshCw" in text
            or "Loader2" in text
        )
        assert has_spinner, f"{filename} missing spinner/skeleton component"

    @pytest.mark.parametrize("filename", LOADING_STATE_VIEWS)
    def test_view_imports_loading_icon(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        has_icon_import = (
            "RefreshCw" in text
            or "Loader2" in text
            or "Skeleton" in text
        )
        assert has_icon_import, f"{filename} missing loading icon import"


# ── 2. Loading guard pattern ───────────────────────────────────

class TestLoadingGuardPattern:
    """Views use an early-return loading guard."""

    @pytest.mark.parametrize("filename", LOADING_STATE_VIEWS)
    def test_has_loading_guard(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        # Pattern: if (isLoading) { return ( or if (xxxLoading && !xxx) { return (
        has_guard = bool(re.search(
            r'if\s*\(\s*(?:isLoading|is[A-Z]\w*Load|.*Loading\s*&&)', text
        ))
        assert has_guard, f"{filename} missing loading guard (if isLoading/xxxLoading)"


# ── 3. All large data-fetching views have loading states ───────

class TestAllLargeViewsCovered:
    """Every view >50 lines that fetches data has a loading indicator."""

    LOADING_KEYWORDS = ["loading", "isloading", "skeleton", "spinner", "animate-spin", "refreshcw", "loader2"]

    def test_no_large_views_without_loading(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            if f.name in EXEMPT_VIEWS or "__tests__" in str(f):
                continue
            text = f.read_text(encoding="utf-8")
            lines = len(text.splitlines())
            if lines <= 50:
                continue
            # Only check views that fetch data
            fetches_data = (
                "useApiData" in text
                or "useEffect" in text and "fetch(" in text
                or "WebSocket" in text
            )
            if not fetches_data:
                continue
            text_lower = text.lower()
            has_loading = any(kw in text_lower for kw in self.LOADING_KEYWORDS)
            if not has_loading:
                violations.append(f"{f.name} ({lines} lines)")
        assert len(violations) == 0, (
            f"Found {len(violations)} large data-fetching view(s) without loading states:\n"
            + "\n".join(violations)
        )


# ── 4. Exempt views are correctly exempt ───────────────────────

class TestExemptViews:
    """Exempt views are small or presentational."""

    def test_operator_status_bar_is_presentational(self):
        text = (VIEWS_DIR / "OperatorStatusBar.tsx").read_text(encoding="utf-8")
        # It receives data via props, not useApiData for primary data
        assert "summary:" in text or "OperatorSummary" in text
        # It's small
        assert len(text.splitlines()) < 120
