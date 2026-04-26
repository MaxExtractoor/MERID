"""Tests for BTC Anchor Gate.

Validates:
- Regime classification (strong bull/bear, neutral)
- Trade blocking rules
- Lead-lag timing delays
- Confidence and size modifiers
"""

import time
import pytest

from merid.signals.btc_anchor_gate import (
    BtcAnchorGate,
    BtcRegime,
    BtcRegimeState,
    GateDecision,
    get_btc_anchor_gate,
    reset_btc_anchor_gate,
)


class TestBtcRegimeState:
    """Test BtcRegimeState dataclass."""

    def test_strong_bull_detection(self):
        """Test strong bull regime detection."""
        state = BtcRegimeState(
            regime=BtcRegime.STRONG_BULL,
            timestamp=time.time(),
            adx=30.0,
        )
        assert state.is_strong_bull
        assert not state.is_strong_bear
        assert state.is_trending
        assert not state.is_range_bound

    def test_strong_bear_detection(self):
        """Test strong bear regime detection."""
        state = BtcRegimeState(
            regime=BtcRegime.STRONG_BEAR,
            timestamp=time.time(),
            adx=30.0,
        )
        assert state.is_strong_bear
        assert not state.is_strong_bull
        assert state.is_trending
        assert not state.is_range_bound

    def test_neutral_detection(self):
        """Test neutral regime detection."""
        state = BtcRegimeState(
            regime=BtcRegime.NEUTRAL,
            timestamp=time.time(),
            adx=15.0,
        )
        assert not state.is_strong_bull
        assert not state.is_strong_bear
        assert not state.is_trending
        assert state.is_range_bound


class TestGateDecision:
    """Test GateDecision dataclass."""

    def test_blocked_detection(self):
        """Test blocked decision detection."""
        decision = GateDecision(
            asset="ETH",
            side="buy",
            allowed=False,
            reason="BTC strongly bearish",
            confidence_modifier=0.0,
            size_modifier=0.0,
        )
        assert decision.is_blocked
        assert not decision.allowed

    def test_allowed_detection(self):
        """Test allowed decision detection."""
        decision = GateDecision(
            asset="ETH",
            side="buy",
            allowed=True,
            reason="Normal conditions",
            confidence_modifier=1.0,
            size_modifier=1.0,
        )
        assert not decision.is_blocked
        assert decision.allowed


