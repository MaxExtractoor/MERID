"""
15m Bollinger Band Mean-Reversion Strategy for Crypto Majors.

Implements a mean-reversion scalping strategy for BTC, ETH, SOL, XRP, DOGE
using Bollinger Bands, Keltner Channels, and regime filters.

STRATEGY IDENTITY: Mean-Reversion Scalping
- Timeframe: 15m for EXECUTION only
- Higher timeframes (1h/daily/weekly): Used for CONTEXT only (regime classification, trend bias)
- No execution signals generated from higher timeframes

Entry: Mean-reversion off bands in range regime only
- Long when price re-enters lower band from below
- Short when price re-enters upper band from above
- Only in range regime (ADX < 20)
- RSI confirmation: oversold for long, overbought for short

Exit: Target mid-band (SMA) with ATR-based stop loss
- TP at SMA mid-band
- SL at ATR multiplier (1.5-2.0x depending on asset)
- Max hold: 240 minutes (4 hours)

Target win-rate: 80%+ with selective entries

Per-Asset Parameters:
- BTC/ETH: 20 SMA, 2.0-2.2 SD (smoother, tighter bands)
- SOL/XRP: 20 SMA, 2.2-2.4 SD (higher beta, wider bands)
- DOGE: 20 SMA, 2.3-2.5 SD (noisiest, widest bands)

Reference:
- https://mudrex.com/learn/bollinger-bands-in-crypto-trading/
- https://mudrex.com/learn/keltner-channels-vs-bollinger-bands-crypto/
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Dict, Tuple
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("merid.strategies.band_strategy_15m")


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BandStrategyConfig:
    """Configuration for 15m band strategy with per-asset parameters."""
    
    # Asset identifier
    asset: str = "BTC"  # BTC, ETH, SOL, XRP, DOGE
    
    # ── Bollinger Bands ────────────────────────────────────────────────
    bb_period: int = 20
    bb_sd_multiplier: float = 2.0  # Per-asset: BTC/ETH 2.0-2.2, SOL/XRP 2.2-2.4, DOGE 2.3-2.5
    
    # ── Keltner Channels ────────────────────────────────────────────────
    kc_period: int = 20
    kc_ema_period: int = 20
    kc_atr_period: int = 14
    kc_atr_multiplier: float = 2.0
    
    # ── Regime Filter (50 EMA + ADX) ────────────────────────────────────
    # NOTE: 50 EMA used for regime classification (range vs trend detection)
    # This is DIFFERENT from the 21/34 EMA in crypto_15m_indicators.py which is used for trend direction
    # 50 EMA: Determines if market is in range (ADX < 20) or trend (ADX >= 20)
    # 21/34 EMA: Determines trend direction (bullish/bearish) via crossover
    # These serve different purposes and are not contradictory
    trend_ema_period: int = 50
    adx_period: int = 14
    adx_trend_threshold: float = 20.0  # ADX >= 20 = trend, < 20 = range
    adx_strong_trend: float = 25.0
    
    # ── Entry Filters ───────────────────────────────────────────────────
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    
    # Volatility filter: skip if ATR > X × 24h median
    atr_spike_multiplier: float = 2.0  # Skip if current ATR > 2× 24h median
    
    # ── Exit Rules ──────────────────────────────────────────────────────
    tp_at_mid_band: bool = True  # TP at SMA (mid-band)
    tp_r_multiple: float = 1.0  # Alternative: TP at 1R
    sl_atr_multiplier: float = 1.5  # SL at 1.5×ATR (or swing high/low)
    sl_max_atr_multiplier: float = 2.0  # Max SL at 2×ATR
    
    # ── Price Buffer ───────────────────────────────────────────────────
    max_bars: int = 200  # Keep ~50 hours of 15m bars
    min_bars_required: int = 52  # Need 50+ for 50 EMA
    
    # ── Deep Touch Validation ───────────────────────────────────────────
    require_deep_touch: bool = True  # Price must close outside band, then re-enter
    min_touch_bars: int = 1  # Minimum bars outside band before re-entry
    
    def __post_init__(self):
        """Apply asset-specific parameter overrides."""
        asset = self.asset.upper()
        
        # Per-asset SD multipliers from spec
        if asset in ["BTC", "ETH"]:
            self.bb_sd_multiplier = 2.1  # 2.0-2.2 range, midpoint
            self.sl_atr_multiplier = 1.5  # Tighter SL for smoother assets
        elif asset in ["SOL", "XRP"]:
            self.bb_sd_multiplier = 2.3  # 2.2-2.4 range, midpoint
            self.sl_atr_multiplier = 1.8  # Wider SL for higher beta
        elif asset == "DOGE":
            self.bb_sd_multiplier = 2.4  # 2.3-2.5 range, midpoint
            self.sl_atr_multiplier = 2.0  # Widest SL for noisiest asset
        
        # Keltner ATR period adjustment for alts
        if asset in ["SOL", "XRP", "DOGE"]:
            self.kc_atr_period = 20  # Longer ATR for smoother channels on alts


# Default configs for each asset
ASSET_CONFIGS: Dict[str, BandStrategyConfig] = {
    "BTC": BandStrategyConfig(asset="BTC"),
    "ETH": BandStrategyConfig(asset="ETH"),
    "SOL": BandStrategyConfig(asset="SOL"),
    "XRP": BandStrategyConfig(asset="XRP"),
    "DOGE": BandStrategyConfig(asset="DOGE"),
}


# ═══════════════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BandSnapshot:
    """Complete band indicator state at a point in time."""
    
    # ── Bollinger Bands ────────────────────────────────────────────────
    bb_sma: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_width: float = 0.0  # % of price
    bb_position: float = 0.0  # %B: 0=lower, 0.5=mid, 1=upper
    bb_sd_multiplier: float = 2.0
    
    # ── Keltner Channels ────────────────────────────────────────────────
    kc_ema: float = 0.0
    kc_upper: float = 0.0
    kc_lower: float = 0.0
    kc_atr: float = 0.0
    kc_squeeze: bool = False  # Bollinger inside Keltner = squeeze
    
    # ── Regime Filter ───────────────────────────────────────────────────
    trend_ema: float = 0.0
    price_above_trend_ema: bool = False
    adx: float = 0.0
    adx_trend_strength: str = "weak"  # "weak", "moderate", "strong"
    regime: str = "range"  # "trend" or "range"
    
    # ── RSI ─────────────────────────────────────────────────────────────
    rsi: float = 50.0
    rsi_zone: str = "neutral"  # "overbought", "oversold", "neutral"
    
    # ── ATR ─────────────────────────────────────────────────────────────
    atr: float = 0.0
    atr_24h_median: float = 0.0
    atr_spike: bool = False  # Current ATR > X × 24h median
    
    # ── Band Touch State ────────────────────────────────────────────────
    touched_upper: bool = False
    touched_lower: bool = False
    bars_outside_upper: int = 0
    bars_outside_lower: int = 0
    reentry_upper: bool = False  # Price closed back inside after touching upper
    reentry_lower: bool = False
    
    # ── Entry Signal ─────────────────────────────────────────────────────
    signal: str = "neutral"  # "long", "short", "neutral"
    signal_strength: float = 0.0  # 0.0-1.0
    signal_reason: str = ""
    
    # ── Exit Levels ─────────────────────────────────────────────────────
    entry_price: float = 0.0
    tp_price: float = 0.0  # Take profit
    sl_price: float = 0.0  # Stop loss
    r_multiple: float = 0.0  # R:R ratio
    
    # ── Meta ─────────────────────────────────────────────────────────────
    timestamp: float = 0.0
    price: float = 0.0
    bars_available: int = 0
    
    def to_dict(self) -> dict:
        return {
            "bb_sma": round(self.bb_sma, 2),
            "bb_upper": round(self.bb_upper, 2),
            "bb_lower": round(self.bb_lower, 2),
            "bb_width": round(self.bb_width, 4),
            "bb_position": round(self.bb_position, 4),
            "bb_sd_multiplier": self.bb_sd_multiplier,
            "kc_ema": round(self.kc_ema, 2),
            "kc_upper": round(self.kc_upper, 2),
            "kc_lower": round(self.kc_lower, 2),
            "kc_atr": round(self.kc_atr, 2),
            "kc_squeeze": self.kc_squeeze,
            "trend_ema": round(self.trend_ema, 2),
            "price_above_trend_ema": self.price_above_trend_ema,
            "adx": round(self.adx, 2),
            "adx_trend_strength": self.adx_trend_strength,
            "regime": self.regime,
            "rsi": round(self.rsi, 2),
            "rsi_zone": self.rsi_zone,
            "atr": round(self.atr, 2),
            "atr_spike": self.atr_spike,
            "touched_upper": self.touched_upper,
            "touched_lower": self.touched_lower,
            "reentry_upper": self.reentry_upper,
            "reentry_lower": self.reentry_lower,
            "signal": self.signal,
            "signal_strength": round(self.signal_strength, 3),
            "signal_reason": self.signal_reason,
            "entry_price": round(self.entry_price, 2),
            "tp_price": round(self.tp_price, 2),
            "sl_price": round(self.sl_price, 2),
            "r_multiple": round(self.r_multiple, 2),
            "price": round(self.price, 2),
            "bars_available": self.bars_available,
        }


@dataclass
class TradeSetup:
    """Complete trade setup with entry/exit levels."""
    
    side: str  # "long" or "short"
    entry_price: float
    tp_price: float
    sl_price: float
    r_multiple: float
    signal_strength: float
    regime: str
    bb_position: float
    rsi: float
    adx: float
    reason: str
    timestamp: datetime
    
    def to_dict(self) -> dict:
        return {
            "side": self.side,
            "entry_price": round(self.entry_price, 2),
            "tp_price": round(self.tp_price, 2),
            "sl_price": round(self.sl_price, 2),
            "r_multiple": round(self.r_multiple, 2),
            "signal_strength": round(self.signal_strength, 3),
            "regime": self.regime,
            "bb_position": round(self.bb_position, 4),
            "rsi": round(self.rsi, 2),
            "adx": round(self.adx, 2),
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


# ═══════════════════════════════════════════════════════════════════════════
# Band Strategy Engine
# ═══════════════════════════════════════════════════════════════════════════

class BandStrategyEngine:
    """15m Bollinger Band strategy engine with regime filtering."""
    
    def __init__(self, config: Optional[BandStrategyConfig] = None):
        self.cfg = config or BandStrategyConfig()
        self._prices: Deque[float] = deque(maxlen=self.cfg.max_bars)
        self._highs: Deque[float] = deque(maxlen=self.cfg.max_bars)
        self._lows: Deque[float] = deque(maxlen=self.cfg.max_bars)
        
        # Indicator state
        self._bb_sma: float = 0.0
        self._bb_std: float = 0.0
        self._kc_ema: float = 0.0
        self._kc_atr: float = 0.0
        self._trend_ema: float = 0.0
        self._rsi_avg_gain: float = 0.0
        self._rsi_avg_loss: float = 0.0
        
        # ADX state
        self._trues: Deque[float] = deque(maxlen=self.cfg.adx_period)
        self._plus_dm: Deque[float] = deque(maxlen=self.cfg.adx_period)
        self._minus_dm: Deque[float] = deque(maxlen=self.cfg.adx_period)
        self._smooth_plus_dm: float = 0.0
        self._smooth_minus_dm: float = 0.0
        self._smooth_tr: float = 0.0
        
        # Initialization flags
        self._bb_initialized: bool = False
        self._kc_initialized: bool = False
        self._trend_initialized: bool = False
        self._rsi_initialized: bool = False
        self._adx_initialized: bool = False
        
        # ATR 24h median tracking
        self._atr_history: Deque[float] = deque(maxlen=96)  # 24h of 15m bars
        self._atr_24h_median: float = 0.0
        
        # Band touch state
        self._prev_bb_position: float = 0.5
        self._bars_outside_upper: int = 0
        self._bars_outside_lower: int = 0
        
    def update(self, high: float, low: float, close: float) -> None:
        """Update with new OHLC bar (15m)."""
        if not all(math.isfinite(x) and x > 0 for x in [high, low, close]):
            return
        if high < low:
            return  # Invalid OHLC
        
        self._prices.append(close)
        self._highs.append(high)
        self._lows.append(low)
        
        n = len(self._prices)
        
        # ── Bollinger Bands ─────────────────────────────────────────────
        if n >= self.cfg.bb_period:
            prices_list = list(self._prices)
            recent = prices_list[-self.cfg.bb_period:]
            self._bb_sma = sum(recent) / len(recent)
            variance = sum((x - self._bb_sma) ** 2 for x in recent) / len(recent)
            self._bb_std = math.sqrt(variance)
            self._bb_initialized = True
        
        # ── Keltner Channels ─────────────────────────────────────────────
        if n >= self.cfg.kc_period:
            # EMA for midline
            if not self._kc_initialized:
                self._kc_ema = sum(list(self._prices)[-self.cfg.kc_period:]) / self.cfg.kc_period
                self._kc_initialized = True
            else:
                k = 2.0 / (self.cfg.kc_ema_period + 1)
                self._kc_ema = close * k + self._kc_ema * (1 - k)
            
            # ATR for channel width
            if n >= self.cfg.kc_atr_period + 1:
                trues = []
                for i in range(-self.cfg.kc_atr_period, 0):
                    h = self._highs[i]
                    l = self._lows[i]
                    c_prev = self._prices[i - 1]
                    tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
                    trues.append(tr)
                self._kc_atr = sum(trues) / len(trues)
        
        # ── Trend EMA (50) ────────────────────────────────────────────────
        if n >= self.cfg.trend_ema_period:
            if not self._trend_initialized:
                self._trend_ema = sum(list(self._prices)[-self.cfg.trend_ema_period:]) / self.cfg.trend_ema_period
                self._trend_initialized = True
            else:
                k = 2.0 / (self.cfg.trend_ema_period + 1)
                self._trend_ema = close * k + self._trend_ema * (1 - k)
        
        # ── RSI ─────────────────────────────────────────────────────────
        if n >= 2:
            delta = close - self._prices[-2]
            gain = max(delta, 0.0)
            loss = max(-delta, 0.0)
            
            if not self._rsi_initialized and n >= self.cfg.rsi_period + 1:
                prices_list = list(self._prices)
                deltas = [prices_list[i] - prices_list[i - 1] for i in range(1, n)]
                recent = deltas[-self.cfg.rsi_period:]
                self._rsi_avg_gain = sum(max(d, 0) for d in recent) / self.cfg.rsi_period
                self._rsi_avg_loss = sum(max(-d, 0) for d in recent) / self.cfg.rsi_period
                self._rsi_initialized = True
            elif self._rsi_initialized:
                self._rsi_avg_gain = (self._rsi_avg_gain * (self.cfg.rsi_period - 1) + gain) / self.cfg.rsi_period
                self._rsi_avg_loss = (self._rsi_avg_loss * (self.cfg.rsi_period - 1) + loss) / self.cfg.rsi_period
        
        # ── ADX ─────────────────────────────────────────────────────────
        if n >= 2:
            h_prev = self._highs[-2]
            l_prev = self._lows[-2]
            c_prev = self._prices[-2]
            
            up_move = high - h_prev
            down_move = l_prev - low
            
            plus_dm = up_move if up_move > down_move and up_move > 0 else 0.0
            minus_dm = down_move if down_move > up_move and down_move > 0 else 0.0
            
            tr = max(high - low, abs(high - c_prev), abs(low - c_prev))
            
            self._trues.append(tr)
            self._plus_dm.append(plus_dm)
            self._minus_dm.append(minus_dm)
            
            if len(self._trues) >= self.cfg.adx_period:
                if not self._adx_initialized:
                    self._smooth_tr = sum(self._trues) / self.cfg.adx_period
                    self._smooth_plus_dm = sum(self._plus_dm) / self.cfg.adx_period
                    self._smooth_minus_dm = sum(self._minus_dm) / self.cfg.adx_period
                    self._adx_initialized = True
                else:
                    alpha = 1.0 / self.cfg.adx_period
                    self._smooth_tr = self._smooth_tr * (1 - alpha) + tr * alpha
                    self._smooth_plus_dm = self._smooth_plus_dm * (1 - alpha) + plus_dm * alpha
                    self._smooth_minus_dm = self._smooth_minus_dm * (1 - alpha) + minus_dm * alpha
        
        # ── ATR 24h Median ───────────────────────────────────────────────
        if self._kc_atr > 0:
            self._atr_history.append(self._kc_atr)
            if len(self._atr_history) >= 24:
                sorted_atr = sorted(self._atr_history)
                self._atr_24h_median = sorted_atr[len(sorted_atr) // 2]
    
    def snapshot(self) -> BandSnapshot:
        """Get current band snapshot with signals."""
        snap = BandSnapshot()
        snap.timestamp = datetime.now(timezone.utc).timestamp()
        snap.bars_available = len(self._prices)
        
        if not self._prices:
            return snap
        
        price = self._prices[-1]
        snap.price = price
        
        # ── Bollinger Bands ─────────────────────────────────────────────
        if self._bb_initialized and self._bb_std > 0:
            snap.bb_sma = self._bb_sma
            snap.bb_sd_multiplier = self.cfg.bb_sd_multiplier
            snap.bb_upper = self._bb_sma + self._bb_std * self.cfg.bb_sd_multiplier
            snap.bb_lower = self._bb_sma - self._bb_std * self.cfg.bb_sd_multiplier
            snap.bb_width = (snap.bb_upper - snap.bb_lower) / self._bb_sma if self._bb_sma > 0 else 0
            snap.bb_position = (price - snap.bb_lower) / (snap.bb_upper - snap.bb_lower) if snap.bb_upper > snap.bb_lower else 0.5
        
        # ── Keltner Channels ─────────────────────────────────────────────
        if self._kc_initialized and self._kc_atr > 0:
            snap.kc_ema = self._kc_ema
            snap.kc_atr = self._kc_atr
            snap.kc_upper = self._kc_ema + self._kc_atr * self.cfg.kc_atr_multiplier
            snap.kc_lower = self._kc_ema - self._kc_atr * self.cfg.kc_atr_multiplier
            # Squeeze: Bollinger inside Keltner
            snap.kc_squeeze = snap.bb_upper <= snap.kc_upper and snap.bb_lower >= snap.kc_lower
        
        # ── Regime Filter ───────────────────────────────────────────────
        if self._trend_initialized:
            snap.trend_ema = self._trend_ema
            snap.price_above_trend_ema = price > self._trend_ema
        
        # ── ADX ─────────────────────────────────────────────────────────
        if self._adx_initialized and self._smooth_tr > 0:
            plus_di = 100 * (self._smooth_plus_dm / self._smooth_tr)
            minus_di = 100 * (self._smooth_minus_dm / self._smooth_tr)
            dx = abs(plus_di - minus_di) / (plus_di + minus_di) * 100 if (plus_di + minus_di) > 0 else 0
            snap.adx = dx  # Simplified ADX (single-period)
            
            if snap.adx >= self.cfg.adx_strong_trend:
                snap.adx_trend_strength = "strong"
            elif snap.adx >= self.cfg.adx_trend_threshold:
                snap.adx_trend_strength = "moderate"
            else:
                snap.adx_trend_strength = "weak"
            
            snap.regime = "trend" if snap.adx >= self.cfg.adx_trend_threshold else "range"
        
        # ── RSI ─────────────────────────────────────────────────────────
        if self._rsi_initialized and (self._rsi_avg_gain + self._rsi_avg_loss) > 0:
            rs = self._rsi_avg_gain / self._rsi_avg_loss
            snap.rsi = 100.0 - (100.0 / (1.0 + rs))
            
            if snap.rsi >= self.cfg.rsi_overbought:
                snap.rsi_zone = "overbought"
            elif snap.rsi <= self.cfg.rsi_oversold:
                snap.rsi_zone = "oversold"
            else:
                snap.rsi_zone = "neutral"
        
        # ── ATR Spike Detection ─────────────────────────────────────────
        snap.atr = self._kc_atr
        snap.atr_24h_median = self._atr_24h_median
        if snap.atr_24h_median > 0:
            snap.atr_spike = snap.atr > (snap.atr_24h_median * self.cfg.atr_spike_multiplier)
        
        # ── Band Touch Detection ─────────────────────────────────────────
        if snap.bb_position >= 1.0:
            snap.touched_upper = True
            self._bars_outside_upper += 1
            snap.bars_outside_upper = self._bars_outside_upper
        elif snap.bb_position <= 0.0:
            snap.touched_lower = True
            self._bars_outside_lower += 1
            snap.bars_outside_lower = self._bars_outside_lower
        else:
            # Price back inside bands - check for reentry
            if self._prev_bb_position >= 1.0 and snap.bb_position < 1.0:
                snap.reentry_upper = True
                self._bars_outside_upper = 0
            elif self._prev_bb_position <= 0.0 and snap.bb_position > 0.0:
                snap.reentry_lower = True
                self._bars_outside_lower = 0
        
        self._prev_bb_position = snap.bb_position
        
        # ── Generate Signal ─────────────────────────────────────────────
        signal = self._generate_signal(snap)
        snap.signal = signal.side
        snap.signal_strength = signal.signal_strength
        snap.signal_reason = signal.reason
        
        # ── Exit Levels ─────────────────────────────────────────────────
        if signal.side != "neutral":
            snap.entry_price = price
            snap.tp_price = signal.tp_price
            snap.sl_price = signal.sl_price
            snap.r_multiple = signal.r_multiple
        
        return snap
    
    def _generate_signal(self, snap: BandSnapshot) -> TradeSetup:
        """Generate trade signal based on band touches and regime."""
        
        # Default neutral setup
        setup = TradeSetup(
            side="neutral",
            entry_price=0.0,
            tp_price=0.0,
            sl_price=0.0,
            r_multiple=0.0,
            signal_strength=0.0,
            regime=snap.regime,
            bb_position=snap.bb_position,
            rsi=snap.rsi,
            adx=snap.adx,
            reason="",
            timestamp=datetime.now(timezone.utc),
        )
        
        # Only trade in range regime (mean-reversion only)
        if snap.regime != "range":
            setup.reason = f"Regime filter: {snap.regime} (require range)"
            return setup
        
        # Skip on volatility spike
        if snap.atr_spike:
            setup.reason = f"Volatility spike: ATR {snap.atr:.2f} > {snap.atr_24h_median * self.cfg.atr_spike_multiplier:.2f}"
            return setup
        
        # Skip on squeeze (breakout likely)
        if snap.kc_squeeze:
            setup.reason = "Keltner squeeze (breakout expected, not mean-reversion)"
            return setup
        
        price = snap.price
        
        # ── Short Signal: Top Edge Mean Reversion ───────────────────────
        if snap.reentry_upper:
            # Must have deep touch (at least 1 bar outside)
            if self.cfg.require_deep_touch and snap.bars_outside_upper < self.cfg.min_touch_bars:
                setup.reason = f"Shallow touch: {snap.bars_outside_upper} bars outside (require {self.cfg.min_touch_bars})"
                return setup
            
            # RSI confirmation (overbought)
            if snap.rsi < 60.0:  # Relaxed from 70 for more entries
                setup.reason = f"RSI not overbought: {snap.rsi:.1f}"
                return setup
            
            # Calculate exit levels
            tp_price = snap.bb_sma if self.cfg.tp_at_mid_band else price - (price - snap.bb_lower) * self.cfg.tp_r_multiple
            
            # SL: max of swing high (approx) or ATR multiple
            sl_atr = price + self._kc_atr * self.cfg.sl_atr_multiplier
            sl_max = price + self._kc_atr * self.cfg.sl_max_atr_multiplier
            sl_price = min(sl_atr, sl_max)
            
            # R:R calculation
            risk = sl_price - price
            reward = price - tp_price
            r_multiple = reward / risk if risk > 0 else 0.0
            
            # Signal strength based on how stretched
            strength = min(1.0, snap.bb_position - 1.0 + 0.5) if snap.bb_position > 1.0 else 0.0
            
            setup.side = "short"
            setup.entry_price = price
            setup.tp_price = tp_price
            setup.sl_price = sl_price
            setup.r_multiple = r_multiple
            setup.signal_strength = strength
            setup.reason = f"Top edge reentry: BB {snap.bb_position:.2f}, RSI {snap.rsi:.1f}"
        
        # ── Long Signal: Bottom Edge Mean Reversion ──────────────────────
        elif snap.reentry_lower:
            # Must have deep touch
            if self.cfg.require_deep_touch and snap.bars_outside_lower < self.cfg.min_touch_bars:
                setup.reason = f"Shallow touch: {snap.bars_outside_lower} bars outside (require {self.cfg.min_touch_bars})"
                return setup
            
            # RSI confirmation (oversold)
            if snap.rsi > 40.0:  # Relaxed from 30 for more entries
                setup.reason = f"RSI not oversold: {snap.rsi:.1f}"
                return setup
            
            # Calculate exit levels
            tp_price = snap.bb_sma if self.cfg.tp_at_mid_band else price + (snap.bb_upper - price) * self.cfg.tp_r_multiple
            
            # SL: max of swing low (approx) or ATR multiple
            sl_atr = price - self._kc_atr * self.cfg.sl_atr_multiplier
            sl_max = price - self._kc_atr * self.cfg.sl_max_atr_multiplier
            sl_price = max(sl_atr, sl_max)
            
            # R:R calculation
            risk = price - sl_price
            reward = tp_price - price
            r_multiple = reward / risk if risk > 0 else 0.0
            
            # Signal strength based on how stretched
            strength = min(1.0, 0.5 - snap.bb_position) if snap.bb_position < 0.0 else 0.0
            
            setup.side = "long"
            setup.entry_price = price
            setup.tp_price = tp_price
            setup.sl_price = sl_price
            setup.r_multiple = r_multiple
            setup.signal_strength = strength
            setup.reason = f"Bottom edge reentry: BB {snap.bb_position:.2f}, RSI {snap.rsi:.1f}"
        
        else:
            setup.reason = "No band touch/reentry detected"
        
        return setup


def get_band_strategy_config(asset: str) -> BandStrategyConfig:
    """Get configuration for a specific asset."""
    asset = asset.upper()
    return ASSET_CONFIGS.get(asset, BandStrategyConfig(asset=asset))


def create_band_engine(asset: str) -> BandStrategyEngine:
    """Create a band strategy engine for a specific asset."""
    config = get_band_strategy_config(asset)
    return BandStrategyEngine(config)
