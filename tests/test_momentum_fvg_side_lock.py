"""Tests for momentum_fvg side-lock, confluence, and role-aware EV gate.

These tests exercise the actual ``_generate_momentum_fvg_signal`` path with
synthetic market state and patched external dependencies. They verify the exact
failure cases that blocked trading:

1. Near-zero / below-threshold velocity must not create a directional thesis
   unless confluence is clear.
2. The signal side is locked to the thesis side; no counter-trend/opposite-side
   fallback is allowed.
3. The EV gate is role-aware: maker (resting) orders use a 0c fee and a small
   impact reserve, so positive model edges become tradable; taker orders use the
   real exchange fee and are rejected when the edge does not clear it.
4. Execution parameters are resolved at signal generation and propagated into the
   candidate dict for the loop/router to consume.
"""

import time
import types
import pytest
from unittest.mock import Mock, MagicMock, patch

from merid.prediction.agent_grid_15m import LeanAgentConfig, LeanAgent15m


# Allowable canonical entry range is 10c-75c for both YES and NO.
YES_ASK_CENTS = 53
NO_ASK_CENTS = 100 - 50  # best_bid=50 -> NO ask = 50
OUT_OF_RANGE_YES_ASK = 5
OUT_OF_RANGE_BEST_BID = 30  # NO ask = 70, in range


def _make_profile():
    """Create a minimal Crypto15mProfile-shaped object for the tests."""
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


def _make_agent(prefer_maker=True):
    """Create a LeanAgent15m with a patched indicator stack for testing."""
    config = LeanAgentConfig(
        name="BTC_15M",
        series_tickers=["KXBTC15M"],
        signal_mode="momentum_fvg",
        prefer_maker_orders=prefer_maker,
    )

    catalog = Mock()
    market_state_store = Mock()
    spot_provider = Mock()
    order_router = Mock()
    risk_config = Mock()

    agent = LeanAgent15m(
        config=config,
        catalog=catalog,
        market_state_store=market_state_store,
        spot_provider=spot_provider,
        order_router=order_router,
        risk_config=risk_config,
    )

    # Feed the indicator stack a warm, bullish snapshot so the fallback path
    # (macd=0, rsi=50, neutral zone) does not suppress the confluence we want.
    indicator_snap = MagicMock()
    indicator_snap.bars_available = 30
    indicator_snap.macd_line = 0.0
    indicator_snap.macd_histogram = 0.001
    indicator_snap.rsi = 60.0
    indicator_snap.rsi_zone = "neutral"
    indicator_snap.macro_regime = "bull"
    indicator_snap.price_above_ema_200 = True
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
    """Return a market-state-shaped mock for _generate_momentum_fvg_signal."""
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
        "signal_type": "strong_long" if velocity > 0 else "neutral",
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


class TestMomentumFVGSideLock:
    """Test side-lock, confluence thesis, and role-aware EV gate."""

    def test_velocity_thesis_is_maker_with_role_aware_ev(self):
        """A clear velocity thesis selects YES and rests as a maker."""
        agent = _make_agent(prefer_maker=True)
        signal = _run_signal(agent, velocity=0.0002)

        assert signal is not None, "Expected a velocity-based YES signal"
        assert signal["side"] == "yes"
        assert signal["thesis_side"] == "yes"
        assert signal["thesis_source"] == "velocity"
        assert signal["is_counter_trend"] is False
        assert signal["liquidity_role"] == "maker"
        assert signal["execution_mode"] == "maker"
        assert signal["aggressiveness"] == 0.0
        assert signal["post_only"] is True
        assert signal["time_in_force"] == "gtc"
        assert signal["order_type"] == "limit"
        assert signal["fee_cents"] == 0.0
        assert signal["impact_reserve_cents"] == 0.5
        assert signal["ev_net_cents"] > 0.0
        assert signal["all_in_cost_cents"] == signal["price_cents"] + signal["fee_cents"] + signal["impact_reserve_cents"]

    def test_confluence_thesis_is_maker_with_role_aware_ev(self):
        """When velocity is neutral, a clear confluence score selects YES as maker."""
        agent = _make_agent(prefer_maker=True)
        # velocity below the ~0.00015 BTC threshold, so the thesis must come from confluence.
        signal = _run_signal(agent, velocity=0.0001, fvg_dir=0.0, fvg_conf=0.0)

        assert signal is not None, "Expected a confluence-based YES signal"
        assert signal["side"] == "yes"
        assert signal["thesis_source"] == "confluence"
        assert signal["is_counter_trend"] is False
        assert signal["liquidity_role"] == "maker"
        assert signal["fee_cents"] == 0.0
        assert signal["ev_net_cents"] > 0.0

    def test_neutral_velocity_and_weak_confluence_reject(self):
        """Near-zero velocity with no clear confluence must produce no signal."""
        agent = _make_agent(prefer_maker=True)
        # velocity effectively zero and no OBI/FVG confirmation
        signal = _run_signal(
            agent,
            velocity=0.0,
            obi_yes=0,
            obi_no=0,
            fvg_dir=0.0,
            fvg_conf=0.0,
        )
        assert signal is None, "No signal expected when velocity and confluence are neutral"

    def test_side_lock_rejects_out_of_range_thesis_no_counter_trend(self):
        """If the thesis side is out of range, the model must not fall back to the opposite side."""
        agent = _make_agent(prefer_maker=True)
        signal = _run_signal(
            agent,
            velocity=0.0002,
            best_bid=OUT_OF_RANGE_BEST_BID,
            best_ask=OUT_OF_RANGE_YES_ASK,
            obi_yes=100,
            obi_no=0,
            fvg_dir=0.0,
            fvg_conf=0.0,
        )
        assert signal is None, "No counter-trend fallback: thesis YES is out of range"

    def test_taker_fee_blocks_weak_edge(self):
        """With prefer_maker=False, the taker fee must block edges that do not clear it."""
        agent = _make_agent(prefer_maker=False)
        # Confluence-only edge is positive for a maker but not large enough to
        # cover the 2c taker fee + 0.5c impact reserve at 53c.
        signal = _run_signal(
            agent,
            velocity=0.0001,
            fvg_dir=0.0,
            fvg_conf=0.0,
        )
        assert signal is None, "Taker fee/impact reserve should block a weak edge"
