"""Tests for Sprint 47 — Backend print() → logging migration."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MERID_DIR = ROOT / "merid"
WEB_API_DIR = ROOT / "web" / "api"

# Files that are allowed to keep print() (CLI output, docstrings, multi-line)
ALLOWLISTED_PRINTS = {
    "agent_gauntlet.py": 3,      # CLI summary output
    "promotion_report.py": 3,    # CLI report formatting
    "ui_views_manifest.py": 3,   # JSON dump + blank lines
    "backtest.py": 1,            # docstring usage example
}


class TestNoPrintStatements:
    """Backend Python files should use logging, not print()."""

    def _count_prints(self, directory: Path) -> dict:
        """Count non-comment print() calls per file."""
        results = {}
        if not directory.exists():
            return results
        for f in directory.rglob("*.py"):
            text = f.read_text(encoding="utf-8", errors="ignore")
            count = 0
            for line in text.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Skip docstring examples (>>> print)
                if stripped.startswith(">>>"):
                    continue
                if "print(" in line:
                    count += 1
            if count > 0:
                results[f.name] = count
        return results

    def test_merid_no_prints(self):
        """merid/ should have no print() except allowlisted CLI files."""
        prints = self._count_prints(MERID_DIR)
        violations = {}
        for fname, count in prints.items():
            allowed = ALLOWLISTED_PRINTS.get(fname, 0)
            if count > allowed:
                violations[fname] = count
        assert len(violations) == 0, f"Unexpected print() in merid/: {violations}"

    def test_web_api_no_prints(self):
        """web/api/ should have no print() statements."""
        prints = self._count_prints(WEB_API_DIR)
        assert len(prints) == 0, f"print() in web/api/: {prints}"


class TestLoggingSetup:
    """Backend files that do logging should have proper logger setup."""

    def test_files_with_logger_calls_have_logger(self):
        """Files using logger.X() should have a logger definition."""
        violations = []
        for d in [MERID_DIR, WEB_API_DIR]:
            if not d.exists():
                continue
            for f in d.rglob("*.py"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                # Only check non-docstring lines for logger calls
                has_logger_call = False
                in_docstring = False
                for line in text.split("\n"):
                    stripped = line.strip()
                    if stripped.startswith('"""') or stripped.startswith("'''"):
                        if stripped.count('"""') == 1 or stripped.count("'''") == 1:
                            in_docstring = not in_docstring
                        continue
                    if in_docstring:
                        continue
                    if re.search(r'\blogger\.(info|warning|error|debug)\(', line):
                        has_logger_call = True
                        break
                has_logger_def = bool(
                    re.search(r'logger\s*=\s*logging\.getLogger', text)
                    or re.search(r'logger\s*=\s*get_logger', text)
                    or re.search(r'from\s+utils\.logger\s+import', text)
                    or re.search(r'import\s+logging', text)
                )
                if has_logger_call and not has_logger_def:
                    violations.append(f.name)
        assert len(violations) == 0, f"Files using logger without getLogger: {violations}"


class TestNoBareExcept:
    """Backend should not use bare except: (use except Exception:)."""

    def test_no_bare_except(self):
        violations = []
        for d in [MERID_DIR, WEB_API_DIR]:
            if not d.exists():
                continue
            for f in d.rglob("*.py"):
                text = f.read_text(encoding="utf-8", errors="ignore")
                for i, line in enumerate(text.split("\n"), 1):
                    if re.match(r'\s*except\s*:', line):
                        violations.append(f"{f.name}:L{i}")
        assert len(violations) == 0, f"Bare except: found: {violations}"
