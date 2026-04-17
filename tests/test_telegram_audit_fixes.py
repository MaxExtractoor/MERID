"""Regression tests for Telegram / Risk Audit Fixes (Bugs 8-14).

Covers:
  BUG-8:  TelegramAgent reads credentials from settings, not just env vars
  BUG-9:  send_portfolio_dashboard no longer hardcodes "Kalshi BTC Swarm"
  BUG-10: reconciliation_alerts.telegram_handler imports tg_send (not non-existent module)
  BUG-11: reconciliation_alerts.webhook_handler imports send_alert (not non-existent func)
  BUG-12: wire_standard_handlers checks settings for TG creds, not just env
  BUG-13: kill_switches.py has Dict/Any in typing imports
  BUG-14: CT calls balance_calibrator.update() after fetching balance
"""

from __future__ import annotations

import ast
import importlib
import inspect
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent


# ── BUG-8: TelegramAgent reads from settings ─────────────────────────

class TestTelegramAgentCredentialSources:
    """BUG-8: TelegramAgent must read from settings first, then env vars."""

    def test_init_reads_from_settings(self):
        """TelegramAgent.__init__ should try merid.settings before os.getenv."""
        src = (ROOT / "agents" / "telegram_agent.py").read_text(encoding="utf-8")
        assert "merid.settings" in src, "TelegramAgent must import from merid.settings"
        assert "TELEGRAM_TOKEN" in src, "Must check settings.TELEGRAM_TOKEN"

    def test_init_falls_back_to_all_env_vars(self):
        """TelegramAgent should check TELEGRAM_BOT_TOKEN, TELEGRAM_TOKEN, TG_BOT_TOKEN."""
        src = (ROOT / "agents" / "telegram_agent.py").read_text(encoding="utf-8")
        assert "TELEGRAM_BOT_TOKEN" in src
        assert "TELEGRAM_TOKEN" in src
        assert "TG_BOT_TOKEN" in src

    def test_chat_id_reads_from_settings(self):
        """TelegramAgent must also read TELEGRAM_CHAT_ID from settings."""
        src = (ROOT / "agents" / "telegram_agent.py").read_text(encoding="utf-8")
        assert "TELEGRAM_CHAT_ID" in src


# ── BUG-9: Portfolio dashboard not BTC-centric ───────────────────────

class TestPortfolioDashboardTitle:
    """BUG-9: send_portfolio_dashboard should not say 'BTC Swarm'."""

    def test_no_btc_swarm_hardcode(self):
        src = (ROOT / "merid" / "alerts" / "webhook_client.py").read_text(encoding="utf-8")
        assert "Kalshi BTC Swarm" not in src, "Hardcoded 'Kalshi BTC Swarm' must be removed"

    def test_uses_generic_title(self):
        src = (ROOT / "merid" / "alerts" / "webhook_client.py").read_text(encoding="utf-8")
        assert "Kalshi Portfolio" in src, "Dashboard title should be 'Kalshi Portfolio'"


# ── BUG-10: reconciliation telegram_handler uses tg_send ─────────────

class TestReconciliationTelegramHandler:
    """BUG-10: telegram_handler must import tg_send from webhook_client."""

    def test_imports_tg_send(self):
        src = (ROOT / "merid" / "alerts" / "reconciliation_alerts.py").read_text(encoding="utf-8")
        assert "from merid.alerts.webhook_client import tg_send" in src
        assert "from merid.alerts.telegram_client" not in src, (
            "Non-existent merid.alerts.telegram_client import must be removed"
        )


# ── BUG-11: reconciliation webhook_handler uses send_alert ───────────

class TestReconciliationWebhookHandler:
    """BUG-11: webhook_handler must import send_alert from webhook_client."""

    def test_imports_send_alert(self):
        src = (ROOT / "merid" / "alerts" / "reconciliation_alerts.py").read_text(encoding="utf-8")
        assert "from merid.alerts.webhook_client import send_alert" in src
        assert "post_webhook_json" not in src, (
            "Non-existent post_webhook_json import must be removed"
        )


