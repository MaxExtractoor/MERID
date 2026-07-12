# Kalshi 15m Signal Generation and Indicators Documentation

## Overview

The Kalshi 15m signal generation system uses a comprehensive indicator stack to generate trading signals for the 5 crypto assets (BTC, ETH, SOL, XRP, DOGE). The indicator stack computes trend, momentum, volatility, and chop filters from 1-minute spot price data.

## Architecture

### Component Hierarchy

```
Crypto15mIndicatorStack (Indicator Calculator)
├── IndicatorConfig (Tunable Parameters)
├── IndicatorSnapshot (Feature Vector)
└── FVGContext (Fair Value Gap - DEPRECATED)
```

### Key Files

- **Indicator Stack**: `merid/signals/crypto_15m_indicators.py`
- **FVG Forecaster**: `merid/prediction/forecasters/fvg.py` (authoritative FVG data)
- **Agent Grid**: `merid/prediction/agent_grid_15m.py` (signal consumption)

## Indicator Configuration (IndicatorConfig)

### Purpose

The `IndicatorConfig` dataclass provides tunable parameters for the 15-minute indicator stack. It supports asset-specific configurations and Kalshi mode for prediction markets.

### Core Parameters

```python
@dataclass
class IndicatorConfig:
    asset: str = "BTC"  # BTC, ETH, SOL, XRP, DOGE
    kalshi_mode: bool = False  # Use lenient thresholds for Kalshi prediction markets
```

### Trend Baselines (EMA Crossovers)

```python
# EMA periods for trend direction
ema_trend_period: int = 21      # EMA(21) for trend direction
ema_fast_period: int = 9        # EMA(9) for fast signal
ema_slow_period: int = 21       # EMA(21) for slow signal
ema_200_period: int = 200       # EMA(200) for macro trend filter
```

**Purpose**:
- **21/34 EMA**: Determines trend direction (bullish/bearish) via crossover
- **50 EMA**: Determines if market is in range (ADX < 20) or trend (ADX >= 20)
- **200 EMA**: Macro trend filter for regime classification (bull/bear market)

**Asset-Specific Overrides**:
- **BTC/ETH**: Faster EMAs (9/21) for responsiveness
- **SOL/XRP/DOGE**: Slower EMAs (13/34) to reduce noise

### Momentum / Overextension

```python
# RSI parameters
rsi_period: int = 8
rsi_oversold: float = 30.0
rsi_overbought: float = 70.0

# Per-asset RSI thresholds
rsi_oversold_asset: Optional[float] = None
rsi_overbought_asset: Optional[float] = None

# Regime-based RSI threshold shifting
regime_based_rsi_enabled: bool = True
rsi_bull_oversold: float = 40.0      # Bull regime oversold threshold
rsi_bull_overbought: float = 80.0    # Bull regime overbought threshold
rsi_bear_oversold: float = 20.0      # Bear regime oversold threshold
rsi_bear_overbought: float = 60.0    # Bear regime overbought threshold

# Distance-from-EMA thresholds
distance_overextended_atrs: float = 2.0
```

**Asset-Specific RSI Thresholds**:
- **BTC/ETH**: 70/30 (blue chip, standard)
- **SOL/XRP**: 65/35 (high-beta, more events)
- **DOGE**: 60/40 (highest volatility, widest bands)

**Regime-Based Shifting**:
- **Bull regime**: Shift thresholds up (80/40) to stay in trades longer
- **Bear regime**: Shift thresholds down (60/20) to exit faster
- **Range regime**: Standard thresholds (70/30)

### MACD (Scalping-Tilted)

```python
# MACD parameters (8-21-5 scalping)
macd_fast: int = 8
macd_slow: int = 21
macd_signal: int = 5

# MACD zero-line filter (2026 research best practices)
macd_zero_line_filter_enabled: bool = True
# Only take long signals when MACD line > 0, short signals when MACD line < 0

# MACD histogram momentum filter (2026 research best practices)
macd_histogram_momentum_filter_enabled: bool = True
macd_histogram_expansion_bars: int = 2  # Require N bars of histogram expansion
```

**Purpose**:
- **Zero-line filter**: Prevents counter-trend entries and aligns with momentum
- **Histogram momentum filter**: Confirms momentum is strengthening, not weakening

### Chop Filters

```python
# Consecutive closes above/below EMA to confirm trend
consecutive_closes_required: int = 3

# MACD histogram persistence
macd_persistence_bars: int = 3

# Minimum histogram magnitude
macd_histogram_min_pct: float = 0.0001  # 0.01% of price
```

