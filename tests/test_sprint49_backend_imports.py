"""Tests for Sprint 49 — Backend duplicate imports + module docstrings."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MERID_DIR = ROOT / "merid"
WEB_API_DIR = ROOT / "web" / "api"


class TestNoDuplicateImports:
    """Backend Python files should not have duplicate import lines."""

    def test_no_duplicate_imports(self):
        violations = []
        for d in [MERID_DIR, WEB_API_DIR]:
            if not d.exists():
                continue
            for f in d.rglob("*.py"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                seen = set()
                for i, line in enumerate(text.split("\n"), 1):
                    stripped = line.strip()
                    # Only check module-level imports (not indented / lazy)
                    if line and line[0] not in (" ", "\t"):
                        if stripped.startswith("import ") or stripped.startswith("from "):
                            if stripped in seen:
                                violations.append(f"{f.name}:L{i}: {stripped[:60]}")
                            seen.add(stripped)
        assert len(violations) == 0, f"Duplicate imports: {violations}"


class TestModuleDocstrings:
    """Non-__init__ backend Python files should have module docstrings."""

    def test_api_files_have_docstrings(self):
        """web/api/ files should have module-level docstrings."""
        violations = []
        for f in sorted(WEB_API_DIR.glob("*.py")):
            if f.name == "__init__.py":
                continue
            text = f.read_text(encoding="utf-8", errors="ignore")
            stripped = text.lstrip()
            if not (stripped.startswith('"""') or stripped.startswith("'''")):
                violations.append(f.name)
        assert len(violations) == 0, f"Missing module docstrings in web/api/: {violations}"
