"""Tests for Sprint 38 — Duplicate Interface Disambiguation."""
import re
from pathlib import Path
from collections import defaultdict

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB_REACT = ROOT / "web" / "react" / "src"
VIEWS_DIR = WEB_REACT / "views"
COMPONENTS_DIR = WEB_REACT / "components"

# Renamed interfaces
RENAMES = {
    "ExplainabilityDecision": "ExplainabilityPanel.tsx",
    "ConsensusPanelStatus": "ConsensusPanel.tsx",
    "PredictionDriftSignal": "Predictions.tsx",
    "LiveNotification": "LiveNotifications.tsx",
    "ActivityOrder": "OperatorActivityStream.tsx",
    "TradingOrder": "Trading.tsx",
    "CrossAssetPosition": "CrossAssetView.tsx",
    "TradingPosition": "Trading.tsx",
    "FundingProposal": "QuadraticFundingPanel.tsx",
    "TradeTableRow": "TradesTable.tsx",
}


# ── 1. Renamed interfaces exist in their files ────────────────

class TestRenamedInterfaces:
    """Verify renamed interfaces exist in their target files."""

    @pytest.mark.parametrize("name,filename", list(RENAMES.items()))
    def test_renamed_interface_exists(self, name: str, filename: str):
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            fpath = d / filename
            if fpath.exists():
                text = fpath.read_text(encoding="utf-8")
                assert f"interface {name}" in text, f"{filename} should have interface {name}"
                return
        pytest.fail(f"File {filename} not found")


# ── 2. No duplicate interface names ───────────────────────────

class TestNoDuplicateInterfaces:
    """No interface name should appear in more than one file."""

    def test_no_duplicates(self):
        interfaces = defaultdict(list)
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            for f in sorted(d.glob("*.tsx")):
                text = f.read_text(encoding="utf-8")
                for m in re.finditer(r"interface\s+(\w+)\s*\{", text):
                    name = m.group(1)
                    interfaces[name].append(f.name)

        duplicates = {k: v for k, v in interfaces.items() if len(v) > 1}
        assert len(duplicates) == 0, f"Duplicate interfaces: {duplicates}"


# ── 3. Old names no longer exist in renamed files ─────────────

class TestOldNamesRemoved:
    """Old interface names should not exist in renamed files."""

    OLD_NAMES = {
        ("ExplainabilityPanel.tsx", "AgentDecision"),
        ("ConsensusPanel.tsx", "ConsensusStatus"),
        ("LiveNotifications.tsx", "Notification"),
        ("QuadraticFundingPanel.tsx", "Proposal"),
        ("TradesTable.tsx", "TradeEvent"),
    }

    @pytest.mark.parametrize("filename,old_name", list(OLD_NAMES))
    def test_old_name_removed(self, filename: str, old_name: str):
        for d in [VIEWS_DIR, COMPONENTS_DIR]:
            fpath = d / filename
            if fpath.exists():
                text = fpath.read_text(encoding="utf-8")
                assert f"interface {old_name} " not in text, \
                    f"{filename} should not have interface {old_name}"
                return
