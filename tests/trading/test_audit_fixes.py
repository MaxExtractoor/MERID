"""Tests for AUDIT-01 through AUDIT-22 audit fixes.

Covers:
  AUDIT-01  — KALSHI_TRADER_BANKROLL required; fail-fast on missing / too low
  AUDIT-05  — Dashboard asset filter chips always show canonical BTC/ETH/SOL/XRP/DOGE
  AUDIT-09  — KALSHI_CT_MIN_EDGE_{ASSET}_{TF} env overrides
  AUDIT-10  — Swarm degraded-mode constants are env-driven
  AUDIT-14  — CT fails fast without credentials (unless dry_run=True)
  AUDIT-15  — Smoke-test guard blocks live-mode flags
  AUDIT-17  — Social broadcaster per-asset throttle
  AUDIT-18  — KalshiCTEnvConfig centralises env reading
  AUDIT-21  — _fetch_spot_prices_with_fallback documented interface
  AUDIT-22  — Per-asset vol anchor (KalshiCryptoRiskEngine.get_vol_anchor)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mock_catalog():
    catalog = MagicMock()
    catalog.get_markets_by_asset.return_value = []
    return catalog


# ── AUDIT-18: KalshiCTEnvConfig ──────────────────────────────────────────────


class TestKalshiCTEnvConfig:
    def test_from_env_reads_bankroll(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "50000")
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.bankroll_cents == 50000

    def test_from_env_missing_bankroll_raises(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.delenv("KALSHI_TRADER_BANKROLL", raising=False)
        with pytest.raises(ValueError, match="KALSHI_TRADER_BANKROLL"):
            KalshiCTEnvConfig.from_env()

    def test_from_env_reads_smoke_test(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")
        monkeypatch.setenv("MERID_SMOKE_TEST", "true")
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.smoke_test is True

    def test_from_env_reads_trade_mode(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")
        monkeypatch.setenv("MERID_TRADE_MODE", "live")
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.trade_mode == "live"

    def test_from_env_reads_min_edge_overrides(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")
        monkeypatch.setenv("KALSHI_CT_MIN_EDGE_BTC_15M", "0.003")
        cfg = KalshiCTEnvConfig.from_env()
        assert ("BTC", "15M") in cfg.min_edge_overrides
        assert cfg.min_edge_overrides[("BTC", "15M")] == pytest.approx(0.003)

    def test_from_env_reads_vol_anchor(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")
        monkeypatch.setenv("KALSHI_CT_VOL_ANCHOR_DOGE", "BTC")
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.vol_anchor_asset.get("DOGE") == "BTC"

    def test_bankroll_dollars_conversion(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "100000")
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.bankroll_dollars() == pytest.approx(1000.0)

    def test_get_min_edge_uses_override(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")
        monkeypatch.setenv("KALSHI_CT_MIN_EDGE_ETH_1H", "0.007")
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.get_min_edge("ETH", "1h", default=0.02) == pytest.approx(0.007)

    def test_get_min_edge_falls_back_to_default(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")
        monkeypatch.delenv("KALSHI_CT_MIN_EDGE_ETH_1H", raising=False)
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.get_min_edge("ETH", "1h", default=0.02) == pytest.approx(0.02)

    def test_get_vol_anchor_self_by_default(self, monkeypatch):
        from config.kalshi_ct_env import KalshiCTEnvConfig

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "10000")
        monkeypatch.delenv("KALSHI_CT_VOL_ANCHOR_ETH", raising=False)
        cfg = KalshiCTEnvConfig.from_env()
        assert cfg.get_vol_anchor("ETH") == "ETH"


# ── AUDIT-01: Bankroll fail-fast ──────────────────────────────────────────────


class TestBankrollFailFast:
    def test_missing_bankroll_raises_value_error(self, monkeypatch):
        from config.kalshi_ct_env import _read_bankroll_cents

        monkeypatch.delenv("KALSHI_TRADER_BANKROLL", raising=False)
        with pytest.raises(ValueError, match="KALSHI_TRADER_BANKROLL is not set"):
            _read_bankroll_cents()

    def test_non_integer_bankroll_raises(self, monkeypatch):
        from config.kalshi_ct_env import _read_bankroll_cents

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", "abc")
        with pytest.raises(ValueError, match="not a valid integer"):
            _read_bankroll_cents()

    def test_too_low_bankroll_raises(self, monkeypatch):
        from config.kalshi_ct_env import _read_bankroll_cents, BANKROLL_MIN_CENTS

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", str(BANKROLL_MIN_CENTS - 1))
        with pytest.raises(ValueError, match="below the minimum"):
            _read_bankroll_cents()

    def test_valid_bankroll_at_minimum(self, monkeypatch):
        from config.kalshi_ct_env import _read_bankroll_cents, BANKROLL_MIN_CENTS

        monkeypatch.setenv("KALSHI_TRADER_BANKROLL", str(BANKROLL_MIN_CENTS))
        assert _read_bankroll_cents() == BANKROLL_MIN_CENTS

    def test_ct_dry_run_bypasses_credential_check(self, monkeypatch):
        """CT with dry_run=True must not raise even without credentials."""
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.delenv("KALSHI_EMAIL", raising=False)
        monkeypatch.delenv("KALSHI_PASSWORD", raising=False)
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        with patch(
            "merid.trading.kalshi_continuous_trader.get_market_catalog",
            return_value=_make_mock_catalog(),
        ):
            # Should NOT raise
            trader = KalshiContinuousTrader(
                catalog=_make_mock_catalog(), dry_run=True
            )
        assert trader._dry_run is True


# ── AUDIT-14: Credential fail-fast ───────────────────────────────────────────


class TestCredentialFailFast:
    def test_no_credentials_raises_without_dry_run(self, monkeypatch):
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.delenv("KALSHI_EMAIL", raising=False)
        monkeypatch.delenv("KALSHI_PASSWORD", raising=False)
        monkeypatch.delenv("MERID_CT_DRY_RUN", raising=False)
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        with patch(
            "merid.trading.kalshi_continuous_trader.get_market_catalog",
            return_value=_make_mock_catalog(),
        ):
            with pytest.raises(RuntimeError, match="No Kalshi credentials"):
                KalshiContinuousTrader(catalog=_make_mock_catalog(), dry_run=False)

    def test_rsa_key_path_satisfies_check(self, monkeypatch):
        monkeypatch.setenv("KALSHI_PRIVATE_KEY_PATH", "/tmp/fake_key.pem")
        monkeypatch.delenv("KALSHI_EMAIL", raising=False)
        monkeypatch.delenv("KALSHI_PASSWORD", raising=False)
        from merid.trading.kalshi_continuous_trader import can_trade

        assert can_trade(dry_run=False) is True

    def test_can_trade_dry_run_always_true(self):
        from merid.trading.kalshi_continuous_trader import can_trade

        assert can_trade(dry_run=True) is True

    def test_email_password_satisfies_check(self, monkeypatch):
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PATH", raising=False)
        monkeypatch.delenv("KALSHI_PRIVATE_KEY_PEM", raising=False)
        monkeypatch.setenv("KALSHI_EMAIL", "user@example.com")
        monkeypatch.setenv("KALSHI_PASSWORD", "secret")
        from merid.trading.kalshi_continuous_trader import can_trade

        assert can_trade(dry_run=False) is True


# ── AUDIT-15: Smoke test mode guard ──────────────────────────────────────────


class TestSmokeTestModeGuard:
    def test_smoke_test_and_live_mode_raises(self, monkeypatch):
        monkeypatch.setenv("MERID_SMOKE_TEST", "true")
        monkeypatch.setenv("MERID_TRADE_MODE", "live")
        from merid.trading.kalshi_continuous_trader import _check_smoke_test_live_mode_conflict

        with pytest.raises(RuntimeError, match="MERID_SMOKE_TEST=true.*incompatible"):
            _check_smoke_test_live_mode_conflict()

    def test_smoke_test_and_paper_mode_ok(self, monkeypatch):
        monkeypatch.setenv("MERID_SMOKE_TEST", "true")
        monkeypatch.setenv("MERID_TRADE_MODE", "paper")
        monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "false")
        monkeypatch.delenv("MERID_PM_TRADING_MODE", raising=False)
        from merid.trading.kalshi_continuous_trader import _check_smoke_test_live_mode_conflict

        # Should NOT raise
        _check_smoke_test_live_mode_conflict()

    def test_no_smoke_test_flag_no_raise(self, monkeypatch):
        monkeypatch.setenv("MERID_SMOKE_TEST", "false")
        monkeypatch.setenv("MERID_TRADE_MODE", "live")
        from merid.trading.kalshi_continuous_trader import _check_smoke_test_live_mode_conflict

        # Should NOT raise — smoke-test is disabled
        _check_smoke_test_live_mode_conflict()

    def test_smoke_test_and_pm_trading_live_raises(self, monkeypatch):
        monkeypatch.setenv("MERID_SMOKE_TEST", "true")
        monkeypatch.setenv("MERID_TRADE_MODE", "paper")
        monkeypatch.setenv("MERID_PM_TRADING_MODE", "live")
        from merid.trading.kalshi_continuous_trader import _check_smoke_test_live_mode_conflict

        with pytest.raises(RuntimeError, match="MERID_PM_TRADING_MODE=live"):
            _check_smoke_test_live_mode_conflict()

    def test_smoke_test_and_allow_live_raises(self, monkeypatch):
        monkeypatch.setenv("MERID_SMOKE_TEST", "true")
        monkeypatch.setenv("MERID_TRADE_MODE", "paper")
        monkeypatch.delenv("MERID_PM_TRADING_MODE", raising=False)
        monkeypatch.setenv("MERID_ALLOW_LIVE_TRADES", "true")
        from merid.trading.kalshi_continuous_trader import _check_smoke_test_live_mode_conflict

        with pytest.raises(RuntimeError, match="MERID_ALLOW_LIVE_TRADES=true"):
            _check_smoke_test_live_mode_conflict()

    @pytest.mark.asyncio
    async def test_ct_start_raises_on_smoke_live_conflict(self, monkeypatch):
        monkeypatch.setenv("MERID_SMOKE_TEST", "true")
        monkeypatch.setenv("MERID_TRADE_MODE", "live")
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

        trader = KalshiContinuousTrader(
            catalog=_make_mock_catalog(), dry_run=True
        )
        with pytest.raises(RuntimeError, match="MERID_SMOKE_TEST=true"):
            await trader.start()


# ── AUDIT-09: Min edge env override ──────────────────────────────────────────


class TestMinEdgeEnvOverride:
    def test_env_override_takes_priority(self, monkeypatch):
        monkeypatch.setenv("KALSHI_CT_MIN_EDGE_BTC_15M", "0.001")
        from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader
        from merid.event_venues.kalshi.market_filter import MarketCandidate

        trader = KalshiContinuousTrader(
            catalog=_make_mock_catalog(), dry_run=True
        )
        from merid.trading.kalshi_continuous_trader import TradingCandidate

        candidate = TradingCandidate.from_candidate(
            MarketCandidate(
                ticker="KXBTC-15M-T95000",
                underlying="BTC",
                timeframe="15m",
                mid_price_cents=55,
                best_bid_cents=50,
                best_ask_cents=60,
            )
        )
        assert trader._get_min_edge(candidate) == pytest.approx(0.001)

    def test_no_env_override_uses_grid(self, monkeypatch):
        monkeypatch.delenv("KALSHI_CT_MIN_EDGE_BTC_15M", raising=False)
        from merid.trading.kalshi_continuous_trader import (
            KalshiContinuousTrader,
            EDGE_THRESHOLDS,
            TradingCandidate,
        )
        from merid.event_venues.kalshi.market_filter import MarketCandidate

        trader = KalshiContinuousTrader(
            catalog=_make_mock_catalog(), dry_run=True
        )
        candidate = TradingCandidate.from_candidate(
            MarketCandidate(
                ticker="KXBTC-15M-T95000",
                underlying="BTC",
                timeframe="15m",
                mid_price_cents=55,
                best_bid_cents=50,
                best_ask_cents=60,
            )
        )
        expected = EDGE_THRESHOLDS.get(("BTC", "15m"), trader._min_edge)
        assert trader._get_min_edge(candidate) == pytest.approx(expected)


# ── AUDIT-10: Swarm degraded-mode env-driven constants ───────────────────────


class TestSwarmDegradedModeConstants:
    def test_default_max_solo_seconds(self, monkeypatch):
        monkeypatch.delenv("MERID_AGENT_MAX_SOLO_SECONDS", raising=False)
        # Re-import to pick up clean env
        import importlib
        import merid.prediction.trading_agent as ta
        importlib.reload(ta)
        assert ta._MAX_SOLO_SECONDS == pytest.approx(300.0)

    def test_env_override_max_solo_seconds(self, monkeypatch):
        monkeypatch.setenv("MERID_AGENT_MAX_SOLO_SECONDS", "600")
        import importlib
        import merid.prediction.trading_agent as ta
        importlib.reload(ta)
        assert ta._MAX_SOLO_SECONDS == pytest.approx(600.0)

    def test_default_max_solo_trades(self, monkeypatch):
        monkeypatch.delenv("MERID_AGENT_MAX_SOLO_TRADES", raising=False)
        import importlib
        import merid.prediction.trading_agent as ta
        importlib.reload(ta)
        assert ta._MAX_SOLO_TRADES_DEGRADED == 3

    def test_env_override_max_solo_trades(self, monkeypatch):
        monkeypatch.setenv("MERID_AGENT_MAX_SOLO_TRADES", "5")
        import importlib
        import merid.prediction.trading_agent as ta
        importlib.reload(ta)
        assert ta._MAX_SOLO_TRADES_DEGRADED == 5


# ── AUDIT-17: Social broadcaster throttle ────────────────────────────────────


class TestSocialBroadcasterThrottle:
    def test_default_cooldown_seconds(self, monkeypatch):
        monkeypatch.delenv("MERID_BROADCASTER_COOLDOWN_SECONDS", raising=False)
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster

        b = KalshiSocialBroadcaster()
        assert b._cooldown_seconds == pytest.approx(300.0)

    def test_env_overrides_cooldown(self, monkeypatch):
        monkeypatch.setenv("MERID_BROADCASTER_COOLDOWN_SECONDS", "60")
        import importlib
        import merid.prediction.social_broadcaster as sb
        importlib.reload(sb)
        b = sb.KalshiSocialBroadcaster()
        assert b._cooldown_seconds == pytest.approx(60.0)

    @pytest.mark.asyncio
    async def test_throttled_fill_queues_on_cooldown(self, monkeypatch):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster

        b = KalshiSocialBroadcaster(cooldown_seconds=300.0)
        # Simulate that we just posted for BTC/15m
        import time
        b._last_post_at[("BTC", "15m")] = time.monotonic()

        payload = {
            "asset": "BTC",
            "timeframe": "15m",
            "market_id": "KXBTC-15M-T95000",
            "contracts": 2,
        }
        posted = []

        async def fake_publish_fill(p):
            posted.append(p)

        b._publish_fill = fake_publish_fill  # type: ignore[method-assign]
        await b._throttled_fill(payload)
        # Should NOT have posted (still in cooldown)
        assert len(posted) == 0
        # Should be queued in pending_batch
        assert ("BTC", "15m") in b._pending_batch
        assert len(b._pending_batch[("BTC", "15m")]) == 1

    @pytest.mark.asyncio
    async def test_throttled_fill_posts_immediately_after_cooldown(self, monkeypatch):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        import time

        b = KalshiSocialBroadcaster(cooldown_seconds=1.0)
        # Set last_post_at to old enough value (2 seconds ago → past cooldown)
        b._last_post_at[("ETH", "1h")] = time.monotonic() - 2.0

        payload = {
            "asset": "ETH",
            "timeframe": "1h",
            "market_id": "KXETH-1H-T3000",
            "contracts": 1,
            "simulated": True,
        }
        posted = []

        async def fake_publish_fill(p):
            posted.append(p)

        async def fake_post_twitter(msg):
            pass

        async def fake_post_telegram(msg, **kw):
            pass

        b._publish_fill = fake_publish_fill  # type: ignore[method-assign]
        b._post_to_twitter = fake_post_twitter  # type: ignore[method-assign]
        b._post_to_telegram = fake_post_telegram  # type: ignore[method-assign]
        await b._throttled_fill(payload)
        assert len(posted) == 1

    def test_summary_includes_throttle_state(self):
        from merid.prediction.social_broadcaster import KalshiSocialBroadcaster
        import time

        b = KalshiSocialBroadcaster(cooldown_seconds=60.0)
        b._last_post_at[("BTC", "15m")] = time.monotonic()
        summary = b.summary()
        assert "cooldown_seconds" in summary
        assert "throttle_cooldown_remaining" in summary
        assert "BTC/15m" in summary["throttle_cooldown_remaining"]


# ── AUDIT-22: Per-asset vol anchor ───────────────────────────────────────────


class TestPerAssetVolAnchor:
    def test_default_self_anchor(self, monkeypatch):
        monkeypatch.delenv("KALSHI_CT_VOL_ANCHOR_SOL", raising=False)
        from merid.event_venues.kalshi.crypto_kalshi_risk import KalshiCryptoRiskEngine

        engine = KalshiCryptoRiskEngine()
        assert engine.get_vol_anchor("SOL") == "SOL"

    def test_env_override_changes_anchor(self, monkeypatch):
        monkeypatch.setenv("KALSHI_CT_VOL_ANCHOR_DOGE", "BTC")
        from merid.event_venues.kalshi.crypto_kalshi_risk import KalshiCryptoRiskEngine

        engine = KalshiCryptoRiskEngine()
        assert engine.get_vol_anchor("DOGE") == "BTC"

    def test_unknown_anchor_falls_back_to_self(self, monkeypatch):
        # Setting an unknown asset as anchor should be ignored
        monkeypatch.setenv("KALSHI_CT_VOL_ANCHOR_XRP", "SHIB")
        from merid.event_venues.kalshi.crypto_kalshi_risk import KalshiCryptoRiskEngine

        engine = KalshiCryptoRiskEngine()
        # Invalid anchor "SHIB" is not in canonical list → falls back to self
        assert engine.get_vol_anchor("XRP") == "XRP"

    def test_profile_field_sets_anchor(self, monkeypatch):
        monkeypatch.delenv("KALSHI_CT_VOL_ANCHOR_ETH", raising=False)
        from merid.event_venues.kalshi.crypto_kalshi_risk import (
            KalshiCryptoRiskEngine,
            CryptoKalshiRiskConfig,
            AssetRiskProfile,
        )

        config = CryptoKalshiRiskConfig()
        config.asset_profiles["ETH"] = AssetRiskProfile(
            bankroll_share_pct=0.25,
            max_risk_pct_trade=0.01,
            cushion_pct_trade=0.0025,
            max_risk_pct_portfolio=0.03,
            vol_anchor_asset="BTC",
        )
        engine = KalshiCryptoRiskEngine(risk_config=config)
        assert engine.get_vol_anchor("ETH") == "BTC"