# ── BUG-12: wire_standard_handlers checks settings ──────────────────

class TestWireStandardHandlers:
    """BUG-12: wire_standard_handlers must check settings, not just env."""

    def test_checks_settings_for_tg_creds(self):
        src = (ROOT / "merid" / "alerts" / "reconciliation_alerts.py").read_text(encoding="utf-8")
        assert "merid.settings" in src, "wire_standard_handlers must check merid.settings"

    def test_does_not_only_check_telegram_bot_token(self):
        """Should not rely solely on TELEGRAM_BOT_TOKEN env var."""
        src = (ROOT / "merid" / "alerts" / "reconciliation_alerts.py").read_text(encoding="utf-8")
        # The old buggy code had: if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        # New code should check settings first
        lines = src.split("\n")
        for i, line in enumerate(lines):
            if "wire_standard_handlers" in line and "def " in line:
                # Find the function body and check it reads from settings
                body = "\n".join(lines[i:i+30])
                assert "TELEGRAM_TOKEN" in body, "Must check TELEGRAM_TOKEN from settings"
                break


# ── BUG-13: kill_switches.py has Dict/Any imports ────────────────────

class TestKillSwitchesImports:
    """BUG-13: kill_switches.py must import Dict and Any from typing."""

    def test_dict_imported(self):
        src = (ROOT / "merid" / "risk" / "kill_switches.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        typing_imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "typing":
                for alias in node.names:
                    typing_imports.add(alias.name)
        assert "Dict" in typing_imports, "Dict must be imported from typing"
        assert "Any" in typing_imports, "Any must be imported from typing"

    def test_compiles(self):
        import py_compile
        py_compile.compile(
            str(ROOT / "merid" / "risk" / "kill_switches.py"), doraise=True
        )


# ── BUG-14: CT calls balance_calibrator.update() ────────────────────

class TestCTBalanceCalibration:
    """BUG-14: CT must call balance_calibrator.update() every cycle."""

    def test_ct_imports_balance_calibrator(self):
        src = (ROOT / "merid" / "trading" / "kalshi_continuous_trader.py").read_text(encoding="utf-8")
        assert "balance_calibrator" in src, (
            "CT must import balance_calibrator for risk limit recalibration"
        )

    def test_ct_calls_update(self):
        src = (ROOT / "merid" / "trading" / "kalshi_continuous_trader.py").read_text(encoding="utf-8")
        assert "get_balance_calibrator().update(balance_cents)" in src, (
            "CT must call get_balance_calibrator().update(balance_cents)"
        )

    def test_calibration_after_get_balance(self):
        """Calibration call should appear after _get_balance()."""
        src = (ROOT / "merid" / "trading" / "kalshi_continuous_trader.py").read_text(encoding="utf-8")
        get_balance_pos = src.index("self._get_balance()")
        calibrator_pos = src.index("get_balance_calibrator().update(balance_cents)")
        assert calibrator_pos > get_balance_pos, (
            "balance_calibrator.update() must be called AFTER _get_balance()"
        )


# ── Compile check for all modified files ─────────────────────────────

class TestAllModifiedFilesCompile:
    """Ensure all files modified in this audit session compile."""

    MODIFIED_FILES = [
        "agents/telegram_agent.py",
        "merid/alerts/reconciliation_alerts.py",
        "merid/alerts/webhook_client.py",
        "merid/risk/kill_switches.py",
        "merid/trading/kalshi_continuous_trader.py",
    ]

    @pytest.mark.parametrize("rel_path", MODIFIED_FILES)
    def test_compile(self, rel_path: str):
        import py_compile
        full = ROOT / rel_path
        assert full.exists(), f"{rel_path} not found"
        py_compile.compile(str(full), doraise=True)
