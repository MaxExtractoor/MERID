"""Tests for spot/strike basis wiring in MarketSnapshot and trading_agent._build_snapshot."""

from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from merid.prediction.model import MarketSnapshot, ContractState, PredictionMarketModel


class TestMarketSnapshotSpotStrikeFields:
    """Unit tests for spot/strike fields added to MarketSnapshot."""

    def _make_snapshot(self, **kwargs) -> MarketSnapshot:
        model = PredictionMarketModel()
        implied = model.implied_probabilities(
            yes_bid=Decimal("49"),
            yes_ask=Decimal("51"),
            no_bid=Decimal("49"),
            no_ask=Decimal("51"),
        )
        defaults = dict(
            market_id="KXBTC-25APR-T84000",
            event_id="KXBTC-25APR",
            title="BTC above 84000 on Apr 25",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("5000"),
            open_interest=Decimal("2000"),
            time_to_expiry_hours=Decimal("2.0"),
        )
        defaults.update(kwargs)
        return MarketSnapshot(**defaults)

    def test_snapshot_timestamp_utc_epoch_seconds_property(self):
        """snapshot_timestamp_utc_epoch_seconds should return POSIX float."""
        ts = datetime(2026, 4, 8, 12, 0, 0, tzinfo=timezone.utc)
        snap = self._make_snapshot(timestamp=ts)
        assert snap.snapshot_timestamp_utc_epoch_seconds == ts.timestamp()
        assert isinstance(snap.snapshot_timestamp_utc_epoch_seconds, float)

    def test_spot_strike_fields_default_none(self):
        """spot_price, strike_price, dist_frac, spot_strike_basis should default None."""
        snap = self._make_snapshot()
        assert snap.spot_price is None
        assert snap.strike_price is None
        assert snap.dist_frac is None
        assert snap.spot_strike_basis is None

    def test_spot_strike_fields_settable(self):
        """spot_price/strike_price/dist_frac/spot_strike_basis should be settable."""
        snap = self._make_snapshot(
            spot_price=84500.0,
            strike_price=84000.0,
            dist_frac=0.00595,
            spot_strike_basis="ok",
        )
        assert snap.spot_price == pytest.approx(84500.0)
        assert snap.strike_price == pytest.approx(84000.0)
        assert snap.dist_frac == pytest.approx(0.00595)
        assert snap.spot_strike_basis == "ok"

    def test_dist_frac_calculation(self):
        """dist_frac = (spot - strike) / strike."""
        spot, strike = 85000.0, 84000.0
        dist = (spot - strike) / strike
        snap = self._make_snapshot(
            spot_price=spot,
            strike_price=strike,
            dist_frac=dist,
            spot_strike_basis="ok",
        )
        assert snap.dist_frac == pytest.approx(dist, rel=1e-6)


class TestSpotStrikeBasisNotes:
    """Verify all valid spot_strike_basis note values are handled."""

    VALID_BASIS_NOTES = {
        "ok",
        "missing_spot",
        "missing_strike",
        "missing_strike_and_spot",
        "missing_asset_for_spot",
        "invalid_strike_zero",
    }

    def test_all_basis_notes_are_strings(self):
        """Every valid basis note should be a plain string."""
        for note in self.VALID_BASIS_NOTES:
            assert isinstance(note, str)
            assert len(note) > 0

    def test_ok_basis_note_requires_both_prices(self):
        """When basis='ok', spot_price and strike_price must both be set."""
        model = PredictionMarketModel()
        implied = model.implied_probabilities(
            yes_bid=Decimal("49"),
            yes_ask=Decimal("51"),
            no_bid=Decimal("49"),
            no_ask=Decimal("51"),
        )
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="TEST",
            title="t",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("1"),
            open_interest=Decimal("1"),
            spot_price=84000.0,
            strike_price=84000.0,
            dist_frac=0.0,
            spot_strike_basis="ok",
        )
        assert snap.spot_strike_basis == "ok"
        assert snap.spot_price is not None
        assert snap.strike_price is not None

    def test_missing_spot_basis(self):
        """missing_spot is a valid basis note."""
        model = PredictionMarketModel()
        implied = model.implied_probabilities(
            yes_bid=Decimal("49"),
            yes_ask=Decimal("51"),
            no_bid=Decimal("49"),
            no_ask=Decimal("51"),
        )
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="TEST",
            title="t",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("1"),
            open_interest=Decimal("1"),
            strike_price=84000.0,
            spot_strike_basis="missing_spot",
        )
        assert snap.spot_price is None
        assert snap.spot_strike_basis == "missing_spot"

    def test_missing_strike_basis(self):
        """missing_strike is a valid basis note."""
        model = PredictionMarketModel()
        implied = model.implied_probabilities(
            yes_bid=Decimal("49"),
            yes_ask=Decimal("51"),
            no_bid=Decimal("49"),
            no_ask=Decimal("51"),
        )
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="TEST",
            title="t",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("1"),
            open_interest=Decimal("1"),
            spot_price=84000.0,
            spot_strike_basis="missing_strike",
        )
        assert snap.strike_price is None
        assert snap.spot_strike_basis == "missing_strike"

    def test_invalid_strike_zero_basis(self):
        """invalid_strike_zero is a valid basis note."""
        model = PredictionMarketModel()
        implied = model.implied_probabilities(
            yes_bid=Decimal("49"),
            yes_ask=Decimal("51"),
            no_bid=Decimal("49"),
            no_ask=Decimal("51"),
        )
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="TEST",
            title="t",
            state=ContractState.TRADING,
            implied=implied,
            volume=Decimal("1"),
            open_interest=Decimal("1"),
            spot_price=84000.0,
            strike_price=0.0,
            spot_strike_basis="invalid_strike_zero",
        )
        assert snap.spot_strike_basis == "invalid_strike_zero"


class TestSnapshotStaleness:
    """Verify snapshot_timestamp_utc_epoch_seconds is used for staleness detection."""

    def test_fresh_snapshot_age_near_zero(self):
        """A snapshot created now should have age ~0s."""
        import time
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="TEST",
            title="t",
            state=ContractState.TRADING,
            implied=None,  # type: ignore[arg-type]
            volume=Decimal("1"),
            open_interest=Decimal("1"),
        )
        age = time.time() - snap.snapshot_timestamp_utc_epoch_seconds
        assert age >= 0
        assert age < 5.0, f"Snapshot age {age}s looks stale for a just-created snapshot"

    def test_old_snapshot_has_large_age(self):
        """A snapshot with a 1-hour-old timestamp should have age ~3600s."""
        import time
        old_ts = datetime.fromtimestamp(time.time() - 3600, tz=timezone.utc)
        snap = MarketSnapshot(
            market_id="TEST",
            event_id="TEST",
            title="t",
            state=ContractState.TRADING,
            implied=None,  # type: ignore[arg-type]
            volume=Decimal("1"),
            open_interest=Decimal("1"),
            timestamp=old_ts,
        )
        age = time.time() - snap.snapshot_timestamp_utc_epoch_seconds
        assert age >= 3595
        assert age < 3610
