"""
KalshiInsightPipeline — Kalshi → MERID consensus → InsightObject emitter.

Architecture:
  1. Poll all open Kalshi markets by category (30–120s cadence per category)
  2. Normalize to internal schema
  3. Run MERID swarm consensus on each market
  4. Detect events: new market, prob threshold cross, large swing, resolution
  5. Emit InsightObject to downstream consumers (KalshiNewsAgent)

InsightObject schema:
  {
    source, category, ticker, question,
    kalshi_prob, swarm_prob, swarm_confidence,
    change_24h, timestamp, narrative, action,
    market_url, volume, open_interest
  }
"""

from __future__ import annotations

import os
import threading
import asyncio
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.publishing.kalshi_insight_pipeline")


# ── Category config ───────────────────────────────────────────────────────────

CATEGORY_CADENCE: Dict[str, int] = {
    "Trending":     30,
    "Politics":     60,
    "Sports":       60,
    "Culture":      90,
    "Crypto":       30,
    "Climate":      120,
    "Economics":    60,
    "Mentions":     45,
    "Companies":    60,
    "Financials":   60,
    "Tech & Science": 90,
}

CATEGORY_TAGS: Dict[str, List[str]] = {
    "Trending":     ["#Trending", "#Kalshi"],
    "Politics":     ["#Politics", "#Kalshi"],
    "Sports":       ["#Sports", "#Kalshi"],
    "Culture":      ["#Culture", "#Entertainment", "#Kalshi"],
    "Crypto":       ["#Crypto", "#Bitcoin", "#Kalshi"],
    "Climate":      ["#Climate", "#ESG", "#Kalshi"],
    "Economics":    ["#Economics", "#Macro", "#Kalshi"],
    "Mentions":     ["#Mentions", "#Media", "#Kalshi"],
    "Companies":    ["#Stocks", "#Companies", "#Kalshi"],
    "Financials":   ["#Finance", "#Markets", "#Kalshi"],
    "Tech & Science": ["#Tech", "#Science", "#Kalshi"],
}

# Kalshi category slug → internal category name
KALSHI_CATEGORY_MAP: Dict[str, str] = {
    "trending":     "Trending",
    "politics":     "Politics",
    "sports":       "Sports",
    "culture":      "Culture",
    "crypto":       "Crypto",
    "climate":      "Climate",
    "economics":    "Economics",
    "mentions":     "Mentions",
    "companies":    "Companies",
    "financials":   "Financials",
    "tech":         "Tech & Science",
    "science":      "Tech & Science",
    "technology":   "Tech & Science",
}

# Kalshi market URLs — single source of truth from invariants
from merid.event_venues.kalshi.invariants import get_kalshi_base_url, get_kalshi_ws_url

def _get_kalshi_market_base_url() -> str:
    """Get Kalshi web market URL for browser links."""
    return os.getenv(
        "KALSHI_WEB_BASE_URL",
        "https://kalshi.com/markets"
    )

KALSHI_MARKET_BASE_URL = _get_kalshi_market_base_url()
KALSHI_API_BASE_URL = get_kalshi_base_url()

# Trigger thresholds
PROB_CROSS_THRESHOLD = 0.10     # 10-point swing triggers a post
SWING_1H_THRESHOLD   = 0.08     # 8% move in 1h triggers a post
MIN_VOLUME           = 500      # Minimum volume (contracts) to consider
CONFIDENCE_FLOOR     = 0.55     # Minimum swarm confidence to post


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class KalshiMarket:
    ticker: str
    question: str
    category: str
    yes_price: float        # 0–100 cents
    no_price: float
    volume: int
    open_interest: int
    end_date: Optional[str]
    status: str             # "open" | "closed" | "settled"
    result: Optional[str]   # "yes" | "no" | None
    event_ticker: Optional[str] = None

    @property
    def prob(self) -> float:
        return self.yes_price / 100.0


@dataclass
class InsightObject:
    source: str
    category: str
    ticker: str
    question: str
    kalshi_prob: float
    swarm_prob: float
    swarm_confidence: float
    change_24h: float
    timestamp: str
    narrative: str
    action: str             # "new_market" | "prob_cross" | "swing" | "resolution" | "update"
    market_url: str
    volume: int
    open_interest: int
    tags: List[str] = field(default_factory=list)
    prev_prob: Optional[float] = None
    resolved_yes: Optional[bool] = None
    # Fear/greed sentiment (from KalshiSentimentService)
    fear_greed_local: Optional[float] = None      # 0–100, this market
    fear_greed_category: Optional[float] = None   # 0–100, category average
    fear_greed_global: Optional[float] = None     # 0–100, all Kalshi
    regime: Optional[str] = None                  # extreme_fear|fear|greed|extreme_greed
    signal: Optional[str] = None                  # e.g. "fade_greed_long_yes"
    size: Optional[int] = None                    # recommended contracts

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Pipeline ──────────────────────────────────────────────────────────────────

