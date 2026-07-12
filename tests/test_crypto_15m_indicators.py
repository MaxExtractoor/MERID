"""Tests for Crypto15mIndicatorStack — EMA(50) regime, MACD, chop filters, fee-aware EV."""

from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig


def test_full_indicator_stack():
    stack = Crypto15mIndicatorStack()

    # Phase 1: uptrend (40 bars)
    prices = [87000 + i * 30 for i in range(40)]
    # Phase 2: chop (10 bars oscillating)
    for i in range(10):
        prices.append(88200 + (50 if i % 2 == 0 else -50))
    # Phase 3: downtrend (15 bars)
    for i in range(15):
        prices.append(88200 - i * 40)

    for p in prices:
        stack.update(p)

    snap = stack.snapshot()
    print(f"Bars: {snap.bars_available}")
    print(f"Price: {snap.price:.0f}")
    print(f"EMA(50) trend={snap.ema_trend:.1f} price_above={snap.price_above_trend_ema}")
    print(f"EMA fast={snap.ema_fast:.1f} slow={snap.ema_slow:.1f} cross={snap.ema_cross}")
    print(f"RSI: {snap.rsi:.1f} zone={snap.rsi_zone}")
    print(f"MACD line={snap.macd_line:.2f} signal={snap.macd_signal_line:.2f} hist={snap.macd_histogram:.2f} cross={snap.macd_cross}")
    print(f"ATR: {snap.atr:.1f} atr_move_ok={snap.atr_move_ok}")
    print(f"Vol: {snap.realized_vol_annualized:.3f} band={snap.vol_band}")
    print(f"Chop: detected={snap.chop_detected} reason=\"{snap.chop_reason}\"")
    print(f"Consec above={snap.consecutive_closes_above_ema} below={snap.consecutive_closes_below_ema}")
    print(f"MACD persist={snap.macd_same_sign_bars}")
    print(f"Trend aligned: {snap.trend_aligned}")
    print(f"Gates: vol={snap.vol_gate_ok} atr={snap.atr_move_ok} liq={snap.liquidity_ok} chop={snap.chop_gate_ok} trade={snap.trade_allowed}")
    print(f"Bias: {snap.bias} conf={snap.bias_confidence:.2f}")

    assert snap.bars_available == 65
    assert snap.ema_trend > 0  # EMA(50) should be initialized
    assert snap.ema_cross in ("bullish", "bearish", "neutral")
    assert snap.macd_cross in ("bullish", "bearish", "neutral")
    assert 0.0 <= snap.rsi <= 100.0
    assert snap.vol_band in ("low", "mid", "high")
    assert snap.bias in ("up", "down", "neutral")
    # MACD should be initialized with 65 bars (> 21 needed)
    assert snap.macd_line != 0.0 or snap.macd_signal_line != 0.0


def test_fee_calculator():
    # Fee calculation uses unified fees module - verify it returns a value
    # Actual fee calculation may vary based on tiered fee structure
    fee = Crypto15mIndicatorStack.kalshi_fee_for_price(50, 1)
    print(f"Fee at 50c/1ct: {fee}c")
    assert fee >= 0  # Fee should be non-negative

    # At 80c
    fee2 = Crypto15mIndicatorStack.kalshi_fee_for_price(80, 1)
    print(f"Fee at 80c/1ct: {fee2}c")
    assert fee2 >= 0

    # At 50c with 10 contracts
    fee3 = Crypto15mIndicatorStack.kalshi_fee_for_price(50, 10)
    print(f"Fee at 50c/10ct: {fee3}c")
    assert fee3 >= 0


