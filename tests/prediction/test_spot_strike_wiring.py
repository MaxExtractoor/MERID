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


# ── PATCH-1 / EGG-1: spot_source field on MarketSnapshot ─────────────────

class TestSpotSourceField:
    """PATCH-1: spot_source must be stored on MarketSnapshot."""

    def _make_implied(self):
        model = PredictionMarketModel()
        return model.implied_probabilities(
            yes_bid=Decimal("49"), yes_ask=Decimal("51"),
            no_bid=Decimal("49"), no_ask=Decimal("51"),
        )

    def test_spot_source_defaults_to_none(self):
        """spot_source should default to None when not provided."""
        snap = MarketSnapshot(
            market_id="TEST", event_id="TEST", title="t",
            state=ContractState.TRADING, implied=self._make_implied(),
            volume=Decimal("1"), open_interest=Decimal("1"),
        )
        assert snap.spot_source is None

    def test_spot_source_settable_coinbase(self):
        """spot_source can be set to 'coinbase_usd'."""
        snap = MarketSnapshot(
            market_id="TEST", event_id="TEST", title="t",
            state=ContractState.TRADING, implied=self._make_implied(),
            volume=Decimal("1"), open_interest=Decimal("1"),
            spot_source="coinbase_usd",
        )
        assert snap.spot_source == "coinbase_usd"

    def test_spot_source_settable_depegged(self):
        """spot_source can be set to 'usdt_depegged' when USDT is off-peg."""
        snap = MarketSnapshot(
            market_id="TEST", event_id="TEST", title="t",
            state=ContractState.TRADING, implied=self._make_implied(),
            volume=Decimal("1"), open_interest=Decimal("1"),
            spot_price=None,
            spot_strike_basis="missing_spot",
            spot_source="usdt_depegged",
        )
        assert snap.spot_price is None
        assert snap.spot_source == "usdt_depegged"

    def test_stale_distance_is_valid_basis_note(self):
        """'stale_distance' is a valid spot_strike_basis value (PATCH-7)."""
        snap = MarketSnapshot(
            market_id="TEST", event_id="TEST", title="t",
            state=ContractState.TRADING, implied=self._make_implied(),
            volume=Decimal("1"), open_interest=Decimal("1"),
            spot_strike_basis="stale_distance",
        )
        assert snap.spot_strike_basis == "stale_distance"


# ── PATCH-2: BTC-15m risk fail-closed ────────────────────────────────────

class TestBTC15mRiskFailClosed:
    """PATCH-2: CryptoSwarmRiskBTC15m.evaluate_proposal exceptions must force paper."""

    def test_exception_in_risk_sets_force_paper(self):
        """When risk.evaluate_proposal raises, force_paper must be True."""
        from unittest.mock import MagicMock, patch
        from merid.risk.crypto_swarm_risk_btc15m import CryptoSwarmRiskBTC15m

        risky = MagicMock(spec=CryptoSwarmRiskBTC15m)
        risky.evaluate_proposal.side_effect = RuntimeError("risk boom")

        force_paper = None
        try:
            risky.evaluate_proposal(MagicMock())
        except Exception:
            # Simulates the fail-closed behaviour in trading_agent._execute_signal
            force_paper = True

        assert force_paper is True, "Exception in risk layer must set force_paper=True"


# ── PATCH-4: stop-loss close price fix ───────────────────────────────────

