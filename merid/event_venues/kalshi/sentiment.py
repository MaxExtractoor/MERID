"""KalshiSentimentService — Per-market, per-category, and global fear/greed index.

Architecture
------------
The index is a 0–100 score built from four components derived entirely from
Kalshi order-flow and price dynamics (primary), plus an optional external
crypto fear/greed feed (contextual only):

  Component                Weight   Source
  ─────────────────────────────────────────────────────────────────────
  Volatility (prob vol)     30 %    Rolling σ of implied-prob time series
  Volume heat               30 %    Current volume vs trailing baseline
  Order-book imbalance      40 %    (bid_depth − ask_depth) / total_depth
  Model gap (optional)       0 %    |swarm_prob − kalshi_prob| (additive)
  ─────────────────────────────────────────────────────────────────────

Bands
-----
  0–24   extreme_fear
  25–49  fear
  50–74  greed
  75–100 extreme_greed

Usage
-----
    svc = get_sentiment_service()
    svc.update_market("BTC-25FEB-50000", prob=0.42, volume=1200,
                      bid_depth=800, ask_depth=400)
    score = svc.market_score("BTC-25FEB-50000")   # SentimentScore
    cat   = svc.category_score("crypto")           # SentimentScore
    glob  = svc.global_score()                     # SentimentScore
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional

from merid.formulas import (
    AUDIT_SPEC_VERSION,
    COMPONENT_WEIGHTS,
    EXTREME_FEAR_MAX,
    FEAR_MAX,
    FORMULAS_VERSION,
    GREED_MAX,
    book_imbalance,
    generate_correlation_id,
    normalize_vol,
    normalize_volume,
    regime,
    rolling_std,
    score_to_100,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.sentiment")


# ── Constants ─────────────────────────────────────────────────────────────────

VOLATILITY_WINDOW   = 60          # samples kept for rolling σ (≈1 h at 1-min cadence)
VOLUME_BASELINE_WIN = 1440        # samples for volume baseline (≈24 h)

# Band boundaries are canonical — imported from merid.formulas
# (re-exported here for backward compatibility)
__all__ = [
    "KalshiSentimentService",
    "SentimentScore",
    "get_sentiment_service",
    "EXTREME_FEAR_MAX",
    "FEAR_MAX",
    "GREED_MAX",
    "COMPONENT_WEIGHTS",
]

# External fear/greed API (alternative.me — crypto only, contextual)
EXTERNAL_FG_URL = "https://api.alternative.me/fng/?limit=1&format=json"
EXTERNAL_FG_TTL = 3600   # refresh at most once per hour


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class SentimentScore:
    """Fear/greed score for one scope (market / category / global)."""
    score: float                  # 0–100
    regime: str                   # extreme_fear | fear | greed | extreme_greed
    components: Dict[str, float]  # raw 0–1 component values
    sample_count: int             # how many markets contributed
    timestamp: float = field(default_factory=time.time)

    # Optional external contextual signal
    external_score: Optional[float] = None   # 0–100 from alternative.me
    external_regime: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 1),
            "regime": self.regime,
            "components": {k: round(v, 3) for k, v in self.components.items()},
            "sample_count": self.sample_count,
            "timestamp": self.timestamp,
            "external_score": self.external_score,
            "external_regime": self.external_regime,
        }


@dataclass
class _MarketState:
    """Rolling state for one Kalshi market."""
    ticker: str
    category: str = "unknown"

    # Circular buffers
    prob_history: Deque[float] = field(default_factory=lambda: deque(maxlen=VOLATILITY_WINDOW))
    volume_history: Deque[float] = field(default_factory=lambda: deque(maxlen=VOLUME_BASELINE_WIN))

    # Latest snapshot
    last_prob: float = 0.5
    last_volume: float = 0.0
    last_bid_depth: float = 0.0
    last_ask_depth: float = 0.0
    last_model_prob: Optional[float] = None   # swarm/model probability
    last_update: float = field(default_factory=time.time)

    # Cached component scores (0–1)
    vol_score: float = 0.5
    volume_score: float = 0.5
    imbal_score: float = 0.5
    composite: float = 50.0       # 0–100


# ── Private shims (delegate to merid.formulas — do NOT add math here) ─────────

def _regime(score: float) -> str:
    return regime(score)


def _rolling_std(buf: "Deque[float]") -> float:
    return rolling_std(buf)


def _normalize_vol(sigma: float, baseline_sigma: float) -> float:
    return normalize_vol(sigma, baseline_sigma)


def _normalize_volume(current: float, baseline: float) -> float:
    return normalize_volume(current, baseline)


def _book_imbalance(bid: float, ask: float) -> float:
    return book_imbalance(bid, ask)


def _score_to_100(vol: float, volume: float, imbal: float) -> float:
    return score_to_100(vol, volume, imbal)


# ── Service ───────────────────────────────────────────────────────────────────

class KalshiSentimentService:
    """Computes and caches fear/greed scores at market, category, and global level.

    Thread-safe for reads; updates are serialised via asyncio (single-threaded
    event loop) or a lock for sync callers.
    """

    def __init__(self) -> None:
        self._markets: Dict[str, _MarketState] = {}

        # Category → list of tickers
        self._category_tickers: Dict[str, List[str]] = {}

        # Cached aggregate scores
        self._category_scores: Dict[str, SentimentScore] = {}
        self._global_score: Optional[SentimentScore] = None

        # External fear/greed cache
        self._ext_score: Optional[float] = None
        self._ext_regime: Optional[str] = None
        self._ext_fetched_at: float = 0.0

        # Background refresh task
        self._task: Optional[asyncio.Task] = None
        self._running = False

        logger.info("KalshiSentimentService initialised")

    # ── Public update API ─────────────────────────────────────────────────────

    def update_market(
        self,
        ticker: str,
        *,
        prob: float,
        volume: float,
        bid_depth: float = 0.0,
        ask_depth: float = 0.0,
        category: str = "unknown",
        model_prob: Optional[float] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        """Ingest a new data point for one market and recompute its score."""
        corr_id = correlation_id or generate_correlation_id()

        if ticker not in self._markets:
            self._markets[ticker] = _MarketState(ticker=ticker, category=category)
            if category not in self._category_tickers:
                self._category_tickers[category] = []
            if ticker not in self._category_tickers[category]:
                self._category_tickers[category].append(ticker)
            logger.debug(
                "[TRACE] stage=ANALYZE action=market_registered ticker=%s "
                "category=%s corr_id=%s formulas_ver=%s audit_spec_ver=%s",
                ticker, category, corr_id, FORMULAS_VERSION, AUDIT_SPEC_VERSION,
            )

        state = self._markets[ticker]
        state.category = category
        state.last_prob = prob
        state.last_volume = volume
        state.last_bid_depth = bid_depth
        state.last_ask_depth = ask_depth
        state.last_model_prob = model_prob
        state.last_update = time.time()

        # Append to rolling buffers
        state.prob_history.append(prob)
        state.volume_history.append(volume)

        # Recompute components (all math delegated to merid.formulas)
        sigma = _rolling_std(state.prob_history)
        baseline_sigma = _rolling_std(deque(list(state.prob_history)[-30:], maxlen=30)) or 0.01

        vol_score    = _normalize_vol(sigma, baseline_sigma)
        volume_score = _normalize_volume(volume, self._volume_baseline(state))
        imbal_score  = _book_imbalance(bid_depth, ask_depth)

        state.vol_score    = vol_score
        state.volume_score = volume_score
        state.imbal_score  = imbal_score
        state.composite    = _score_to_100(vol_score, volume_score, imbal_score)

        logger.debug(
            "[TRACE] stage=ANALYZE action=score_updated ticker=%s "
            "composite=%.1f regime=%s vol=%.3f volume=%.3f imbal=%.3f "
            "corr_id=%s",
            ticker, state.composite, _regime(state.composite),
            vol_score, volume_score, imbal_score, corr_id,
        )

        # Invalidate aggregate caches
        self._category_scores.pop(category, None)
        self._global_score = None

    def _volume_baseline(self, state: _MarketState) -> float:
        """Mean of the volume history as baseline."""
        if not state.volume_history:
            return 1.0
        return sum(state.volume_history) / len(state.volume_history)

    # ── Score accessors ───────────────────────────────────────────────────────

    def market_score(self, ticker: str) -> Optional[SentimentScore]:
        """Return the latest SentimentScore for one market, or None if unknown."""
        state = self._markets.get(ticker)
        if state is None:
            return None
        return SentimentScore(
            score=state.composite,
            regime=_regime(state.composite),
            components={
                "volatility":  state.vol_score,
                "volume_heat": state.volume_score,
                "book_imbal":  state.imbal_score,
            },
            sample_count=1,
            external_score=self._ext_score,
            external_regime=self._ext_regime,
        )

    def category_score(self, category: str) -> SentimentScore:
        """Volume-weighted average score across all markets in a category."""
        cached = self._category_scores.get(category)
        if cached is not None:
            return cached

        tickers = self._category_tickers.get(category, [])
        states  = [self._markets[t] for t in tickers if t in self._markets]

        if not states:
            return SentimentScore(
                score=50.0, regime="greed", components={}, sample_count=0,
                external_score=self._ext_score, external_regime=self._ext_regime,
            )

        # Volume-weighted composite
        total_vol = sum(max(s.last_volume, 1.0) for s in states)
        w_score   = sum(s.composite * s.last_volume / total_vol for s in states)
        w_vol     = sum(s.vol_score    * s.last_volume / total_vol for s in states)
        w_volume  = sum(s.volume_score * s.last_volume / total_vol for s in states)
        w_imbal   = sum(s.imbal_score  * s.last_volume / total_vol for s in states)

        result = SentimentScore(
            score=w_score,
            regime=_regime(w_score),
            components={"volatility": w_vol, "volume_heat": w_volume, "book_imbal": w_imbal},
            sample_count=len(states),
            external_score=self._ext_score,
            external_regime=self._ext_regime,
        )
        self._category_scores[category] = result
        return result

    def global_score(self) -> SentimentScore:
        """Volume-weighted average across all tracked markets."""
        if self._global_score is not None:
            return self._global_score

        states = list(self._markets.values())
        if not states:
            return SentimentScore(
                score=50.0, regime="greed", components={}, sample_count=0,
                external_score=self._ext_score, external_regime=self._ext_regime,
            )

        total_vol = sum(max(s.last_volume, 1.0) for s in states)
        w_score   = sum(s.composite * s.last_volume / total_vol for s in states)
        w_vol     = sum(s.vol_score    * s.last_volume / total_vol for s in states)
        w_volume  = sum(s.volume_score * s.last_volume / total_vol for s in states)
        w_imbal   = sum(s.imbal_score  * s.last_volume / total_vol for s in states)

        self._global_score = SentimentScore(
            score=w_score,
            regime=_regime(w_score),
            components={"volatility": w_vol, "volume_heat": w_volume, "book_imbal": w_imbal},
            sample_count=len(states),
            external_score=self._ext_score,
            external_regime=self._ext_regime,
        )
        return self._global_score

    def all_market_scores(self) -> Dict[str, Dict[str, Any]]:
        """Return a dict of ticker → score dict for all tracked markets."""
        out: Dict[str, Dict[str, Any]] = {}
        for ticker, state in self._markets.items():
            out[ticker] = {
                "score": round(state.composite, 1),
                "regime": _regime(state.composite),
                "category": state.category,
                "components": {
                    "volatility":  round(state.vol_score, 3),
                    "volume_heat": round(state.volume_score, 3),
                    "book_imbal":  round(state.imbal_score, 3),
                },
                "last_update": state.last_update,
            }
        return out

    def summary(self) -> Dict[str, Any]:
        """JSON-serialisable summary for /health and AgentGrid.summary()."""
        glob = self.global_score()
        cat_scores = {
            cat: self.category_score(cat).to_dict()
            for cat in self._category_tickers
        }
        return {
            "global": glob.to_dict(),
            "by_category": cat_scores,
            "tracked_markets": len(self._markets),
            "external": {
                "score": self._ext_score,
                "regime": self._ext_regime,
                "fetched_at": self._ext_fetched_at,
            },
        }

    # ── External fear/greed fetch ─────────────────────────────────────────────

    async def fetch_external(self) -> None:
        """Fetch crypto fear/greed from alternative.me (best-effort, contextual only)."""
        now = time.time()
        if now - self._ext_fetched_at < EXTERNAL_FG_TTL:
            return
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(EXTERNAL_FG_URL)
                resp.raise_for_status()
                data = resp.json()
            entry = data.get("data", [{}])[0]
            self._ext_score  = float(entry.get("value", 50))
            self._ext_regime = entry.get("value_classification", "").lower().replace(" ", "_")
            self._ext_fetched_at = now
            logger.debug("External fear/greed: %.0f (%s)", self._ext_score, self._ext_regime)
        except Exception as exc:
            logger.debug("External fear/greed fetch skipped: %s", exc)

    # ── Background refresh loop ───────────────────────────────────────────────

    async def start(self) -> None:
        """Start background loop: ingest from market catalog + refresh external."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._refresh_loop(), name="kalshi-sentiment-refresh")
        logger.info("KalshiSentimentService background loop started")

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _refresh_loop(self) -> None:
        """Every 60 s: pull catalog snapshot and update all market states."""
        while self._running:
            try:
                await self._ingest_catalog()
                await self.fetch_external()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Sentiment refresh error: %s", exc)
            try:
                await asyncio.wait_for(asyncio.sleep(60), timeout=65)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                break

    async def _ingest_catalog(self) -> None:
        """Pull all open markets from the catalog and update sentiment state."""
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            markets = catalog.get_all_markets()
        except Exception as exc:
            logger.debug("Catalog ingest skipped: %s", exc)
            return

        for m in markets:
            try:
                ticker   = m.ticker if hasattr(m, "ticker") else getattr(m, "market_id", None)
                if not ticker:
                    continue
                prob     = float(getattr(m, "yes_price", 50)) / 100.0
                volume   = float(getattr(m, "volume", 0) or 0)
                oi       = float(getattr(m, "open_interest", 0) or 0)
                category = (getattr(m, "category", None) or "unknown").lower()

                # Order book depth: use OI as proxy if no live book
                bid_depth = volume * 0.5
                ask_depth = volume * 0.5

                # Try to get live book from ws_bridge snapshot
                try:
                    from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
                    bridge = get_ws_bridge()
                    book = bridge.get_orderbook(ticker) if hasattr(bridge, "get_orderbook") else None
                    if book:
                        bid_depth = float(book.get("bid_depth", bid_depth))
                        ask_depth = float(book.get("ask_depth", ask_depth))
                except Exception as _bde:
                    logger.debug("orderbook depth lookup skipped for %s: %s", ticker, _bde)

                self.update_market(
                    ticker,
                    prob=prob,
                    volume=volume,
                    bid_depth=bid_depth,
                    ask_depth=ask_depth,
                    category=category,
                )
            except Exception as exc:
                logger.debug("Market ingest error for %s: %s", getattr(m, "ticker", "?"), exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_service: Optional[KalshiSentimentService] = None


def get_sentiment_service() -> KalshiSentimentService:
    """Return the module-level KalshiSentimentService singleton."""
    global _service
    if _service is None:
        _service = KalshiSentimentService()
    return _service
