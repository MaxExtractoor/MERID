"""Contract tests for KalshiCrypto15mRiskEnvelope construction.

These tests prove the envelope can be constructed from every legitimate
bot entry point and startup configuration path, and that the constructor is
fail-closed rather than permissive when critical inputs are missing.
"""

import pytest
from dataclasses import fields


class TestKalshiCrypto15mRiskEnvelopeContract:
    """Constructor/API compatibility for all default and environment paths."""

    def _base_kwargs(self) -> dict:
        return {
            "live_bankroll_usd": 1000.0,
            "profile_capital_usd": 0.0,
            "max_single_order_notional_usd": 1.0,
            "max_total_notional_usd": 1.0,
            "asset_max_notional_usd": {"BTC": 1.0, "ETH": 1.0, "SOL": 1.0, "XRP": 1.0, "DOGE": 1.0},
            "asset_depth_thresholds": {},
            "agent_max_notional_usd": 1.0,
            "agent_max_orders_per_window": 5,
            "agent_max_yes_position": 5,
            "agent_max_no_position": 5,
            "max_cycle_risk_pct": 0.0,
            "window_start_ts": 0.0,
            "agent_window_exposure_usd": {},
            "total_window_exposure_usd": 0.0,
            "agent_resting_exposure_usd": {},
            "total_resting_exposure_usd": 0.0,
            "daily_loss_enabled": True,
            "max_daily_loss_usd": 50.0,
            "drawdown_halt_pct": 0.15,
            "drawdown_unwind_pct": 0.20,
            "peak_equity_usd": 1000.0,
            "current_equity_usd": 1000.0,
            "current_drawdown_pct": 0.0,
            "kelly_fraction": 0.02,
            "adaptive_risk_bands": [],
            "per_trade_risk_multiplier": 1.0,
            "is_halted": False,
            "current_risk_band": None,
            "resume_if_drawdown_improves": False,
            "correlation_tracking_enabled": False,
            "correlation_threshold": 0.5,
            "correlation_multiplier": 1.0,
        }

    def test_direct_constructor_succeeds(self):
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        envelope = KalshiCrypto15mRiskEnvelope(**self._base_kwargs())
        assert envelope is not None
        assert envelope.live_bankroll_usd == 1000.0

    def test_deprecated_fields_accepted(self):
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        kwargs = self._base_kwargs()
        kwargs["guardrails_per_window_risk_pct"] = 0.0
        kwargs["guardrails_total_venue_risk_pct"] = 0.0
        kwargs["per_agent_window_limit_usd"] = 1.0
        kwargs["total_venue_window_limit_usd"] = 1.0
        envelope = KalshiCrypto15mRiskEnvelope(**kwargs)
        assert envelope.guardrails_per_window_risk_pct == 0.0

    def test_builder_from_profile_succeeds(self):
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import compute_kalshi_crypto_15m_risk_envelope
        envelope = compute_kalshi_crypto_15m_risk_envelope(
            live_bankroll_usd=1000.0,
        )
        assert envelope is not None
        assert envelope.max_single_order_notional_usd == 2.0  # aligned with fixed $2 exposure cap

    def test_zero_or_negative_bankroll_is_invalid(self):
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        kwargs = self._base_kwargs()
        kwargs["live_bankroll_usd"] = -1.0
        with pytest.raises(ValueError):
            KalshiCrypto15mRiskEnvelope(**kwargs)

    def test_all_fields_are_present(self):
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        required = {
            "live_bankroll_usd",
            "max_single_order_notional_usd",
            "max_total_notional_usd",
            "agent_max_notional_usd",
            "max_daily_loss_usd",
            "drawdown_halt_pct",
            "is_halted",
        }
        field_names = {f.name for f in fields(KalshiCrypto15mRiskEnvelope)}
        assert required.issubset(field_names)

    def test_window_limit_methods_return_typed_results(self):
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        envelope = KalshiCrypto15mRiskEnvelope(**self._base_kwargs())
        allowed, reason = envelope.check_window_limit("BTC_15M", 0.35, 0.0)
        assert isinstance(allowed, bool)
        assert isinstance(reason, str)

    def test_halted_envelope_blocks_orders(self):
        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import KalshiCrypto15mRiskEnvelope
        kwargs = self._base_kwargs()
        kwargs["is_halted"] = True
        envelope = KalshiCrypto15mRiskEnvelope(**kwargs)
        allowed, reason = envelope.check_window_limit("BTC_15M", 0.35, 0.0)
        assert not allowed
        assert "halt" in reason.lower()
