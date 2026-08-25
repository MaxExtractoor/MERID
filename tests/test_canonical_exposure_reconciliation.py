"""Canonical signed-YES exposure reconciliation property and replay tests.

These tests encode the boundary contract from AGENTS.md:
- All fills are normalized to signed-YES exposure at the ledger boundary.
- REST position snapshots are normalized to signed-YES exposure independently.
- Cache apply and ledger rebuild produce the same signed exposure.
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock
from merid.event_venues.kalshi.position_cache import KalshiPositionCache

from merid.event_venues.kalshi.binary_price_space import (
    yes_delta,
    to_signed_yes_exposure,
    from_signed_yes_exposure,
    fill_to_signed_yes_exposure,
    normalize_rest_position,
    PositionDataError,
)
from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill
from merid.event_venues.kalshi.position_cache import CachedPosition


@pytest.mark.parametrize("n", [1, 5, 10, 100])
def test_yes_delta_cross_leg_equivalence_buy_no_and_sell_yes(n: int):
    """BUY_NO(n) and SELL_YES(n) both produce the same long-NO exposure."""
    assert yes_delta("buy", "no", n) == yes_delta("sell", "yes", n)
    assert yes_delta("buy", "no", n) == -n


@pytest.mark.parametrize("n", [1, 5, 10, 100])
def test_yes_delta_cross_leg_equivalence_buy_yes_and_sell_no(n: int):
    """BUY_YES(n) and SELL_NO(n) both produce the same long-YES exposure."""
    assert yes_delta("buy", "yes", n) == yes_delta("sell", "no", n)
    assert yes_delta("buy", "yes", n) == n


@pytest.mark.parametrize("n", [1, 5, 10, 100])
def test_yes_delta_opposite_legs_cancel_no(n: int):
    """BUY_NO(n) followed by SELL_NO(n) net to zero."""
    assert yes_delta("buy", "no", n) + yes_delta("sell", "no", n) == 0


@pytest.mark.parametrize("n", [1, 5, 10, 100])
def test_yes_delta_opposite_legs_cancel_yes(n: int):
    """BUY_YES(n) followed by SELL_YES(n) net to zero."""
    assert yes_delta("buy", "yes", n) + yes_delta("sell", "yes", n) == 0


def test_rest_position_normalization_handles_both_conventions():
    """normalize_rest_position enforces canonical side/sign agreement."""
    # Positive size with explicit YES side -> long YES.
    assert normalize_rest_position(3, "yes", "KXBTC15M") == 3
    # Positive size with explicit NO side -> long NO.
    assert normalize_rest_position(3, "no", "KXBTC15M") == -3
    # Kalshi sometimes reports a long-NO position as a negative size with no side.
    assert normalize_rest_position(-3, "", "KXBTC15M") == -3
    # A negative signed quantity with an explicit YES side is a data contradiction:
    # side is the source of truth, not the counterparty's raw sign convention.
    with pytest.raises(PositionDataError):
        normalize_rest_position(-3, "yes", "KXBTC15M")


def test_fill_to_signed_yes_exposure_defensive_on_malformed():
    """fill_to_signed_yes_exposure returns 0 for missing or non-actionable fields."""
    assert fill_to_signed_yes_exposure("", "yes", 1) == 0
    assert fill_to_signed_yes_exposure("buy", "", 1) == 0
    assert fill_to_signed_yes_exposure("settle", "yes", 1) == 0
    assert fill_to_signed_yes_exposure("buy", "yes", 0) == 0


def _make_fill(fill_id: str, action: str, side: str, count: int, price_cents: int, ticker: str) -> KalshiFill:
    """Helper to construct a canonical KalshiFill for testing."""
    if side == "yes":
        yes_price = Decimal(price_cents) / Decimal(100)
        no_price = None
    else:
        yes_price = None
        no_price = Decimal(price_cents) / Decimal(100)
    return KalshiFill(
        fill_id=fill_id,
        market_ticker=ticker,
        side=side,
        action=action,
        count_fp=count,
        yes_price_dollars=yes_price,
        no_price_dollars=no_price,
        fee_cost=Decimal("0"),
        created_time=datetime.now(timezone.utc),
        canonicalization_state="TRUSTED_LIVE_V1",
        ledger_schema_version=3,
        canonicalization_version=1,
    )


def test_ledger_rebuild_matches_incremental_cache_apply():
    """Rebuild from fills ledger == sequential apply on a CachedPosition."""
    ticker = "KXDOGE15M-26AUG092200-00"
    fills = [
        _make_fill("f1", "buy", "no", 1, 49, ticker),
        _make_fill("f2", "sell", "no", 1, 51, ticker),
    ]

    # Ledger rebuild
    ledger = KalshiFillsLedger.__new__(KalshiFillsLedger)
    ledger._initialized = True
    ledger._fills = {}
    for f in fills:
        ledger._fills[f.fill_id] = f
    ledger._fills_by_market = {ticker: [f.fill_id for f in fills]}

    ledger_pos = ledger.compute_position_from_fills(ticker)
    assert ledger_pos is None, f"Full round-trip should net to zero, got {ledger_pos}"

    # Incremental cache apply
    position = CachedPosition(
        market_id=ticker,
        agent_id="DOGE_15M",
        side="no",
        thesis_side="no",
        contracts=0,
        avg_price_cents=49,
    )
    for f in fills:
        position.apply_fill(f.count_fp, f.price_cents, 0, f.side, f.action)
    assert position.contracts == 0
    assert position.contracts == 0
    assert position.side == "no"


def test_doge_replay_sell_no_closes_buy_no():
    """Replay the live DOGE case: BUY_NO @49c then SELL_NO @51c -> flat."""
    ticker = "KXDOGE15M-26AUG092200-00"
    fills = [
        _make_fill("doge-entry", "buy", "no", 1, 49, ticker),
        _make_fill("doge-exit", "sell", "no", 1, 51, ticker),
    ]

    ledger = KalshiFillsLedger.__new__(KalshiFillsLedger)
    ledger._initialized = True
    ledger._fills = {f.fill_id: f for f in fills}
    ledger._fills_by_market = {ticker: [f.fill_id for f in fills]}

    ledger_pos = ledger.compute_position_from_fills(ticker)
    assert ledger_pos is None, f"DOGE replay should be flat, got {ledger_pos}"

    # Entry BUY_NO and exit SELL_NO are opposite in signed-YES space.
    entry_yes = fill_to_signed_yes_exposure(fills[0].action, fills[0].side, fills[0].count_fp)
    exit_yes = fill_to_signed_yes_exposure(fills[1].action, fills[1].side, fills[1].count_fp)
    assert entry_yes == -1
    assert exit_yes == 1
    assert entry_yes + exit_yes == 0
    assert entry_yes + exit_yes == 0


def test_rest_and_ledger_exposure_match_for_equivalent_positions():
    """A REST snapshot and a fill sequence for the same long-NO position agree on signed-YES."""
    ticker = "KXETH15M-26AUG092200-00"
    rest_contracts = 1
    rest_side = "no"
    rest_signed_yes = normalize_rest_position(rest_contracts, rest_side, ticker)

    fills = [_make_fill("eth-entry", "buy", "no", 1, 20, ticker)]
    ledger = KalshiFillsLedger.__new__(KalshiFillsLedger)
    ledger._initialized = True
    ledger._fills = {f.fill_id: f for f in fills}
    ledger._fills_by_market = {ticker: [f.fill_id for f in fills]}

    ledger_pos = ledger.compute_position_from_fills(ticker)
    assert ledger_pos is not None
    ledger_signed_yes = to_signed_yes_exposure(ledger_pos["side"], ledger_pos["contracts"])

    assert rest_signed_yes == ledger_signed_yes == -1


def test_ledger_flips_and_netting_with_yes_delta():
    """Mixed buy/sell on both sides still net to the correct signed exposure."""
    ticker = "KXSOL15M-26AUG092200-00"
    fills = [
        _make_fill("s1", "buy", "yes", 1, 30, ticker),   # long YES +1
        _make_fill("s2", "sell", "no", 1, 70, ticker),   # also long YES +1 (cross-leg)
        _make_fill("s3", "sell", "yes", 2, 35, ticker),  # short YES -2
    ]
    # +1 +1 -2 = 0
    ledger = KalshiFillsLedger.__new__(KalshiFillsLedger)
    ledger._initialized = True
    ledger._fills = {f.fill_id: f for f in fills}
    ledger._fills_by_market = {ticker: [f.fill_id for f in fills]}

    ledger_pos = ledger.compute_position_from_fills(ticker)
    assert ledger_pos is None, f"Expected flat, got {ledger_pos}"


class TestReconcilerUnitConversions:
    """REST and ledger positions must be converted to canonical centi-contracts."""

    @pytest.mark.asyncio
    async def test_fetch_exchange_positions_converts_whole_contracts_to_quantity_cc(self, monkeypatch):
        """A one-contract position from the exchange becomes 100 centi-contracts."""
        from merid.event_venues.kalshi.continuous_reconciliation import ContinuousReconciler

        pos = Mock()
        pos.market_id = "KXBTC15M-26AUG100000-00"
        pos.size = Decimal("1.55")
        pos.outcome_id = "yes"
        pos.average_entry_price = Decimal("0.50")

        client = Mock()
        client.get_positions = AsyncMock(return_value=[pos])
        monkeypatch.setattr(
            "merid.event_venues.kalshi.client.get_kalshi_client",
            lambda: client,
        )

        reconciler = ContinuousReconciler()
        result = await reconciler._fetch_exchange_positions()

        assert result["KXBTC15M-26AUG100000-00"]["contracts"] == 1
        assert result["KXBTC15M-26AUG100000-00"]["quantity_cc"] == 155

    @pytest.mark.asyncio
    async def test_fetch_ledger_positions_rekeys_by_market_ticker(self, monkeypatch):
        """Ledger positions are re-keyed by market_ticker so key/value fields agree."""
        from merid.event_venues.kalshi.continuous_reconciliation import ContinuousReconciler

        ledger = Mock()
        ledger.compute_net_positions.return_value = {
            "KXBTC15M-26AUG100000-00": {
                "market_ticker": "KXBTC15M-26AUG100000-00",
                "side": "yes",
                "contracts": Decimal("1.5"),
                "quantity_cc": 150,
            }
        }
        monkeypatch.setattr(
            "merid.event_venues.kalshi.fills_ledger.get_fills_ledger",
            lambda: ledger,
        )

        reconciler = ContinuousReconciler()
        result = await reconciler._fetch_ledger_positions()

        assert "KXBTC15M-26AUG100000-00" in result
        assert result["KXBTC15M-26AUG100000-00"]["market_ticker"] == "KXBTC15M-26AUG100000-00"

    @pytest.mark.asyncio
    async def test_sync_from_rest_is_idempotent_in_quantity_cc(self, monkeypatch):
        """Calling sync_from_rest twice with the same one-contract position yields
        the same canonical quantity and does not double-count exposure."""
        from merid.event_venues.kalshi.position_cache import _is_expired_ticker

        cache = KalshiPositionCache()
        original_positions = dict(cache._positions)
        original_last_sync = cache._last_sync
        original_last_rest_ts = cache._last_rest_sync_timestamp
        original_fills_ledger = cache._fills_ledger

        try:
            cache._positions = {}
            cache._last_sync = None
            cache._last_rest_sync_timestamp = 0.0
            cache._fills_ledger = Mock()
            cache._fills_ledger.get_fills.return_value = []

            monkeypatch.setattr(
                "merid.position_management.position_monitor.get_position_monitor",
                lambda: Mock(),
            )
            monkeypatch.setattr(
                "merid.event_venues.kalshi.position_cache._is_expired_ticker",
                lambda _t: False,
            )

            positions = [{
                "market_id": "KXBTC15M-26AUG100000-00",
                "contracts": 1,
                "quantity_cc": 100,
                "side": "yes",
                "avg_price_cents": 50,
            }]

            await cache.sync_from_rest(positions, rest_timestamp=1.0, force=True)
            assert cache._positions["KXBTC15M-26AUG100000-00"].quantity_cc == 100

            await cache.sync_from_rest(positions, rest_timestamp=2.0, force=True)
            assert cache._positions["KXBTC15M-26AUG100000-00"].quantity_cc == 100
        finally:
            cache._positions = original_positions
            cache._last_sync = original_last_sync
            cache._last_rest_sync_timestamp = original_last_rest_ts
            cache._fills_ledger = original_fills_ledger
