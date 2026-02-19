"""Tests for Sprint 30 — useEffect Cleanup + console.warn Removal."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Files where console.warn was removed
WARN_CLEANED_FILES = [
    "Orders.tsx",
    "Positions.tsx",
    "TradeFloor.tsx",
]


# ── 1. No console.warn in views ───────────────────────────────

class TestNoConsoleWarnViews:
    """Views should not use console.warn."""

    @pytest.mark.parametrize("filename", WARN_CLEANED_FILES)
    def test_no_console_warn(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        warns = re.findall(r"console\.warn\(", text)
        assert len(warns) == 0, f"{filename} still has {len(warns)} console.warn calls"

    def test_no_console_warn_in_any_view(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            if "console.warn(" in text:
                violations.append(f.name)
        assert len(violations) == 0, f"Views with console.warn: {violations}"


# ── 2. useEffect cleanup in CommandPalette ────────────────────

class TestUseEffectCleanup:
    """CommandPalette useEffect with setTimeout has proper cleanup."""

    def test_command_palette_has_clear_timeout(self):
        text = (COMPONENTS_DIR / "CommandPalette.tsx").read_text(encoding="utf-8")
        assert "clearTimeout" in text, "CommandPalette missing clearTimeout cleanup"

    def test_command_palette_timer_variable(self):
        text = (COMPONENTS_DIR / "CommandPalette.tsx").read_text(encoding="utf-8")
        # Verify the pattern: const timer = setTimeout(...); return () => clearTimeout(timer);
        assert "const timer = setTimeout" in text, "Missing timer variable assignment"
        assert "clearTimeout(timer)" in text, "Missing clearTimeout(timer) cleanup"


# ── 3. No unguarded setTimeout/setInterval in useEffect ───────

class TestNoUnguardedTimers:
    """All useEffect hooks with timers should have cleanup returns."""

    def test_command_palette_all_effects_have_cleanup(self):
        text = (COMPONENTS_DIR / "CommandPalette.tsx").read_text(encoding="utf-8")
        # Find all useEffect blocks and verify they have return statements
        effects = list(re.finditer(r"useEffect\(\s*\(\)\s*=>\s*\{", text))
        for m in effects:
            # Get the effect body (next 500 chars)
            body = text[m.start():m.start() + 500]
            has_timer = "setTimeout" in body or "setInterval" in body
            has_listener = "addEventListener" in body
            if has_timer or has_listener:
                assert "return" in body, (
                    f"useEffect at offset {m.start()} has timer/listener but no cleanup return"
                )
