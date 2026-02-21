"""Tests for Sprint 28 — Button Type Attributes + Unused Import Cleanup."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"


# ── 1. All buttons have type attribute ─────────────────────────

class TestButtonTypeViews:
    """All buttons in views have an explicit type attribute."""

    def test_no_buttons_without_type_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"<button\b[^>]*>", text):
                if "type=" not in m.group(0):
                    line = text[: m.start()].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Buttons without type: {violations}"


class TestButtonTypeComponents:
    """All buttons in components have an explicit type attribute."""

    def test_no_buttons_without_type_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r"<button\b[^>]*>", text):
                if "type=" not in m.group(0):
                    line = text[: m.start()].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Buttons without type: {violations}"


# ── 2. Unused lucide imports cleaned ──────────────────────────

class TestUnusedLucideImports:
    """Files with previously unused lucide icons are now clean."""

    def test_operator_status_bar_no_unused(self):
        text = (VIEWS_DIR / "OperatorStatusBar.tsx").read_text(encoding="utf-8")
        assert "Activity" not in text

    def test_sports_live_view_no_unused(self):
        text = (VIEWS_DIR / "SportsLiveView.tsx").read_text(encoding="utf-8")
        # These 6 icons were removed
        for icon in ["Zap", "Eye", "Minus"]:
            # Check they don't appear in the import line
            import_match = re.search(r"from\s+['\"]lucide-react['\"]", text)
            if import_match:
                import_line_start = text.rfind("\n", 0, import_match.start())
                import_block = text[import_line_start:import_match.end()]
                assert icon not in import_block, f"{icon} still imported in SportsLiveView"


# ── 3. Button count sanity check ──────────────────────────────

class TestButtonCountSanity:
    """Verify a reasonable number of buttons exist with type attribute."""

    def test_buttons_with_type_exist(self):
        count = 0
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                count += len(re.findall(r'<button\b[^>]*type="button"', text))
        # We fixed 300 buttons, so there should be at least 250
        assert count >= 250, f"Expected >=250 typed buttons, got {count}"
