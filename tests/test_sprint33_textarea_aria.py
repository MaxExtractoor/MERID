"""Tests for Sprint 33 — aria-label on Textarea Elements."""
import re
from pathlib import Path

import pytest


def _find_jsx_tags(text: str, tag: str):
    """Yield (start, full_tag_str) for JSX opening tags, handling braces."""
    pattern = re.compile(rf"<{tag}\b")
    for m in pattern.finditer(text):
        start = m.start()
        i = m.end()
        depth = 0
        while i < len(text):
            ch = text[i]
            if ch == '{': depth += 1
            elif ch == '}': depth -= 1
            elif ch == '>' and depth == 0:
                yield start, text[start:i+1]
                break
            elif ch == '/' and i + 1 < len(text) and text[i+1] == '>' and depth == 0:
                yield start, text[start:i+2]
                break
            i += 1

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"


# ── 1. All textareas have aria-label ──────────────────────────

class TestTextareaAriaLabels:
    """All textarea elements should have aria-label."""

    def test_no_textareas_without_aria_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for start, tag in _find_jsx_tags(text, "textarea"):
                if "aria-label" not in tag:
                    line = text[:start].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Textareas without aria-label: {violations}"

    def test_no_textareas_without_aria_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for start, tag in _find_jsx_tags(text, "textarea"):
                if "aria-label" not in tag:
                    line = text[:start].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Textareas without aria-label: {violations}"


# ── 2. Comprehensive form element a11y check ──────────────────

class TestFormElementA11y:
    """All form elements (select, input, textarea) have aria-label."""

    def test_all_selects_labeled(self):
        violations = []
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                for start, tag in _find_jsx_tags(text, "select"):
                    if "aria-label" not in tag and "aria-labelledby" not in tag:
                        violations.append(f.name)
        assert len(violations) == 0

    def test_all_inputs_labeled(self):
        violations = []
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                for start, tag in _find_jsx_tags(text, "input"):
                    if 'type="hidden"' in tag:
                        continue
                    if "aria-label" not in tag and "aria-labelledby" not in tag:
                        violations.append(f.name)
        assert len(violations) == 0

    def test_all_textareas_labeled(self):
        violations = []
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                for start, tag in _find_jsx_tags(text, "textarea"):
                    if "aria-label" not in tag and "aria-labelledby" not in tag:
                        violations.append(f.name)
        assert len(violations) == 0
