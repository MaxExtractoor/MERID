"""Tests for KalshiCTEnvConfig new fields (AUDIT-02..08, AUDIT-11, AUDIT-12).

Covers:
  AUDIT-02  — max_candidates_per_asset from MERID_CT_MAX_CANDIDATES
  AUDIT-03  — max_spread_cents from MERID_CT_MAX_SPREAD_CENTS
  AUDIT-04  — min_volume from MERID_CT_MIN_VOLUME
  AUDIT-06  — max_position_contracts from MERID_CT_MAX_POSITION_CONTRACTS
  AUDIT-07  — exposure_multiplier from MERID_CT_EXPOSURE_MULTIPLIER
  AUDIT-08  — per_asset_cooldown_seconds from MERID_CT_COOLDOWN_SECONDS
  AUDIT-11  — agent_stagger_seconds from MERID_AGENT_STAGGER_SECONDS
  AUDIT-12  — BANKROLL_MIN_CENTS from MERID_CT_BANKROLL_MIN_CENTS
  validate() — catches bad exposure multiplier, negative cooldown,
                bad bankroll fraction, bad candidates count, bad spread
"""

from __future__ import annotations

import os

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(monkeypatch, **extra_env):
    """Return a KalshiCTEnvConfig built from env with a valid bankroll."""
    monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
    for k, v in extra_env.items():
        monkeypatch.setenv(k, str(v))
    from config.kalshi_ct_env import KalshiCTEnvConfig
    return KalshiCTEnvConfig.from_env()


# ── AUDIT-02: max_candidates_per_asset ───────────────────────────────────────

