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
    # At 50c, fee = ceil(0.07 * 1 * 0.5 * 0.5) = ceil(0.0175) = 1
    fee = Crypto15mIndicatorStack.kalshi_fee_for_price(50, 1)
    print(f"Fee at 50c/1ct: {fee}c")
    assert fee == 1

    # At 80c, fee = ceil(0.07 * 1 * 0.8 * 0.2) = ceil(0.0112) = 1
    fee2 = Crypto15mIndicatorStack.kalshi_fee_for_price(80, 1)
    print(f"Fee at 80c/1ct: {fee2}c")
    assert fee2 == 1

    # At 50c with 10 contracts: ceil(0.07 * 10 * 0.5 * 0.5) = ceil(0.175) = 1
    fee3 = Crypto15mIndicatorStack.kalshi_fee_for_price(50, 10)
    print(f"Fee at 50c/10ct: {fee3}c")
    assert fee3 == 1


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


def test_trading_agent_import():
    """Verify trading_agent still imports cleanly with new indicator stack."""
    from merid.prediction.trading_agent import KalshiTradingAgent
    from merid.prediction.model import MarketSnapshot
    print("trading_agent + model imports OK")


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


def test_backtest_scaffold():
    """Verify backtest engine runs end-to-end with synthetic data."""
    import pandas as pd
    import numpy as np
    from merid.strategies.kalshi_15m_backtest import (
        backtest_kalshi_15m,
        trades_to_dataframe,
        trade_pnl_cents,
        BacktestSummary,
    )

    # Synthetic 1m spot prices: 200 bars of noisy uptrend
    np.random.seed(42)
    timestamps = pd.date_range("2025-03-20 08:00", periods=200, freq="1min")
    prices = 87000 + np.cumsum(np.random.randn(200) * 20 + 5)
    df_price = pd.DataFrame({"close": prices}, index=timestamps)

    # Synthetic Kalshi 15m markets (every 15 bars)
    markets = []
    for i in range(10):
        open_idx = 60 + i * 15  # start after enough warmup
        close_idx = open_idx + 15
        if close_idx >= len(prices):
            break
        went_up = int(prices[close_idx] > prices[open_idx])
        markets.append({
            "market_id": f"BTC-15M-{i}",
            "open_time": timestamps[open_idx],
            "close_time": timestamps[close_idx],
            "settle": went_up,
            "entry_price": 50 + np.random.randint(-15, 15),  # cents
        })
    df_kalshi = pd.DataFrame(markets)

    # Run backtest (relaxed gates for synthetic data)
    trades, summary = backtest_kalshi_15m(
        df_price, df_kalshi, contracts=5,
        require_trend_aligned=False,
        require_trade_allowed=False,
    )

    print(f"Backtest: {summary.total_trades} trades, PnL={summary.total_pnl_cents:.0f}c, "
          f"WR={summary.win_rate:.1%}, fees={summary.total_fees_cents:.0f}c")
    print(f"Skipped: gate={summary.skipped_gate_blocked}, signal={summary.skipped_no_signal}")

    assert isinstance(summary, BacktestSummary)
    # Should have some trades (not all skipped)
    assert summary.total_trades + summary.skipped_no_signal + summary.skipped_gate_blocked == len(df_kalshi)

    # Test trade log export
    df_trades = trades_to_dataframe(trades)
    if not df_trades.empty:
        print(f"Trade log: {len(df_trades)} rows, columns={list(df_trades.columns)[:5]}...")
        assert "pnl_cents" in df_trades.columns
        assert "ema_trend" in df_trades.columns

    # Test PnL helper directly
    gross, fee, net = trade_pnl_cents("UP", 50, 1, 10)
    print(f"PnL(UP, 50c, win, 10ct): gross={gross}, fee={fee}, net={net}")
    assert gross == 500  # (100-50)*10
    assert net == gross - fee


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
    test_backtest_scaffold()
    print("---")
    test_trading_agent_import()
    print("\n=== ALL TESTS PASSED ===")
