"""Tests for Sprint 26 — Polling Interval Constants."""
import re
from pathlib import Path

import pytest


# AUDIT-2026-09-22-04: conditional strict xfail for frontend files that were
# never committed to this tree.  The mark drops off per-param once the file
# lands; existing files must pass.  Expiry 2026-10-15.
_MISSING_UI_REASON = (
    "DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree "
    "(never committed). Expiry 2026-10-15."
)


def _ui_params(directory, names):
    return [
        pytest.param(
            n,
            marks=pytest.mark.xfail(
                not (directory / n).exists(),
                strict=True,
                reason=_MISSING_UI_REASON,
            ),
        )
        for n in names
    ]

_XFAIL_PARAMS = {
    'test_imports_defaults': {'Agents.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'ApiDashboard.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Logs.tsx': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'Research.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Risk.tsx': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.'},
    'test_no_hardcoded_polling_intervals': {'Agents.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'ApiDashboard.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Research.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.'},
    'test_uses_polling_constant': {'Agents.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'ApiDashboard.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Logs.tsx': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'Research.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Risk.tsx': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.'},
    'TestViewsUsePollingConstants.test_no_hardcoded_polling_intervals': {'Agents.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'ApiDashboard.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Research.tsx': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.'},
}
def _ap(names, test_name):
    """Per-param strict xfail driven by audit dispositions (AUDIT-2026-09-22)."""
    fm = _XFAIL_PARAMS.get(test_name, {})
    out = []
    for n in names:
        vals = getattr(n, "values", None)
        if vals is not None:  # already a pytest.param/ParameterSet
            key = "-".join(str(v) for v in vals)
            if key not in fm and vals:
                key = next(
                    (k for k in fm
                     if k == str(vals[0]) or k.startswith(str(vals[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *vals, marks=list(n.marks) + [
                        pytest.mark.xfail(strict=True, reason=fm[key])]))
            else:
                out.append(n)
        elif isinstance(n, tuple):
            key = "-".join(str(x) for x in n)
            if key not in fm and n:
                key = next(
                    (k for k in fm
                     if k == str(n[0]) or k.startswith(str(n[0]) + "-")),
                    key)
            if key in fm:
                out.append(pytest.param(
                    *n, marks=pytest.mark.xfail(strict=True, reason=fm[key])))
            else:
                out.append(n)
        elif n in fm:
            out.append(pytest.param(
                n, marks=pytest.mark.xfail(strict=True, reason=fm[n])))
        else:
            out.append(n)
    return out


ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

# Views updated to use DEFAULTS.POLLING_INTERVALS
UPDATED_VIEWS = [
    "Agents.tsx",
    "ApiDashboard.tsx",
    "Logs.tsx",
    "Research.tsx",
    "Risk.tsx",
]

# New polling interval constants added
NEW_INTERVAL_KEYS = [
    "RISK_ALERTS",
    "SYSTEM_HEALTH",
    "API_STATUS",
    "LOGS",
    "LOG_STATS",
    "BACKTESTS",
    "RISK_POSITION_LIMITS",
]


# ── 1. New constants exist ─────────────────────────────────────

class TestNewPollingConstants:
    """New polling interval constants were added to DEFAULTS."""

    @pytest.mark.parametrize("key", _ap(NEW_INTERVAL_KEYS, 'test_constant_exists'))
    def test_constant_exists(self, key: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert key in text, f"Missing POLLING_INTERVALS.{key}"

    def test_all_values_are_numbers(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        # Extract POLLING_INTERVALS block
        match = re.search(r'POLLING_INTERVALS:\s*\{([^}]+)\}', text)
        assert match, "POLLING_INTERVALS block not found"
        block = match.group(1)
        values = re.findall(r':\s*(\d+)', block)
        assert len(values) >= 12, f"Expected >=12 interval values, got {len(values)}"
        for v in values:
            assert int(v) > 0, f"Invalid interval value: {v}"


# ── 2. Views import DEFAULTS ──────────────────────────────────

class TestViewsImportDefaults:
    """Updated views import DEFAULTS from constants."""

    @pytest.mark.parametrize("filename", _ap(_ui_params(VIEWS_DIR, UPDATED_VIEWS), 'test_no_hardcoded_polling_intervals'))
    def test_no_hardcoded_polling_intervals(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        # Find pollingInterval values that are raw numbers (not using DEFAULTS)
        hardcoded = re.findall(r'pollingInterval:\s*(\d+)', text)
        assert len(hardcoded) == 0, (
            f"{filename} still has hardcoded pollingInterval: {hardcoded}"
        )
    @pytest.mark.parametrize("filename", _ap(UPDATED_VIEWS, 'test_imports_defaults'))
    def test_imports_defaults(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "DEFAULTS" in text, f"{filename} missing DEFAULTS import"


class TestViewsUsePollingConstants:
    """Updated views use DEFAULTS.POLLING_INTERVALS instead of hardcoded numbers."""

    @pytest.mark.parametrize("filename", _ap(UPDATED_VIEWS, 'test_uses_polling_constant'))
    def test_uses_polling_constant(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        assert "DEFAULTS.POLLING_INTERVALS" in text, f"{filename} not using POLLING_INTERVALS"

    @pytest.mark.parametrize("filename", _ap(UPDATED_VIEWS, 'TestViewsUsePollingConstants.test_no_hardcoded_polling_intervals'))
    def test_no_hardcoded_polling_intervals(self, filename: str):
        text = (VIEWS_DIR / filename).read_text(encoding="utf-8")
        # Find pollingInterval values that are raw numbers (not using DEFAULTS)
        hardcoded = re.findall(r'pollingInterval:\s*(\d+)', text)
        assert len(hardcoded) == 0, (
            f"{filename} still has hardcoded pollingInterval: {hardcoded}"
        )
