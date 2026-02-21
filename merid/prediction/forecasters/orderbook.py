"""Orderbook Microstructure Forecaster — Sprint N.

Standalone forecaster that uses orderbook-level signals to predict
short-term price direction. Distinct from MeanReversionForecaster
which uses imbalance as one of several mean-reversion signals.

Signal components:
1. **Bid/Ask Imbalance** — ratio of bid depth to ask depth near touch
2. **Spread Compression** — narrowing spread signals convergence on fair value
3. **Depth-Weighted Fair Value** — volume-weighted mid from top N levels
4. **Trade Flow Imbalance** — buy vs sell aggressor flow (when available)

Archetype: "orderbook_micro"
"""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.orderbook")

# Rolling history for spread tracking
_spread_history: Dict[str, List[float]] = defaultdict(list)
_MAX_SPREAD_HISTORY = 30


class OrderbookForecaster(Forecaster):
    """Forecaster based on orderbook microstructure signals.

    Unlike MeanReversionForecaster (which bets on price extremes reverting),
    this forecaster reads the *structure* of the orderbook to infer
    short-term supply/demand shifts.
    """

    @property
    def forecaster_id(self) -> str:
        return "orderbook_micro"

    def predict(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float = 0.0,
        open_interest: float = 0.0,
        minutes_to_expiry: Optional[float] = None,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        category: Optional[str] = None,
        **kwargs,
    ) -> Optional[ForecastResult]:
        """Generate a probability forecast from orderbook microstructure."""
        if implied_yes <= 0.01 or implied_yes >= 0.99:
            return None

        components: Dict[str, float] = {}
        adjustments: List[float] = []

        # ── 1. Bid/Ask Imbalance ────────────────────────────────────
        imbalance = self._bid_ask_imbalance(bid, ask, kwargs)
        components["bid_ask_imbalance"] = imbalance
        if abs(imbalance) > 0.05:
            adjustments.append(imbalance * 0.06)  # ±6% max

        # ── 2. Spread Compression ───────────────────────────────────
        spread_signal = self._spread_compression(market_id, bid, ask)
        components["spread_compression"] = spread_signal
        if abs(spread_signal) > 0.01:
            adjustments.append(spread_signal * 0.03)  # ±3% max

        # ── 3. Depth-Weighted Fair Value ────────────────────────────
        dwfv_shift = self._depth_weighted_fv(bid, ask, kwargs)
        components["dwfv_shift"] = dwfv_shift
        if abs(dwfv_shift) > 0.01:
            adjustments.append(dwfv_shift * 0.04)  # ±4% max

        # ── 4. Trade Flow Imbalance ─────────────────────────────────
        flow = kwargs.get("trade_flow_imbalance", 0.0)
        components["trade_flow"] = float(flow)
        if abs(flow) > 0.1:
            adjustments.append(float(flow) * 0.03)

        # ── Combine ─────────────────────────────────────────────────
        if not adjustments:
            return None  # No signal

        total_adj = sum(adjustments)
        total_adj = max(-0.08, min(0.08, total_adj))  # Clamp ±8%
        components["total_adjustment"] = total_adj

        p_model = implied_yes + total_adj
        p_model = max(0.02, min(0.98, p_model))

        # Confidence: higher when multiple signals agree
        n_active = len([a for a in adjustments if abs(a) > 0.005])
        confidence = min(0.85, 0.15 + n_active * 0.2)

        # Lower confidence when spread is wide (noisy signal)
        if bid is not None and ask is not None:
            spread = ask - bid
            if spread > 0.10:
                confidence *= 0.6
            elif spread > 0.05:
                confidence *= 0.8

        edge_estimate = abs(p_model - implied_yes) * 100
        components["edge_estimate"] = round(edge_estimate, 2)

        return ForecastResult(
            forecaster_id=self.forecaster_id,
            p_model=round(p_model, 4),
            confidence=round(max(0.05, confidence), 3),
            components=components,
        )

    def _bid_ask_imbalance(
        self,
        bid: Optional[float],
        ask: Optional[float],
        kwargs: Dict,
    ) -> float:
        """Compute bid/ask depth imbalance.

        Positive = bid-heavy (bullish), negative = ask-heavy (bearish).
        Uses top-of-book depth if available, else infers from bid/ask prices.
        """
        bid_depth = kwargs.get("bid_depth", 0)
        ask_depth = kwargs.get("ask_depth", 0)

        if bid_depth > 0 and ask_depth > 0:
            total = bid_depth + ask_depth
            return (bid_depth - ask_depth) / total  # -1 to +1

        # Fallback: use bid/ask distance from mid as proxy
        if bid is not None and ask is not None and ask > bid:
            mid = (bid + ask) / 2
            bid_dist = mid - bid
            ask_dist = ask - mid
            if bid_dist + ask_dist > 0:
                # Tighter bid = more bid pressure (bullish)
                return (ask_dist - bid_dist) / (bid_dist + ask_dist)

        return 0.0

    def _spread_compression(
        self,
        market_id: str,
        bid: Optional[float],
        ask: Optional[float],
    ) -> float:
        """Detect spread narrowing (convergence signal).

        Narrowing spread → market is agreeing on fair value → trend continuation.
        Widening spread → uncertainty → mean reversion likely.
        """
        if bid is None or ask is None:
            return 0.0

        spread = ask - bid
        history = _spread_history[market_id]
        history.append(spread)
        if len(history) > _MAX_SPREAD_HISTORY:
            history[:] = history[-_MAX_SPREAD_HISTORY:]

        if len(history) < 3:
            return 0.0

        avg_spread = sum(history) / len(history)
        if avg_spread <= 0:
            return 0.0

        # Compression ratio: < 1 = narrowing, > 1 = widening
        ratio = spread / avg_spread
        if ratio < 0.7:
            return 0.5  # Strong compression → convergence
        elif ratio < 0.9:
            return 0.2  # Mild compression
        elif ratio > 1.3:
            return -0.3  # Widening → uncertainty
        return 0.0

    def _depth_weighted_fv(
        self,
        bid: Optional[float],
        ask: Optional[float],
        kwargs: Dict,
    ) -> float:
        """Compute depth-weighted fair value shift from mid.

        If the DWFV is above mid → bullish bias (more bid support below).
        If below mid → bearish bias.
        """
        bid_depth = kwargs.get("bid_depth", 0)
        ask_depth = kwargs.get("ask_depth", 0)

        if bid is None or ask is None:
            return 0.0
        if bid_depth <= 0 and ask_depth <= 0:
            return 0.0

        total_depth = bid_depth + ask_depth
        if total_depth <= 0:
            return 0.0

        # DWFV = depth-weighted average of bid and ask
        dwfv = (bid * bid_depth + ask * ask_depth) / total_depth
        mid = (bid + ask) / 2

        if mid <= 0:
            return 0.0

        # Shift as fraction of spread
        spread = ask - bid
        if spread <= 0:
            return 0.0

        shift = (dwfv - mid) / spread  # -0.5 to +0.5 range
        return max(-1.0, min(1.0, shift * 2))  # Normalize to -1..+1