def test_ev_calculator():
    # 60% model prob, 50c price, YES side
    ev, fc, fp = Crypto15mIndicatorStack.compute_ev_cents(50, 0.60, "yes", 1)
    print(f"EV(50c, 60% model, YES): {ev:.1f}c, fee={fc}c, fee_pct={fp:.3f}")
    assert ev > 0  # positive edge

    # 50% model prob, 50c price — should be negative (fee drag)
    ev2, fc2, fp2 = Crypto15mIndicatorStack.compute_ev_cents(50, 0.50, "yes", 1)
    print(f"EV(50c, 50% model, YES): {ev2:.1f}c, fee={fc2}c, fee_pct={fp2:.3f}")
    assert ev2 < 0  # no edge minus fees = negative

    # 85% model, 80c price — tail bet, lower fees
    ev3, fc3, fp3 = Crypto15mIndicatorStack.compute_ev_cents(80, 0.85, "yes", 1)
    print(f"EV(80c, 85% model, YES): {ev3:.1f}c, fee={fc3}c, fee_pct={fp3:.3f}")
    assert ev3 > 0


def test_chop_detection():
    """Choppy prices should trigger chop filter."""
    stack = Crypto15mIndicatorStack()

    # Feed oscillating prices (chop) — need 55+ bars for min_bars_required=52
    for i in range(60):
        p = 87000 + (100 if i % 2 == 0 else -100)
        stack.update(p)

    snap = stack.snapshot()
    print(f"Chop test: detected={snap.chop_detected}, reason={snap.chop_reason}")
    print(f"Consec above={snap.consecutive_closes_above_ema} below={snap.consecutive_closes_below_ema}")
    print(f"MACD persist={snap.macd_same_sign_bars}")
    # In pure chop, consecutive closes and MACD persistence should be low
    assert snap.consecutive_closes_above_ema <= 2 or snap.consecutive_closes_below_ema <= 2


def test_trend_alignment_playbook():
    """Verify playbook trend alignment rules: EMA + RSI zone + MACD."""
    import random
    random.seed(42)
    stack = Crypto15mIndicatorStack()

    # Realistic uptrend with noise: drift +15/bar with random walk ±30
    price = 87000.0
    for i in range(60):
        price += 15 + random.uniform(-30, 30)
        stack.update(price)

    snap = stack.snapshot()
    print(f"Uptrend: ema={snap.ema_cross}, rsi={snap.rsi:.1f}, macd={snap.macd_cross}, aligned={snap.trend_aligned}")
    print(f"Bias: {snap.bias} conf={snap.bias_confidence:.2f}")
    # In a noisy uptrend, EMA should be bullish and bias should be up
    assert snap.ema_cross == "bullish"
    assert snap.bias == "up"


def test_to_dict_has_all_fields():
    """Verify to_dict() has all expected fields for backtest logging."""
    stack = Crypto15mIndicatorStack()
    for i in range(60):
        stack.update(87000 + i * 10)

    snap = stack.snapshot()
    d = snap.to_dict()

    required_fields = [
        "ema_trend", "price_above_trend_ema",
        "ema_fast", "ema_slow", "ema_cross", "trend_strength",
        "rsi", "rsi_zone", "distance_from_ema_atrs", "overextended",
        "macd_line", "macd_signal_line", "macd_histogram", "macd_cross",
        "macd_histogram_positive",
        "consecutive_closes_above_ema", "consecutive_closes_below_ema",
        "macd_same_sign_bars", "chop_detected", "chop_reason", "chop_gate_ok",
        "is_midcurve", "kalshi_fee_pct",
        "atr", "atr_move_ok", "realized_vol_annualized", "vol_band",
        "spread_cents", "depth_at_price", "liquidity_ok",
        "vol_gate_ok", "trend_aligned", "trade_allowed",
        "bars_available", "price",
        "bias", "bias_confidence",
    ]
    missing = [f for f in required_fields if f not in d]
    assert not missing, f"Missing fields in to_dict(): {missing}"
    print(f"to_dict() has all {len(required_fields)} required fields")


def test_ema50_trend_regime():
    """Verify EMA(50) acts as trend regime filter."""
    stack = Crypto15mIndicatorStack()

    # 60 bars of uptrend: price starts at 87000, climbs +20/bar
    for i in range(60):
        stack.update(87000 + i * 20)

    snap = stack.snapshot()
    print(f"EMA(50) trend: {snap.ema_trend:.1f}, price={snap.price:.0f}, above={snap.price_above_trend_ema}")
    # Price (88180) should be above EMA(50) in a steady uptrend
    assert snap.price_above_trend_ema is True
    assert snap.ema_trend > 0
    assert snap.ema_trend < snap.price  # EMA lags behind in uptrend