class KalshiInsightPipeline:
    """
    Continuous Kalshi → MERID consensus → InsightObject pipeline.

    Usage:
        pipeline = KalshiInsightPipeline()
        pipeline.add_consumer(my_news_agent.handle_insight)
        await pipeline.run()
    """

    def __init__(self) -> None:
        self._consumers: List[Callable[[InsightObject], Any]] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []

        # State: ticker → last known prob + last post time
        self._last_prob: Dict[str, float] = {}
        self._last_post_ts: Dict[str, float] = {}
        self._seen_tickers: Set[str] = set()
        self._recent_insights: List[InsightObject] = []
        self._stats: Dict[str, Any] = {
            "total_emitted": 0,
            "by_category": {},
            "by_action": {},
            "errors": 0,
            "started_at": None,
        }

    # ── Public API ────────────────────────────────────────────────────────────

    def add_consumer(self, fn: Callable[[InsightObject], Any]) -> None:
        """Register a downstream consumer (sync or async callable). Idempotent."""
        if fn not in self._consumers:
            self._consumers.append(fn)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stats["started_at"] = datetime.now(timezone.utc).isoformat()
        logger.info("KalshiInsightPipeline starting — %d categories", len(CATEGORY_CADENCE))
        for category, cadence in CATEGORY_CADENCE.items():
            task = asyncio.create_task(
                self._category_loop(category, cadence),
                name=f"insight-{category.lower()}",
            )
            self._tasks.append(task)

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("KalshiInsightPipeline stopped")

    def summary(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "consumers": len(self._consumers),
            "tracked_tickers": len(self._seen_tickers),
            "recent_insights": [i.to_dict() for i in self._recent_insights[-20:]],
            **self._stats,
        }

    # ── Category polling loop ─────────────────────────────────────────────────

    async def _category_loop(self, category: str, cadence: int) -> None:
        logger.info("Category loop started: %s (every %ds)", category, cadence)
        while self._running:
            try:
                markets = await self._fetch_markets(category)
                for market in markets:
                    await self._process_market(market)
                    # Yield control after each market to allow other tasks
                    await asyncio.sleep(0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._stats["errors"] += 1
                logger.warning("Category loop error [%s]: %s", category, exc)
            await asyncio.sleep(cadence)

    # ── Market fetching ───────────────────────────────────────────────────────

    async def _fetch_markets(self, category: str) -> List[KalshiMarket]:
        """Fetch open markets for a category from Kalshi API."""
        try:
            executor = self._get_executor()
            if executor:
                return await self._fetch_via_executor(executor, category)
        except Exception as exc:
            logger.debug("Executor fetch failed for %s: %s", category, exc)

        try:
            return await self._fetch_via_rest_client(category)
        except Exception as exc:
            logger.debug("REST client fetch failed for %s: %s", category, exc)

        return []

    async def _fetch_via_executor(self, executor: Any, category: str) -> List[KalshiMarket]:
        """Fetch via KalshiExecutor (authenticated)."""
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(
            None,
            lambda: executor.get_markets(status="open", limit=200),
        )
        markets_raw = raw if isinstance(raw, list) else raw.get("markets", [])
        return [
            m for m in (self._normalize_market(r) for r in markets_raw)
            if m and m.category == category and m.volume >= MIN_VOLUME
        ]

    async def _fetch_via_rest_client(self, category: str) -> List[KalshiMarket]:
        """Fetch via merid_core REST client."""
        import httpx
        # Public endpoint — no auth needed for market browsing
        slug = category.lower().replace(" & ", "-").replace(" ", "-")
        url = f"{KALSHI_API_BASE_URL}/markets"
        params = {"status": "open", "limit": 200}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
        markets_raw = data.get("markets", [])
        return [
            m for m in (self._normalize_market(r) for r in markets_raw)
            if m and m.category == category and m.volume >= MIN_VOLUME
        ]

    def _normalize_market(self, raw: Dict[str, Any]) -> Optional[KalshiMarket]:
        """Normalize a raw Kalshi market dict to KalshiMarket."""
        try:
            ticker = raw.get("ticker") or raw.get("market_ticker", "")
            if not ticker:
                return None

            # Map category from event metadata
            event_category = (
                raw.get("category") or
                raw.get("event_category") or
                raw.get("series_ticker", "").split("-")[0].lower()
            )
            category = KALSHI_CATEGORY_MAP.get(event_category.lower(), "Trending")

            yes_price = float(raw.get("yes_bid") or raw.get("last_price") or raw.get("yes_price") or 50)
            no_price  = float(raw.get("no_bid") or raw.get("no_price") or (100 - yes_price))
            volume    = int(raw.get("volume") or raw.get("volume_24h") or 0)
            oi        = int(raw.get("open_interest") or 0)

            return KalshiMarket(
                ticker=ticker,
                question=raw.get("title") or raw.get("question") or ticker,
                category=category,
                yes_price=yes_price,
                no_price=no_price,
                volume=volume,
                open_interest=oi,
                end_date=raw.get("close_time") or raw.get("expiration_time"),
                status=raw.get("status", "open"),
                result=raw.get("result"),
                event_ticker=raw.get("event_ticker"),
            )
        except Exception as exc:
            logger.debug("Market normalize error: %s — %s", exc, raw.get("ticker", "?"))
            return None

    # ── Market processing ─────────────────────────────────────────────────────

    async def _process_market(self, market: KalshiMarket) -> None:
        ticker = market.ticker
        now = time.time()
        prev_prob = self._last_prob.get(ticker)
        last_post = self._last_post_ts.get(ticker, 0)

        # Determine action
        action: Optional[str] = None

        if market.status in ("settled", "closed") and market.result:
            action = "resolution"
        elif ticker not in self._seen_tickers:
            action = "new_market"
        elif prev_prob is not None:
            delta = abs(market.prob - prev_prob)
            if delta >= PROB_CROSS_THRESHOLD:
                action = "prob_cross"
            elif delta >= SWING_1H_THRESHOLD and (now - last_post) >= 3600:
                action = "swing"

        # Periodic update (every 6h minimum for active markets)
        if action is None and (now - last_post) >= 21600 and prev_prob is not None:
            action = "update"

        if action is None:
            # Update state but don't emit
            self._last_prob[ticker] = market.prob
            self._seen_tickers.add(ticker)
            return

        # Compute swarm consensus
        swarm_prob, swarm_conf = await self._get_swarm_consensus(market)
        if swarm_conf < CONFIDENCE_FLOOR and action not in ("resolution", "new_market"):
            self._last_prob[ticker] = market.prob
            self._seen_tickers.add(ticker)
            return

        # Build narrative
        narrative = self._build_narrative(market, action, prev_prob, swarm_prob, swarm_conf)

        # Fetch sentiment scores
        fg_local: Optional[float] = None
        fg_category: Optional[float] = None
        fg_global: Optional[float] = None
        fg_regime: Optional[str] = None
        fg_signal: Optional[str] = None
        try:
            from merid.event_venues.kalshi.sentiment import get_sentiment_service
            svc = get_sentiment_service()
            cat_key = market.category.lower() if market.category else "unknown"
            local_s = svc.market_score(ticker)
            cat_s   = svc.category_score(cat_key)
            glob_s  = svc.global_score()
            fg_local    = round(local_s.score, 1) if local_s else None
            fg_category = round(cat_s.score, 1)
            fg_global   = round(glob_s.score, 1)
            fg_regime   = local_s.regime if local_s else glob_s.regime
            # Derive a human-readable signal label
            gap = swarm_prob - market.prob
            if fg_regime == "extreme_greed" and gap < -0.05:
                fg_signal = "fade_greed_long_no"
            elif fg_regime == "extreme_greed" and gap > 0.05:
                fg_signal = "fade_greed_long_yes"
            elif fg_regime == "extreme_fear" and gap > 0.05:
                fg_signal = "buy_fear_dip_yes"
            elif fg_regime == "extreme_fear" and gap < -0.05:
                fg_signal = "short_fear_no"
            else:
                fg_signal = "neutral"
        except Exception as _fge:
            logger.debug("fg_signal enrichment skipped: %s", _fge)

        insight = InsightObject(
            source="kalshi",
            category=market.category,
            ticker=ticker,
            question=market.question,
            kalshi_prob=round(market.prob, 3),
            swarm_prob=round(swarm_prob, 3),
            swarm_confidence=round(swarm_conf, 3),
            change_24h=round(market.prob - (prev_prob or market.prob), 3),
            timestamp=datetime.now(timezone.utc).isoformat(),
            narrative=narrative,
            action=action,
            market_url=f"{KALSHI_MARKET_BASE_URL}/{ticker}",
            volume=market.volume,
            open_interest=market.open_interest,
            tags=CATEGORY_TAGS.get(market.category, ["#Kalshi"]),
            prev_prob=prev_prob,
            resolved_yes=(market.result == "yes") if market.result else None,
            fear_greed_local=fg_local,
            fear_greed_category=fg_category,
            fear_greed_global=fg_global,
            regime=fg_regime,
            signal=fg_signal,
        )

        # Update state
        self._last_prob[ticker] = market.prob
        self._last_post_ts[ticker] = now
        self._seen_tickers.add(ticker)
        self._recent_insights.append(insight)
        if len(self._recent_insights) > 200:
            self._recent_insights = self._recent_insights[-200:]

        # Update stats
        self._stats["total_emitted"] += 1
        self._stats["by_category"][market.category] = self._stats["by_category"].get(market.category, 0) + 1
        self._stats["by_action"][action] = self._stats["by_action"].get(action, 0) + 1

        logger.info("Insight emitted: %s [%s] prob=%.2f action=%s", ticker, market.category, market.prob, action)

        # Dispatch to consumers
        await self._dispatch(insight)

    # ── Swarm consensus ───────────────────────────────────────────────────────

    async def _get_swarm_consensus(self, market: KalshiMarket) -> tuple[float, float]:
        """Get MERID swarm consensus probability and confidence for a market."""
        try:
            from core.consensus_engine import get_consensus_engine
            engine = get_consensus_engine()

            # Look for existing votes on this ticker
            relevant = [
                v for v in engine.pending_votes.values()
                if market.ticker in v.proposal or market.ticker in v.agent_id
            ]
            if relevant:
                total_w = sum(v.weight for v in relevant)
                yes_w   = sum(v.weight for v in relevant if v.signal in ("bullish", "yes", "long"))
                prob    = yes_w / total_w if total_w > 0 else market.prob
                conf    = sum(v.confidence for v in relevant) / len(relevant)
                return prob, conf
        except Exception as _ve:
            logger.debug("vote-weighted prob skipped: %s", _ve)

        try:
            # Fall back to AgentPerformanceTracker system win rate as proxy confidence
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
            tracker = get_agent_performance_tracker()
            sys = tracker.get_system_summary()
            conf = float(sys.get("system_win_rate", 0.6))
            return market.prob, max(0.5, conf)
        except Exception as _sye:
            logger.debug("system win_rate conf skipped: %s", _sye)

        # Default: trust Kalshi price, low confidence
        return market.prob, 0.60

    # ── Narrative builder ─────────────────────────────────────────────────────

    def _build_narrative(
        self,
        market: KalshiMarket,
        action: str,
        prev_prob: Optional[float],
        swarm_prob: float,
        swarm_conf: float,
    ) -> str:
        prob_pct = f"{market.prob * 100:.0f}%"
        swarm_pct = f"{swarm_prob * 100:.0f}%"
        conf_pct = f"{swarm_conf * 100:.0f}%"

        if action == "resolution":
            result_word = "YES" if market.result == "yes" else "NO"
            return (
                f"Market settled {result_word}. "
                f"Final Kalshi price was {prob_pct}. "
                f"MERID swarm had called {swarm_pct} with {conf_pct} confidence."
            )
        if action == "new_market":
            return (
                f"New market opened at {prob_pct}. "
                f"MERID swarm initial read: {swarm_pct} ({conf_pct} confidence)."
            )
        if action in ("prob_cross", "swing") and prev_prob is not None:
            direction = "up" if market.prob > prev_prob else "down"
            delta_pts = abs(market.prob - prev_prob) * 100
            return (
                f"Probability moved {direction} {delta_pts:.0f} points to {prob_pct}. "
                f"MERID swarm: {swarm_pct} ({conf_pct} confidence)."
            )
        return (
            f"Current market price: {prob_pct}. "
            f"MERID swarm consensus: {swarm_pct} ({conf_pct} confidence)."
        )

    # ── Dispatch ──────────────────────────────────────────────────────────────

    async def _dispatch(self, insight: InsightObject) -> None:
        for consumer in self._consumers:
            try:
                result = consumer(insight)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("Consumer error for %s: %s", insight.ticker, exc)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_executor(self) -> Optional[Any]:
        if not hasattr(self, "_executor_cache"):
            try:
                from merid.execution.executors.kalshi import KalshiExecutor
                self._executor_cache = KalshiExecutor()
            except Exception as _exe:
                logger.debug("KalshiExecutor init failed, executor disabled: %s", _exe)
                self._executor_cache = None
        return self._executor_cache


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline: Optional[KalshiInsightPipeline] = None
_pipeline_lock = threading.Lock()


def get_insight_pipeline() -> KalshiInsightPipeline:
    global _pipeline
    if _pipeline is None:
        with _pipeline_lock:
            if _pipeline is None:
                _pipeline = KalshiInsightPipeline()
    return _pipeline
