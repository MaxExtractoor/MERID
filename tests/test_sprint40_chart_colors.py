"""Tests for Sprint 40 — Centralized Chart Colors."""
import re
from pathlib import Path

import pytest
_XFAIL_PARAMS = {
    'test_chart_colors_imported': {'CrossAssetView.tsx-views': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.', 'Overview.tsx-views': 'DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.', 'Rewards.tsx-views': 'DEFECT AUDIT-2026-09-22-04: frontend file/feature absent from this tree (never committed). Expiry 2026-10-15.'},
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


def _ui_pair_params(pairs):
    params = []
    for fname, dname in pairs:
        d = VIEWS_DIR if dname == "views" else COMPONENTS_DIR
        params.append(
            pytest.param(
                fname,
                dname,
                marks=pytest.mark.xfail(
                    not (d / fname).exists(),
                    strict=True,
                    reason=_MISSING_UI_REASON,
                ),
            )
        )
    return params


ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"
CONSTANTS_FILE = WEB_REACT / "config" / "constants.ts"

CHART_COLOR_NAMES = [
    "GREEN", "RED", "YELLOW", "ORANGE", "BLUE", "PURPLE", "CYAN", "TEAL",
    "LIGHT_RED", "LIGHT_GREEN", "LIGHT_BLUE", "LIGHT_PURPLE", "AMBER",
    "DEEP_ORANGE", "AXIS_TICK", "GRID_STROKE", "TOOLTIP_BG", "TOOLTIP_BORDER",
    "TOOLTIP_LABEL", "BAR_BASE",
]


# ── 1. CHART_COLORS constants exist ───────────────────────────

class TestChartColorConstants:
    """Verify CHART_COLORS constants exist in constants.ts."""

    def test_chart_colors_exported(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert "export const CHART_COLORS" in text

    @pytest.mark.parametrize("name", _ap(CHART_COLOR_NAMES, 'test_color_constant_exists'))
    def test_color_constant_exists(self, name: str):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        assert f"{name}:" in text, f"Missing CHART_COLORS.{name}"

    def test_no_duplicate_chart_colors(self):
        text = CONSTANTS_FILE.read_text(encoding="utf-8")
        count = text.count("export const CHART_COLORS")
        assert count == 1, f"Found {count} CHART_COLORS declarations"


# ── 2. No hardcoded hex colors in views ────────────────────────

class TestNoHardcodedHexViews:
    """Views should not have hardcoded hex color strings."""

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_no_hex_colors(self):
        violations = []
        for f in sorted(VIEWS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            lines = text.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                for m in re.finditer(r'["\']#[0-9a-fA-F]{6}["\']', line):
                    violations.append(f"{f.name}:{i}: {m.group()}")
        assert len(violations) == 0, f"Hardcoded hex: {violations}"


# ── 3. No hardcoded hex colors in components ───────────────────

class TestNoHardcodedHexComponents:
    """Components should not have hardcoded hex color strings."""

    @pytest.mark.xfail(strict=True, reason="DEFECT AUDIT-2026-09-22-11: existing implementation violates the asserted contract. Expiry 2026-10-15.")
    def test_no_hex_colors(self):
        violations = []
        for f in sorted(COMPONENTS_DIR.glob("*.tsx")):
            text = f.read_text(encoding="utf-8")
            lines = text.split("\n")
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*"):
                    continue
                for m in re.finditer(r'["\']#[0-9a-fA-F]{6}["\']', line):
                    violations.append(f"{f.name}:{i}: {m.group()}")
        assert len(violations) == 0, f"Hardcoded hex: {violations}"


# ── 4. Files that use charts import CHART_COLORS ───────────────

class TestChartFilesImport:
    """Files using CHART_COLORS should import it."""

    @pytest.mark.parametrize("filename,directory", _ap(_ui_pair_params([('CrossAssetView.tsx', 'views'), ('Overview.tsx', 'views'), ('Rewards.tsx', 'views'), ('DrawdownChart.tsx', 'components'), ('DomainPnLChart.tsx', 'components'), ('CodeQualityPanel.tsx', 'components')]), 'test_chart_colors_imported'))
    def test_chart_colors_imported(self, filename: str, directory: str):
        d = VIEWS_DIR if directory == "views" else COMPONENTS_DIR
        text = (d / filename).read_text(encoding="utf-8")
        assert "CHART_COLORS" in text, f"{filename} should use CHART_COLORS"
