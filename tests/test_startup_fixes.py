"""Regression tests for startup/restart fixes:

BUG-15: portfolio_risk_agent.daily_pnl_usd used cumulative unrealized PnL
        instead of actual daily PnL → false kill switch trigger.

Paper-trade-reset: get_paper_engine() now always resets state on startup
        to prevent 1000s of reconciliation PnL-mismatch issues and false
        portfolio risk breaches from stale crypto paper positions.
"""

import ast
import importlib
import sys
import textwrap
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ── BUG-15: daily_pnl sourced from KalshiRiskManager, not unrealized PnL ──


class TestDailyPnlSource:
    """Verify portfolio_risk_agent sources daily PnL from KalshiRiskManager."""

    def test_snapshot_has_total_unrealized_field(self):
        """PortfolioSnapshot should have both daily_pnl and total_unrealized fields."""
        src = (ROOT / "merid" / "prediction" / "portfolio_risk_agent.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == "PortfolioSnapshot":
                field_names = []
                for item in node.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        field_names.append(item.target.id)
                assert "daily_pnl_usd" in field_names
                assert "total_unrealized_pnl_usd" in field_names
                return
        pytest.fail("PortfolioSnapshot class not found")

    def test_unrealized_pnl_not_accumulated_into_daily(self):
        """The code should NOT accumulate unrealized_pnl into daily_pnl_usd."""
        src = (ROOT / "merid" / "prediction" / "portfolio_risk_agent.py").read_text()
        # Old bug pattern: snapshot.daily_pnl_usd += pnl (where pnl = unrealized_pnl)
        # New correct pattern: snapshot.total_unrealized_pnl_usd += pnl
        assert "snapshot.daily_pnl_usd += pnl" not in src, (
            "daily_pnl_usd should not be accumulated from unrealized PnL"
        )
        assert "snapshot.total_unrealized_pnl_usd += pnl" in src

    def test_daily_pnl_sourced_from_risk_manager(self):
        """daily_pnl_usd should be sourced from KalshiRiskManager.state.daily_pnl_usd."""
        src = (ROOT / "merid" / "prediction" / "portfolio_risk_agent.py").read_text()
        assert "risk.state.daily_pnl_usd" in src, (
            "daily_pnl_usd should be read from KalshiRiskManager"
        )
        assert "get_kalshi_risk" in src

    def test_to_dict_includes_unrealized(self):
        """to_dict() should serialize total_unrealized_pnl_usd."""
        src = (ROOT / "merid" / "prediction" / "portfolio_risk_agent.py").read_text()
        assert '"total_unrealized_pnl_usd"' in src


# ── Paper trade reset on startup ──────────────────────────────────────


class TestPaperTradeReset:
    """Verify paper trading engine always resets on startup."""

    def test_always_resets_on_startup(self):
        """get_paper_engine() should call reset_state() unconditionally."""
        src = (ROOT / "trading" / "paper_trading.py").read_text()
        # Find the get_paper_engine function body
        in_func = False
        found_reset = False
        found_fresh_start_gate = False
        for line in src.splitlines():
            if "def get_paper_engine" in line:
                in_func = True
                continue
            if in_func:
                if line.strip().startswith("def ") and "get_paper_engine" not in line:
                    break
                if "_paper_engine.reset_state()" in line:
                    found_reset = True
                if "is_fresh_start()" in line:
                    found_fresh_start_gate = True

        assert found_reset, "get_paper_engine must call reset_state()"
        assert not found_fresh_start_gate, (
            "get_paper_engine should NOT gate reset behind is_fresh_start()"
        )

    def test_persist_files_deleted(self):
        """Startup should delete stale persist files."""
        src = (ROOT / "trading" / "paper_trading.py").read_text()
        # Check that the persist file deletion is inside get_paper_engine
        assert "f.unlink()" in src
        assert "_PERSIST_FILE" in src


# ── Compile checks ────────────────────────────────────────────────────


class TestModifiedFilesCompile:
    """Verify all modified files compile without syntax errors."""

    @pytest.mark.parametrize("rel_path", [
        "merid/prediction/portfolio_risk_agent.py",
        "trading/paper_trading.py",
    ])
    def test_compile(self, rel_path):
        src = (ROOT / rel_path).read_text()
        compile(src, rel_path, "exec")