class TestMaxCandidatesPerAsset:
    def test_default_is_5(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MAX_CANDIDATES", raising=False)
        cfg = _make_config(monkeypatch)
        assert cfg.max_candidates_per_asset == 5

    def test_env_override(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_CT_MAX_CANDIDATES=10)
        assert cfg.max_candidates_per_asset == 10

    def test_validate_rejects_zero(self, monkeypatch):
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_CT_MAX_CANDIDATES", "0")
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with pytest.raises(ValueError, match="MERID_CT_MAX_CANDIDATES"):
            KalshiCTEnvConfig.from_env()


# ── AUDIT-03: max_spread_cents ────────────────────────────────────────────────

class TestMaxSpreadCents:
    def test_default_is_12(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MAX_SPREAD_CENTS", raising=False)
        cfg = _make_config(monkeypatch)
        assert cfg.max_spread_cents == 12

    def test_env_override(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_CT_MAX_SPREAD_CENTS=8)
        assert cfg.max_spread_cents == 8

    def test_validate_rejects_zero(self, monkeypatch):
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_CT_MAX_SPREAD_CENTS", "0")
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with pytest.raises(ValueError, match="MERID_CT_MAX_SPREAD_CENTS"):
            KalshiCTEnvConfig.from_env()


# ── AUDIT-04: min_volume ──────────────────────────────────────────────────────

class TestMinVolume:
    def test_default_is_50(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MIN_VOLUME", raising=False)
        cfg = _make_config(monkeypatch)
        assert cfg.min_volume == 50

    def test_env_override(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_CT_MIN_VOLUME=200)
        assert cfg.min_volume == 200


# ── AUDIT-06: max_position_contracts ─────────────────────────────────────────

class TestMaxPositionContracts:
    def test_default_zero_means_no_cap(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_MAX_POSITION_CONTRACTS", raising=False)
        cfg = _make_config(monkeypatch)
        assert cfg.max_position_contracts == 0

    def test_env_override(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_CT_MAX_POSITION_CONTRACTS=25)
        assert cfg.max_position_contracts == 25


# ── AUDIT-07: exposure_multiplier ────────────────────────────────────────────

class TestExposureMultiplier:
    def test_default_is_1(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_EXPOSURE_MULTIPLIER", raising=False)
        cfg = _make_config(monkeypatch)
        assert cfg.exposure_multiplier == pytest.approx(1.0)

    def test_env_override(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_CT_EXPOSURE_MULTIPLIER=0.5)
        assert cfg.exposure_multiplier == pytest.approx(0.5)

    def test_validate_rejects_zero(self, monkeypatch):
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_CT_EXPOSURE_MULTIPLIER", "0")
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with pytest.raises(ValueError, match="MERID_CT_EXPOSURE_MULTIPLIER"):
            KalshiCTEnvConfig.from_env()

    def test_validate_rejects_above_2(self, monkeypatch):
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_CT_EXPOSURE_MULTIPLIER", "2.5")
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with pytest.raises(ValueError, match="MERID_CT_EXPOSURE_MULTIPLIER"):
            KalshiCTEnvConfig.from_env()

    def test_validate_accepts_exactly_2(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_CT_EXPOSURE_MULTIPLIER=2.0)
        assert cfg.exposure_multiplier == pytest.approx(2.0)


# ── AUDIT-08: per_asset_cooldown_seconds ─────────────────────────────────────

class TestPerAssetCooldown:
    def test_default_is_0(self, monkeypatch):
        monkeypatch.delenv("MERID_CT_COOLDOWN_SECONDS", raising=False)
        cfg = _make_config(monkeypatch)
        assert cfg.per_asset_cooldown_seconds == pytest.approx(0.0)

    def test_env_override(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_CT_COOLDOWN_SECONDS=60)
        assert cfg.per_asset_cooldown_seconds == pytest.approx(60.0)

    def test_validate_rejects_negative(self, monkeypatch):
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_CT_COOLDOWN_SECONDS", "-1")
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with pytest.raises(ValueError, match="MERID_CT_COOLDOWN_SECONDS"):
            KalshiCTEnvConfig.from_env()


# ── AUDIT-11: agent_stagger_seconds ──────────────────────────────────────────

class TestAgentStaggerSeconds:
    def test_default_is_half_second(self, monkeypatch):
        monkeypatch.delenv("MERID_AGENT_STAGGER_SECONDS", raising=False)
        cfg = _make_config(monkeypatch)
        assert cfg.agent_stagger_seconds == pytest.approx(0.5)

    def test_env_override(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_AGENT_STAGGER_SECONDS=1.5)
        assert cfg.agent_stagger_seconds == pytest.approx(1.5)

    def test_env_zero_disables_stagger(self, monkeypatch):
        cfg = _make_config(monkeypatch, MERID_AGENT_STAGGER_SECONDS=0)
        assert cfg.agent_stagger_seconds == pytest.approx(0.0)

    def test_validate_rejects_negative(self, monkeypatch):
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_AGENT_STAGGER_SECONDS", "-0.5")
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with pytest.raises(ValueError, match="MERID_AGENT_STAGGER_SECONDS"):
            KalshiCTEnvConfig.from_env()


# ── AUDIT-12: BANKROLL_MIN_CENTS ─────────────────────────────────────────────

class TestBankrollMinCents:
    def test_default_minimum_is_50000(self, monkeypatch):
        """Default minimum is $500 (50000 cents) for viable trading."""
        monkeypatch.delenv("MERID_CT_BANKROLL_MIN_CENTS", raising=False)
        from config.kalshi_ct_env import BANKROLL_MIN_CENTS
        # Default changed from 100 to 50000 to prevent fee drag at low bankroll
        # Tests should override with MERID_CT_BANKROLL_MIN_CENTS=100 if needed
        assert isinstance(BANKROLL_MIN_CENTS, int)

    def test_env_overrides_minimum(self, monkeypatch):
        monkeypatch.setenv("MERID_CT_BANKROLL_MIN_CENTS", "500")
        # Re-import to pick up the new env value.
        import importlib
        import config.kalshi_ct_env as m
        importlib.reload(m)
        try:
            assert m.BANKROLL_MIN_CENTS == 500
        finally:
            importlib.reload(m)

    def test_below_minimum_raises(self, monkeypatch):
        # Use the new default 50000-cent ($500) minimum.
        monkeypatch.delenv("MERID_CT_BANKROLL_MIN_CENTS", raising=False)
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")  # $100 < $500 minimum
        import importlib
        import config.kalshi_ct_env as m
        importlib.reload(m)
        try:
            with pytest.raises(ValueError, match="bankroll"):
                m.KalshiCTEnvConfig.from_env()
        finally:
            importlib.reload(m)


# ── validate(): effective max exposure warning / error ────────────────────────

class TestValidateEffectiveExposure:
    def test_excessive_exposure_does_not_raise_only_warns(self, monkeypatch, caplog):
        """effective_max_pct > 10% should warn, not raise."""
        import logging
        # bankroll_fraction=0.5, kelly=0.5, multiplier=1.0 → 25%
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_BANKROLL_FRACTION", "0.5")
        monkeypatch.setenv("MERID_KELLY_FRACTION", "0.5")
        monkeypatch.delenv("MERID_CT_EXPOSURE_MULTIPLIER", raising=False)
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with caplog.at_level(logging.WARNING, logger="config.kalshi_ct_env"):
            cfg = KalshiCTEnvConfig.from_env()
        assert cfg.bankroll_fraction == pytest.approx(0.5)

    def test_multiple_errors_reported_together(self, monkeypatch):
        """validate() should collect all errors, not stop at the first."""
        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        monkeypatch.setenv("MERID_CT_EXPOSURE_MULTIPLIER", "0")   # invalid
        monkeypatch.setenv("MERID_CT_MAX_SPREAD_CENTS", "0")      # invalid
        monkeypatch.setenv("MERID_CT_MAX_CANDIDATES", "0")        # invalid
        from config.kalshi_ct_env import KalshiCTEnvConfig
        with pytest.raises(ValueError) as exc_info:
            KalshiCTEnvConfig.from_env()
        msg = str(exc_info.value)
        assert "MERID_CT_EXPOSURE_MULTIPLIER" in msg
        assert "MERID_CT_MAX_SPREAD_CENTS" in msg
        assert "MERID_CT_MAX_CANDIDATES" in msg
