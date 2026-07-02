"""
TA Engine Core
==============
Indicator calculations and divergence detection in a deterministic,
config-driven way for RSI, MACD, moving averages, and Fibonacci pivots.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
import numpy as np

from .ta_models import (
    OHLCVSnapshot,
    IndicatorBundle,
    Divergence,
    FibPivots,
    MarketStructure,
    SignalScore,
    PricePivot,
)


@dataclass
class IndicatorConfig:
    """Configuration for all indicator calculations."""
    # RSI
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0

    # MACD
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9

    # EMAs
    ema_fast: int = 12
    ema_slow: int = 26
    ema_trend: int = 50
    sma_50_period: int = 50
    sma_200_period: int = 200

    # ATR
    atr_period: int = 14

    # Fib pivots
    fib_lookback: int = 20

    # Divergence
    div_min_bars: int = 5
    div_confirmation_pct: float = 0.02
    div_min_strength: float = 0.3

    # Volume
    volume_ma_period: int = 20


class TAEngine:
    """
    Core engine for computing all indicators and signals.
    Pure functions - no state, thread-safe.
    """

    def __init__(self, config: Optional[IndicatorConfig] = None):
        self.config = config or IndicatorConfig()

    def compute_bundle(
        self,
        ohlcv_buffer: List[OHLCVSnapshot],
        asset: str,
        timeframe: str,
    ) -> IndicatorBundle:
        """Compute full IndicatorBundle from OHLCV buffer."""
        if len(ohlcv_buffer) < 30:
            return IndicatorBundle(
                asset=asset,
                timeframe=timeframe,
                timestamp=ohlcv_buffer[-1].timestamp_window_end if ohlcv_buffer else 0,
                close=ohlcv_buffer[-1].close if ohlcv_buffer else 0,
                volume=ohlcv_buffer[-1].volume if ohlcv_buffer else 0,
                ema_fast=ohlcv_buffer[-1].close if ohlcv_buffer else 0,
                ema_slow=ohlcv_buffer[-1].close if ohlcv_buffer else 0,
                ema_trend=ohlcv_buffer[-1].close if ohlcv_buffer else 0,
                ema_trend_slope=0.0,
                sma_50=ohlcv_buffer[-1].close if ohlcv_buffer else 0,
                bars_available=len(ohlcv_buffer),
            )

        closes = np.array([bar.close for bar in ohlcv_buffer])
        highs = np.array([bar.high for bar in ohlcv_buffer])
        lows = np.array([bar.low for bar in ohlcv_buffer])
        volumes = np.array([bar.volume for bar in ohlcv_buffer])

        # EMAs
        ema_fast = self._ema(closes, self.config.ema_fast)
        ema_slow = self._ema(closes, self.config.ema_slow)
        ema_trend = self._ema(closes, self.config.ema_trend)
        ema_slope = (ema_trend[-1] - ema_trend[-10]) / ema_trend[-10] if len(ema_trend) >= 10 else 0.0

        # SMAs
        sma_50 = self._sma(closes, self.config.sma_50_period)
        sma_200 = None
        if len(closes) >= self.config.sma_200_period:
            sma_200 = self._sma(closes, self.config.sma_200_period)

        # RSI
        rsi = self._rsi(closes, self.config.rsi_period)
        rsi_zone = "neutral"
        if rsi[-1] < self.config.rsi_oversold:
            rsi_zone = "oversold"
        elif rsi[-1] > self.config.rsi_overbought:
            rsi_zone = "overbought"

        # MACD
        macd_line, macd_signal, macd_hist = self._macd(
            closes,
            self.config.macd_fast,
            self.config.macd_slow,
            self.config.macd_signal,
        )
        hist_slope = macd_hist[-1] - macd_hist[-3] if len(macd_hist) >= 3 else 0.0

        # ATR
        atr = self._atr(highs, lows, closes, self.config.atr_period)
        atr_pct = atr[-1] / closes[-1] if closes[-1] > 0 else 0.0

        # Volume z-score
        volume_z = self._volume_zscore(volumes, self.config.volume_ma_period)

        # Fib pivots
        fib_pivots = self._compute_fib_pivots(highs, lows, closes)

        # Divergences
        divergences = self._detect_divergences(
            highs, lows, closes,
            rsi, macd_line,
            ohlcv_buffer,
        )

        return IndicatorBundle(
            asset=asset,
            timeframe=timeframe,
            timestamp=ohlcv_buffer[-1].timestamp_window_end,
            close=closes[-1],
            volume=volumes[-1],
            ema_fast=ema_fast[-1],
            ema_slow=ema_slow[-1],
            ema_trend=ema_trend[-1],
            ema_trend_slope=ema_slope,
            sma_50=sma_50[-1],
            sma_200=sma_200[-1] if sma_200 is not None else None,
            fib_pivots=fib_pivots,
            rsi=rsi[-1],
            rsi_zone=rsi_zone,
            macd_line=macd_line[-1],
            macd_signal=macd_signal[-1],
            macd_histogram=macd_hist[-1],
            macd_histogram_slope=hist_slope,
            divergences=divergences,
            atr=atr[-1],
            atr_pct=atr_pct,
            volume_zscore=volume_z,
            bars_available=len(ohlcv_buffer),
        )

    def _ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate EMA for array."""
        if len(data) < period:
            return data
        alpha = 2.0 / (period + 1)
        ema = np.zeros_like(data)
        ema[0] = data[0]
        for i in range(1, len(data)):
            ema[i] = alpha * data[i] + (1 - alpha) * ema[i - 1]
        return ema

    def _sma(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate SMA for array."""
        if len(data) < period:
            return data
        sma = np.convolve(data, np.ones(period) / period, mode='valid')
        pad = np.full(period - 1, data[0])
        return np.concatenate([pad, sma])

    def _rsi(self, closes: np.ndarray, period: int = 14) -> np.ndarray:
        """Calculate RSI for closes array."""
        if len(closes) < period + 1:
            return np.full_like(closes, 50.0)

        deltas = np.diff(closes)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)

        avg_gain = np.convolve(gains, np.ones(period) / period, mode='valid')
        avg_loss = np.convolve(losses, np.ones(period) / period, mode='valid')

        # Pad to match length
        pad_len = len(closes) - len(avg_gain)
        avg_gain = np.concatenate([np.full(pad_len, avg_gain[0] if len(avg_gain) > 0 else 0), avg_gain])
        avg_loss = np.concatenate([np.full(pad_len, avg_loss[0] if len(avg_loss) > 0 else 0), avg_loss])

        rs = np.where(avg_loss == 0, 100, avg_gain / avg_loss)
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _macd(
        self,
        closes: np.ndarray,
        fast: int,
        slow: int,
        signal: int,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Calculate MACD line, signal line, and histogram."""
        ema_fast = self._ema(closes, fast)
        ema_slow = self._ema(closes, slow)
        macd_line = ema_fast - ema_slow
        macd_signal = self._ema(macd_line, signal)
        histogram = macd_line - macd_signal
        return macd_line, macd_signal, histogram

    def _atr(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        period: int = 14,
    ) -> np.ndarray:
        """Calculate Average True Range."""
        if len(closes) < 2:
            return np.zeros_like(closes)

        tr1 = highs[1:] - lows[1:]
        tr2 = np.abs(highs[1:] - closes[:-1])
        tr3 = np.abs(lows[1:] - closes[:-1])
        tr = np.maximum(np.maximum(tr1, tr2), tr3)
        tr = np.concatenate([[tr[0]], tr])

        atr = np.zeros_like(closes)
        atr[:period] = np.mean(tr[:period])
        for i in range(period, len(closes)):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
        return atr

    def _volume_zscore(self, volumes: np.ndarray, period: int = 20) -> float:
        """Calculate z-score of latest volume vs recent average."""
        if len(volumes) < period:
            return 0.0
        recent = volumes[-period:]
        mean = np.mean(recent[:-1])
        std = np.std(recent[:-1])
        if std == 0:
            return 0.0
        return (volumes[-1] - mean) / std

    def _compute_fib_pivots(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
    ) -> Optional[FibPivots]:
        """Compute Fibonacci pivot levels from recent swing range."""
        lookback = min(self.config.fib_lookback, len(closes))
        if lookback < 5:
            return None

        swing_high = np.max(highs[-lookback:])
        swing_low = np.min(lows[-lookback:])
        pivot = (swing_high + swing_low) / 2

        # Fib extensions from pivot
        range_size = swing_high - swing_low
        s1 = pivot - 0.382 * range_size
        s2 = pivot - 0.618 * range_size
        r1 = pivot + 0.382 * range_size
        r2 = pivot + 0.618 * range_size

        return FibPivots(s2=s2, s1=s1, pivot=pivot, r1=r1, r2=r2)

    def _find_pivots(
        self,
        data: np.ndarray,
        window: int = 3,
    ) -> List[PricePivot]:
        """Find swing highs and lows in price series."""
        pivots = []
        for i in range(window, len(data) - window):
            # Check for swing high
            if all(data[i] >= data[i - j] for j in range(1, window + 1)) and \
               all(data[i] >= data[i + j] for j in range(1, window + 1)):
                pivots.append(PricePivot(
                    pivot_type="high",
                    price=data[i],
                    index=i,
                    timestamp=float(i),
                ))
            # Check for swing low
            elif all(data[i] <= data[i - j] for j in range(1, window + 1)) and \
                 all(data[i] <= data[i + j] for j in range(1, window + 1)):
                pivots.append(PricePivot(
                    pivot_type="low",
                    price=data[i],
                    index=i,
                    timestamp=float(i),
                ))
        return pivots

    def _detect_divergences(
        self,
        highs: np.ndarray,
        lows: np.ndarray,
        closes: np.ndarray,
        rsi: np.ndarray,
        macd: np.ndarray,
        ohlcv: List[OHLCVSnapshot],
    ) -> List[Divergence]:
        """
        Detect RSI and MACD divergences.

        Bullish RSI divergence:
        - Price makes lower low (below pivot support or recent low)
        - RSI makes higher low while RSI < oversold threshold

        Bearish RSI divergence:
        - Price makes higher high (above pivot resistance or recent high)
        - RSI makes lower high while RSI > overbought threshold

        MACD divergences follow same logic on MACD histogram.
        """
        divergences = []

        # Find price pivots
        price_pivots = self._find_pivots(highs, window=3)
        if len(price_pivots) < 2:
            return divergences

        # RSI divergences
        for i in range(1, len(price_pivots)):
            prev_pivot = price_pivots[i - 1]
            curr_pivot = price_pivots[i]

            min_bars = self.config.div_min_bars
            if curr_pivot.index - prev_pivot.index < min_bars:
                continue

            prev_rsi = rsi[prev_pivot.index]
            curr_rsi = rsi[curr_pivot.index]

            # Bullish divergence: price lower low, RSI higher low + oversold
            if curr_pivot.pivot_type == "low":
                if curr_pivot.price < prev_pivot.price and curr_rsi > prev_rsi:
                    if curr_rsi < self.config.rsi_oversold + 10:  # Near oversold
                        strength = self._calc_div_strength(
                            prev_pivot.price, curr_pivot.price,
                            prev_rsi, curr_rsi,
                            "bullish"
                        )
                        divergences.append(Divergence(
                            div_type="bullish_rsi",
                            strength=strength,
                            price_pivot=curr_pivot.price,
                            indicator_pivot=curr_rsi,
                            price_pivot_idx=curr_pivot.index,
                            indicator_pivot_idx=curr_pivot.index,
                            confirmed=self._check_div_confirmation(
                                closes, curr_pivot.index, "bullish"
                            ),
                            rsi_at_pivot=curr_rsi,
                        ))

            # Bearish divergence: price higher high, RSI lower high + overbought
            elif curr_pivot.pivot_type == "high":
                if curr_pivot.price > prev_pivot.price and curr_rsi < prev_rsi:
                    if curr_rsi > self.config.rsi_overbought - 10:  # Near overbought
                        strength = self._calc_div_strength(
                            prev_pivot.price, curr_pivot.price,
                            prev_rsi, curr_rsi,
                            "bearish"
                        )
                        divergences.append(Divergence(
                            div_type="bearish_rsi",
                            strength=strength,
                            price_pivot=curr_pivot.price,
                            indicator_pivot=curr_rsi,
                            price_pivot_idx=curr_pivot.index,
                            indicator_pivot_idx=curr_pivot.index,
                            confirmed=self._check_div_confirmation(
                                closes, curr_pivot.index, "bearish"
                            ),
                            rsi_at_pivot=curr_rsi,
                        ))

        # MACD histogram divergences (similar logic on MACD histogram)
        macd_hist = macd - self._ema(macd, self.config.macd_signal)
        hist_pivots = self._find_pivots(macd_hist, window=3)

        for i in range(1, len(price_pivots)):
            curr_price_pivot = price_pivots[i]
            prev_price_pivot = price_pivots[i - 1]

            # Find matching hist pivot
            matching_hist_pivot = None
            for hp in hist_pivots:
                if abs(hp.index - curr_price_pivot.index) <= 2:
                    matching_hist_pivot = hp
                    break

            if matching_hist_pivot and i > 1:
                prev_hist_idx = None
                for hp in hist_pivots:
                    if abs(hp.index - prev_price_pivot.index) <= 2:
                        prev_hist_idx = hp.index
                        break

                if prev_hist_idx:
                    prev_hist = macd_hist[prev_hist_idx]
                    curr_hist = macd_hist[matching_hist_pivot.index]

                    # Bullish MACD divergence
                    if curr_price_pivot.pivot_type == "low":
                        if curr_price_pivot.price < prev_price_pivot.price and curr_hist > prev_hist:
                            strength = self._calc_div_strength(
                                prev_price_pivot.price, curr_price_pivot.price,
                                prev_hist, curr_hist,
                                "bullish"
                            )
                            divergences.append(Divergence(
                                div_type="bullish_macd",
                                strength=strength,
                                price_pivot=curr_price_pivot.price,
                                indicator_pivot=curr_hist,
                                price_pivot_idx=curr_price_pivot.index,
                                indicator_pivot_idx=matching_hist_pivot.index,
                                confirmed=self._check_div_confirmation(
                                    closes, curr_price_pivot.index, "bullish"
                                ),
                            ))

                    # Bearish MACD divergence
                    elif curr_price_pivot.pivot_type == "high":
                        if curr_price_pivot.price > prev_price_pivot.price and curr_hist < prev_hist:
                            strength = self._calc_div_strength(
                                prev_price_pivot.price, curr_price_pivot.price,
                                prev_hist, curr_hist,
                                "bearish"
                            )
                            divergences.append(Divergence(
                                div_type="bearish_macd",
                                strength=strength,
                                price_pivot=curr_price_pivot.price,
                                indicator_pivot=curr_hist,
                                price_pivot_idx=curr_price_pivot.index,
                                indicator_pivot_idx=matching_hist_pivot.index,
                                confirmed=self._check_div_confirmation(
                                    closes, curr_price_pivot.index, "bearish"
                                ),
                            ))

        return divergences

    def _calc_div_strength(
        self,
        prev_price: float,
        curr_price: float,
        prev_ind: float,
        curr_ind: float,
        direction: str,
    ) -> float:
        """Calculate divergence strength 0-1 based on price/indicator divergence magnitude."""
        price_diff = abs(curr_price - prev_price) / prev_price
        ind_diff = abs(curr_ind - prev_ind) / (abs(prev_ind) + 0.001)

        # Strength increases with both divergences
        strength = min(1.0, (price_diff + ind_diff) / 2)
        strength = max(self.config.div_min_strength, strength)
        return round(strength, 3)

    def _check_div_confirmation(
        self,
        closes: np.ndarray,
        pivot_idx: int,
        direction: str,
        lookforward: int = 3,
    ) -> bool:
        """Check if divergence is confirmed by subsequent price action."""
        if pivot_idx + lookforward >= len(closes):
            return False

        post_prices = closes[pivot_idx + 1:pivot_idx + lookforward + 1]
        pivot_price = closes[pivot_idx]

        if direction == "bullish":
            # Confirmed if price moves up after bullish div at low
            return any(p > pivot_price * 1.005 for p in post_prices)
        else:
            # Confirmed if price moves down after bearish div at high
            return any(p < pivot_price * 0.995 for p in post_prices)

    def compute_signal_score(
        self,
        bundle: IndicatorBundle,
        market_structure: MarketStructure,
    ) -> SignalScore:
        """
        Convert IndicatorBundle + MarketStructure into SignalScore.
        This is where signal logic is applied.
        """
        tags = []
        trend_score = 0.0
        momentum_score = 0.0
        divergence_score = 0.0
        fib_score = 0.0
        volume_score = 0.0

        # Trend score based on EMAs and SMAs
        if bundle.close > bundle.ema_fast > bundle.ema_slow:
            trend_score = 0.6
            tags.append("ema_bull_stack")
        elif bundle.close < bundle.ema_fast < bundle.ema_slow:
            trend_score = -0.6
            tags.append("ema_bear_stack")

        if bundle.ema_trend_slope > 0.0001:
            trend_score += 0.2
        elif bundle.ema_trend_slope < -0.0001:
            trend_score -= 0.2

        # Momentum score based on RSI
        if bundle.rsi < 30:
            momentum_score = 0.5  # Oversold bounce potential
            tags.append("rsi_oversold")
        elif bundle.rsi > 70:
            momentum_score = -0.5
            tags.append("rsi_overbought")
        elif 45 < bundle.rsi < 55:
            momentum_score = 0.0
            tags.append("rsi_neutral")
        else:
            momentum_score = (bundle.rsi - 50) / 50

        # MACD histogram direction
        if bundle.macd_histogram > 0 and bundle.macd_histogram_slope > 0:
            momentum_score += 0.3
            tags.append("macd_bullish")
        elif bundle.macd_histogram < 0 and bundle.macd_histogram_slope < 0:
            momentum_score -= 0.3
            tags.append("macd_bearish")

        # Divergence score (highest weight)
        if bundle.has_bullish_divergence():
            bullish_divs = [d for d in bundle.divergences if "bullish" in d.div_type and d.confirmed]
            if bullish_divs:
                divergence_score = max(d.strength for d in bullish_divs)
                tags.append("bullish_div")

        if bundle.has_bearish_divergence():
            bearish_divs = [d for d in bundle.divergences if "bearish" in d.div_type and d.confirmed]
            if bearish_divs:
                divergence_score = -max(d.strength for d in bearish_divs)
                tags.append("bearish_div")

        # Fibonacci confluence
        if bundle.fib_pivots:
            if bundle.close > bundle.fib_pivots.pivot:
                fib_score = 0.3
            else:
                fib_score = -0.3

            if market_structure.near_support:
                fib_score += 0.4
                tags.append("near_support")
            if market_structure.near_resistance:
                fib_score -= 0.4
                tags.append("near_resistance")

        # Volume confirmation
        if bundle.volume_zscore > 1.5:
            volume_score = 0.3
            tags.append("volume_spike")

        # Determine direction
        total_score = trend_score + momentum_score + divergence_score * 2 + fib_score + volume_score

        direction = "flat"
        confidence = 0.0
        primary_driver = ""

        if total_score > 0.8:
            direction = "long"
            confidence = min(1.0, 0.5 + abs(total_score) / 4)
            primary_driver = "div" if abs(divergence_score) > 0.5 else "trend"
        elif total_score < -0.8:
            direction = "short"
            confidence = min(1.0, 0.5 + abs(total_score) / 4)
            primary_driver = "div" if abs(divergence_score) > 0.5 else "trend"

        # Quality score for sizing (independent of direction)
        quality = (
            abs(trend_score) * 0.25 +
            abs(divergence_score) * 0.35 +
            fib_score if fib_score > 0 else -fib_score * 0.20 +
            volume_score * 0.20
        )
        quality = min(1.0, quality)

        return SignalScore(
            asset=bundle.asset,
            timeframe=bundle.timeframe,
            timestamp=bundle.timestamp,
            direction=direction,
            confidence=round(confidence, 3),
            quality_score=round(quality, 3),
            rationale_tags=tags,
            primary_driver=primary_driver,
            trend_score=round(trend_score, 3),
            momentum_score=round(momentum_score, 3),
            divergence_score=round(divergence_score, 3),
            fib_confluence_score=round(fib_score, 3),
            volume_confirm_score=round(volume_score, 3),
        )
