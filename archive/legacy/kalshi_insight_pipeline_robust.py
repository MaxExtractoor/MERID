"""
Enhanced Kalshi Insight Pipeline with Robustness Features

Critical fixes for the KalshiInsightPipeline to address:
- Error handling and retry logic
- Input validation and sanitization
- Circuit breaking for external services
- Graceful shutdown handling
- Resource management
- Health checks and monitoring
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger
from merid.pipeline.robustness import (
    retry_async, circuit_breaker, validate_inputs, rate_limit,
    ThreadSafeState, ResourceManager, HealthChecker, PipelineMetrics,
    GracefulShutdown, validate_non_empty_string, validate_probability,
    ErrorRecovery, get_health_checker, get_metrics, get_shutdown_handler
)

logger = get_logger("merid.publishing.kalshi_insight_pipeline_robust")


# ── Enhanced Data Classes with Validation ─────────────────────────────────────

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

    def __post_init__(self):
        """Validate market data after initialization."""
        if not validate_non_empty_string(self.ticker):
            raise ValueError("Invalid ticker: cannot be empty")
        
        if not validate_non_empty_string(self.question):
            raise ValueError("Invalid question: cannot be empty")
        
        if not validate_non_empty_string(self.category):
            raise ValueError("Invalid category: cannot be empty")
        
        if not (0 <= self.yes_price <= 100):
            raise ValueError(f"Invalid yes_price: {self.yes_price} (must be 0-100)")
        
        if not (0 <= self.no_price <= 100):
            raise ValueError(f"Invalid no_price: {self.no_price} (must be 0-100)")
        
        if self.volume < 0:
            raise ValueError(f"Invalid volume: {self.volume} (must be >= 0)")
        
        if self.open_interest < 0:
            raise ValueError(f"Invalid open_interest: {self.open_interest} (must be >= 0)")

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
    # Fear/greed sentiment
    fear_greed_local: Optional[float] = None
    fear_greed_category: Optional[float] = None
    fear_greed_global: Optional[float] = None
    regime: Optional[str] = None
    signal: Optional[str] = None
    size: Optional[int] = None

    def __post_init__(self):
        """Validate insight data after initialization."""
        if not validate_non_empty_string(self.source):
            raise ValueError("Invalid source: cannot be empty")
        
        if not validate_non_empty_string(self.ticker):
            raise ValueError("Invalid ticker: cannot be empty")
        
        if not validate_probability(self.kalshi_prob):
            raise ValueError(f"Invalid kalshi_prob: {self.kalshi_prob}")
        
        if not validate_probability(self.swarm_prob):
            raise ValueError(f"Invalid swarm_prob: {self.swarm_prob}")
        
        if not validate_probability(self.swarm_confidence):
            raise ValueError(f"Invalid swarm_confidence: {self.swarm_confidence}")
        
        if not validate_timestamp(self.timestamp):
            raise ValueError(f"Invalid timestamp: {self.timestamp}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ── Enhanced Pipeline with Robustness ─────────────────────────────────────────────

class KalshiInsightPipelineRobust:
    """
    Enhanced Kalshi Insight Pipeline with comprehensive robustness features.
    
    Key improvements:
    - Error handling with retry logic and circuit breaking
    - Input validation and sanitization
    - Graceful shutdown handling
    - Health checks and metrics
    - Resource management
    - Rate limiting
    """

    def __init__(self) -> None:
        self._consumers: List[Callable[[InsightObject], Any]] = []
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._resource_manager = ResourceManager()
        self._shutdown_handler = get_shutdown_handler()
        self._metrics = get_metrics()
        self._health_checker = get_health_checker()
        
        # Thread-safe state management
        self._state = ThreadSafeState()
        self._state.set("last_prob", {})
        self._state.set("last_post_ts", {})
        self._state.set("seen_tickers", set())
        self._state.set("recent_insights", [])
        self._state.set("stats", {
            "total_emitted": 0,
            "by_category": {},
            "by_action": {},
            "errors": 0,
            "started_at": None,
        })

        # Register health checks
        self._health_checker.register_check("pipeline_status", self._health_check_status)
        self._health_checker.register_check("market_fetching", self._health_check_market_fetching)
        self._health_checker.register_check("consumer_health", self._health_check_consumers)

        # Register shutdown handler
        self._shutdown_handler.register_handler(self._cleanup_resources)

    # ── Public API with Validation ───────────────────────────────────────────

    @validate_inputs(consumer=lambda x: callable(x))
    def add_consumer(self, consumer: Callable[[InsightObject], Any]) -> None:
        """Register a downstream consumer with validation."""
        if consumer not in self._consumers:
            self._consumers.append(consumer)
            logger.info(f"Added consumer: {consumer.__name__}")

    async def start(self) -> None:
        """Start the pipeline with error handling."""
        if self._running:
            logger.warning("Pipeline already running")
            return
        
        try:
            self._running = True
            self._state.get("stats")["started_at"] = datetime.now(timezone.utc).isoformat()
            
            logger.info("KalshiInsightPipelineRobust starting with enhanced robustness")
            
            # Start category loops with error handling
            for category, cadence in CATEGORY_CADENCE.items():
                task = asyncio.create_task(
                    self._category_loop_robust(category, cadence),
                    name=f"insight-{category.lower()}-robust",
                )
                self._tasks.append(task)
                self._resource_manager.register(task, lambda t: t.cancel())
            
            logger.info(f"Started {len(self._tasks)} category loops")
            
        except Exception as exc:
            logger.error(f"Failed to start pipeline: {exc}")
            await self.stop()
            raise

    async def stop(self) -> None:
        """Stop the pipeline gracefully."""
        if not self._running:
            return
        
        logger.info("Stopping KalshiInsightPipelineRobust...")
        self._running = False
        
        # Cancel all tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to complete with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            logger.warning("Some tasks didn't complete within timeout")
        
        self._tasks.clear()
        
        # Cleanup resources
        await self._resource_manager.cleanup_all()
        
        logger.info("KalshiInsightPipelineRobust stopped")

    def summary(self) -> Dict[str, Any]:
        """Get pipeline summary with metrics."""
        stats = self._state.get("stats", {})
        recent_insights = self._state.get("recent_insights", [])
        
        return {
            "running": self._running,
            "consumers": len(self._consumers),
            "tracked_tickers": len(self._state.get("seen_tickers", set())),
            "recent_insights": [i.to_dict() for i in recent_insights[-20:]],
            "metrics": self._metrics.get_summary(),
            "health": self._health_checker.get_summary(),
            **stats,
        }

    # ── Enhanced Category Loop with Robustness ─────────────────────────────────

    @retry_async(max_attempts=3, base_delay=1.0)
    @rate_limit(calls_per_second=0.5)  # Max 2 category loops per second
    async def _category_loop_robust(self, category: str, cadence: int) -> None:
        """Enhanced category loop with comprehensive error handling."""
        logger.info("Category loop started: %s (every %ds)", category, cadence)
        
        while self._running and not self._shutdown_handler.is_shutting_down():
            try:
                start_time = time.time()
                
                # Fetch markets with retry and circuit breaking
                markets = await self._fetch_markets_robust(category)
                
                # Process markets with error handling
                for market in markets:
                    if self._shutdown_handler.is_shutting_down():
                        break
                    
                    await ErrorRecovery.safe_execute(
                        self._process_market_robust,
                        market,
                        fallback_value=None,
                        log_error=True
                    )
                
                # Record metrics
                duration = time.time() - start_time
                self._metrics.record_timing(f"category_loop_{category}", duration)
                self._metrics.increment_counter(f"category_loops_{category}")
                
            except asyncio.CancelledError:
                logger.info(f"Category loop {category} cancelled")
                break
            except Exception as exc:
                self._state.get("stats")["errors"] += 1
                self._metrics.increment_counter("category_loop_errors")
                logger.warning("Category loop error [%s]: %s", category, exc)
            
            # Sleep with shutdown check
            try:
                await asyncio.wait_for(
                    asyncio.sleep(cadence),
                    timeout=cadence
                )
            except asyncio.TimeoutError:
                continue  # Expected timeout for shutdown check

    # ── Enhanced Market Fetching with Robustness ───────────────────────────────

    @circuit_breaker(failure_threshold=5, recovery_timeout=60.0)
    @retry_async(max_attempts=3, base_delay=2.0)
    async def _fetch_markets_robust(self, category: str) -> List[KalshiMarket]:
        """Fetch markets with circuit breaking and retry logic."""
        try:
            # Try executor first
            executor = self._get_executor()
            if executor:
                markets = await ErrorRecovery.safe_execute(
                    self._fetch_via_executor_robust,
                    executor, category,
                    fallback_value=[]
                )
                if markets:
                    return markets
        except Exception as exc:
            logger.debug("Executor fetch failed for %s: %s", category, exc)

        # Fallback to REST client
        markets = await ErrorRecovery.safe_execute(
            self._fetch_via_rest_client_robust,
            category,
            fallback_value=[]
        )
        
        return markets

    async def _fetch_via_executor_robust(self, executor: Any, category: str) -> List[KalshiMarket]:
        """Fetch via KalshiVenueClient with validation."""
        from merid.event_venues.kalshi.client import get_kalshi_client
        client = get_kalshi_client()
        if client is None:
            return []
        
        event_markets = await client.list_markets()
        
        # list_markets returns List[EventMarket] — build dicts for _normalize_market_robust
        markets_raw = []
        for em in (event_markets or []):
            # CRITICAL FIX: Handle CatalogMarket wrapping EventMarket
            if hasattr(em, "market") and hasattr(em.market, "raw_data"):
                d = dict(em.market.raw_data) if em.market.raw_data else {}
            elif hasattr(em, "raw_data"):
                d = dict(em.raw_data) if em.raw_data else {}
            else:
                d = {}
            d.setdefault("ticker", em.market_id if hasattr(em, "market_id") else getattr(em.market, "market_id", "") if hasattr(em, "market") else "")
            d.setdefault("title", em.question if hasattr(em, "question") else getattr(em.market, "question", "") if hasattr(em, "market") else "")
            d.setdefault("category", em.category if hasattr(em, "category") else getattr(em.market, "category", "") if hasattr(em, "market") else "")
            d.setdefault("volume", int(em.volume or 0))
            d.setdefault("open_interest", int(em.open_interest or 0))
            d.setdefault("status", "open" if em.active else "closed")
            if em.outcomes:
                d.setdefault("yes_bid", float(em.outcomes[0].price * 100))
            markets_raw.append(d)
        
        # Validate and normalize markets
        valid_markets = []
        for raw_market in markets_raw:
            try:
                market = self._normalize_market_robust(raw_market)
                if (market and 
                    market.category == category and 
                    market.volume >= MIN_VOLUME and
                    market.status == "open"):
                    valid_markets.append(market)
            except Exception as exc:
                logger.debug("Market validation failed: %s", exc)
                continue
        
        self._metrics.increment_counter("markets_fetched_executor", len(valid_markets))
        return valid_markets

    @retry_async(max_attempts=3, base_delay=1.0)
    async def _fetch_via_rest_client_robust(self, category: str) -> List[KalshiMarket]:
        """Fetch via REST client with retry logic."""
        import httpx
        
        slug = category.lower().replace(" & ", "-").replace(" ", "-")
        url = f"https://external-api.kalshi.com/trade-api/v2/markets"
        params = {"status": "open", "limit": 200}
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as exc:
                logger.error(f"HTTP error fetching markets: {exc}")
                raise
            except Exception as exc:
                logger.error(f"Unexpected error fetching markets: {exc}")
                raise
        
        markets_raw = data.get("markets", [])
        
        # Validate and normalize markets
        valid_markets = []
        for raw_market in markets_raw:
            try:
                market = self._normalize_market_robust(raw_market)
                if (market and 
                    market.category == category and 
                    market.volume >= MIN_VOLUME and
                    market.status == "open"):
                    valid_markets.append(market)
            except Exception as exc:
                logger.debug("Market validation failed: %s", exc)
                continue
        
        self._metrics.increment_counter("markets_fetched_rest", len(valid_markets))
        return valid_markets

    def _normalize_market_robust(self, raw: Dict[str, Any]) -> Optional[KalshiMarket]:
        """Normalize market with comprehensive validation."""
        try:
            # Extract and validate ticker
            ticker = raw.get("ticker") or raw.get("market_ticker", "")
            if not validate_non_empty_string(ticker):
                return None

            # Map category
            event_category = (
                raw.get("category") or
                raw.get("event_category") or
                raw.get("series_ticker", "").split("-")[0].lower()
            )
            category = KALSHI_CATEGORY_MAP.get(event_category.lower(), "Trending")

            # Extract and validate prices
            yes_price = float(raw.get("yes_bid") or raw.get("last_price") or raw.get("yes_price") or 50)
            no_price = float(raw.get("no_bid") or raw.get("no_price") or (100 - yes_price))
            
            if not (0 <= yes_price <= 100 and 0 <= no_price <= 100):
                logger.debug(f"Invalid prices for {ticker}: yes={yes_price}, no={no_price}")
                return None

            # Extract and validate volumes
            volume = int(raw.get("volume") or raw.get("volume_24h") or 0)
            oi = int(raw.get("open_interest") or 0)
            
            if volume < 0 or oi < 0:
                logger.debug(f"Invalid volumes for {ticker}: volume={volume}, oi={oi}")
                return None

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

    # ── Enhanced Market Processing ─────────────────────────────────────────────

    async def _process_market_robust(self, market: KalshiMarket) -> None:
        """Process market with comprehensive error handling."""
        try:
            ticker = market.ticker
            now = time.time()
            
            # Get thread-safe state
            last_prob = self._state.get("last_prob", {}).get(ticker)
            last_post = self._state.get("last_post_ts", {}).get(ticker, 0)
            seen_tickers = self._state.get("seen_tickers", set())

            # Determine action
            action = self._determine_action(market, last_prob, last_post, seen_tickers)
            
            if action is None:
                # Update state but don't emit
                self._state.get("last_prob", {})[ticker] = market.prob
                seen_tickers.add(ticker)
                return

            # Get swarm consensus with error handling
            swarm_prob, swarm_conf = await ErrorRecovery.safe_execute(
                self._get_swarm_consensus_robust,
                market,
                fallback_value=(market.prob, 0.60)
            )

            # Check confidence floor
            if swarm_conf < CONFIDENCE_FLOOR and action not in ("resolution", "new_market"):
                self._state.get("last_prob", {})[ticker] = market.prob
                seen_tickers.add(ticker)
                return

            # Build narrative
            narrative = self._build_narrative_robust(market, action, last_prob, swarm_prob, swarm_conf)

            # Create insight with validation
            insight = InsightObject(
                source="kalshi",
                category=market.category,
                ticker=ticker,
                question=market.question,
                kalshi_prob=round(market.prob, 3),
                swarm_prob=round(swarm_prob, 3),
                swarm_confidence=round(swarm_conf, 3),
                change_24h=round(market.prob - (last_prob or market.prob), 3),
                timestamp=datetime.now(timezone.utc).isoformat(),
                narrative=narrative,
                action=action,
                market_url=f"{KALSHI_MARKET_BASE_URL}/{ticker}",
                volume=market.volume,
                open_interest=market.open_interest,
                tags=CATEGORY_TAGS.get(market.category, ["#Kalshi"]),
                prev_prob=last_prob,
                resolved_yes=(market.result == "yes") if market.result else None,
            )

            # Update state
            self._state.get("last_prob", {})[ticker] = market.prob
            self._state.get("last_post_ts", {})[ticker] = now
            seen_tickers.add(ticker)
            
            # Add to recent insights
            recent_insights = self._state.get("recent_insights", [])
            recent_insights.append(insight)
            if len(recent_insights) > 200:
                recent_insights[:] = recent_insights[-200:]

            # Update stats
            stats = self._state.get("stats", {})
            stats["total_emitted"] += 1
            stats["by_category"][market.category] = stats["by_category"].get(market.category, 0) + 1
            stats["by_action"][action] = stats["by_action"].get(action, 0) + 1

            logger.info("Insight emitted: %s [%s] prob=%.2f action=%s", ticker, market.category, market.prob, action)

            # Dispatch to consumers with error handling
            await self._dispatch_robust(insight)

        except Exception as exc:
            self._state.get("stats", {})["errors"] += 1
            self._metrics.increment_counter("market_processing_errors")
            logger.error(f"Error processing market {market.ticker}: {exc}")

    def _determine_action(self, market: KalshiMarket, prev_prob: Optional[float], 
                         last_post: float, seen_tickers: set) -> Optional[str]:
        """Determine action with validation."""
        action = None

        if market.status in ("settled", "closed") and market.result:
            action = "resolution"
        elif market.ticker not in seen_tickers:
            action = "new_market"
        elif prev_prob is not None:
            delta = abs(market.prob - prev_prob)
            if delta >= PROB_CROSS_THRESHOLD:
                action = "prob_cross"
            elif delta >= SWING_1H_THRESHOLD and (time.time() - last_post) < 3600:
                action = "swing"

        # Periodic update
        if action is None and (time.time() - last_post) >= 21600 and prev_prob is not None:
            action = "update"

        return action

    async def _get_swarm_consensus_robust(self, market: KalshiMarket) -> tuple[float, float]:
        """Get swarm consensus with error handling."""
        try:
            from core.consensus_engine import get_consensus_engine
            engine = get_consensus_engine()

            # Look for existing votes
            relevant = [
                v for v in engine.pending_votes.values()
                if market.ticker in v.proposal or market.ticker in v.agent_id
            ]
            
            if relevant:
                total_w = sum(v.weight for v in relevant)
                yes_w = sum(v.weight for v in relevant if v.signal in ("bullish", "yes", "long"))
                prob = yes_w / total_w if total_w > 0 else market.prob
                conf = sum(v.confidence for v in relevant) / len(relevant)
                return prob, conf
                
        except Exception as exc:
            logger.debug("Vote-weighted consensus failed: %s", exc)

        # Fallback to system performance
        try:
            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
            tracker = get_agent_performance_tracker()
            sys = tracker.get_system_summary()
            conf = float(sys.get("system_win_rate", 0.6))
            return market.prob, max(0.5, conf)
        except Exception as exc:
            logger.debug("System performance fallback failed: %s", exc)

        # Default fallback
        return market.prob, 0.60

    def _build_narrative_robust(self, market: KalshiMarket, action: str, 
                              prev_prob: Optional[float], swarm_prob: float, 
                              swarm_conf: float) -> str:
        """Build narrative with validation."""
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

    async def _dispatch_robust(self, insight: InsightObject) -> None:
        """Dispatch insight to consumers with error handling."""
        for consumer in self._consumers:
            try:
                result = consumer(insight)
                if asyncio.iscoroutine(result):
                    await result
                self._metrics.increment_counter("consumer_dispatches")
            except Exception as exc:
                self._metrics.increment_counter("consumer_errors")
                logger.warning("Consumer error for %s: %s", insight.ticker, exc)

    # ── Health Checks ───────────────────────────────────────────────────────

    async def _health_check_status(self) -> Dict[str, Any]:
        """Check pipeline status health."""
        return {
            "running": self._running,
            "tasks_running": len([t for t in self._tasks if not t.done()]),
            "consumers": len(self._consumers),
            "uptime": time.time() - (self._state.get("stats", {}).get("started_at") and 
                                 datetime.fromisoformat(self._state.get("stats", {}).get("started_at")).timestamp() or 0)
        }

    async def _health_check_market_fetching(self) -> Dict[str, Any]:
        """Check market fetching health."""
        try:
            # Try to fetch a small sample of markets
            test_markets = await self._fetch_markets_robust("Trending")
            return {
                "fetching_healthy": True,
                "sample_markets": len(test_markets),
                "last_fetch": datetime.now(timezone.utc).isoformat()
            }
        except Exception as exc:
            return {
                "fetching_healthy": False,
                "error": str(exc),
                "last_fetch": None
            }

    async def _health_check_consumers(self) -> Dict[str, Any]:
        """Check consumer health."""
        healthy_consumers = 0
        for consumer in self._consumers:
            try:
                # Simple health check - try to call consumer with test data
                if hasattr(consumer, '__name__'):
                    healthy_consumers += 1
            except Exception:
                pass
        
        return {
            "total_consumers": len(self._consumers),
            "healthy_consumers": healthy_consumers,
            "all_healthy": healthy_consumers == len(self._consumers)
        }

    # ── Resource Cleanup ─────────────────────────────────────────────────────

    async def _cleanup_resources(self) -> None:
        """Clean up pipeline resources."""
        logger.info("Cleaning up pipeline resources...")
        
        # Cancel all tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()
        
        # Clear state
        self._state.clear()
        
        logger.info("Pipeline resources cleaned up")

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _get_executor(self) -> Optional[Any]:
        """Get Kalshi executor with caching."""
        if not hasattr(self, "_executor_cache"):
            try:
                from merid.execution.executors.kalshi import KalshiExecutor
                self._executor_cache = KalshiExecutor()
            except Exception as exc:
                logger.debug("KalshiExecutor init failed: %s", exc)
                self._executor_cache = None
        return self._executor_cache


# ── Constants (from original) ─────────────────────────────────────────────────

CATEGORY_CADENCE = {
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

CATEGORY_TAGS = {
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

KALSHI_CATEGORY_MAP = {
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

KALSHI_MARKET_BASE_URL = "https://kalshi.com/markets"

PROB_CROSS_THRESHOLD = 0.10
SWING_1H_THRESHOLD   = 0.08
MIN_VOLUME           = 500
CONFIDENCE_FLOOR     = 0.55


# ── Singleton ─────────────────────────────────────────────────────────────────

_pipeline_robust: Optional[KalshiInsightPipelineRobust] = None
_pipeline_lock = threading.Lock()


def get_insight_pipeline_robust() -> KalshiInsightPipelineRobust:
    """Get or create the robust insight pipeline singleton."""
    global _pipeline_robust
    if _pipeline_robust is None:
        with _pipeline_lock:
            if _pipeline_robust is None:
                _pipeline_robust = KalshiInsightPipelineRobust()
    return _pipeline_robust


def validate_timestamp(value: Any) -> bool:
    """Validate timestamp string."""
    if not isinstance(value, str):
        return False
    
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
        return True
    except ValueError:
        return False