**Asset-Specific Overrides**:
- **BTC/ETH**: Strict (3 consecutive closes)
- **SOL/XRP/DOGE**: Relaxed (2 consecutive closes)

### Fee-Aware EV

```python
# Kalshi fee formula: ceil(0.07 * contracts * P * (1-P))
fee_midcurve_low: float = 0.45
fee_midcurve_high: float = 0.55

# Minimum net EV after fees
min_ev_cents: float = 1.5

# Fee drag halt threshold
fee_drag_halt_pct: float = 0.30
```

**Purpose**: Accounts for Kalshi's fee structure and mid-curve penalty zone (0.45-0.55) where fees are highest.

### Volatility Gate

```python
# ATR parameters
atr_period: int = 14
atr_min_move_pct: float = 0.0002  # 0.02% of price (BTC default)

# Realized volatility
vol_window_bars: int = 30          # 30 1m bars
vol_low_threshold: float = 0.15    # Annualized vol below = dead market
vol_high_threshold: float = 1.20   # Annualized vol above = chaos
```

**Asset-Specific ATR Thresholds**:
- **BTC**: 0.0002 (0.02%) - lowest threshold
- **ETH**: 0.00025 (0.025%)
- **SOL**: 0.0004 (0.04%)
- **XRP**: 0.00035 (0.035%)
- **DOGE**: 0.0005 (0.05%) - highest threshold

### Liquidity Filter

```python
max_spread_cents: int = 8          # Wider spread = skip
min_depth_at_price: int = 3        # Fewer contracts = skip
```

**Note**: Microstructure checks removed - handled by unified edge. Indicator stack is now purely TA-based.

### Price Buffer

```python
max_bars: int = 250                # Keep ~4 hours of 1m bars (supports EMA(200))
min_bars_required: int = 52        # Sufficient history for EMA/MACD
min_bars_cold_start: int = 1       # Cold start: allow trading with minimal bars
min_bars_for_macd: int = 30        # MACD needs more history
```

### Fair Value Gap (FVG) - DEPRECATED

```python
# CRITICAL FIX: 2026-07-06 - FVG detection moved to merid/prediction/forecasters/fvg.py
# These parameters are kept for backward compatibility but not used
fvg_enabled: bool = True
fvg_min_gap_size_atr: float = 1.5
fvg_min_gap_size_pct: float = 0.002
fvg_max_age_bars: int = 50
fvg_max_zones_tracked: int = 10
```

**Important**: FVG detection has been consolidated to `merid/prediction/forecasters/fvg.py`. Use `get_fvg_forecaster()` for authoritative FVG data.

### Staleness Threshold

```python
staleness_threshold_seconds: float = 30.0  # Reject data older than 30s
```

### Kalshi Mode

```python
kalshi_mode: bool = False
```

