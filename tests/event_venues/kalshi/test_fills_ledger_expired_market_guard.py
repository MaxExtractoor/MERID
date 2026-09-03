"""Regression tests for expired/quarantined market filtering in fills_ledger.

These tests verify that `compute_position_from_fills`,
`reconcile_with_kalshi_positions`, and `compute_net_positions` do not fall
through to fill-price computation for expired or quarantined markets, which
caused "Cannot determine no-side price" warning spam for long-expired markets.

The warning is still emitted for active markets with missing price data.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import pytest

from merid.event_venues.kalshi.fills_ledger import KalshiFill, KalshiFillsLedger


ACTIVE_TICKER = "KXDOGE15M-50AUG300000-15"
EXPIRED_TICKER = "KXDOGE15M-26AUG110015-15"


def _mock_parse_expiry(
    ticker: str, market: Optional[dict] = None
) -> float:
    """Return an expired timestamp for the expired ticker, 0.0 otherwise."""
    if ticker == EXPIRED_TICKER:
        return 1.0
    return 0.0


def _mock_is_expired(ticker: str) -> bool:
    """Return True only for the quarantined/expired ticker."""
    return ticker == EXPIRED_TICKER


def _unpriced_no_fill(fill_id: str, market_ticker: str) -> KalshiFill:
    """Create a trusted NO fill whose held-side price cannot be determined.

    The fill only carries a YES leg price; the NO leg and canonical leg price
    are missing, so `_fill_position_side_price_cents` returns None and the
    ledger would normally emit a missing-side warning.
    """
    return KalshiFill(
        fill_id=fill_id,
        market_ticker=market_ticker,
        side="yes",
        action="buy",
        count_fp=Decimal("1.0"),
        quantity_cc=100,
        yes_price_dollars=Decimal("0.50"),
        no_price_dollars=None,
        fee_cost=Decimal("0.02"),
        created_time=datetime.now(timezone.utc),
        canonicalization_state="TRUSTED_LIVE_V1",
        canonical_position_side="no",
        canonical_position_action="buy",
        canonical_leg_price_cents=None,
    )


@pytest.fixture
def ledger(monkeypatch, tmp_path) -> KalshiFillsLedger:
    """Provide a fresh fills ledger for each test."""
    monkeypatch.setenv("MERID_FILLS_DB_PATH", str(tmp_path / "test_fills.db"))
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    # Clear global singleton state so direct construction gives a fresh instance.
    import merid.event_venues.kalshi.fills_ledger as _fl_mod

    _fl_mod._ledgers.clear()
    KalshiFillsLedger._initialized = False

    l = KalshiFillsLedger()
    l._fills = {}
    l._fills_by_market = {}
    l._fills_by_order = {}
    l._intents = {}
    l._http_ingested = 0
    l._ws_ingested = 0
    l._duplicates_dropped = 0
    return l


def _index_fill(ledger: KalshiFillsLedger, fill: KalshiFill) -> None:
    ledger._fills[fill.fill_id] = fill
    if fill.market_ticker not in ledger._fills_by_market:
        ledger._fills_by_market[fill.market_ticker] = []
    ledger._fills_by_market[fill.market_ticker].append(fill.fill_id)


def _missing_price_warning_present(caplog: Any) -> bool:
    return any(
        "Cannot determine" in record.message
        for record in caplog.records
    )


class TestExpiredMarketGuard:
    """Expired/quarantined markets must not emit missing-side price warnings."""

    def test_compute_position_from_fills_skips_expired_no_warning(
        self, ledger: KalshiFillsLedger, monkeypatch: Any, caplog: Any
    ) -> None:
        """Expired markets with missing-price fills should return None silently."""
        caplog.set_level(
            logging.WARNING,
            logger="merid.event_venues.kalshi.fills_ledger",
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_filter.parse_expiry_from_ticker",
            _mock_parse_expiry,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.position_cache._is_expired_ticker",
            _mock_is_expired,
        )

        _index_fill(ledger, _unpriced_no_fill("exp-001", EXPIRED_TICKER))

        pos = ledger.compute_position_from_fills(EXPIRED_TICKER)

        assert pos is None
        assert not _missing_price_warning_present(caplog)

    def test_compute_position_from_fills_still_warns_for_active_market(
        self, ledger: KalshiFillsLedger, monkeypatch: Any, caplog: Any
    ) -> None:
        """Active markets with missing-price fills still emit the useful warning."""
        caplog.set_level(
            logging.WARNING,
            logger="merid.event_venues.kalshi.fills_ledger",
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_filter.parse_expiry_from_ticker",
            _mock_parse_expiry,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.position_cache._is_expired_ticker",
            _mock_is_expired,
        )

        _index_fill(ledger, _unpriced_no_fill("act-001", ACTIVE_TICKER))

        pos = ledger.compute_position_from_fills(ACTIVE_TICKER)

        assert pos is None
        assert _missing_price_warning_present(caplog)

    @pytest.mark.asyncio
    async def test_reconcile_skips_expired_no_warning(
        self, ledger: KalshiFillsLedger, monkeypatch: Any, caplog: Any
    ) -> None:
        """Reconciliation must not call fill computation for expired markets."""
        caplog.set_level(
            logging.WARNING,
            logger="merid.event_venues.kalshi.fills_ledger",
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_filter.parse_expiry_from_ticker",
            _mock_parse_expiry,
        )
        monkeypatch.setattr(
            "merid.event_venues.kalshi.position_cache._is_expired_ticker",
            _mock_is_expired,
        )

        _index_fill(ledger, _unpriced_no_fill("exp-001", EXPIRED_TICKER))

        report = await ledger.reconcile_with_kalshi_positions([])

        assert EXPIRED_TICKER not in report["settled_tickers"]
        assert EXPIRED_TICKER not in {d["market"] for d in report["divergences"]}
        assert not _missing_price_warning_present(caplog)


class TestComputeNetPositionsExceptionFallthrough:
    """Exception in the expiry check must not fall through to fill computation."""

    def test_compute_net_positions_exception_skips_market(
        self, ledger: KalshiFillsLedger, monkeypatch: Any, caplog: Any
    ) -> None:
        """If parse_expiry_from_ticker raises, the market is skipped entirely."""
        caplog.set_level(
            logging.WARNING,
            logger="merid.event_venues.kalshi.fills_ledger",
        )

        exc_ticker = "KXDOGE15M-EXC-26AUG110015-15"

        def _raising_parse_expiry(
            ticker: str, market: Optional[dict] = None
        ) -> float:
            if ticker == exc_ticker:
                raise ValueError("simulated expiry parse failure")
            return 0.0

        monkeypatch.setattr(
            "merid.event_venues.kalshi.market_filter.parse_expiry_from_ticker",
            _raising_parse_expiry,
        )

        _index_fill(ledger, _unpriced_no_fill("exc-001", exc_ticker))

        positions = ledger.compute_net_positions(since_hours=24)

        assert exc_ticker not in positions
        assert not _missing_price_warning_present(caplog)
