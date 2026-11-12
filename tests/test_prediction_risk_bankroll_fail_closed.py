"""Fail-closed global bankroll cap tests (WP4, 2026-11-12).

_prediction_risk.check_order previously fell back to a fabricated $1000
cap on exception and floored verified-tiny bankrolls to $50/$1 — turning
unavailable bankroll state into apparent purchasing power.  Now any
unavailable/error/tiny-cap state rejects with BANKROLL_UNAVAILABLE.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest


def _risk():
    from merid.prediction.risk._prediction_risk import PredictionMarketRisk
    from merid.prediction.risk import PredictionRiskConfig

    return PredictionMarketRisk(PredictionRiskConfig())


def _check(risk):
    return risk.check_order(
        market_id="KXBTC15M-TEST",
        event_id="evt-test",
        side="yes",
        contracts=1,
        price_cents=Decimal("50"),
        best_bid_cents=Decimal("49"),
        best_ask_cents=Decimal("51"),
        depth_at_price=100,
        edge=Decimal("5"),
    )


class TestGlobalBankrollCapFailClosed:
    def test_equity_fetch_exception_rejects(self):
        risk = _risk()
        with patch(
            "merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync",
            side_effect=RuntimeError("bankroll service down"),
        ):
            result = _check(risk)
        assert result.allowed is False
        assert "BANKROLL" in (result.reason or "")

    def test_unavailable_equity_rejects(self):
        risk = _risk()
        with patch(
            "merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync",
            return_value=None,
        ):
            result = _check(risk)
        assert result.allowed is False
        assert "BANKROLL" in (result.reason or "")

    def test_zero_equity_rejects(self):
        risk = _risk()
        with patch(
            "merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync",
            return_value=0.0,
        ):
            result = _check(risk)
        assert result.allowed is False
        assert "BANKROLL" in (result.reason or "")

    def test_sub_cent_equity_rejects_not_floored(self):
        """Verified equity of $0.005 must not floor to the old $50/$1 caps."""
        risk = _risk()
        with patch(
            "merid.event_venues.kalshi.bankroll_service_v2.get_equity_for_risk_calc_sync",
            return_value=0.005,
        ):
            result = _check(risk)
        assert result.allowed is False
        assert "BANKROLL" in (result.reason or "")