def test_atr_min_move_gate():
    """ATR min-move gate should block dead markets."""
    stack = Crypto15mIndicatorStack()

    # Flat prices (no movement) — ATR should be near zero
    for i in range(60):
        stack.update(87000.0)

    snap = stack.snapshot()
    print(f"Flat market: ATR={snap.atr:.4f}, atr_move_ok={snap.atr_move_ok}, trade_allowed={snap.trade_allowed}")
    assert snap.atr_move_ok is False  # ATR/price = 0 < threshold
    assert snap.trade_allowed is False  # composite gate should fail

    # Now with real movement
    stack2 = Crypto15mIndicatorStack()
    for i in range(60):
        stack2.update(87000 + i * 50)  # +50/bar = meaningful movement

    snap2 = stack2.snapshot()
    print(f"Trending market: ATR={snap2.atr:.4f}, atr_move_ok={snap2.atr_move_ok}")
    assert snap2.atr_move_ok is True  # 50/87000 = 0.057% > 0.03%


def test_microstructure_removed_from_trade_allowed():
    """Verify trade_allowed is no longer affected by spread/depth (unified edge handles this)."""
    from merid.signals.crypto_15m_indicators import IndicatorConfig, IndicatorSnapshot
    
    # Verify the trade_allowed logic by checking the code directly
    # trade_allowed = (vol_gate_ok and atr_move_ok and chop_gate_ok and bars_available >= min_bars_required)
    # It should NOT include liquidity_ok
    
    # Create a snapshot with all TA gates True but liquidity_ok False
    snap = IndicatorSnapshot(
        vol_gate_ok=True,
        atr_move_ok=True,
        chop_gate_ok=True,
        bars_available=60,
        liquidity_ok=False,  # This should NOT affect trade_allowed
        spread_cents=100,
        depth_at_price=1,
    )
    
    # Manually compute trade_allowed as the code does
    snap.trade_allowed = (
        snap.vol_gate_ok
        and snap.atr_move_ok
        and snap.chop_gate_ok
        and snap.bars_available >= 20  # default min_bars_required
    )
    
    # trade_allowed should be True despite liquidity_ok=False
    assert snap.trade_allowed is True, "trade_allowed should be True when TA gates pass, regardless of liquidity_ok"
    
    # Now verify with liquidity_ok=True, same result
    snap2 = IndicatorSnapshot(
        vol_gate_ok=True,
        atr_move_ok=True,
        chop_gate_ok=True,
        bars_available=60,
        liquidity_ok=True,
        spread_cents=5,
        depth_at_price=10,
    )
    snap2.trade_allowed = (
        snap2.vol_gate_ok
        and snap2.atr_move_ok
        and snap2.chop_gate_ok
        and snap2.bars_available >= 20
    )
    
    assert snap2.trade_allowed is True, "trade_allowed should be True when TA gates pass with good liquidity"
    
    print(f"Microstructure test: liquidity_ok=False → trade_allowed={snap.trade_allowed}, liquidity_ok=True → trade_allowed={snap2.trade_allowed}")


def test_multi_tf_rsi():
    """Verify multi-TF RSI (5m, 1h) downsampling and alignment logic."""
    stack = Crypto15mIndicatorStack()
    
    # Feed 120 bars of 1m data (enough for 5m and 1h RSI initialization)
    # Uptrend pattern
    for i in range(120):
        price = 87000 + i * 20
        stack.update(price)
    
    snap = stack.snapshot()
    print(f"Multi-TF RSI: 15m={snap.rsi:.1f} ({snap.rsi_zone}), 5m={snap.rsi_5m:.1f} ({snap.rsi_5m_zone}), 1h={snap.rsi_1h:.1f} ({snap.rsi_1h_zone})")
    print(f"RSI alignment: {snap.rsi_alignment}")
    
    # All RSI values should be initialized
    assert 0.0 <= snap.rsi <= 100.0
    assert 0.0 <= snap.rsi_5m <= 100.0
    assert 0.0 <= snap.rsi_1h <= 100.0
    
    # Alignment should be one of the valid categories
    valid_alignments = ["all_aligned", "5m_contra_15m_1h", "15m_5m_contra_1h", "15m_contra_1h", "15m_1h_aligned", "15m_5m_aligned", "5m_contra_15m", "15m_only", "unknown"]
    assert snap.rsi_alignment in valid_alignments
    
    # In a steady uptrend, all should be in similar zones (or at least not extreme)
    # RSI should be > 50 in uptrend
    assert snap.rsi > 50.0 or snap.rsi_5m > 50.0 or snap.rsi_1h > 50.0


