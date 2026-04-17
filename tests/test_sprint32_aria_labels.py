"""Tests for Sprint 32 — aria-label on Select and Input Elements."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"


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


# ── 1. All selects have aria-label ─────────────────────────────

class TestSelectAriaLabels:
    """All select elements should have aria-label or aria-labelledby."""

    def test_no_selects_without_aria_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for start, tag in _find_jsx_tags(text, "select"):
                if "aria-label" not in tag and "aria-labelledby" not in tag:
                    line = text[:start].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Selects without aria-label: {violations}"

    def test_no_selects_without_aria_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for start, tag in _find_jsx_tags(text, "select"):
                if "aria-label" not in tag and "aria-labelledby" not in tag:
                    line = text[:start].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Selects without aria-label: {violations}"


# ── 2. All inputs have aria-label ──────────────────────────────

class TestInputAriaLabels:
    """All input elements should have aria-label (except hidden)."""

    def test_no_inputs_without_aria_in_views(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for start, tag in _find_jsx_tags(text, "input"):
                if 'type="hidden"' in tag:
                    continue
                if "aria-label" not in tag and "aria-labelledby" not in tag:
                    line = text[:start].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Inputs without aria-label: {violations}"

    def test_no_inputs_without_aria_in_components(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            for start, tag in _find_jsx_tags(text, "input"):
                if 'type="hidden"' in tag:
                    continue
                if "aria-label" not in tag and "aria-labelledby" not in tag:
                    line = text[:start].count("\n") + 1
                    violations.append(f"{f.name}:{line}")
        assert len(violations) == 0, f"Inputs without aria-label: {violations}"


# ── 3. Sanity: aria-label count ────────────────────────────────

class TestAriaLabelCount:
    """Verify a reasonable number of aria-labels exist."""

    def test_aria_labels_exist(self):
        count = 0
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                count += len(re.findall(r'aria-label="[^"]+"', text))
        # We fixed 89 elements, so there should be at least 80
        assert count >= 80, f"Expected >=80 aria-labels, got {count}"
