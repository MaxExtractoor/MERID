"""
Price side-lock boundary matrix.

Verifies the canonical 10c-75c range is enforced for both YES and NO thesis
sides, with strict side lock: the model may not fall back to the opposite
side when the thesis side is out of range.
"""

import time
import types

import pytest
from unittest.mock import Mock, MagicMock, patch

from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m


YES_ASK_CENTS = 53
NO_ASK_CENTS = 100 - 50  # best_bid=50 -> NO ask = 50


def _make_profile():
    """Create a minimal Crypto15mProfile-shaped object."""
    momentum_fvg = types.SimpleNamespace(
        momentum_rsi_long_min=40.0,
        momentum_rsi_short_max=60.0,
        macd_zero_line_filter_enabled=True,
        macd_histogram_momentum_filter_enabled=True,
        min_macd_hist_long=0,
        min_macd_hist_short=0,
        macd_dead_zone=0.0,
        obi_strong_btc=0.3,
        obi_strong_eth=0.3,
        obi_strong_sol=0.3,
        obi_strong_xrp=0.3,
        obi_strong_doge=0.3,
    )
    profile = types.SimpleNamespace(momentum_fvg=momentum_fvg)
    return profile


def _make_agent(prefer_maker=True, bearish=False):
    """Create a LeanAgent15m with a patched indicator stack."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        signal_mode="momentum_fvg",
        prefer_maker_orders=prefer_maker,
    )

    agent = LeanAgent15m(
        config=config,
        catalog=Mock(),
        market_state_store=Mock(),
        spot_provider=Mock(),
        order_router=Mock(),
        risk_config=Mock(),
    )

    indicator_snap = MagicMock()
    indicator_snap.bars_available = 30
    indicator_snap.macd_line = 0.0
    indicator_snap.macd_histogram = -0.001 if bearish else 0.001
    indicator_snap.rsi = 50.0 if bearish else 60.0
    indicator_snap.rsi_zone = "neutral"
    indicator_snap.macro_regime = "bear" if bearish else "bull"
    indicator_snap.price_above_ema_200 = not bearish
    indicator_snap.macd_zero_line_ok = True
    indicator_snap.macd_histogram_expanding = True
    indicator_snap.bias = "neutral"
    indicator_snap.bias_confidence = 0.5
    indicator_snap.macd_slope = 0.0

    stack = MagicMock()
    stack.snapshot.return_value = indicator_snap
    agent._indicator_stacks = {"BTC": stack}

    return agent


def _make_market_state(best_bid, best_ask, obi_yes=100, obi_no=0, yes_price=0.50):
    """Return a market-state-shaped mock."""
    state = Mock()
    state.best_bid_cents = best_bid
    state.best_ask_cents = best_ask
    state.yes_price = yes_price
    state.volume_24h = 10000.0
    state.open_interest = 5000.0
    state.bid = yes_price - 0.01
    state.ask = yes_price + 0.01
    state.depth_10c_yes = obi_yes
    state.depth_10c_no = obi_no
    state.yes_ask_size = 100
    state.no_ask_size = 100
    state.window_strike_price = 65000.0
    return state


def _run_signal(
    agent,
    velocity,
    best_bid=50,
    best_ask=YES_ASK_CENTS,
    obi_yes=100,
    obi_no=0,
    fvg_dir=0.0,
    fvg_conf=0.0,
):
    """Run _generate_momentum_fvg_signal with patched profile and FVG forecaster."""
    agent._coinbase_velocity_signals["BTC"] = {
        "velocity": velocity,
        "timestamp": time.time(),
        "signal_type": (
            "strong_long"
            if velocity > 0
            else "strong_short"
            if velocity < 0
            else "neutral"
        ),
    }

    market = MagicMock(spec=["market_id"])
    market.market_id = "KXBTC15M-TEST-01"

    state = _make_market_state(best_bid, best_ask, obi_yes=obi_yes, obi_no=obi_no)
    agent.market_state_store.get.return_value = state
    agent.market_state_store.get_orderbook_snapshot.return_value = None

    fvg_result = Mock()
    fvg_result.confidence = fvg_conf
    fvg_result.components = {"fvg_nearest_direction": fvg_dir}
    fvg_forecaster = Mock()
    fvg_forecaster.predict.return_value = fvg_result

    with patch(
        "merid.risk.profiles.crypto_15m_profile.get_active_profile", return_value=None
    ), patch(
        "merid.risk.profiles.crypto_15m_profile.get_crypto_15m_profile",
        return_value=_make_profile(),
    ), patch(
        "merid.prediction.forecasters.fvg.get_fvg_forecaster",
        return_value=fvg_forecaster,
    ), patch(
        "merid.prediction.agent_grid_15m.get_settlement_input_price",
        return_value=(65000.0, 0.0),
    ):
        return agent._generate_momentum_fvg_signal("BTC", 65000.0, market, 5.0)


class TestYesSidePriceLockMatrix:
    """Boundary tests for a bullish YES thesis."""

    @pytest.fixture
    def agent(self):
        return _make_agent(prefer_maker=True, bearish=False)

    @pytest.mark.parametrize(
        "best_ask, expected_accepted, label",
        [
            (9, False, "YES thesis at 9c (below 10c) rejects"),
            (10, True, "YES thesis at 10c (inclusive) accepts"),
            (75, True, "YES thesis at 75c (inclusive) accepts"),
            (76, False, "YES thesis at 76c (above 75c) rejects"),
        ],
    )
    def test_yes_thesis_boundary(self, agent, best_ask, expected_accepted, label):
        """YES thesis must be accepted only inside 10c-75c."""
        signal = _run_signal(agent, velocity=0.0002, best_ask=best_ask)
        assert (signal is not None) == expected_accepted, label
        if signal is not None:
            assert signal["side"] == "yes"


class TestNoSidePriceLockMatrix:
    """Boundary tests for a bearish NO thesis."""

    @pytest.fixture
    def agent(self):
        # Bearish stack with macd < 0 and rsi < 60 so confluence can produce a NO thesis.
        return _make_agent(prefer_maker=True, bearish=True)

    @pytest.mark.parametrize(
        "best_bid, expected_accepted, label",
        [
            (91, False, "NO thesis at 9c (below 10c) rejects"),
            (90, True, "NO thesis at 10c (inclusive) accepts"),
            (25, True, "NO thesis at 75c (inclusive) accepts"),
            (24, False, "NO thesis at 76c (above 75c) rejects"),
        ],
    )
    def test_no_thesis_boundary(self, agent, best_bid, expected_accepted, label):
        """NO thesis = 100 - best_bid; must be inside 10c-75c."""
        no_price = 100 - best_bid
        # negative velocity below threshold lets confluence drive the thesis side
        signal = _run_signal(
            agent,
            velocity=-0.0001,
            best_bid=best_bid,
            best_ask=10,
            obi_yes=0,
            obi_no=100,
            fvg_dir="bearish",
            fvg_conf=0.9,
        )
        assert (signal is not None) == expected_accepted, (
            f"{label} (NO price={no_price}c)"
        )
        if signal is not None:
            assert signal["side"] == "no"


class TestThesisSideOutOfRangeWithOppositeInRange:
    """Strict side lock: thesis side out of range must never fall back."""

    def test_yes_thesis_rejects_when_opposite_no_in_range(self):
        """YES thesis out of range, NO in range -> reject."""
        # best_ask=5 gives YES=5 (out of range), best_bid=50 gives NO=50 (in range)
        agent = _make_agent(prefer_maker=True, bearish=False)
        signal = _run_signal(
            agent,
            velocity=0.0002,
            best_bid=50,
            best_ask=5,
        )
        assert signal is None, "Side lock must reject out-of-range YES thesis even when NO is in range"

    def test_no_thesis_rejects_when_opposite_yes_in_range(self):
        """NO thesis out of range, YES in range -> reject."""
        # best_bid=95 gives NO=5 (out of range), best_ask=10 gives YES=10 (in range)
        agent = _make_agent(prefer_maker=True, bearish=True)
        signal = _run_signal(
            agent,
            velocity=-0.0001,
            best_bid=95,
            best_ask=10,
            obi_yes=0,
            obi_no=100,
            fvg_dir="bearish",
            fvg_conf=0.9,
        )
        assert signal is None, "Side lock must reject out-of-range NO thesis even when YES is in range"