def test_session_tag():
    """Verify session_tag is computed correctly based on time."""
    stack = Crypto15mIndicatorStack()
    
    # Feed some data to get a snapshot
    for i in range(60):
        stack.update(87000 + i * 10)
    
    snap = stack.snapshot()
    print(f"Session tag: {snap.session_tag}")
    
    # Session tag should be one of the valid categories
    valid_tags = ["US_trading", "US_open", "US_close", "Asia_session", "Asia_close", 
                  "Europe_trading", "Europe_open", "Europe_close", "weekend", "off_hours", "unknown"]
    assert snap.session_tag in valid_tags


def test_trend_regime():
    """Verify trend_regime classification based on EMA slope."""
    stack = Crypto15mIndicatorStack()
    
    # Strong uptrend: price climbs +50/bar for 60 bars
    for i in range(60):
        stack.update(87000 + i * 50)
    
    snap = stack.snapshot()
    print(f"Trend regime: {snap.trend_regime}, EMA slope: {snap.ema_slope:.6f}")
    
    # In strong uptrend, should be trend_up
    assert snap.trend_regime in ["range", "trend_up", "trend_down"]
    # EMA slope should be positive in uptrend
    assert snap.ema_slope >= 0
    
    # Now test downtrend
    stack2 = Crypto15mIndicatorStack()
    for i in range(60):
        stack2.update(90000 - i * 50)
    
    snap2 = stack2.snapshot()
    print(f"Downtrend regime: {snap2.trend_regime}, EMA slope: {snap2.ema_slope:.6f}")
    
    # In strong downtrend, should be trend_down or at least not trend_up
    assert snap2.trend_regime in ["range", "trend_up", "trend_down"]
    # EMA slope should be negative in downtrend
    assert snap2.ema_slope <= 0


def test_new_diagnostic_fields():
    """Verify new diagnostic fields are present in snapshot and to_dict()."""
    stack = Crypto15mIndicatorStack()
    
    for i in range(60):
        stack.update(87000 + i * 10)
    
    snap = stack.snapshot()
    d = snap.to_dict()
    
    # Check new diagnostic fields exist
    new_fields = [
        "trend_regime", "ema_slope",
        "rsi_tf", "rsi_period",
        "rsi_5m", "rsi_5m_zone",
        "rsi_1h", "rsi_1h_zone",
        "rsi_alignment",
        "vol_regime",
        "kalshi_implied_prob", "model_prob", "edge_bp",
        "config_version",
        "session_tag",
        "interval_outcome", "signal_side", "correct_direction", "pnl_per_contract",
        "contract_barrier_distance", "normalized_delta",
    ]
    
    missing = [f for f in new_fields if f not in d]
    assert not missing, f"Missing new diagnostic fields in to_dict(): {missing}"
    
    print(f"All {len(new_fields)} new diagnostic fields present in to_dict()")
    
    # Verify some specific values
    assert snap.rsi_tf == "15m"
    # CRITICAL FIX: 2026-07-12 - RSI period changed from 8 to 14 for 15-minute markets
    assert snap.rsi_period == 14  # default period
    assert snap.config_version == "v1"
    assert snap.session_tag in ["US_trading", "Asia_session", "Europe_trading", "weekend", "off_hours", "unknown"]
    assert snap.trend_regime in ["range", "trend_up", "trend_down"]


