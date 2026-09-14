"""Sizing must fit notional + exact taker fee inside the trading-shard cash."""
from __future__ import annotations

from decimal import Decimal

import pytest

from merid.event_venues.kalshi import shard_funding as sf
from merid.event_venues.kalshi.parabolic_fees import kalshi_taker_fee_cents_parabolic
from merid.prediction.unified_sizing import compute_order_size


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("MERID_FIXED_EXPOSURE_CAP_USD", "0.90")
    monkeypatch.setenv("MERID_MAX_CONTRACTS_PER_ORDER", "1")
    sf._last_result = None


def test_low_balance_sizes_fractional_and_covers_fee():
    sf._last_result = sf.ShardFundingResult(2, {0: Decimal("0.0084"), 2: Decimal("0.0891")}, Decimal("0.0891"), Decimal("0.0891"))
    count, notional, meta = compute_order_size(
        bankroll_usd=Decimal("0.0975"), price_cents=55, asset="BTC", model_prob=0.70, side="yes"
    )
    q = Decimal(str(count))
    assert q >= Decimal("0.01"), meta
    fee = Decimal(kalshi_taker_fee_cents_parabolic(0.55, q)) / 100
    assert q * Decimal("0.55") + fee <= Decimal("0.0891")
    assert q == q.quantize(Decimal("0.01"))


def test_shard_cash_caps_below_total_equity():
    sf._last_result = sf.ShardFundingResult(2, {0: Decimal("5.00"), 2: Decimal("0.20")}, Decimal("0.20"), Decimal("0.90"))
    count, _, _ = compute_order_size(
        bankroll_usd=Decimal("5.20"), price_cents=50, asset="ETH", model_prob=0.70, side="yes"
    )
    q = Decimal(str(count))
    fee = Decimal(kalshi_taker_fee_cents_parabolic(0.50, q)) / 100
    assert q * Decimal("0.50") + fee <= Decimal("0.20")
