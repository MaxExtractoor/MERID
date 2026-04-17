import pytest
from unittest.mock import MagicMock, patch

from merid.prediction.opinion_strategy import (
    SpotBasisFairValueStrategy,
    get_strategy,
)
from merid.prediction.opinion_strategy import TrendMomentumOpinionStrategy


def _mock_tsm(ready=True, fair_prob=0.65, up_prob=0.55, bracket_prob=0.25):
    m = MagicMock()
    m.is_ready.return_value = ready
    m.fair_prob.return_value = fair_prob
    m.up_prob.return_value = up_prob
    m.bracket_prob.return_value = bracket_prob
    return m


_PATCH = "merid.risk.crypto_term_structure.get_global_crypto_tsm"


class TestSpotBasisFairValueStrategy:

    def test_returns_none_when_not_ready(self):
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(ready=False)):
            result = s.estimate("ag", "KXBTC-T95000", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result is None

    def test_threshold_uses_fair_prob(self):
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(fair_prob=0.70)):
            result = s.estimate("ag", "KXBTC-T95000", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result is not None
        assert result.agent_prob == pytest.approx(0.70, abs=0.01)
        assert result.edge == pytest.approx(0.20, abs=0.01)

    def test_up_down_uses_up_prob(self):
        s = SpotBasisFairValueStrategy()
        tsm = _mock_tsm(up_prob=0.58)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is not None
        tsm.up_prob.assert_called_once_with("BTC", 900.0)

    def test_bracket_uses_bracket_prob(self):
        s = SpotBasisFairValueStrategy()
        tsm = _mock_tsm(bracket_prob=0.30)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC-B", 0.15,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "bracket",
                                         "bracket": (90_000.0, 100_000.0)})
        assert result is not None
        tsm.bracket_prob.assert_called_once_with("BTC", 3_600.0, 90_000.0, 100_000.0)

    def test_edge_below_min_returns_none(self):
        s = SpotBasisFairValueStrategy(min_edge=0.05)
        with patch(_PATCH, return_value=_mock_tsm(fair_prob=0.51)):
            result = s.estimate("ag", "KXBTC-T", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result is None

    def test_no_orderbook_overlay_for_long_horizon(self):
        s = SpotBasisFairValueStrategy()
        tsm = _mock_tsm(fair_prob=0.70)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTCW1-T", 0.50,
                                context={"asset": "BTC", "horizon_secs": 7 * 86_400.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result is not None
        assert result.agent_prob == pytest.approx(0.70, abs=0.01)

    def test_p_model_clipped(self):
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(up_prob=0.9999)):
            result = s.estimate("ag", "KXBTC15M-UP", 0.10,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is not None
        assert result.agent_prob <= 1 - 1e-4

    def test_registered_in_registry(self):
        s = get_strategy("spot_basis_fair_value")
        assert isinstance(s, SpotBasisFairValueStrategy)

    def test_reasoning_tag(self):
        s = SpotBasisFairValueStrategy()
        with patch(_PATCH, return_value=_mock_tsm(fair_prob=0.70)):
            result = s.estimate("ag", "KXBTC-T", 0.50,
                                context={"asset": "BTC", "horizon_secs": 3_600.0,
                                         "market_type": "threshold", "strike": 95_000.0})
        assert result.reasoning_tag == "spot_basis_fair_value"

    def test_orderbook_overlay_fires_for_short_horizon(self):
        s = SpotBasisFairValueStrategy(imbalance_weight=0.10)
        tsm = _mock_tsm(fair_prob=0.60)
        mock_state = MagicMock()
        mock_state.book_initialized = True
        mock_state.yes_bids = [(95, 100), (94, 50)]   # yes_depth = 150
        mock_state.no_bids  = [(6, 50)]                # no_depth = 50 → total=200, yes/total=0.75
        # imbalance_bias = (0.75 - 0.5) * 0.10 = 0.025
        store_mock = MagicMock()
        store_mock.get.return_value = mock_state
        store_patch = "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
        with patch(_PATCH, return_value=tsm):
            with patch(store_patch, return_value=store_mock):
                result = s.estimate("ag", "KXBTC-T", 0.50,
                                    context={"asset": "BTC", "horizon_secs": 900.0,
                                             "market_type": "threshold", "strike": 95_000.0})
        assert result is not None
        assert result.agent_prob == pytest.approx(0.625, abs=0.001)  # 0.60 + 0.025
        assert "orderbook_imbalance" in result.signal_sources


def _mock_tsm_trend(ready=True, prices=None, returns=None, fair_prob=0.55):
    m = MagicMock()
    m.is_ready.return_value = ready
    m.get_recent_prices.return_value = prices or [100.0] * 50
    m.get_returns.return_value = returns if returns is not None else [0.001] * 30
    m.fair_prob.return_value = fair_prob
    m.bracket_prob.return_value = 0.25
    return m


class TestTrendMomentumOpinionStrategy:

    def test_returns_none_when_not_ready(self):
        s = TrendMomentumOpinionStrategy()
        tsm = _mock_tsm_trend(ready=False)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is None

    def test_returns_none_with_insufficient_history(self):
        s = TrendMomentumOpinionStrategy()
        # get_returns returns fewer bars than long_w (30 for ≤15m)
        tsm = _mock_tsm_trend(returns=[0.001] * 5)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is None

    def test_up_down_bullish_signal_above_half(self):
        s = TrendMomentumOpinionStrategy()
        # Rising prices: short MA > long MA → bullish
        prices = [100.0 + i * 0.5 for i in range(40)]
        tsm = _mock_tsm_trend(
            prices=prices,
            returns=[0.005] * 40,  # strongly positive returns
        )
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is not None
        assert result.agent_prob > 0.50
        assert "bullish" in result.reasoning_tag

    def test_up_down_bearish_signal_below_half(self):
        s = TrendMomentumOpinionStrategy()
        prices = [100.0 - i * 0.5 for i in range(40)]
        tsm = _mock_tsm_trend(
            prices=prices,
            returns=[-0.005] * 40,
        )
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        assert result is not None
        assert result.agent_prob < 0.50
        assert "bearish" in result.reasoning_tag

    def test_signal_capped_at_max_strength(self):
        s = TrendMomentumOpinionStrategy(max_signal_strength=0.10)
        # Extreme signal: all large positive returns + steep price rise
        prices = [100.0 + i * 10 for i in range(40)]
        tsm = _mock_tsm_trend(prices=prices, returns=[0.10] * 40)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.50,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        if result:
            assert result.agent_prob <= 0.50 + 0.10 + 1e-3

    def test_horizon_selects_correct_windows(self):
        """Verify that weekly horizon uses 480/4320 windows, not 5/30."""
        s = TrendMomentumOpinionStrategy()
        tsm = _mock_tsm_trend(
            prices=[100.0 + i * 0.1 for i in range(4_400)],
            returns=[0.001] * 4_400,
        )
        with patch(_PATCH, return_value=tsm):
            s.estimate("ag", "KXBTCW1-T", 0.50,
                       context={"asset": "BTC", "horizon_secs": 7 * 86_400.0,
                                "market_type": "up_down"})
        # For weekly horizon, long_w=4320; get_returns called with 4320
        call_args = tsm.get_returns.call_args_list
        long_w_calls = [c for c in call_args if c.args[1] >= 4_320]
        assert len(long_w_calls) > 0

    def test_p_model_clipped(self):
        s = TrendMomentumOpinionStrategy(max_signal_strength=0.99)
        prices = [100.0 + i * 100 for i in range(40)]
        tsm = _mock_tsm_trend(prices=prices, returns=[0.99] * 40)
        with patch(_PATCH, return_value=tsm):
            result = s.estimate("ag", "KXBTC15M-UP", 0.01,
                                context={"asset": "BTC", "horizon_secs": 900.0,
                                         "market_type": "up_down"})
        if result:
            assert 1e-4 <= result.agent_prob <= 1 - 1e-4

    def test_registered_in_registry(self):
        s = get_strategy("trend_momentum")
        assert isinstance(s, TrendMomentumOpinionStrategy)