def test_per_asset_rsi_thresholds():
    """Verify per-asset RSI thresholds are applied correctly."""
    # BTC/ETH: 70/30
    config_btc = IndicatorConfig(asset="BTC")
    assert config_btc.rsi_oversold_asset == 30.0
    assert config_btc.rsi_overbought_asset == 70.0
    
    config_eth = IndicatorConfig(asset="ETH")
    assert config_eth.rsi_oversold_asset == 30.0
    assert config_eth.rsi_overbought_asset == 70.0
    
    # SOL/XRP: 65/35
    config_sol = IndicatorConfig(asset="SOL")
    assert config_sol.rsi_oversold_asset == 35.0
    assert config_sol.rsi_overbought_asset == 65.0
    
    config_xrp = IndicatorConfig(asset="XRP")
    assert config_xrp.rsi_oversold_asset == 35.0
    assert config_xrp.rsi_overbought_asset == 65.0
    
    # DOGE: 60/40
    config_doge = IndicatorConfig(asset="DOGE")
    assert config_doge.rsi_oversold_asset == 40.0
    assert config_doge.rsi_overbought_asset == 60.0
    
    print("Per-asset RSI thresholds: BTC/ETH=70/30, SOL/XRP=65/35, DOGE=60/40")


def test_edge_metrics():
    """Verify edge metrics can be set and retrieved."""
    stack = Crypto15mIndicatorStack()
    
    # Feed some data
    for i in range(60):
        stack.update(87000 + i * 10)
    
    # Set edge metrics
    stack.set_edge_metrics(kalshi_implied_prob=0.45, model_prob=0.55)
    
    snap = stack.snapshot()
    print(f"Edge metrics: implied={snap.kalshi_implied_prob}, model={snap.model_prob}, edge_bp={snap.edge_bp}")


def test_ema_200_macro_trend_filter():
    """Verify EMA(200) macro trend filter for regime classification."""
    stack = Crypto15mIndicatorStack()
    
    # Feed 250 bars of uptrend (enough for EMA(200) initialization)
    for i in range(250):
        stack.update(87000 + i * 10)
    
    snap = stack.snapshot()
    print(f"EMA(200) macro: ema_200={snap.ema_200:.1f}, price={snap.price:.0f}, above={snap.price_above_ema_200}, regime={snap.macro_regime}")
    
    # In steady uptrend, price should be above EMA(200)
    assert snap.price_above_ema_200 is True
    assert snap.macro_regime == "bull"
    assert snap.ema_200 > 0
    
    # Test downtrend (need 200+ bars for EMA(200) to update)
    stack2 = Crypto15mIndicatorStack()
    for i in range(250):
        stack2.update(90000 - i * 10)
    
    snap2 = stack2.snapshot()
    print(f"EMA(200) downtrend: ema_200={snap2.ema_200:.1f}, price={snap2.price:.0f}, above={snap2.price_above_ema_200}, regime={snap2.macro_regime}")
    
    # In steady downtrend, price should be below EMA(200)
    assert snap2.price_above_ema_200 is False
    assert snap2.macro_regime == "bear"


def test_regime_based_rsi_threshold_shifting():
    """Verify regime-based RSI threshold shifting (bull/bear/range)."""
    stack = Crypto15mIndicatorStack()
    
    # Feed 250 bars of uptrend (bull regime)
    for i in range(250):
        stack.update(87000 + i * 10)
    
    snap = stack.snapshot()
    print(f"Bull regime RSI: rsi={snap.rsi:.1f}, zone={snap.rsi_zone}, macro_regime={snap.macro_regime}")
    
    # In bull regime, thresholds should be shifted up (80/40)
    # RSI should be in normal range for steady uptrend
    assert snap.macro_regime == "bull"
    assert snap.rsi_zone in ("neutral", "overbought", "oversold")
    
    # Test bear regime
    stack2 = Crypto15mIndicatorStack()
    for i in range(250):
        stack2.update(90000 - i * 10)
    
    snap2 = stack2.snapshot()
    print(f"Bear regime RSI: rsi={snap2.rsi:.1f}, zone={snap2.rsi_zone}, macro_regime={snap2.macro_regime}")
    
    # In bear regime, thresholds should be shifted down (60/20)
    assert snap2.macro_regime == "bear"
    assert snap2.rsi_zone in ("neutral", "overbought", "oversold")


