"""Unit tests for config-based max_notional computation."""

import pytest
from unittest.mock import MagicMock, patch
from merid.guardrails.capabilities import _compute_kalshi_max_notional_from_config


_ENVELOPE_PATH = "merid.risk.profiles.kalshi_crypto_15m_risk_envelope.get_kalshi_crypto_15m_risk_envelope"
_EQUITY_PATH = "merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync"


def _envelope(per_trade: float, total: float) -> MagicMock:
    env = MagicMock()
    env.max_single_order_notional_usd = per_trade
    env.max_total_notional_usd = total
    return env


class TestConfigBasedMaxNotional:
    """max_notional comes from the canonical risk envelope's total notional cap.

    The per_trade_cap x max_concurrent model was removed 2026-08-22; the
    envelope's max_total_notional_usd is the single source of truth.
    """

    def test_max_notional_from_envelope(self):
        with patch(_ENVELOPE_PATH, return_value=_envelope(2500.0, 7500.0)), \
             patch(_EQUITY_PATH, return_value=100_000.0):
            assert _compute_kalshi_max_notional_from_config() == 7500.0

    def test_max_notional_uses_envelope_total_not_per_trade(self):
        """Total cap drives the result; per-trade cap is informational only."""
        with patch(_ENVELOPE_PATH, return_value=_envelope(100.0, 4200.0)), \
             patch(_EQUITY_PATH, return_value=100_000.0):
            assert _compute_kalshi_max_notional_from_config() == 4200.0

    def test_max_notional_different_envelope_caps(self):
        for total in (1500.0, 3000.0, 7500.0, 15000.0, 30000.0):
            with patch(_ENVELOPE_PATH, return_value=_envelope(500.0, total)), \
                 patch(_EQUITY_PATH, return_value=100_000.0):
                assert _compute_kalshi_max_notional_from_config() == total

    def test_max_notional_fail_safe_on_envelope_error(self):
        """Envelope unavailable -> conservative $500 fallback."""
        with patch(_ENVELOPE_PATH, side_effect=RuntimeError("bankroll not ready")), \
             patch(_EQUITY_PATH, return_value=100_000.0):
            assert _compute_kalshi_max_notional_from_config() == 500.0

    def test_max_notional_balance_guardrail_warning(self):
        """Config cap > available cash still returns the config cap."""
        with patch(_ENVELOPE_PATH, return_value=_envelope(2500.0, 7500.0)), \
             patch(_EQUITY_PATH, return_value=1000.0):
            assert _compute_kalshi_max_notional_from_config() == 7500.0

    def test_max_notional_balance_guardrail_info(self):
        """Config cap within cash returns the config cap."""
        with patch(_ENVELOPE_PATH, return_value=_envelope(2500.0, 7500.0)), \
             patch(_EQUITY_PATH, return_value=10_000.0):
            assert _compute_kalshi_max_notional_from_config() == 7500.0

    def test_max_notional_balance_guardrail_optional(self):
        """Balance fetch failure doesn't affect the cap."""
        with patch(_ENVELOPE_PATH, return_value=_envelope(2500.0, 7500.0)), \
             patch(_EQUITY_PATH, side_effect=Exception("Balance fetch error")):
            assert _compute_kalshi_max_notional_from_config() == 7500.0

    def test_max_notional_balance_none_is_safe(self):
        """Bankroll service returning None must not crash the guardrail."""
        with patch(_ENVELOPE_PATH, return_value=_envelope(2500.0, 7500.0)), \
             patch(_EQUITY_PATH, return_value=None):
            assert _compute_kalshi_max_notional_from_config() == 7500.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
