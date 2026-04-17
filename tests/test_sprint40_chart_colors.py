"""Tests for Sprint 40 — Centralized Chart Colors."""
import re
from pathlib import Path

import pytest

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

    @pytest.mark.parametrize("name", CHART_COLOR_NAMES)
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

    @pytest.mark.parametrize("filename,directory", [
        ("CrossAssetView.tsx", "views"),
        ("Overview.tsx", "views"),
        ("Rewards.tsx", "views"),
        ("DrawdownChart.tsx", "components"),
        ("DomainPnLChart.tsx", "components"),
        ("CodeQualityPanel.tsx", "components"),
    ])
    def test_chart_colors_imported(self, filename: str, directory: str):
        d = VIEWS_DIR if directory == "views" else COMPONENTS_DIR
        text = (d / filename).read_text(encoding="utf-8")
        assert "CHART_COLORS" in text, f"{filename} should use CHART_COLORS"