**When enabled**:
- Disable vol gate (prediction markets don't have spot-like volatility)
- Disable ATR move gate (prediction markets are binary contracts)
- Disable chop gate (allow trades without consecutive closes)
- Set all thresholds to lenient values

**Rationale**: Kalshi prediction markets are binary contracts, not continuous price instruments. They don't have the same volatility characteristics as spot markets.

## Indicator Stack (Crypto15mIndicatorStack)

### Purpose

The `Crypto15mIndicatorStack` is a streaming indicator calculator fed with 1-minute close prices. It maintains running state for all indicators and provides a snapshot API for signal generation.

### Initialization

```python
class Crypto15mIndicatorStack:
    def __init__(self, config: Optional[IndicatorConfig] = None):
        self.cfg = config or IndicatorConfig()
        self._instance_id = id(self)  # Track instance for debugging
        self._asset_symbol: str = ""  # Set via set_asset_symbol()
        
        # Price buffer
        self._prices: Deque[float] = deque(maxlen=self.cfg.max_bars)
        
        # EMA(50) trend state
        self._ema_trend: float = 0.0
        self._ema_trend_k: float = 2.0 / (self.cfg.ema_trend_period + 1)
        self._ema_trend_initialized: bool = False
        
        # EMA(200) macro trend state
        self._ema_200: float = 0.0
        self._ema_200_k: float = 2.0 / (self.cfg.ema_200_period + 1)
        self._ema_200_initialized: bool = False
        
        # EMA(5)/EMA(20) crossover state
        self._ema_fast: float = 0.0
        self._ema_slow: float = 0.0
        self._ema_fast_k: float = 2.0 / (self.cfg.ema_fast_period + 1)
        self._ema_slow_k: float = 2.0 / (self.cfg.ema_slow_period + 1)
        self._ema_initialized: bool = False
        
        # Multi-TF RSI state (downsampled from 1m data)
        self._5m_prices: Deque[float] = deque(maxlen=200)
        self._1h_prices: Deque[float] = deque(maxlen=200)
        self._5m_rsi_initialized: bool = False
        self._1h_rsi_initialized: bool = False
        self._5m_avg_gain: float = 0.0
        self._5m_avg_loss: float = 0.0
        self._1h_avg_gain: float = 0.0
        self._1h_avg_loss: float = 0.0
        self._bar_count_5m: int = 0
        self._bar_count_1h: int = 0
        
        # RSI state (incremental Wilder smoothing)
        self._avg_gain: float = 0.0
        self._avg_loss: float = 0.0
        self._rsi_initialized: bool = False
        self._rsi_period = self.cfg.rsi_period
        
        # MACD state (dual EMA + signal EMA)
        self._macd_ema_fast: float = 0.0
        self._macd_ema_slow: float = 0.0
        self._macd_signal_ema: float = 0.0
        self._macd_fast_k: float = 2.0 / (self.cfg.macd_fast + 1)
        self._macd_slow_k: float = 2.0 / (self.cfg.macd_slow + 1)
        self._macd_signal_k: float = 2.0 / (self.cfg.macd_signal + 1)
        self._macd_initialized: bool = False
        self._macd_signal_initialized: bool = False
        
        # Chop filter state
        self._consecutive_above: int = 0
        self._consecutive_below: int = 0
        self._macd_hist_sign_bars: int = 0
        self._prev_macd_hist_positive: Optional[bool] = None
        
        # Staleness tracking
        self._last_price_timestamp: Optional[float] = None
```

### Update Method

```python
def update_with_timestamp(self, price: float, timestamp: float) -> None:
    """Append a new 1-minute close price with timestamp and update running state."""
    
    # Validate price
    if price is None or not math.isfinite(price) or price <= 0:
        logger.warning("[INDICATOR-STACK-UPDATE] Invalid price: %s", price)
        return
    
    self._last_price_timestamp = timestamp
    prev = self._prices[-1] if self._prices else price
    self._prices.append(price)
    
    n = len(self._prices)
    
    # Multi-TF RSI downsampling (5m, 1h from 1m data)
    self._bar_count_5m += 1
    self._bar_count_1h += 1
    
    # Sample 5m close every 5 bars
    if self._bar_count_5m >= 5:
        self._5m_prices.append(price)
        self._bar_count_5m = 0
    
    # Sample 1h close every 60 bars
    if self._bar_count_1h >= 60:
        self._1h_prices.append(price)
        self._bar_count_1h = 0
    
    # Update 5m RSI
    if len(self._5m_prices) >= 2:
        prev_5m = self._5m_prices[-2]
        delta_5m = price - prev_5m
        gain_5m = max(delta_5m, 0.0)
        loss_5m = max(-delta_5m, 0.0)
        
        if not self._5m_rsi_initialized and len(self._5m_prices) >= self._rsi_period + 1:
            recent_5m = list(self._5m_prices)
            deltas_5m = [recent_5m[i] - recent_5m[i - 1] for i in range(1, len(recent_5m))]
            recent_deltas_5m = deltas_5m[-self._rsi_period:]
            self._5m_avg_gain = sum(max(d, 0) for d in recent_deltas_5m) / self._rsi_period
            self._5m_avg_loss = sum(max(-d, 0) for d in recent_deltas_5m) / self._rsi_period
            self._5m_rsi_initialized = True
        elif self._5m_rsi_initialized:
            self._5m_avg_gain = (self._5m_avg_gain * (self._rsi_period - 1) + gain_5m) / self._rsi_period
            self._5m_avg_loss = (self._5m_avg_loss * (self._rsi_period - 1) + loss_5m) / self._rsi_period
    
    # Update 1h RSI (similar logic)
    # ...
    
    # Update EMA(50) trend
    if not self._ema_trend_initialized and n >= self.cfg.ema_trend_period:
        self._ema_trend = sum(list(self._prices)[-self.cfg.ema_trend_period:]) / self.cfg.ema_trend_period
        self._ema_trend_initialized = True
    elif self._ema_trend_initialized:
        self._ema_trend = price * self._ema_trend_k + self._ema_trend * (1 - self._ema_trend_k)
    
    # Update EMA(200) macro trend
    if not self._ema_200_initialized and n >= self.cfg.ema_200_period:
        self._ema_200 = sum(list(self._prices)[-self.cfg.ema_200_period:]) / self.cfg.ema_200_period
        self._ema_200_initialized = True
    elif self._ema_200_initialized:
        self._ema_200 = price * self._ema_200_k + self._ema_200 * (1 - self._ema_200_k)
    
    # Update EMA(5)/EMA(20) crossover
    if not self._ema_initialized and n >= self.cfg.ema_slow_period:
        self._ema_fast = sum(list(self._prices)[-self.cfg.ema_fast_period:]) / self.cfg.ema_fast_period
        self._ema_slow = sum(list(self._prices)[-self.cfg.ema_slow_period:]) / self.cfg.ema_slow_period
        self._ema_initialized = True
    elif self._ema_initialized:
        self._ema_fast = price * self._ema_fast_k + self._ema_fast * (1 - self._ema_fast_k)
        self._ema_slow = price * self._ema_slow_k + self._ema_slow * (1 - self._ema_slow_k)
    
    # Update RSI (Wilder smoothing)
    delta = price - prev
    gain = max(delta, 0.0)
    loss = max(-delta, 0.0)
    
    if not self._rsi_initialized and n >= self._rsi_period + 1:
        prices_list = list(self._prices)
        deltas = [prices_list[i] - prices_list[i - 1] for i in range(1, n)]
        recent = deltas[-(self._rsi_period):]
        self._avg_gain = sum(max(d, 0) for d in recent) / self._rsi_period
        self._avg_loss = sum(max(-d, 0) for d in recent) / self._rsi_period
        self._rsi_initialized = True
    elif self._rsi_initialized:
        self._avg_gain = (self._avg_gain * (self._rsi_period - 1) + gain) / self._rsi_period
        self._avg_loss = (self._avg_loss * (self._rsi_period - 1) + loss) / self._rsi_period
    
    # Update MACD (8-21-5 scalping)
    if not self._macd_initialized and n >= self.cfg.macd_slow:
        prices_list = list(self._prices)
        self._macd_ema_fast = sum(prices_list[-self.cfg.macd_fast:]) / self.cfg.macd_fast
        self._macd_ema_slow = sum(prices_list[-self.cfg.macd_slow:]) / self.cfg.macd_slow
        self._macd_initialized = True
        macd_val = self._macd_ema_fast - self._macd_ema_slow
        self._macd_signal_ema = macd_val
        self._macd_signal_initialized = True
    elif self._macd_initialized:
        self._macd_ema_fast = price * self._macd_fast_k + self._macd_ema_fast * (1 - self._macd_fast_k)
        self._macd_ema_slow = price * self._macd_slow_k + self._macd_ema_slow * (1 - self._macd_slow_k)
        macd_val = self._macd_ema_fast - self._macd_ema_slow
        if self._macd_signal_initialized:
            self._macd_signal_ema = macd_val * self._macd_signal_k + self._macd_signal_ema * (1 - self._macd_signal_k)
    
    # Update chop filter: consecutive closes above/below EMA(50)
    if self._ema_trend_initialized:
        if price > self._ema_trend:
            self._consecutive_above += 1
            self._consecutive_below = 0
        elif price < self._ema_trend:
            self._consecutive_below += 1
            self._consecutive_above = 0
        else:
            self._consecutive_above = 0
            self._consecutive_below = 0
    
    # Update chop filter: MACD histogram persistence
    if self._macd_initialized and self._macd_signal_initialized:
        hist = (self._macd_ema_fast - self._macd_ema_slow) - self._macd_signal_ema
        hist_positive = hist > 0
        if self._prev_macd_hist_positive is None:
            self._macd_hist_sign_bars = 1
        elif hist_positive == self._prev_macd_hist_positive:
            self._macd_hist_sign_bars += 1
        else:
            self._macd_hist_sign_bars = 1
        self._prev_macd_hist_positive = hist_positive
```

### Snapshot Method

```python
def snapshot(self) -> IndicatorSnapshot:
    """Compute and return the current indicator snapshot."""
    
    n = len(self._prices)
    price = self._prices[-1] if self._prices else 0.0
    
    snap = IndicatorSnapshot()
    snap.bars_available = n
    snap.price = price
    snap.timestamp = self._last_price_timestamp or time.time()
    
    # Compute EMA values
    snap.ema_trend = self._ema_trend if self._ema_trend_initialized else 0.0
    snap.ema_200 = self._ema_200 if self._ema_200_initialized else 0.0
    snap.ema_fast = self._ema_fast if self._ema_initialized else 0.0
    snap.ema_slow = self._ema_slow if self._ema_initialized else 0.0
    
    # Compute trend regime
    snap.price_above_trend_ema = price > snap.ema_trend if snap.ema_trend > 0 else False
    snap.price_above_ema_200 = price > snap.ema_200 if snap.ema_200 > 0 else False
    
    # Compute EMA crossover
    if snap.ema_fast > snap.ema_slow:
        snap.ema_cross = "bullish"
    elif snap.ema_fast < snap.ema_slow:
        snap.ema_cross = "bearish"
    else:
        snap.ema_cross = "neutral"
    
    # Compute trend strength
    if snap.ema_slow > 0:
        snap.trend_strength = abs(snap.ema_fast - snap.ema_slow) / snap.ema_slow
    
    # Compute RSI
    if self._rsi_initialized:
        if self._avg_loss == 0:
            snap.rsi = 100.0
        else:
            rs = self._avg_gain / self._avg_loss
            snap.rsi = 100.0 - (100.0 / (1.0 + rs))
    
    # Compute RSI zone
    oversold = self.cfg.rsi_oversold_asset or self.cfg.rsi_oversold
    overbought = self.cfg.rsi_overbought_asset or self.cfg.rsi_overbought
    
    if snap.rsi < oversold:
        snap.rsi_zone = "oversold"
    elif snap.rsi > overbought:
        snap.rsi_zone = "overbought"
    else:
        snap.rsi_zone = "neutral"
    
    # Compute 5m RSI
    if self._5m_rsi_initialized:
        if self._5m_avg_loss == 0:
            snap.rsi_5m = 100.0
        else:
            rs = self._5m_avg_gain / self._5m_avg_loss
            snap.rsi_5m = 100.0 - (100.0 / (1.0 + rs))
    
    # Compute 1h RSI (similar logic)
    # ...
    
    # Compute MACD
    if self._macd_initialized:
        snap.macd_line = self._macd_ema_fast - self._macd_ema_slow
    if self._macd_signal_initialized:
        snap.macd_signal_line = self._macd_signal_ema
    snap.macd_histogram = snap.macd_line - snap.macd_signal_line
    
    # Compute MACD cross
    if snap.macd_line > snap.macd_signal_line:
        snap.macd_cross = "bullish"
    elif snap.macd_line < snap.macd_signal_line:
        snap.macd_cross = "bearish"
    else:
        snap.macd_cross = "neutral"
    
    # Compute MACD zero-line filter
    if self.cfg.macd_zero_line_filter_enabled:
        snap.macd_zero_line_ok = snap.macd_line > 0  # Only allow long signals when MACD > 0
    
    # Compute MACD histogram expansion
    if self.cfg.macd_histogram_momentum_filter_enabled:
        # Check if histogram is expanding in direction of trade
        # (implementation details in full code)
        pass
    
    # Compute chop filter
    snap.consecutive_closes_above_ema = self._consecutive_above
    snap.consecutive_closes_below_ema = self._consecutive_below
    snap.macd_same_sign_bars = self._macd_hist_sign_bars
    
    # Compute chop detection
    if (self._consecutive_above < self.cfg.consecutive_closes_required and
        self._consecutive_below < self.cfg.consecutive_closes_required):
        snap.chop_detected = True
        snap.chop_reason = "insufficient_consecutive_closes"
    
    if self._macd_hist_sign_bars < self.cfg.macd_persistence_bars:
        snap.chop_detected = True
        snap.chop_reason = "insufficient_macd_persistence"
    
    # Compute ATR
    if n >= self.cfg.atr_period + 1:
        prices_list = list(self._prices)
        true_ranges = [abs(prices_list[i] - prices_list[i - 1]) 
                       for i in range(-self.cfg.atr_period, 0)]
        snap.atr = sum(true_ranges) / len(true_ranges)
    
    # Compute ATR move gate
    if snap.atr > 0:
        atr_pct = snap.atr / price
        snap.atr_move_ok = atr_pct >= self.cfg.atr_min_move_pct
    
    # Compute realized volatility
    if n >= self.cfg.vol_window_bars:
        prices_list = list(self._prices)
        returns = [(prices_list[i] - prices_list[i - 1]) / prices_list[i - 1] 
                  for i in range(-self.cfg.vol_window_bars, 0)]
        vol = math.sqrt(sum(r * r for r in returns) / len(returns))
        snap.realized_vol_annualized = vol * math.sqrt(525600)  # Annualize (1m bars)
    
    # Compute vol band
    if snap.realized_vol_annualized < self.cfg.vol_low_threshold:
        snap.vol_band = "low"
    elif snap.realized_vol_annualized > self.cfg.vol_high_threshold:
        snap.vol_band = "high"
    else:
        snap.vol_band = "mid"
    
    # Compute composite gates
    snap.vol_gate_ok = snap.vol_band in ("mid", "high")
    snap.chop_gate_ok = not snap.chop_detected
    snap.trend_aligned = snap.ema_cross == snap.macd_cross
    snap.trade_allowed = snap.vol_gate_ok and snap.chop_gate_ok and snap.trend_aligned
    
    # Compute session tag
    snap.session_tag = self._compute_session_tag(snap.timestamp)
    
    return snap
```

## Indicator Snapshot (IndicatorSnapshot)

### Purpose

The `IndicatorSnapshot` dataclass provides a complete feature vector for one evaluation point. It contains all computed indicators and composite gates for signal generation.

### Fields

#### Trend Indicators

```python
ema_trend: float = 0.0              # EMA(50) primary trend filter
ema_200: float = 0.0               # EMA(200) macro trend filter
price_above_trend_ema: bool = False  # price > EMA(50) = bullish regime
price_above_ema_200: bool = False   # price > EMA(200) = bull market regime
ema_fast: float = 0.0
ema_slow: float = 0.0
ema_cross: str = "neutral"         # "bullish", "bearish", "neutral"
trend_strength: float = 0.0        # |ema_fast - ema_slow| / ema_slow
trend_regime: str = "range"        # "range", "trend_up", "trend_down"
macro_regime: str = "neutral"      # "bull", "bear", "neutral"
ema_slope: float = 0.0             # EMA(50) slope (rate of change)
```

#### Momentum Indicators

```python
rsi: float = 50.0
rsi_zone: str = "neutral"          # "oversold", "overbought", "neutral"
rsi_tf: str = "15m"               # Timeframe of RSI
rsi_period: int = 8
rsi_5m: float = 50.0              # 5m RSI (timing gate)
rsi_5m_zone: str = "neutral"
rsi_1h: float = 50.0              # 1h RSI (regime filter)
rsi_1h_zone: str = "neutral"
rsi_alignment: str = "unknown"     # "all_aligned", "15m_contra_1h", "5m_contra_15m", "mixed"
distance_from_ema_atrs: float = 0.0  # signed: +ve = above, -ve = below
overextended: bool = False
```

#### MACD Indicators

```python
macd_line: float = 0.0             # MACD line (fast EMA - slow EMA)
macd_signal_line: float = 0.0      # signal line (EMA of MACD)
macd_histogram: float = 0.0        # histogram (MACD - signal)
macd_cross: str = "neutral"        # "bullish", "bearish", "neutral"
macd_histogram_positive: bool = False
macd_zero_line_ok: bool = True      # MACD line on correct side of zero
macd_histogram_expanding: bool = False  # Histogram expanding in direction of trade
```

#### Chop Filters

```python
consecutive_closes_above_ema: int = 0  # streak of closes above EMA(slow)
consecutive_closes_below_ema: int = 0  # streak of closes below EMA(slow)
macd_same_sign_bars: int = 0       # bars MACD histogram stayed same sign
chop_detected: bool = False        # True = choppy, avoid trading
chop_reason: str = ""              # human-readable reason
```

#### Fee-Aware EV

```python
is_midcurve: bool = False          # implied prob in 0.45-0.55 danger zone
kalshi_fee_pct: float = 0.0        # estimated fee as % of notional
net_ev_cents: float = 0.0          # estimated net EV after fees
kalshi_implied_prob: Optional[float] = None  # Kalshi implied probability
model_prob: Optional[float] = None  # Model's fair probability
edge_bp: Optional[float] = None    # Edge in basis points (model - implied)
```

#### Volatility Indicators

```python
atr: float = 0.0
atr_move_ok: bool = True           # ATR large enough for directional move
realized_vol_annualized: float = 0.0
vol_band: str = "mid"              # "low", "mid", "high"
vol_regime: str = "mid"            # "low", "mid", "high"
```

#### Liquidity Indicators

```python
spread_cents: Optional[int] = None
depth_at_price: Optional[int] = None
liquidity_ok: bool = True
```

**Note**: Microstructure checks removed - handled by unified edge.

#### Composite Gates

```python
vol_gate_ok: bool = True           # vol in tradeable band
trend_aligned: bool = True         # trend + momentum agree
chop_gate_ok: bool = True          # not in choppy conditions
trade_allowed: bool = True         # composite: all gates pass
```

#### Meta Fields

```python
bars_available: int = 0
timestamp: float = 0.0
price: float = 0.0                 # latest 1m close
config_version: str = "v1"
session_tag: str = "unknown"      # Time-of-day/weekday seasonality tag
```

#### Outcome Tracking

```python
interval_outcome: Optional[str] = None  # "YES" or "NO" - contract resolution
signal_side: Optional[str] = None       # "YES" or "NO" - side we traded
correct_direction: Optional[bool] = None  # Did signal direction match outcome?
pnl_per_contract: Optional[float] = None  # Net PnL per contract (cents)
```

#### Contract Barrier Metrics

```python
contract_barrier_distance: Optional[float] = None  # Distance from price to barrier
normalized_delta: Optional[float] = None  # Barrier distance / ATR
```

#### Directional Bias

```python
bias: str = "neutral"              # "up", "down", "neutral"
bias_confidence: float = 0.0       # 0.0 – 1.0
```

#### Fair Value Gap (FVG) - DEPRECATED

```python
fvg_enabled: bool = False
fvg_pressure: float = 0.0           # Normalized pressure (-1 bearish to +1 bullish)
unfilled_fvg_count: int = 0
nearest_fvg_distance_atr: float = 0.0
has_local_fvg_confluence: bool = False
fvg_context: Optional[FVGContext] = None
fvg_dominant_direction: str = "neutral"
```

**Important**: FVG detection moved to `merid/prediction/forecasters/fvg.py`. These fields are kept for backward compatibility.

## Signal Generation Process

### Velocity-Based Signal (Primary)

The primary signal generation method in the 15m stack is velocity-based momentum:

```python
def _calculate_velocity(self, asset: str, current_price: float) -> float:
    """Calculate velocity as percentage change per second."""
    if len(self._spot_price_history[asset]) < 2:
        return 0.0
    
    last_price = self._spot_price_history[asset][-1]
    velocity = (current_price - last_price) / last_price
    
    return velocity

def _calculate_dynamic_velocity_threshold(self, asset: str) -> float:
    """Calculate dynamic velocity threshold based on ATR and ADX."""
    # Get base threshold from config (per-asset)
    base_threshold = asset_threshold_map.get(asset, 0.0002)
    
    # Calculate ATR for current asset
    atr_pct = self._calculate_atr(asset)
    
    # Calculate ADX for trend strength adjustment
    adx = self._calculate_adx(asset)
    
    # CRITICAL FIX: ATR and ADX multipliers set to 1.0 (neutral)
    atr_adjustment = 1.0
    adx_multiplier = 1.0
    
    dynamic_threshold = base_threshold * atr_adjustment * adx_multiplier
    return dynamic_threshold
```

**Signal Logic**:
1. Calculate velocity from spot price changes
2. Compare against dynamic threshold (per-asset)
3. If velocity > threshold, generate signal
4. Signal side determined by velocity direction (positive = YES, negative = NO)

### Panic Fade Signal (Volatility Reversion)

Panic fade strategy (Turbine research winner) detects statistical extremes and fades the panic:

```python
def _check_panic_fade_conditions(self, asset: str, velocity: float) -> Optional[Dict[str, Any]]:
    """Check if panic fade conditions are met."""
    
    # Check velocity magnitude (must be panic-level move)
    if abs(velocity) < self._panic_fade_min_velocity:
        return None
    
    # Calculate RSI and Z-score
    rsi = self._calculate_rsi(asset)
    zscore = self._calculate_price_zscore(asset)
    
    # Check statistical extreme conditions
    is_oversold = (rsi < 25.0) and (zscore < -2.0)
    is_overbought = (rsi > 75.0) and (zscore > 2.0)
    
    if is_oversold:
        return {"side": "yes", "action": "buy", "strategy": "panic_fade"}
    elif is_overbought:
        return {"side": "no", "action": "buy", "strategy": "panic_fade"}
    
    return None
```

**Conditions**:
- Velocity magnitude exceeds minimum threshold (0.0065%)
- RSI < 25 (oversold) or > 75 (overbought)
- Z-score < -2.0 or > 2.0 (statistical extreme)
- Regime is choppy/range-bound (not trending)

**Action**:
- Oversold → BUY YES (expect reversion up)
- Overbought → BUY NO (expect reversion down)

### Multi-Timeframe Alignment

Industry standard: 1m + 5m confirmation for +10-20 pp win rate:

```python
def _check_multi_timeframe_alignment(self, asset: str) -> bool:
    """Check if 1m and 5m timeframes are aligned."""
    
    # Calculate 1m momentum
    momentum_1m = (recent_1m[-1] - recent_1m[0]) / recent_1m[0]
    
    # Calculate 5m momentum
    momentum_5m = (recent_5m[-1] - recent_5m[0]) / recent_5m[0]
    
    # Check alignment: both positive or both negative
    aligned = (momentum_1m > 0 and momentum_5m > 0) or (momentum_1m < 0 and momentum_5m < 0)
    
    return aligned
```

## Fair Value Gap (FVG) - DEPRECATED

### Critical Fix (2026-07-06)

FVG detection has been consolidated to `merid/prediction/forecasters/fvg.py` to avoid duplicate implementations.

**Previous Implementation**: Approximation-based FVG detection in indicator stack
**New Implementation**: OHLC-based FVG detection in dedicated forecaster

**Migration Guide**:
```python
# OLD (deprecated)
fvg_context = indicator_stack.snapshot().fvg_context

# NEW (authoritative)
from merid.prediction.forecasters.fvg import get_fvg_forecaster
fvg_forecaster = get_fvg_forecaster()
fvg_context = fvg_forecaster.get_fvg_context(asset)
```

**Rationale**:
- Single source of truth for FVG data
- Consistent OHLC-based detection across all agents
- Better separation of concerns

## Critical Fixes

### Fix 1: Kalshi Mode for Indicator Stacks (2026-07-08)

**Problem**: Strict spot market thresholds (vol/ATR/chop gates) were blocking all signals.

**Solution**: Enable `kalshi_mode=True` in IndicatorConfig to disable strict spot market thresholds. Kalshi prediction markets are binary contracts, not continuous spot instruments.

**Implementation**:
```python
if self.kalshi_mode:
    self.vol_low_threshold = 0.0  # Always pass vol gate
    self.vol_high_threshold = 999.0  # Never reject due to high vol
    self.atr_min_move_pct = 0.0  # Always pass ATR move gate
    self.consecutive_closes_required = 0  # No consecutive closes needed
    self.macd_persistence_bars = 0  # No MACD persistence needed
    self.macd_histogram_min_pct = 0.0  # No minimum histogram magnitude
```

### Fix 2: Indicator Stack Redundancy (2026-07-10)

**Problem**: Each agent only initialized its own asset's indicator stack, causing "bars_available=1" because each agent is called once per cycle.

**Solution**: Each agent initializes ALL 5 assets' indicator stacks, ensuring each stack gets 5 updates per cycle.

**Implementation**:
```python
# Initialize indicator stack for ALL 5 crypto assets
for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
    cfg = IndicatorConfig(asset=asset, kalshi_mode=True)
    self._indicator_stacks[asset] = Crypto15mIndicatorStack(config=cfg)
    self._indicator_stacks[asset].set_asset_symbol(asset)
```

### Fix 3: FVG Consolidation (2026-07-06)

**Problem**: Duplicate FVG implementations in indicator stack and forecaster caused inconsistency.

**Solution**: Consolidated FVG detection to `merid/prediction/forecasters/fvg.py`. Deprecated indicator stack FVG methods.

**Implementation**:
```python
def _detect_fvg(self, window: List[Dict[str, float]], atr: float) -> Optional[FVGZone]:
    """DEPRECATED: FVG detection moved to merid/prediction/forecasters/fvg.py"""
    return None
```

## Performance Optimizations

### 1. Incremental Indicator Updates

- **Before**: Recalculate all indicators from scratch on each update
- **After**: Maintain running state and update incrementally
- **Benefit**: O(1) per update instead of O(n)

### 2. Multi-Timeframe Downsampling

- **Before**: Fetch separate data feeds for 5m and 1h timeframes
- **After**: Downsample from 1m data (sample every 5 bars for 5m, every 60 bars for 1h)
- **Benefit**: Single data feed, reduced API calls

### 3. Wilder Smoothing for RSI

- **Before**: Standard RSI calculation with full recalculation
- **After**: Incremental Wilder smoothing (EMA-based)
- **Benefit**: O(1) per update instead of O(n)

## Monitoring and Observability

### Key Log Messages

- `[INDICATOR-STACK-UPDATE]`: Price update with bar count
- `[INDICATOR-CONFIG]`: Configuration initialization
- `[INDICATOR-STACK-INIT]`: Stack initialization
- `[INDICATOR-SNAPSHOT]`: Snapshot computation

### Metrics

- **Bars available**: Number of bars in price buffer
- **RSI values**: 15m, 5m, 1h RSI values
- **MACD values**: Line, signal, histogram
- **EMA values**: Trend, fast, slow, 200
- **Volatility bands**: Low, mid, high
- **Chop detection**: True/False with reason
- **Trade allowed**: Composite gate result

## References

- **Indicator Stack**: `merid/signals/crypto_15m_indicators.py`
- **FVG Forecaster**: `merid/prediction/forecasters/fvg.py`
- **Agent Grid**: `merid/prediction/agent_grid_15m.py`
- **Spot Service**: `data/unified_spot_service.py`