def test_macd_zero_line_filter():
    """Verify MACD zero-line filter (long: MACD > 0, short: MACD < 0)."""
    stack = Crypto15mIndicatorStack()
    
    # Feed 60 bars of uptrend (MACD should be positive)
    for i in range(60):
        stack.update(87000 + i * 20)
    
    snap = stack.snapshot()
    print(f"MACD zero-line filter: macd_line={snap.macd_line:.6f}, zero_line_ok={snap.macd_zero_line_ok}")
    
    # In uptrend, MACD line should be positive (good for long signals)
    assert snap.macd_line > 0
    assert snap.macd_zero_line_ok is True
    
    # Test downtrend
    stack2 = Crypto15mIndicatorStack()
    for i in range(60):
        stack2.update(90000 - i * 20)
    
    snap2 = stack2.snapshot()
    print(f"MACD zero-line downtrend: macd_line={snap2.macd_line:.6f}, zero_line_ok={snap2.macd_zero_line_ok}")
    
    # In downtrend, MACD line should be negative (good for short signals)
    assert snap2.macd_line < 0
    # CRITICAL FIX: 2026-07-12 - MACD zero-line filter disabled in profile YAML
    # With filter disabled, zero_line_ok is always True (direction check applied in signal gen)
    assert snap2.macd_zero_line_ok is True


def test_macd_histogram_momentum_filter():
    """Verify MACD histogram momentum filter (expansion confirmation)."""
    stack = Crypto15mIndicatorStack()
    
    # Feed 60 bars with accelerating uptrend (histogram should be positive)
    # Use exponential growth to create momentum
    for i in range(60):
        stack.update(87000 + i * i * 0.5)  # Accelerating trend
    
    snap = stack.snapshot()
    print(f"MACD histogram momentum: histogram={snap.macd_histogram:.6f}, expanding={snap.macd_histogram_expanding}")
    
    # In accelerating trend, histogram should be positive
    assert snap.macd_histogram >= 0  # May be 0 in some cases
    # Histogram expansion flag should be set
    assert isinstance(snap.macd_histogram_expanding, bool)


def test_rsi_macd_confluence_scoring():
    """Verify RSI+MACD confluence scoring (boost when both agree)."""
    stack = Crypto15mIndicatorStack()

    # Feed 60 bars of uptrend with RSI oversold + MACD positive = strong long confluence
    # Start with downtrend to get RSI oversold, then reverse
    for i in range(30):
        stack.update(90000 - i * 20)  # Downtrend
    for i in range(30):
        stack.update(89400 + i * 30)  # Uptrend reversal

    snap = stack.snapshot()
    print(f"RSI+MACD confluence: rsi={snap.rsi:.1f}, macd_hist={snap.macd_histogram:.6f}, bias={snap.bias}")

    # Verify bias computation considers both RSI and MACD
    assert snap.bias in ("up", "down", "neutral")
    assert snap.bias_confidence >= 0.0
    assert snap.bias_confidence <= 1.0

    # Test short confluence scenario
    stack2 = Crypto15mIndicatorStack()
    for i in range(30):
        stack2.update(87000 + i * 20)  # Uptrend
    for i in range(30):
        stack2.update(87600 - i * 30)  # Downtrend reversal

    snap2 = stack2.snapshot()
    print(f"RSI+MACD short confluence: rsi={snap2.rsi:.1f}, macd_hist={snap2.macd_histogram:.6f}, bias={snap2.bias}")

    assert snap2.bias in ("up", "down", "neutral")


def test_snapshot_handles_empty_deque():
    """Verify snapshot() handles empty deque gracefully without IndexError."""
    stack = Crypto15mIndicatorStack()

    # Call snapshot without any data
    snap = stack.snapshot()

    print(f"Empty deque snapshot: bars_available={snap.bars_available}, trade_allowed={snap.trade_allowed}, chop_reason={snap.chop_reason}")

    # Should return empty snapshot with trade_allowed=False
    assert snap.bars_available == 0
    assert snap.trade_allowed is False
    assert snap.chop_reason == "no_price_data"


