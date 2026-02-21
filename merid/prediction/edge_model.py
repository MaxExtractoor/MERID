"""Edge Model — Unified probability estimation for the /edge API.

Combines multiple signal sources to produce a fair probability estimate
for each Kalshi market:

1. **Spot-relative model** (crypto): Uses live spot price vs strike to
   derive a probability using distance-from-strike + vol adjustment.
2. **Spread-based heuristic**: Tighter spread → higher confidence in the
   mid-price as fair value, with slight mean-reversion bias.
3. **Volume/OI signal**: Higher volume and OI increase confidence.

The ``predict()`` method returns ``{"probability": float, "confidence": float}``
which the ``/edge`` endpoint consumes per market.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.edge_model")


@dataclass
class EdgePrediction:
    """Result of an edge model prediction."""
    probability: float      # 0.0–1.0 fair probability estimate
    confidence: float       # 0.0–1.0 signal confidence
    source: str             # Which model produced this: "spot", "spread", "ensemble"
    components: Dict[str, float]  # Breakdown of contributing signals


class EdgeModel:
    """Multi-source edge model for Kalshi markets.

    Provides ``predict(ticker, asset, timeframe)`` returning a probability
    and confidence estimate that can be compared against the market-implied
    probability to compute EV.
    """

    def __init__(self):
        self._price_feed = None
        self._vol_cache: Dict[str, float] = {}
        self._prediction_cache: Dict[str, EdgePrediction] = {}
        self._cache_ttl_s = 15.0  # cache predictions for 15s
        self._cache_ts: Dict[str, float] = {}

        # Try to connect to live price feed
        try:
            from data.live_price_feed import get_live_price_feed
            self._price_feed = get_live_price_feed()
        except (ImportError, Exception):
            self._price_feed = None

        # Try to load market catalog for strike prices
        self._catalog = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            self._catalog = get_market_catalog()
        except (ImportError, Exception):
            pass

    def predict(
        self,
        ticker: str,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Predict fair probability for a Kalshi market.

        Args:
            ticker: Kalshi market ticker (e.g. KXBTC-26FEB15-1H-T95000).
            asset: Underlying asset (BTC, ETH, SOL, etc.).
            timeframe: Market timeframe (15m, 1h, daily).

        Returns:
            Dict with ``probability`` (float 0-1) and ``confidence`` (float 0-1),
            or None if no prediction can be made.
        """
        now = datetime.now(timezone.utc).timestamp()

        # Check cache
        if ticker in self._prediction_cache:
            age = now - self._cache_ts.get(ticker, 0)
            if age < self._cache_ttl_s:
                pred = self._prediction_cache[ticker]
                return {"probability": pred.probability, "confidence": pred.confidence}

        # Gather market data from catalog
        strike_price = None
        implied_prob = None
        bid = None
        ask = None
        volume = 0
        minutes_to_expiry = None

        if self._catalog:
            try:
                cm = self._catalog.get_market(ticker)
                if cm:
                    strike_price = cm.strike_price if hasattr(cm, 'strike_price') else None
                    minutes_to_expiry = cm.minutes_to_expiry
                    volume = float(cm.market.volume) if cm.market.volume else 0
                    if cm.market.outcomes:
                        o = cm.market.outcomes[0]
                        implied_prob = float(o.price) if o.price else None
                        bid = float(o.best_bid) if o.best_bid else None
                        ask = float(o.best_ask) if o.best_ask else None
            except Exception as exc:
                logger.debug(f"Catalog lookup failed for {ticker}: {exc}")

        # Default implied if not found
        if implied_prob is None:
            implied_prob = 0.5

        # ── Signal 1: Spot-relative model (crypto only) ──────────────────
        spot_prob = None
        spot_confidence = 0.0

        if asset and self._price_feed and strike_price is not None:
            spot_prob, spot_confidence = self._spot_relative_probability(
                asset, strike_price, timeframe, minutes_to_expiry
            )

        # ── Signal 2: Spread-based model ─────────────────────────────────
        spread_prob, spread_confidence = self._spread_model(
            implied_prob, bid, ask, volume
        )

        # ── Signal 3: Time decay model ───────────────────────────────────
        time_adj = self._time_decay_adjustment(implied_prob, minutes_to_expiry)

        # ── Ensemble: weighted average ───────────────────────────────────
        components: Dict[str, float] = {}
        total_weight = 0.0
        weighted_prob = 0.0

        if spot_prob is not None and spot_confidence > 0.1:
            w = spot_confidence * 3.0  # spot model gets heavy weight when available
            weighted_prob += spot_prob * w
            total_weight += w
            components["spot"] = spot_prob

        if spread_confidence > 0.05:
            w = spread_confidence * 1.0
            weighted_prob += spread_prob * w
            total_weight += w
            components["spread"] = spread_prob

        if time_adj is not None:
            w = 0.3
            weighted_prob += time_adj * w
            total_weight += w
            components["time_decay"] = time_adj

        if total_weight > 0:
            fair_prob = weighted_prob / total_weight
        else:
            # No signals — return None (caller will use heuristic)
            return None

        # Clamp
        fair_prob = max(0.02, min(0.98, fair_prob))

        # Ensemble confidence
        confidence = min(1.0, max(0.0,
            (spot_confidence * 0.5 if spot_prob is not None else 0.0)
            + spread_confidence * 0.3
            + (0.2 if time_adj is not None else 0.0)
        ))

        # Boost confidence if multiple sources agree
        if len(components) >= 2:
            probs = list(components.values())
            agreement = 1.0 - (max(probs) - min(probs))
            confidence = min(1.0, confidence + agreement * 0.1)

        source = "ensemble" if len(components) > 1 else next(iter(components), "unknown")

        pred = EdgePrediction(
            probability=round(fair_prob, 4),
            confidence=round(confidence, 3),
            source=source,
            components=components,
        )
        self._prediction_cache[ticker] = pred
        self._cache_ts[ticker] = now

        return {"probability": pred.probability, "confidence": pred.confidence}

    def _spot_relative_probability(
        self,
        asset: str,
        strike_price: float,
        timeframe: Optional[str],
        minutes_to_expiry: Optional[float],
    ) -> tuple:
        """Derive YES probability from spot price vs strike.

        Uses a logistic function centered on the strike, scaled by
        estimated volatility and time to expiry.

        Returns:
            (probability, confidence) tuple.
        """
        symbol = f"{asset.upper()}/USDT"
        price_data = self._price_feed.get_current_price(symbol) if self._price_feed else None
        if not price_data or not price_data.price or price_data.price <= 0:
            return None, 0.0

        spot = price_data.price
        strike = float(strike_price)
        if strike <= 0:
            return None, 0.0

        # Distance from strike as percentage
        dist_pct = (spot - strike) / strike

        # Estimate volatility scale from timeframe
        vol_map = {
            "15m": 0.003,   # ~0.3% expected move in 15 min
            "1h": 0.008,    # ~0.8% in 1 hour
            "daily": 0.025, # ~2.5% in a day
            "weekly": 0.06, # ~6% in a week
        }
        vol_scale = vol_map.get(timeframe or "1h", 0.008)

        # Adjust vol by time remaining (sqrt-time scaling)
        if minutes_to_expiry is not None and minutes_to_expiry > 0:
            # If less time remains, tighter distribution
            base_minutes = {"15m": 15, "1h": 60, "daily": 1440, "weekly": 10080}
            base = base_minutes.get(timeframe or "1h", 60)
            time_factor = math.sqrt(min(minutes_to_expiry, base) / base)
            vol_scale *= time_factor

        # Logistic function: P(YES) = sigmoid(dist / vol_scale)
        if vol_scale > 0:
            z = dist_pct / vol_scale
            prob_yes = 1.0 / (1.0 + math.exp(-z))
        else:
            prob_yes = 0.5

        # Confidence based on:
        # - Data freshness (how old is the spot price?)
        age_seconds = (datetime.now(timezone.utc) - price_data.timestamp).total_seconds()
        freshness = max(0.0, 1.0 - age_seconds / 120.0)  # decays over 2 min

        # - Bid-ask spread tightness on exchange
        if price_data.bid > 0 and price_data.ask > 0:
            exchange_spread_pct = (price_data.ask - price_data.bid) / price_data.price
            spread_quality = max(0.0, 1.0 - exchange_spread_pct * 100)
        else:
            spread_quality = 0.5

        confidence = freshness * 0.6 + spread_quality * 0.4

        return prob_yes, confidence

    def _spread_model(
        self,
        implied_prob: float,
        bid: Optional[float],
        ask: Optional[float],
        volume: float,
    ) -> tuple:
        """Spread-based fair value model.

        When spread is tight, mid-price is a good estimate.
        Applies slight mean-reversion bias toward 0.5 for extreme prices.

        Returns:
            (probability, confidence) tuple.
        """
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0
            spread = ask - bid

            # Mean-reversion: pull slightly toward 0.5
            reversion_strength = 0.03  # weak bias
            fair = mid + reversion_strength * (0.5 - mid)

            # Confidence from spread tightness and volume
            spread_cents = spread * 100
            if spread_cents <= 2:
                spread_conf = 0.8
            elif spread_cents <= 5:
                spread_conf = 0.5
            elif spread_cents <= 10:
                spread_conf = 0.3
            else:
                spread_conf = 0.1

            # Volume boost
            vol_boost = min(0.2, math.log1p(volume) / 50.0)
            confidence = min(1.0, spread_conf + vol_boost)

            return fair, confidence

        # No bid/ask — very low confidence
        return implied_prob, 0.05

    def _time_decay_adjustment(
        self,
        implied_prob: float,
        minutes_to_expiry: Optional[float],
    ) -> Optional[float]:
        """Adjust probability based on time remaining.

        Near expiry, probabilities become more extreme (closer to 0 or 1).
        Far from expiry, probabilities should be more moderate.

        Returns:
            Adjusted probability, or None if no time info.
        """
        if minutes_to_expiry is None:
            return None

        if minutes_to_expiry <= 0:
            return implied_prob  # expired — trust market

        # In terminal phase (< 5 min), let market price dominate
        if minutes_to_expiry < 5:
            return implied_prob

        # Far from expiry, apply moderate pull toward 0.5
        # The further out, the more uncertain we are
        hours = minutes_to_expiry / 60.0
        uncertainty = min(0.15, hours * 0.01)  # caps at 15% pull

        adjusted = implied_prob + uncertainty * (0.5 - implied_prob)
        return max(0.02, min(0.98, adjusted))

    def clear_cache(self):
        """Clear the prediction cache."""
        self._prediction_cache.clear()
        self._cache_ts.clear()


# ── Singleton ────────────────────────────────────────────────────────────

_instance: Optional[EdgeModel] = None


def get_edge_model() -> EdgeModel:
    """Get or create the singleton EdgeModel instance."""
    global _instance
    if _instance is None:
        _instance = EdgeModel()
    return _instance