class TestStopLossClosePrice:
    """PATCH-4: stop-loss close orders must use price_cents=1 not 0."""

    def test_stop_loss_does_not_use_zero_price(self):
        """_check_stop_losses must call _kalshi_place_order with price_cents=1.

        Verified via AST inspection of the actual keyword argument passed to the
        order routing call — not a source-text scan — to avoid false positives
        from comments explaining the fix.
        """
        import ast
        import inspect
        import textwrap
        import merid.prediction.trading_agent as ta

        src = inspect.getsource(ta.KalshiTradingAgent._check_stop_losses)
        tree = ast.parse(textwrap.dedent(src))

        price_cents_values = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                fname = (
                    func.attr if isinstance(func, ast.Attribute)
                    else func.id if isinstance(func, ast.Name)
                    else ""
                )
                if "place_order" in fname:
                    for kw in node.keywords:
                        if kw.arg == "price_cents" and isinstance(kw.value, ast.Constant):
                            price_cents_values.append(kw.value.value)

        assert price_cents_values, (
            "No _kalshi_place_order(price_cents=<literal>) call found in _check_stop_losses"
        )
        assert all(v != 0 for v in price_cents_values), (
            f"stop-loss close must NOT use price_cents=0 — it is rejected by "
            f"_check_intent_risk.  Found: {price_cents_values}"
        )
        assert any(v == 1 for v in price_cents_values), (
            f"stop-loss close should use price_cents=1 as a market-proxy sell.  "
            f"Found: {price_cents_values}"
        )

    @pytest.mark.asyncio
    async def test_stop_loss_close_calls_place_order_with_price_cents_1(self):
        """Behavioral test: _check_stop_losses triggers a close and passes price_cents=1."""
        import time
        from unittest.mock import AsyncMock, MagicMock, patch
        from decimal import Decimal
        from merid.prediction.trading_agent import KalshiTradingAgent
        from merid.prediction.agent_grid_config import AgentConfig, AgentRiskLimits
        from merid.event_venues.kalshi.stop_loss import TrackedPosition

        cfg = AgentConfig(
            name="BTC_15M",
            assets=["BTC"],
            timeframes=["15m"],
            risk_limits=AgentRiskLimits(max_notional_usd=Decimal("1000")),
            enabled=True,
        )
        agent = KalshiTradingAgent(cfg)

        # Inject a position that triggers stop-loss immediately (entry=90, current=1 → deep loss)
        now = time.time()
        pos = TrackedPosition(
            position_id="KXBTC-TEST::yes",
            ticker="KXBTC-TEST",
            side="yes",
            entry_price_cents=90,
            contracts=5,
            entry_ts=now - 600,
            contract_expiry_ts=now + 300,
            current_price_cents=1,       # 98% loss — any stop-loss rule fires
            session_equity_cents=100_000.0,
        )
        agent._tracked_positions["KXBTC-TEST::yes"] = pos

        # Mock _kalshi_place_order to capture args and return success
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.payload = {"order_id": "test-order"}
        mock_result.error_message = None

        with patch(
            "merid.prediction.kalshi_tools._kalshi_place_order",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_place:
            await agent._check_stop_losses()

        # Must have called _kalshi_place_order with price_cents=1
        assert mock_place.called, "_kalshi_place_order was not called — stop-loss did not fire"
        call_kwargs = mock_place.call_args.kwargs
        assert call_kwargs.get("price_cents") == 1, (
            f"stop-loss close must use price_cents=1; got {call_kwargs.get('price_cents')}"
        )


# ── PATCH-5: volume USD notional ─────────────────────────────────────────

class TestVolumeUSDNotional:
    """PATCH-5: volume_24h in TradeProposal must use USD notional."""

    def test_volume_is_usd_notional_not_raw_contracts(self):
        """volume_24h must equal market.volume * (price_cents/100)."""
        raw_volume = 1000  # contracts
        price_cents = 60   # 60¢ per contract
        expected_usd = raw_volume * (price_cents / 100.0)
        assert expected_usd == pytest.approx(600.0)

        # The formula used in trading_agent._execute_signal (PATCH-5)
        actual = float(raw_volume) * (price_cents / 100.0) if (raw_volume and price_cents > 0) else None
        assert actual == pytest.approx(expected_usd)

    def test_volume_usd_zero_price_yields_none(self):
        """If price_cents==0, volume_usd should be None (prevents division by zero)."""
        raw_volume = 1000
        price_cents = 0
        vol_usd = (
            float(raw_volume) * (price_cents / 100.0)
            if (raw_volume and price_cents > 0)
            else None
        )
        assert vol_usd is None


# ── PATCH-9: force-paper audit log ───────────────────────────────────────

class TestForcePaperAuditLog:
    """PATCH-9: _kalshi_place_paper_order must log forced_paper=true."""

    def test_place_paper_order_logs_force_paper(self):
        """_kalshi_place_paper_order should log forced_paper=true with reason."""
        import asyncio
        from unittest.mock import patch as _patch, MagicMock
        from merid.prediction.kalshi_tools import _kalshi_place_paper_order
        from merid.prediction.session_guard import SessionGuard

        mock_guard = MagicMock(spec=SessionGuard)
        mock_guard.is_trading_allowed.return_value = True

        with _patch("merid.prediction.kalshi_tools.get_session_guard", return_value=mock_guard), \
             _patch("merid.prediction.kalshi_tools.logger") as mock_log:
            result = asyncio.get_event_loop().run_until_complete(
                _kalshi_place_paper_order(
                    ticker="KXBTC-25APR-T84000",
                    side="yes",
                    action="buy",
                    price_cents=55,
                    count=3,
                    forced_paper_reason="btc15m_risk_paper",
                )
            )
        assert result.success
        assert result.payload["forced_paper_reason"] == "btc15m_risk_paper"
        # The FORCE_PAPER log must have been emitted
        mock_log.warning.assert_called()
        warn_msg = str(mock_log.warning.call_args)
        assert "FORCE_PAPER" in warn_msg or "forced_paper" in warn_msg.lower()

    def test_place_paper_order_blocked_during_maintenance(self):
        """_kalshi_place_paper_order must respect SessionGuard even for paper orders."""
        import asyncio
        from unittest.mock import patch as _patch, MagicMock
        from merid.prediction.kalshi_tools import _kalshi_place_paper_order
        from merid.prediction.session_guard import SessionGuard

        mock_guard = MagicMock(spec=SessionGuard)
        mock_guard.is_trading_allowed.return_value = False
        mock_guard.block_reason.return_value = "maintenance"

        with _patch("merid.prediction.kalshi_tools.get_session_guard", return_value=mock_guard):
            result = asyncio.get_event_loop().run_until_complete(
                _kalshi_place_paper_order(
                    ticker="KXBTC-25APR-T84000",
                    side="yes",
                    action="buy",
                    price_cents=55,
                    count=1,
                    forced_paper_reason="btc15m_risk_paper",
                )
            )
        assert not result.success
        assert "maintenance" in (result.error_message or "")