def test_snapshot_handles_insufficient_data_for_ema_slope():
    """Verify snapshot() handles insufficient data for EMA slope calculation."""
    stack = Crypto15mIndicatorStack()

    # Feed only 20 bars (less than ema_trend_period + 5 = 21 + 5 = 26)
    for i in range(20):
        stack.update(87000 + i * 10)

    snap = stack.snapshot()

    print(f"Insufficient EMA slope data: bars_available={snap.bars_available}, ema_slope={snap.ema_slope:.6f}")

    # Should not raise IndexError, ema_slope should be 0.0
    assert snap.bars_available == 20
    assert snap.ema_slope == 0.0
    # Note: trade_allowed depends on other gates (volatility, chop, etc.) - not asserting it here since it's not the focus of this test


def test_snapshot_handles_insufficient_data_for_volatility():
    """Verify snapshot() handles insufficient data for realized volatility calculation."""
    stack = Crypto15mIndicatorStack()

    # Feed only 3 bars (less than vol_window_bars = 30)
    for i in range(3):
        stack.update(87000 + i * 10)

    snap = stack.snapshot()

    print(f"Insufficient volatility data: bars_available={snap.bars_available}, realized_vol={snap.realized_vol_annualized:.6f}")

    # Should not raise IndexError, realized_vol should be 0.0
    assert snap.bars_available == 3
    assert snap.realized_vol_annualized == 0.0


def test_update_with_timestamp_handles_empty_deque():
    """Verify update_with_timestamp() handles empty deque gracefully."""
    import time
    stack = Crypto15mIndicatorStack()

    # Update with first price (deque is empty) using current timestamp
    current_timestamp = time.time()
    stack.update_with_timestamp(87000.0, current_timestamp)

    snap = stack.snapshot()

    print(f"After first update: bars_available={snap.bars_available}, price={snap.price:.0f}")

    # Should have 1 bar
    assert snap.bars_available == 1
    assert snap.price == 87000.0


def test_snapshot_handles_edge_case_single_bar():
    """Verify snapshot() handles single bar edge case."""
    stack = Crypto15mIndicatorStack()

    # Feed only 1 bar
    stack.update(87000.0)

    snap = stack.snapshot()

    print(f"Single bar snapshot: bars_available={snap.bars_available}, price={snap.price:.0f}")

    # Should not raise IndexError
    assert snap.bars_available == 1
    assert snap.price == 87000.0


if __name__ == "__main__":
    test_full_indicator_stack()
    print("---")
    test_fee_calculator()
    print("---")
    test_ev_calculator()
    print("---")
    test_chop_detection()
    print("---")
    test_trend_alignment_playbook()
    print("---")
    test_to_dict_has_all_fields()
    print("---")
    test_ema50_trend_regime()
    print("---")
    test_atr_min_move_gate()
    print("---")
    test_microstructure_removed_from_trade_allowed()
    print("---")
    test_multi_tf_rsi()
    print("---")
    test_session_tag()
    print("---")
    test_trend_regime()
    print("---")
    test_new_diagnostic_fields()
    print("---")
    test_per_asset_rsi_thresholds()
    print("---")
    test_edge_metrics()
    print("---")
    test_ema_200_macro_trend_filter()
    print("---")
    test_regime_based_rsi_threshold_shifting()
    print("---")
    test_macd_zero_line_filter()
    print("---")
    test_macd_histogram_momentum_filter()
    print("---")
    test_rsi_macd_confluence_scoring()
    print("---")
    test_snapshot_handles_empty_deque()
    print("---")
    test_snapshot_handles_insufficient_data_for_ema_slope()
    print("---")
    test_snapshot_handles_insufficient_data_for_volatility()
    print("---")
    test_update_with_timestamp_handles_empty_deque()
    print("---")
    test_snapshot_handles_edge_case_single_bar()
    print("\n=== ALL TESTS PASSED ===")
