"""BTC Anchor Regime Gate for Altcoin Trading

Implements Phase 4 BTC anchor requirements:
- Block altcoin longs when BTC regime is strongly bearish
- Block altcoin shorts when BTC regime is strongly bullish  
- Lead-lag timing logic for altcoin entry after BTC impulses

Part of MERID single-signal hierarchy (Level 2).
"""

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Optional, Dict, Set
from enum import Enum

from merid.signals.btc_anchored_move import get_btc_anchored_model
from utils.logger import get_logger

logger = get_logger("merid.signals.btc_anchor_gate")


class BtcRegime(str, Enum):
    """BTC market regime classification."""
    STRONG_BULL = "strong_bull"
    BULL = "bull"
    NEUTRAL = "neutral"
    BEAR = "bear"
    STRONG_BEAR = "strong_bear"


@dataclass
class BtcRegimeState:
    """Current BTC regime with gating information."""
    regime: BtcRegime
    timestamp: float
    adx: float = 0.0
    slope_15m: float = 0.0
    slope_1h: float = 0.0
    atr_pct: float = 0.0
    last_impulse_ts: Optional[float] = None
    impulse_direction: Optional[str] = None
    impulse_magnitude: float = 0.0

    @property
    def is_strong_bull(self) -> bool:
        return self.regime == BtcRegime.STRONG_BULL

    @property
    def is_strong_bear(self) -> bool:
        return self.regime == BtcRegime.STRONG_BEAR

    @property
    def is_trending(self) -> bool:
        return self.regime in (BtcRegime.STRONG_BULL, BtcRegime.STRONG_BEAR)

    @property
    def is_range_bound(self) -> bool:
        return self.regime == BtcRegime.NEUTRAL


@dataclass
class GateDecision:
    """Decision from BTC anchor gate for an altcoin trade."""
    asset: str
    side: str
    allowed: bool
    reason: str
    confidence_modifier: float = 1.0
    size_modifier: float = 1.0
    timing_delay_seconds: float = 0.0

    @property
    def is_blocked(self) -> bool:
        return not self.allowed


