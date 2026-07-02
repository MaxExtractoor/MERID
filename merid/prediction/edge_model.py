"""Edge Model — Unified probability estimation for the /edge API.

Combines multiple signal sources to produce a fair probability estimate
for each Kalshi market:

1. **Spot-relative model** (crypto): Uses live spot price vs strike to
   derive a probability using distance-from-strike + vol adjustment.
   IMPORTANT: These spot feeds (CoinGecko/Coinbase/Binance) are PROXIES
   for market context, NOT the CF Benchmarks RTIs that Kalshi uses for
   settlement. Coinbase may be one constituent of some CF Benchmarks
   indices, but these spot prices should not be equated with settlement.
2. **Spread-based heuristic**: Tighter spread → higher confidence in the
   mid-price as fair value, with slight mean-reversion bias.
3. **Volume/OI signal**: Higher volume and OI increase confidence.

The ``predict()`` method returns ``{"probability": float, "confidence": float}``
which the ``/edge`` endpoint consumes per market.

Reference: https://www.cfbenchmarks.com/blog/kalshi-leads-surging-crypto-event-contract-market-powered-by-cf-benchmarks
"""

from __future__ import annotations

import threading
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from utils.logger import get_logger

from merid.event_venues.kalshi.constants import ALL_CRYPTO_ASSETS
from merid.event_venues.kalshi.invariants import clamp_probability
from merid.prediction.model import pm_spot_feed_symbol_candidates

logger = get_logger("merid.prediction.edge_model")

