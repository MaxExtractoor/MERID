"""Tests for Kalshi exchange-shard collateral management."""
from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, List, Optional

import pytest

from merid.event_venues.kalshi import shard_funding as sf
from merid.event_venues.kalshi.types import RawVenueBalance


class _Res:
    def __init__(self, data: Any = None, error: Optional[str] = None):
        self.success = error is None
        self.data = data
        self.error = error


class FakeClient:
    def __init__(self, shards: Dict[int, Decimal], fail_transfer: bool = False):
        self.shards = dict(shards)
        self.transfers: List[tuple] = []
        self.fail_transfer = fail_transfer

    async def get_shard_balances(self):
        return _Res(dict(self.shards))

    async def transfer_between_shards(self, src, dst, amount_cents, client_transfer_id=None):
        if self.fail_transfer:
            return _Res(error="403 forbidden")
        self.transfers.append((src, dst, amount_cents))
        amt = Decimal(amount_cents) / 100
        self.shards[src] -= amt
        self.shards[dst] = self.shards.get(dst, Decimal("0")) + amt
        return _Res({"transfer_id": "t-1"})


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.delenv("MERID_KALSHI_TRADING_SHARD", raising=False)
    monkeypatch.setenv("MERID_FIXED_EXPOSURE_CAP_USD", "0.90")
    monkeypatch.setenv("MERID_AUTO_FUND_TRADING_SHARD", "1")
    sf._last_check_ts = 0.0
    sf._last_result = None
    sf._bal_cache = {}
    sf._bal_cache_ts = 0.0
    monkeypatch.setattr(sf.asyncio, "sleep", _fast_sleep)


async def _fast_sleep(_s):
    return None


def test_parse_balance_breakdown_dollars():
    raw = RawVenueBalance.from_kalshi_response(
        {
            "balance": 94,
            "balance_breakdown": [
                {"balance": "0.9084", "exchange_index": 0},
                {"balance": "0.0391", "exchange_index": 2},
            ],
            "portfolio_value": 0,
        }
    )
    assert raw.cash_available == Decimal("0.94")
    assert raw.shard_balances == {0: Decimal("0.9084"), 2: Decimal("0.0391")}
    assert raw.shard_cash(2) == Decimal("0.0391")
    assert raw.shard_cash(None) == Decimal("0.94")


def test_shard_cash_falls_back_when_unsharded():
    raw = RawVenueBalance.from_kalshi_response({"balance": 500})
    assert raw.shard_cash(2) == Decimal("5.00")


def test_moves_idle_cash_onto_crypto_shard():
    client = FakeClient({0: Decimal("0.9084"), 2: Decimal("0.0391")})
    res = asyncio.run(sf.ensure_trading_shard_funded(client, None))
    assert res.trading_shard == 2
    assert client.transfers == [(0, 2, 86)]  # min(deficit 86c, donor 90c)
    assert res.funded and res.reason == "transferred"
    assert res.trading_shard_usd == Decimal("0.8991")


def test_already_funded_is_noop():
    client = FakeClient({0: Decimal("0.01"), 2: Decimal("1.50")})
    res = asyncio.run(sf.ensure_trading_shard_funded(client, None))
    assert client.transfers == []
    assert res.funded and res.reason == "already_funded"


def test_tiny_account_all_on_trading_shard_is_funded():
    client = FakeClient({0: Decimal("0"), 2: Decimal("0.30")})
    res = asyncio.run(sf.ensure_trading_shard_funded(client, None))
    assert client.transfers == []
    assert res.funded


def test_fails_closed_when_auto_fund_disabled(monkeypatch):
    monkeypatch.setenv("MERID_AUTO_FUND_TRADING_SHARD", "0")
    client = FakeClient({0: Decimal("5.00"), 2: Decimal("0.02")})
    res = asyncio.run(sf.ensure_trading_shard_funded(client, None))
    assert client.transfers == []
    assert not res.funded and res.reason == "auto_fund_disabled"


def test_transfer_rejection_is_reported_not_raised():
    client = FakeClient({0: Decimal("5.00"), 2: Decimal("0.02")}, fail_transfer=True)
    res = asyncio.run(sf.ensure_trading_shard_funded(client, None))
    assert not res.funded and res.reason == "transfer_rejected" and "403" in res.error


def test_no_cash_anywhere_is_not_funded():
    client = FakeClient({0: Decimal("0.00"), 2: Decimal("0.05")})
    res = asyncio.run(sf.ensure_trading_shard_funded(client, None))
    assert not res.funded


def test_env_override_for_trading_shard(monkeypatch):
    monkeypatch.setenv("MERID_KALSHI_TRADING_SHARD", "3")
    assert sf.resolve_trading_shard(None) == 3