class BtcAnchorGate:
    """BTC anchor regime gate for altcoin trading decisions."""

    ADX_STRONG_TREND = 25.0
    SLOPE_THRESHOLD = 0.0001
    LEAD_LAG_SECONDS = 60
    IMPULSE_MIN_PCT = 0.3

    ASSET_BETAS: Dict[str, float] = {
        "BTC": 1.0,
        "ETH": 1.15,
        "SOL": 1.40,
        "XRP": 1.10,
        "DOGE": 1.35,
    }

    def __init__(self):
        self._btc_model = get_btc_anchored_model()
        self._current_regime: Optional[BtcRegimeState] = None
        self._last_update: float = 0.0
        self._recent_impulses: list = []
        # TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
        # TODO: Re-enable lock after startup is stable and investigate proper async synchronization
        # self._lock = threading.Lock()
        self._lock = None  # Disabled to prevent startup hang
        logger.info("BtcAnchorGate initialized")

    def update_regime(self, btc_price: float, btc_prices_15m: list, btc_prices_1h: list) -> BtcRegimeState:
        """Update BTC regime state from price data."""
        if self._lock is not None:
            with self._lock:
                adx = self._calculate_adx(btc_prices_15m)
                slope_15m = self._calculate_slope(btc_prices_15m)
                slope_1h = self._calculate_slope(btc_prices_1h)
                atr_pct = self._calculate_atr_pct(btc_prices_15m)
                impulse = self._detect_impulse(btc_prices_15m)
                regime = self._classify_regime(adx, slope_15m, slope_1h)

                state = BtcRegimeState(
                    regime=regime,
                    timestamp=time.time(),
                    adx=adx,
                    slope_15m=slope_15m,
                    slope_1h=slope_1h,
                    atr_pct=atr_pct,
                )

                if impulse:
                    state.last_impulse_ts = impulse[0]
        else:
            # Lock disabled - direct update (startup workaround)
            adx = self._calculate_adx(btc_prices_15m)
            slope_15m = self._calculate_slope(btc_prices_15m)
            slope_1h = self._calculate_slope(btc_prices_1h)
            atr_pct = self._calculate_atr_pct(btc_prices_15m)
            impulse = self._detect_impulse(btc_prices_15m)
            regime = self._classify_regime(adx, slope_15m, slope_1h)

            state = BtcRegimeState(
                regime=regime,
                timestamp=time.time(),
                adx=adx,
                slope_15m=slope_15m,
                slope_1h=slope_1h,
                atr_pct=atr_pct,
            )

            if impulse:
                state.last_impulse_ts = impulse[0]
                state.impulse_direction = impulse[1]
                state.impulse_magnitude = impulse[2]
                self._recent_impulses.append(impulse)
                self._recent_impulses = self._recent_impulses[-10:]

            self._current_regime = state
            self._last_update = time.time()
            return state

    def check_trade(self, asset: str, side: str, proposed_confidence: float = 0.5, proposed_size: float = 1.0) -> GateDecision:
        """Check if an altcoin trade is allowed based on BTC regime."""
        with self._lock:
            if self._current_regime is None:
                return GateDecision(
                    asset=asset, side=side, allowed=True,
                    reason="No BTC regime data (permissive default)",
                    confidence_modifier=1.0, size_modifier=1.0
                )

            regime = self._current_regime
            now = time.time()

            # Rule 1: Block altcoin longs when BTC strongly bearish
            if side == "buy" and regime.is_strong_bear:
                return GateDecision(
                    asset=asset, side=side, allowed=False,
                    reason=f"BTC strongly bearish (ADX={regime.adx:.1f})",
                    confidence_modifier=0.0, size_modifier=0.0
                )

            # Rule 2: Block altcoin shorts when BTC strongly bullish
            if side == "sell" and regime.is_strong_bull:
                return GateDecision(
                    asset=asset, side=side, allowed=False,
                    reason=f"BTC strongly bullish (ADX={regime.adx:.1f})",
                    confidence_modifier=0.0, size_modifier=0.0
                )

            # Rule 3: Apply lead-lag delay after BTC impulse
            delay_seconds = 0.0
            if regime.last_impulse_ts and (now - regime.last_impulse_ts) < self.LEAD_LAG_SECONDS:
                delay_seconds = self.LEAD_LAG_SECONDS - (now - regime.last_impulse_ts)

            # Calculate modifiers based on beta and regime alignment
            beta = self.ASSET_BETAS.get(asset, 1.0)
            confidence_mod = 1.0
            size_mod = 1.0

            if regime.is_trending:
                # Reduce confidence for high-beta assets in strong trends
                confidence_mod = max(0.5, 1.0 - (beta - 1.0) * 0.3)
                # Reduce size for counter-trend trades
                if (side == "buy" and regime.slope_15m < 0) or (side == "sell" and regime.slope_15m > 0):
                    size_mod = 0.7

            return GateDecision(
                asset=asset, side=side, allowed=True,
                reason=f"BTC regime: {regime.regime.value}, beta: {beta:.2f}",
                confidence_modifier=confidence_mod,
                size_modifier=size_mod,
                timing_delay_seconds=delay_seconds
            )

    def _calculate_adx(self, prices: list) -> float:
        """Simplified ADX calculation."""
        if len(prices) < 14:
            return 0.0
        # Simplified: use price momentum as proxy
        momentum = abs(prices[-1] - prices[-14]) / prices[-14] * 100
        return min(50.0, momentum * 5)  # Scale to 0-50

    def _calculate_slope(self, prices: list) -> float:
        """Calculate price slope (per-bar)."""
        if len(prices) < 10:
            return 0.0
        # Simple linear regression slope
        n = min(len(prices), 20)
        y = prices[-n:]
        x = list(range(n))
        x_mean = sum(x) / n
        y_mean = sum(y) / n
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))
        if denominator == 0:
            return 0.0
        slope = numerator / denominator
        return slope / y_mean  # Normalize

    def _calculate_atr_pct(self, prices: list) -> float:
        """Calculate ATR as percentage of price."""
        if len(prices) < 2:
            return 0.0
        tr_list = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
        if not tr_list:
            return 0.0
        atr = sum(tr_list[-14:]) / min(14, len(tr_list))
        return atr / prices[-1] * 100 if prices[-1] > 0 else 0.0

    def _detect_impulse(self, prices: list) -> Optional[tuple]:
        """Detect recent price impulse."""
        if len(prices) < 3:
            return None
        change_pct = (prices[-1] - prices[-3]) / prices[-3] * 100
        if abs(change_pct) >= self.IMPULSE_MIN_PCT:
            direction = "up" if change_pct > 0 else "down"
            return (time.time(), direction, abs(change_pct))
        return None

    def _classify_regime(self, adx: float, slope_15m: float, slope_1h: float) -> BtcRegime:
        """Classify BTC regime."""
        strong_trend = adx > self.ADX_STRONG_TREND
        avg_slope = (slope_15m + slope_1h) / 2

        if strong_trend and avg_slope > self.SLOPE_THRESHOLD * 2:
            return BtcRegime.STRONG_BULL
        elif strong_trend and avg_slope < -self.SLOPE_THRESHOLD * 2:
            return BtcRegime.STRONG_BEAR
        elif avg_slope > self.SLOPE_THRESHOLD:
            return BtcRegime.BULL
        elif avg_slope < -self.SLOPE_THRESHOLD:
            return BtcRegime.BEAR
        else:
            return BtcRegime.NEUTRAL

    def get_current_regime(self) -> Optional[BtcRegimeState]:
        """Get current BTC regime state."""
        with self._lock:
            return self._current_regime

    def reset(self) -> None:
        """Reset gate state."""
        with self._lock:
            self._current_regime = None
            self._last_update = 0.0
            self._recent_impulses.clear()
            logger.info("BtcAnchorGate reset")


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_gate_instance: Optional[BtcAnchorGate] = None
# TEMPORARILY DISABLED: threading.Lock causing deadlock during startup
# TODO: Re-enable lock after startup is stable and investigate proper async synchronization
# _gate_lock = threading.Lock()
_gate_lock = None  # Disabled to prevent startup hang


def get_btc_anchor_gate() -> BtcAnchorGate:
    """Get or create the singleton BtcAnchorGate."""
    global _gate_instance
    if _gate_instance is None:
        if _gate_lock is not None:
            with _gate_lock:
                if _gate_instance is None:
                    _gate_instance = BtcAnchorGate()
                    logger.info("BtcAnchorGate singleton initialized")
        else:
            # Lock disabled - direct initialization (startup workaround)
            _gate_instance = BtcAnchorGate()
            logger.info("BtcAnchorGate singleton initialized (lock disabled)")
    return _gate_instance


def reset_btc_anchor_gate() -> None:
    """Reset the singleton (for testing)."""
    global _gate_instance
    if _gate_lock is not None:
        with _gate_lock:
            _gate_instance = None
            logger.info("BtcAnchorGate singleton reset")
    else:
        _gate_instance = None
        logger.info("BtcAnchorGate singleton reset (lock disabled)")