# Perp feature keys in ``_perp_features`` use lowercase asset slug (extend when API adds alts).
_ASSET_PERP_SLUG = {
    "BTC": "btc",
    "ETH": "eth",
    "SOL": "sol",
    "XRP": "xrp",
    "DOGE": "doge",
}


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

        # D5/E4/F5: lazy-cached context snapshots (set by _refresh_context_cache)
        self._macro_features: Optional[Dict[str, float]] = None
        self._perp_features: Optional[Dict[str, float]] = None
        self._finnhub_features: Optional[Dict[str, float]] = None
        self._polygon_features: Optional[Dict[str, float]] = None
        self._trends_features: Optional[Dict[str, float]] = None
        self._hurricane_features: Optional[Dict[str, float]] = None
        self._news_features: Optional[Dict[str, float]] = None
        self._av_features: Optional[Dict[str, float]] = None
        self._fg_features: Optional[Dict[str, float]] = None
        self._messari_features: Optional[Dict[str, float]] = None
        self._coingecko_features: Optional[Dict[str, float]] = None
        self._cmc_features: Optional[Dict[str, float]] = None
        self._macro_loaded_at: float = 0.0
        self._perp_loaded_at: float = 0.0
        self._finnhub_loaded_at: float = 0.0
        self._polygon_loaded_at: float = 0.0
        self._trends_loaded_at: float = 0.0
        self._hurricane_loaded_at: float = 0.0
        self._news_loaded_at: float = 0.0
        self._av_loaded_at: float = 0.0
        self._fg_loaded_at: float = 0.0
        self._messari_loaded_at: float = 0.0
        self._coingecko_loaded_at: float = 0.0
        self._cmc_loaded_at: float = 0.0
        self._CONTEXT_TTL = 120.0  # refresh context every 2 minutes

        # BUG-SC1 fix: eagerly trigger initial context load to avoid staleness
        try:
            self._refresh_context_cache()
        except Exception as _init_exc:
            logger.debug("EdgeModel: initial context refresh deferred: %s", _init_exc)

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
                    # CRITICAL: Use window_strike_price from market state for 15m markets
                    # This is the dual-source captured strike (Kalshi's floor_strike at window start)
                    # Falls back to catalog strike_price if window_strike not available
                    if hasattr(cm, 'market_state') and cm.market_state:
                        window_strike = getattr(cm.market_state, 'window_strike_price', None)
                        if window_strike is not None and window_strike > 0:
                            strike_price = window_strike
                            logger.debug(
                                "[EDGE-MODEL] ticker=%s using window_strike_price=%.2f (dual-source capture)",
                                ticker, strike_price
                            )
                        else:
                            strike_price = cm.strike_price if hasattr(cm, 'strike_price') else None
                    else:
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

        # ── Signal 4: Cross-venue context (macro + perp) ─────────────────
        self._refresh_context_cache()
        context_adj, context_conf = self._context_signal(
            implied_prob, asset, ticker
        )
        if context_adj is not None and context_conf > 0.05:
            w = context_conf * 0.5   # context is a light nudge, not dominant
            weighted_prob += context_adj * w
            total_weight += w
            components["context"] = context_adj

        if total_weight > 0:
            fair_prob = weighted_prob / total_weight
        else:
            # No signals — return None (caller will use heuristic)
            return None

        # Clamp using centralized invariant (single source of truth for probability bounds)
        fair_prob = clamp_probability(fair_prob)

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
        price_data = None
        if self._price_feed:
            for sym in pm_spot_feed_symbol_candidates(asset):
                price_data = self._price_feed.get_current_price(sym)
                if price_data:
                    break
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
            "15m": 0.003,    # ~0.3% expected move in 15 min
            "1h": 0.008,     # ~0.8% in 1 hour
            "daily": 0.025,  # ~2.5% in a day
            "weekly": 0.06,  # ~6% in a week
            "monthly": 0.12, # ~12% in a month (≈weekly×√4.3)
            "annual": 0.35,  # ~35% in a year (≈monthly×√12)
        }
        vol_scale = vol_map.get(timeframe or "1h", 0.008)

        # Adjust vol by time remaining (sqrt-time scaling)
        if minutes_to_expiry is not None and minutes_to_expiry > 0:
            # If less time remains, tighter distribution
            base_minutes = {
                "15m": 15,
                "1h": 60,
                "daily": 1440,
                "weekly": 10080,
                "monthly": 43200,   # 30 days
                "annual": 525600,   # 365 days
            }
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
        _ts = price_data.timestamp
        if getattr(_ts, "tzinfo", None) is None:
            _ts_naive = _ts
        else:
            _ts_naive = _ts.astimezone(timezone.utc).replace(tzinfo=None)
        _now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        age_seconds = (_now_naive - _ts_naive).total_seconds()
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
        return clamp_probability(adjusted)

    # ── D5: Cross-venue context helpers ──────────────────────────────────────

    def _refresh_context_cache(self) -> None:
        """Fire-and-forget background refresh of macro + perp feature caches.

        Uses cached snapshots synchronously; schedules async refresh if stale.
        Never blocks the calling thread.
        """
        import asyncio, threading
        now = datetime.now(timezone.utc).timestamp()

        def _run_refresh():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

                async def _fetch_all():
                    feats: dict = {}
                    try:
                        from merid.prediction.macro_context import get_macro_context_service
                        snap = await get_macro_context_service().get_snapshot()
                        feats["macro"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: macro context unavailable: %s", exc)
                    try:
                        from merid.prediction.perp_context import get_perp_context_service
                        snap = await get_perp_context_service().get_snapshot()
                        feats["perp"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: perp context unavailable: %s", exc)
                    try:
                        from merid.prediction.finnhub_context import get_finnhub_context_service
                        snap = await get_finnhub_context_service().get_snapshot()
                        feats["finnhub"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: finnhub context unavailable: %s", exc)
                    try:
                        from merid.prediction.polygon_context import get_polygon_context_service
                        snap = await get_polygon_context_service().get_snapshot()
                        feats["polygon"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: polygon context unavailable: %s", exc)
                    try:
                        from merid.prediction.trends_context import get_trends_context_service
                        snap = await get_trends_context_service().get_snapshot()
                        feats["trends"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: trends context unavailable: %s", exc)
                    try:
                        from merid.prediction.hurricane_context import get_hurricane_context_service
                        snap = await get_hurricane_context_service().get_snapshot()
                        feats["hurricane"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: hurricane context unavailable: %s", exc)
                    try:
                        from merid.prediction.news_context import get_news_context_service
                        snap = await get_news_context_service().get_snapshot()
                        feats["news"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: news context unavailable: %s", exc)
                    try:
                        from merid.prediction.alphavantage_context import get_alphavantage_context_service
                        snap = await get_alphavantage_context_service().get_snapshot()
                        feats["av"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: alphavantage context unavailable: %s", exc)
                    try:
                        from merid.prediction.fear_greed_context import get_fear_greed_context_service
                        snap = await get_fear_greed_context_service().get_snapshot()
                        feats["fg"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: fear/greed context unavailable: %s", exc)
                    try:
                        from merid.prediction.messari_context import get_messari_context_service
                        snap = await get_messari_context_service().get_snapshot()
                        feats["messari"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: messari context unavailable: %s", exc)
                    try:
                        from merid.prediction.coingecko_context import get_coingecko_context_service
                        snap = await get_coingecko_context_service().get_snapshot()
                        feats["coingecko"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: coingecko context unavailable: %s", exc)
                    try:
                        from merid.prediction.coinmarketcap_context import get_cmc_context_service
                        snap = await get_cmc_context_service().get_snapshot()
                        feats["cmc"] = snap.to_edge_features()
                    except Exception as exc:
                        logger.debug("edge_model: cmc context unavailable: %s", exc)
                    return feats

                result = loop.run_until_complete(_fetch_all())
                loop.close()
                if "macro" in result:
                    self._macro_features = result["macro"]
                    self._macro_loaded_at = now
                if "perp" in result:
                    self._perp_features = result["perp"]
                    self._perp_loaded_at = now
                if "finnhub" in result:
                    self._finnhub_features = result["finnhub"]
                    self._finnhub_loaded_at = now
                if "polygon" in result:
                    self._polygon_features = result["polygon"]
                    self._polygon_loaded_at = now
                if "trends" in result:
                    self._trends_features = result["trends"]
                    self._trends_loaded_at = now
                if "hurricane" in result:
                    self._hurricane_features = result["hurricane"]
                    self._hurricane_loaded_at = now
                if "news" in result:
                    self._news_features = result["news"]
                    self._news_loaded_at = now
                if "av" in result:
                    self._av_features = result["av"]
                    self._av_loaded_at = now
                if "fg" in result:
                    self._fg_features = result["fg"]
                    self._fg_loaded_at = now
                if "messari" in result:
                    self._messari_features = result["messari"]
                    self._messari_loaded_at = now
                if "coingecko" in result:
                    self._coingecko_features = result["coingecko"]
                    self._coingecko_loaded_at = now
                if "cmc" in result:
                    self._cmc_features = result["cmc"]
                    self._cmc_loaded_at = now
            except Exception as exc:
                logger.debug("EdgeModel: context refresh failed: %s", exc)

        _ts_attrs = [
            "_macro_loaded_at", "_perp_loaded_at", "_finnhub_loaded_at",
            "_polygon_loaded_at", "_trends_loaded_at",
            "_hurricane_loaded_at", "_news_loaded_at",
            "_av_loaded_at", "_fg_loaded_at", "_messari_loaded_at",
            "_coingecko_loaded_at", "_cmc_loaded_at",
        ]
        stale = any(
            (now - getattr(self, a, 0.0)) > self._CONTEXT_TTL
            for a in _ts_attrs
        )
        if stale:
            threading.Thread(target=_run_refresh, daemon=True).start()

    def _context_signal(
        self,
        implied_prob: float,
        asset: Optional[str],
        ticker: str,
    ) -> tuple:
        """Compute a context-adjusted probability nudge from macro + perp + regime features.

        Rules (all additive nudges, capped at ±0.08 total):
          - High VIX (>25)        → pull toward 0.5 (more uncertainty)
          - Inverted curve        → bearish crypto tilt (lower prob for BTC/ETH YES)
          - High CPI momentum     → hawkish environment → slight crypto bearish
          - Strong positive fund  → crowded longs → slight mean-reversion
          - High IV               → widen uncertainty → pull toward 0.5
          - Regime-aware          → adjust edge threshold based on execution regime

        Returns (adjusted_prob, confidence).  confidence = 0 if no features loaded.
        """
        macro   = getattr(self, "_macro_features",     None) or {}
        perp    = getattr(self, "_perp_features",      None) or {}
        fh      = getattr(self, "_finnhub_features",   None) or {}
        poly    = getattr(self, "_polygon_features",   None) or {}
        news    = getattr(self, "_news_features",      None) or {}
        trend   = getattr(self, "_trends_features",    None) or {}
        hurr    = getattr(self, "_hurricane_features", None) or {}
        av       = getattr(self, "_av_features",         None) or {}
        fg       = getattr(self, "_fg_features",         None) or {}
        messari  = getattr(self, "_messari_features",    None) or {}
        coingecko = getattr(self, "_coingecko_features", None) or {}
        cmc       = getattr(self, "_cmc_features",        None) or {}

        # ── Unified Regime Integration (regime/anomaly/momentum stacks) ───────
        unified_regime = None
        try:
            from merid.signals.unified_regime_classifier import get_unified_regime_classifier
            classifier = get_unified_regime_classifier()
            unified_regime = classifier.get_current_state()
        except Exception as _regime_exc:
            logger.debug("edge_model: unified regime classifier unavailable: %s", _regime_exc)

        if not any([macro, perp, fh, poly, news, trend, hurr, av, fg, messari, coingecko, cmc, unified_regime]):
            return None, 0.0

        nudge = 0.0
        signals_fired = 0

        # ── Macro signals ─────────────────────────────────────────────────────
        vix = macro.get("macro_vix", 0.0)
        if vix > 25.0:
            pull = min(0.03, (vix - 25.0) / 100.0)
            nudge += pull * (0.5 - implied_prob)   # toward 0.5
            signals_fired += 1

        inverted = macro.get("macro_inverted_curve", 0.0)
        au = asset.upper() if asset else ""
        is_crypto = bool(asset and au in ALL_CRYPTO_ASSETS)
        if inverted > 0.5 and is_crypto:
            nudge -= 0.015   # mild bearish on crypto YES in inverted regime
            signals_fired += 1

        cpi_momentum = macro.get("macro_cpi_momentum", 0.0)
        if cpi_momentum > 0.3 and is_crypto:   # accelerating inflation
            nudge -= 0.01
            signals_fired += 1

        # BLS release proximity: widen uncertainty within 1 day of major release
        release_days = macro.get("macro_release_days_away", 99.0)
        if release_days <= 1.0:
            nudge += 0.02 * (0.5 - implied_prob)
            signals_fired += 1

        # ── Perp signals ──────────────────────────────────────────────────────
        if is_crypto:
            symbol_key = _ASSET_PERP_SLUG.get(au, "btc")
            funding = perp.get(f"{symbol_key}_funding_rate", 0.0)
            iv      = perp.get(f"{symbol_key}_iv_30d", 0.0)

            # Strongly positive funding → crowded longs → mean-revert YES prob
            if funding > 0.0005:
                nudge -= min(0.02, funding * 20)
                signals_fired += 1
            elif funding < -0.0005:
                nudge += min(0.02, abs(funding) * 20)
                signals_fired += 1

            # High IV → binary uncertain → pull toward 0.5
            if iv > 0.80:
                nudge += 0.015 * (0.5 - implied_prob)
                signals_fired += 1

        # ── Signal 5: Finnhub sentiment + release imminence ──────────────────
        if fh:
            # Imminent high-impact release → pull toward 0.5 (uncertainty)
            nearest_release = fh.get("fh_nearest_release_days", 99.0)
            if nearest_release <= 0.5:
                nudge += 0.025 * (0.5 - implied_prob)
                signals_fired += 1

            # Macro surprise direction: hot print → bearish crypto
            macro_surprise = fh.get("fh_macro_surprise", 0.0)
            if abs(macro_surprise) > 0.15 and is_crypto:
                nudge -= macro_surprise * 0.05   # hot = negative, miss = positive
                signals_fired += 1

            # SPY sentiment as risk-on/risk-off proxy for crypto
            spy_bull = fh.get("fh_spy_bullish_pct", 0.5)
            if spy_bull > 0.65 and is_crypto:
                nudge += 0.01    # risk-on → slightly favour crypto YES
                signals_fired += 1
            elif spy_bull < 0.35 and is_crypto:
                nudge -= 0.01    # risk-off → slightly bearish crypto
                signals_fired += 1

            # Crypto-specific news sentiment
            crypto_bull = fh.get("fh_crypto_bullish_pct", 0.5)
            if crypto_bull > 0.65 and is_crypto:
                nudge += 0.015
                signals_fired += 1
            elif crypto_bull < 0.35 and is_crypto:
                nudge -= 0.015
                signals_fired += 1

        # ── Signal 6: Polygon equity momentum + News + Trends ────────────────

        if poly:
            regime = poly.get("poly_risk_on", 0.0) - poly.get("poly_risk_off", 0.0)
            pcr    = poly.get("poly_pcr", 1.0)

            # Risk-on (SPY above MA20, strong 5d return) → favour crypto YES
            if regime > 0.5 and is_crypto:
                nudge += 0.012
                signals_fired += 1
            elif regime < -0.5 and is_crypto:
                nudge -= 0.012
                signals_fired += 1

            # High PCR (put buying = fear) → pull toward 0.5 uncertainty
            if pcr > 1.3:
                nudge += 0.01 * (0.5 - implied_prob)
                signals_fired += 1

        if news:
            # Crypto news net sentiment
            crypto_net = news.get("news_crypto_net", 0.0)
            if abs(crypto_net) > 0.15 and is_crypto:
                nudge += crypto_net * 0.06
                signals_fired += 1
            # Macro bearish news → general risk-off nudge
            if news.get("news_macro_bearish", 0.0) > 0.5 and is_crypto:
                nudge -= 0.008
                signals_fired += 1

        if trend:
            # Search spike for risk/crash terms → uncertainty → pull toward 0.5
            risk_spike = trend.get("trends_risk_spike", 1.0)
            if risk_spike > 2.0:
                nudge += 0.015 * (0.5 - implied_prob)
                signals_fired += 1
            # Crypto search spike → retail FOMO → contrarian bearish nudge
            crypto_spike = trend.get("trends_crypto_spike", 1.0)
            if crypto_spike > 2.5 and is_crypto:
                nudge -= 0.01   # contrarian: retail FOMO → mean revert
                signals_fired += 1

        # ── Signal 7: Hurricane FL threat ────────────────────────────────────
        if hurr:
            peak_threat = hurr.get("hurr_peak_threat", 0.0)
            fl_alerts   = hurr.get("hurr_fl_alerts", 0.0)
            # Active FL hurricane threat → widen uncertainty on all markets
            if peak_threat > 0.3 or fl_alerts > 0:
                nudge += 0.02 * (0.5 - implied_prob)
                signals_fired += 1

        # ── Signal 8: Fear/Greed (contrarian), Messari dominance, AV GDP ────

        if fg:
            contrarian = fg.get("fg_contrarian", 0.0)
            if abs(contrarian) > 0.01 and is_crypto:
                nudge += contrarian          # ±0.05 at extremes
                signals_fired += 1
            # Extreme greed + rising trend → extra caution
            if fg.get("fg_extreme_greed", 0.0) > 0.5 and fg.get("fg_trend_rising", 0.0) > 0.5:
                nudge -= 0.01
                signals_fired += 1

        if messari and is_crypto:
            # High BTC dominance → alt selloff → slightly bearish non-BTC
            btc_dom_high = messari.get("messari_btc_dom_high", 0.0)
            if btc_dom_high > 0.5 and asset and au not in ("BTC",):
                nudge -= 0.01
                signals_fired += 1
            # Strong BTC/ETH 7d momentum → risk-on
            btc_7d = messari.get("messari_btc_7d", 0.0)
            eth_7d = messari.get("messari_eth_7d", 0.0)
            if btc_7d >= 5.0 and eth_7d >= 5.0:
                nudge += 0.01
                signals_fired += 1
            elif btc_7d < -5.0:
                nudge -= 0.01
                signals_fired += 1

        if av:
            # Decelerating GDP → macro headwind → mild bearish on crypto
            if av.get("av_gdp_trend", 0.0) < -0.5 and is_crypto:
                nudge -= 0.008
                signals_fired += 1
            # Strong tech sector momentum → risk-on lift
            tech_1m = av.get("av_tech_ret_1m", 0.0)
            if tech_1m > 3.0 and is_crypto:
                nudge += 0.008
                signals_fired += 1
            elif tech_1m < -3.0 and is_crypto:
                nudge -= 0.008
                signals_fired += 1

        # ── Signal 9: CoinGecko global market metrics ────────────────────
        if coingecko and is_crypto:
            mkt_chg = coingecko.get("cg_market_change_24h", 0.0)
            if coingecko.get("cg_market_expanding", 0.0) > 0.5:
                nudge += 0.008
                signals_fired += 1
            elif coingecko.get("cg_market_contracting", 0.0) > 0.5:
                nudge -= 0.008
                signals_fired += 1
            # Alt season: BTC dominance falling, alts outperforming
            if coingecko.get("cg_alt_season", 0.0) > 0.5:
                if asset and au not in ("BTC",):
                    nudge += 0.008    # altcoin YES markets in alt season
                    signals_fired += 1
            # Extreme top-gainer (FOMO regime) → contrarian caution
            top_gainer = coingecko.get("cg_top_gainer", 0.0)
            if top_gainer > 30.0:
                nudge -= 0.008   # single coin FOMO → mean reversion likely
                signals_fired += 1

        # ── Signal 10: CoinMarketCap gainers/losers + concentration ────────────
        if cmc and is_crypto:
            # FOMO regime (many coins up >20%) → contrarian bearish
            if cmc.get("cmc_fomo", 0.0) > 0.5:
                nudge -= 0.01
                signals_fired += 1
            # Panic regime (many coins down >20%) → contrarian bullish
            if cmc.get("cmc_panic", 0.0) > 0.5:
                nudge += 0.01
                signals_fired += 1
            # Concentrated market (top-10 > 70%) → higher alt risk
            if cmc.get("cmc_concentrated", 0.0) > 0.5 and asset and au not in ("BTC", "ETH"):
                nudge -= 0.008
                signals_fired += 1
            # High volume ratio → healthy liquidity → slight risk-on
            if cmc.get("cmc_vol_ratio", 0.0) > 0.08:
                nudge += 0.005
                signals_fired += 1

        # ── Signal 11: Unified Regime (regime/anomaly/momentum stacks) ───────────
        if unified_regime and is_crypto:
            # Execution regime adjustments
            if unified_regime.is_defensive:
                # Defensive regime: pull toward 0.5 (more uncertainty)
                nudge += 0.015 * (0.5 - implied_prob)
                signals_fired += 1
            elif unified_regime.is_aggressive:
                # Aggressive regime: slight boost to directional conviction
                if implied_prob > 0.6:
                    nudge += 0.005
                elif implied_prob < 0.4:
                    nudge -= 0.005
                signals_fired += 1

            # Momentum leader adjustment
            if unified_regime.momentum_leader and asset:
                # Favor momentum leader, penalize laggards
                if au == unified_regime.momentum_leader:
                    nudge += 0.008
                elif unified_regime.momentum_avg_score > 0.05:
                    # Positive momentum environment, slight boost to all
                    nudge += 0.003
                signals_fired += 1

            # BTC anchor regime
            if unified_regime.btc_trending and asset and au != "BTC":
                # BTC trending: slight adjustment to alts based on BTC direction
                btc_regime = unified_regime.btc_regime
                if "bull" in btc_regime.lower():
                    nudge += 0.003  # risk-on lift for alts
                elif "bear" in btc_regime.lower():
                    nudge -= 0.003  # risk-off drag on alts
                signals_fired += 1

        if signals_fired == 0:
            return None, 0.0

        # Cap total nudge at ±0.08 to prevent context from overriding market price
        nudge = max(-0.08, min(0.08, nudge))
        adjusted = clamp_probability(implied_prob + nudge)
        confidence = min(0.4, 0.05 * signals_fired)   # max 0.4 so it never dominates
        return adjusted, confidence

    def clear_cache(self):
        """Clear the prediction cache."""
        self._prediction_cache.clear()
        self._cache_ts.clear()


# ── Singleton ────────────────────────────────────────────────────────────
# Singleton instance
_instance: Optional[EdgeModel] = None
_instance_lock = None


def get_edge_model() -> EdgeModel:
    """Get or create the singleton EdgeModel instance."""
    global _instance
    if _instance is None:
        if _instance_lock is not None:
            with _instance_lock:
                if _instance is None:
                    _instance = EdgeModel()
        else:
            _instance = EdgeModel()
    return _instance