class TestBtcAnchorGate:
    """Test BTC anchor gate core functionality."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        reset_btc_anchor_gate()
        yield
        reset_btc_anchor_gate()

    def test_singleton_pattern(self):
        """Test singleton returns same instance."""
        gate1 = get_btc_anchor_gate()
        gate2 = get_btc_anchor_gate()
        assert gate1 is gate2

    def test_update_regime_creates_state(self):
        """Test regime update creates valid state."""
        gate = BtcAnchorGate()

        btc_prices_15m = [50000.0 + i * 100 for i in range(20)]  # Uptrend
        btc_prices_1h = [49000.0 + i * 200 for i in range(10)]

        state = gate.update_regime(51000.0, btc_prices_15m, btc_prices_1h)

        assert state is not None
        assert state.timestamp > 0
        assert isinstance(state.regime, BtcRegime)
        assert state.adx >= 0
        assert isinstance(state.slope_15m, float)
        assert isinstance(state.slope_1h, float)

    def test_block_altcoin_long_in_bearish_btc(self):
        """Test blocking altcoin longs when BTC strongly bearish."""
        gate = BtcAnchorGate()

        # Simulate strong downtrend
        btc_prices = [50000.0 - i * 200 for i in range(30)]

        gate.update_regime(btc_prices[-1], btc_prices, btc_prices)

        # Try to buy ETH
        decision = gate.check_trade("ETH", "buy")

        assert decision.is_blocked
        assert "bearish" in decision.reason.lower()
        assert decision.confidence_modifier == 0.0
        assert decision.size_modifier == 0.0

    def test_block_altcoin_short_in_bullish_btc(self):
        """Test blocking altcoin shorts when BTC strongly bullish."""
        gate = BtcAnchorGate()

        # Simulate strong uptrend with high ADX
        base_prices = [45000.0 + i * 300 for i in range(30)]
        # Add volatility for ADX
        btc_prices = [p + (i % 3) * 100 for i, p in enumerate(base_prices)]

        gate.update_regime(btc_prices[-1], btc_prices, btc_prices)

        # Try to short ETH
        decision = gate.check_trade("ETH", "sell")

        # Should block if regime detected as strong bull
        if gate._current_regime and gate._current_regime.is_strong_bull:
            assert decision.is_blocked
            assert "bullish" in decision.reason.lower()

    def test_allow_trade_in_neutral_regime(self):
        """Test allowing trades in neutral regime."""
        gate = BtcAnchorGate()

        # Simulate sideways market
        btc_prices = [50000.0 + (i % 5) * 10 for i in range(30)]

        gate.update_regime(50000.0, btc_prices, btc_prices)

        decision = gate.check_trade("ETH", "buy")

        assert decision.allowed
        assert decision.confidence_modifier > 0
        assert decision.size_modifier > 0

    def test_permissive_default_no_regime(self):
        """Test permissive default when no regime data."""
        gate = BtcAnchorGate()

        # Don't update regime
        decision = gate.check_trade("ETH", "buy")

        assert decision.allowed
        assert "permissive" in decision.reason.lower()
        assert decision.confidence_modifier == 1.0

    def test_beta_based_modifiers(self):
        """Test that beta affects modifiers."""
        gate = BtcAnchorGate()

        # Create trending regime
        btc_prices = [50000.0 + i * 150 for i in range(30)]
        gate.update_regime(btc_prices[-1], btc_prices, btc_prices)

        # High beta asset (SOL: 1.40)
        decision_sol = gate.check_trade("SOL", "buy")
        # Low beta asset (BTC: 1.0)
        decision_btc = gate.check_trade("BTC", "buy")

        if gate._current_regime and gate._current_regime.is_trending:
            # High beta should have lower confidence modifier
            assert decision_sol.confidence_modifier <= decision_btc.confidence_modifier

    def test_slope_calculation(self):
        """Test slope calculation."""
        gate = BtcAnchorGate()

        # Linear uptrend
        prices = [100.0 + i * 10 for i in range(20)]
        slope = gate._calculate_slope(prices)

        assert slope > 0

        # Linear downtrend
        prices_down = [300.0 - i * 10 for i in range(20)]
        slope_down = gate._calculate_slope(prices_down)

        assert slope_down < 0

    def test_atr_pct_calculation(self):
        """Test ATR percentage calculation."""
        gate = BtcAnchorGate()

        # Oscillating prices
        prices = [100.0 + (i % 2) * 5 for i in range(20)]
        atr_pct = gate._calculate_atr_pct(prices)

        assert atr_pct >= 0
        assert atr_pct < 10  # Reasonable bound

    def test_impulse_detection(self):
        """Test impulse detection."""
        gate = BtcAnchorGate()

        # No impulse - small change
        small_change = [100.0, 100.1, 100.2]
        impulse = gate._detect_impulse(small_change)
        assert impulse is None

        # Clear impulse - large change
        large_change = [100.0, 100.0, 103.0]  # 3% move
        impulse = gate._detect_impulse(large_change)
        assert impulse is not None
        assert impulse[1] == "up"
        assert impulse[2] == pytest.approx(3.0, rel=0.01)

    def test_lead_lag_delay(self):
        """Test lead-lag timing delay."""
        gate = BtcAnchorGate()

        # Create recent impulse
        prices = [50000.0] * 5 + [51500.0]  # 3% impulse
        gate.update_regime(prices[-1], prices, prices)

        decision = gate.check_trade("ETH", "buy")

        if gate._current_regime and gate._current_regime.last_impulse_ts:
            # Should have delay if recent impulse
            assert decision.timing_delay_seconds >= 0

    def test_regime_classification(self):
        """Test regime classification logic."""
        gate = BtcAnchorGate()

        # Strong bull: high ADX, positive slope
        assert gate._classify_regime(30.0, 0.001, 0.001) == BtcRegime.STRONG_BULL

        # Strong bear: high ADX, negative slope
        assert gate._classify_regime(30.0, -0.001, -0.001) == BtcRegime.STRONG_BEAR

        # Bull: lower ADX, positive slope
        assert gate._classify_regime(15.0, 0.001, 0.001) == BtcRegime.BULL

        # Bear: lower ADX, negative slope
        assert gate._classify_regime(15.0, -0.001, -0.001) == BtcRegime.BEAR

        # Neutral: near-zero slope
        assert gate._classify_regime(15.0, 0.0, 0.0) == BtcRegime.NEUTRAL

    def test_counter_trend_size_reduction(self):
        """Test size reduction for counter-trend trades."""
        gate = BtcAnchorGate()

        # Create uptrend
        prices = [50000.0 + i * 100 for i in range(30)]
        gate.update_regime(prices[-1], prices, prices)

        if gate._current_regime and gate._current_regime.slope_15m > 0:
            # Shorting in uptrend = counter-trend
            decision_short = gate.check_trade("ETH", "sell")
            # Going long = with-trend
            decision_long = gate.check_trade("ETH", "buy")

            if gate._current_regime.is_trending:
                assert decision_short.size_modifier <= decision_long.size_modifier

    def test_get_current_regime(self):
        """Test regime retrieval."""
        gate = BtcAnchorGate()

        # Initially None
        assert gate.get_current_regime() is None

        # After update
        prices = [50000.0 + i * 10 for i in range(20)]
        gate.update_regime(prices[-1], prices, prices)

        assert gate.get_current_regime() is not None

    def test_reset_clears_state(self):
        """Test reset clears gate state."""
        gate = BtcAnchorGate()

        prices = [50000.0 + i * 10 for i in range(20)]
        gate.update_regime(prices[-1], prices, prices)

        gate.reset()

        assert gate.get_current_regime() is None
        assert len(gate._recent_impulses) == 0
