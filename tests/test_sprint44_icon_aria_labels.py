"""Tests for Sprint 44 — Icon-Only Button aria-labels."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"


# ── 1. No icon-only buttons without aria-label ────────────────

class TestNoIconButtonsWithoutAria:
    """All icon-only buttons must have aria-label."""

    def test_views_no_icon_buttons_without_aria(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r'<button\b([^>]*)>', text):
                attrs = m.group(1)
                if 'aria-label' in attrs:
                    continue
                after = text[m.end():m.end() + 150]
                btn_close = after.find('</button>')
                if btn_close < 0:
                    continue
                between = after[:btn_close].strip()
                text_content = re.sub(r'<[^>]+/?>', '', between).strip()
                if not text_content:
                    line = text[:m.start()].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Icon buttons without aria-label: {violations}"

    def test_components_no_icon_buttons_without_aria(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for m in re.finditer(r'<button\b([^>]*)>', text):
                attrs = m.group(1)
                if 'aria-label' in attrs:
                    continue
                after = text[m.end():m.end() + 150]
                btn_close = after.find('</button>')
                if btn_close < 0:
                    continue
                between = after[:btn_close].strip()
                text_content = re.sub(r'<[^>]+/?>', '', between).strip()
                if not text_content:
                    line = text[:m.start()].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Icon buttons without aria-label: {violations}"
