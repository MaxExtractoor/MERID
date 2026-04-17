"""Tests for merid.startup_validations — live-mode safety checks.

Covers:
  - BUG-3b: KALSHI_ENV/KALSHI_USE_DEMO consistency guard
  - BUG-3b: Live RSA credential presence check
  - Existing guards: smoke test interlock, grace window, PM-live double-key
"""
from __future__ import annotations

import pytest

from merid.startup_validations import StartupValidationError, validate_env_for_live_mode


# ── Helpers ──────────────────────────────────────────────────────────────────

def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set env to a minimally valid non-live configuration (demo mode, paper PM)."""
    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.setenv("KALSHI_USE_DEMO", "true")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "paper")
    monkeypatch.delenv("MERID_PM_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("MERID_PM_PROFILE", raising=False)
    monkeypatch.delenv("KALSHI_TRADER_SMOKE_TEST", raising=False)
    monkeypatch.setenv("MERID_PROMOTION_GRACE_S", "30")


def _live_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set env to the canonical production-live profile (all guards satisfied)."""
    _base_env(monkeypatch)
    monkeypatch.setenv("KALSHI_ENV", "live")
    monkeypatch.setenv("KALSHI_USE_DEMO", "false")
    monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
    monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "true")
    monkeypatch.setenv("MERID_KALSHI_WS_CLIENT", "ws")
    monkeypatch.delenv("MERID_ENABLE_KALSHI_CT", raising=False)
    # Live credentials
    monkeypatch.setenv("KALSHI_LIVE_API_KEY_ID", "test-key-id")
    monkeypatch.setenv("KALSHI_LIVE_PRIVATE_KEY_PATH", "/tmp/fake.pem")


# ── KALSHI_ENV / KALSHI_USE_DEMO consistency ─────────────────────────────────

class TestKalshiEnvUseDemo:
    def test_live_env_with_use_demo_true_raises(self, monkeypatch):
        """KALSHI_ENV=live + KALSHI_USE_DEMO=true is contradictory — must block."""
        _live_env(monkeypatch)
        monkeypatch.setenv("KALSHI_USE_DEMO", "true")  # contradicts KALSHI_ENV=live

        with pytest.raises(StartupValidationError) as exc_info:
            validate_env_for_live_mode()

        assert "KALSHI_USE_DEMO" in str(exc_info.value)
        assert "contradictory" in str(exc_info.value).lower()

    def test_live_env_with_use_demo_false_passes_consistency(self, monkeypatch):
        """KALSHI_ENV=live + KALSHI_USE_DEMO=false is consistent — should not raise on that check."""
        _live_env(monkeypatch)
        # _live_env already sets KALSHI_USE_DEMO=false and all live credentials
        validate_env_for_live_mode()  # must not raise

    def test_demo_env_with_use_demo_true_passes(self, monkeypatch):
        """KALSHI_ENV=demo + KALSHI_USE_DEMO=true is the normal demo config — fine."""
        _base_env(monkeypatch)
        validate_env_for_live_mode()  # must not raise


# ── Live RSA credential presence ─────────────────────────────────────────────

class TestLiveCredentialPresence:
    def test_live_env_missing_api_key_raises(self, monkeypatch):
        """KALSHI_ENV=live without any API key ID must block startup."""
        _live_env(monkeypatch)
        monkeypatch.delenv("KALSHI_LIVE_API_KEY_ID", raising=False)
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)

        with pytest.raises(StartupValidationError) as exc_info:
            validate_env_for_live_mode()

        msg = str(exc_info.value)
        assert "API key" in msg or "key ID" in msg.lower()

    def test_live_env_missing_private_key_raises(self, monkeypatch):
        """KALSHI_ENV=live without any RSA private key must block startup."""
        _live_env(monkeypatch)
        monkeypatch.delenv("KALSHI_LIVE_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("KALSHI_LIVE_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)

        with pytest.raises(StartupValidationError) as exc_info:
            validate_env_for_live_mode()

        msg = str(exc_info.value)
        assert "private key" in msg.lower() or "RSA" in msg

    def test_live_env_legacy_key_accepted(self, monkeypatch):
        """Legacy KALSHI_API_KEY_ID + KALSHI_PRIVATE_KEY_PATH also satisfies the check."""
        _live_env(monkeypatch)
        monkeypatch.delenv("KALSHI_LIVE_API_KEY_ID", raising=False)
        monkeypatch.delenv("KALSHI_LIVE_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.setenv("KALSHI_API_KEY_ID", "legacy-key-id")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/tmp/legacy.pem")

        validate_env_for_live_mode()  # must not raise

    def test_demo_env_no_credentials_is_fine(self, monkeypatch):
        """Demo mode must not be blocked by missing live credentials."""
        _base_env(monkeypatch)
        monkeypatch.delenv("KALSHI_LIVE_API_KEY_ID", raising=False)
        monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
        monkeypatch.delenv("KALSHI_LIVE_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)

        validate_env_for_live_mode()  # must not raise — demo doesn't need live keys


# ── Pre-existing guards (regression) ────────────────────────────────────────

class TestExistingGuards:
    def test_smoke_test_flag_blocks_regardless_of_mode(self, monkeypatch):
        _base_env(monkeypatch)
        monkeypatch.setenv("KALSHI_TRADER_SMOKE_TEST", "true")

        with pytest.raises(StartupValidationError) as exc_info:
            validate_env_for_live_mode()

        assert "KALSHI_TRADER_SMOKE_TEST" in str(exc_info.value)

    def test_grace_window_too_large_blocks(self, monkeypatch):
        _base_env(monkeypatch)
        monkeypatch.setenv("MERID_PROMOTION_GRACE_S", "120")

        with pytest.raises(StartupValidationError) as exc_info:
            validate_env_for_live_mode()

        assert "MERID_PROMOTION_GRACE_S" in str(exc_info.value)

    def test_pm_live_mode_without_live_enabled_blocks(self, monkeypatch):
        """MERID_PM_TRADING_MODE=live without MERID_PM_LIVE_ENABLED blocks."""
        _base_env(monkeypatch)
        monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
        monkeypatch.setenv("MERID_PM_LIVE_ENABLED", "false")

        with pytest.raises(StartupValidationError) as exc_info:
            validate_env_for_live_mode()

        assert "MERID_PM_LIVE_ENABLED" in str(exc_info.value)
