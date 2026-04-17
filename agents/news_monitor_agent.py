"""
News Monitor Agent for MERID — Kalshi-Market-Driven Edition.

DISCOVER: Monitors crypto news feeds
ANALYZE: Converts headlines → per-market MarketOpinions (BTC/ETH/SOL/XRP/DOGE)
CONSENSUS: Submits opinions to SwarmConsensusAggregator per Kalshi ticker

Key change: Every opinion is keyed to a specific Kalshi market ticker
(e.g., "KXBTC-15M", "KXETH-D1") rather than floating as abstract news items.
"""

from __future__ import annotations

import html
import threading
import asyncio
import time
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from monitoring.news_feeds import AggregatedNewsFeed
from config.crypto_universe import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_TIMEFRAMES,
    get_kalshi_series_ticker,
)
from utils.logger import get_logger

logger = get_logger("agents.news_monitor_agent")


class _DisabledTwitter:
    """Placeholder when OrchestratorAgentManager does not inject TwitterAgent."""

    enabled = False

    def post_tweet(self, text: str):
        return None


class _DisabledTelegram:
    """Placeholder when OrchestratorAgentManager does not inject TelegramAgent."""

    enabled = False

    async def send_message(self, text: str):
        return None


# ── Kalshi Crypto Markets We Track ─────────────────────────────────────────
# Dynamically generate all 25 pairs from crypto_universe config

def _generate_kalshi_crypto_markets() -> List[tuple]:
    """Generate all 25 (ticker, asset, timeframe) tuples from crypto_universe."""
    markets = []
    for asset in ACTIVE_CRYPTO_ASSETS:
        for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
            ticker = get_kalshi_series_ticker(asset, timeframe)
            markets.append((ticker, asset, timeframe))
    return markets

KALSHI_CRYPTO_MARKETS = _generate_kalshi_crypto_markets()


# ── News Impact Model ───────────────────────────────────────────────────────

class NewsImpact(str, Enum):
    """Impact classification for a headline on crypto markets."""
    STRONG_BULLISH = "strong_bullish"   # ETF approval, major adoption
    BULLISH = "bullish"                  # Positive news
    NEUTRAL = "neutral"                  # No clear impact
    BEARISH = "bearish"                  # Negative news
    STRONG_BEARISH = "strong_bearish"    # Major hack, regulatory ban


@dataclass
class HeadlineImpact:
    """Scored impact of a headline on specific assets."""
    headline: str
    source: str
    url: str
    published_at: datetime
    importance: float  # 0-1
    
    # Per-asset impact scores (-1 to +1) - dynamic dict for all assets
    asset_impacts: Dict[str, float] = field(default_factory=dict)
    
    # Timeframe relevance (which Kalshi timeframes does this affect)
    timeframe_relevance: Dict[str, bool] = field(default_factory=lambda: {
        "15m": False,
        "1h": True,      # Default: most news affects hourly
        "daily": True,
        "weekly": False,
        "monthly": False,
    })
    
    def get_asset_impact(self, asset: str) -> float:
        """Get impact score for a specific asset."""
        return self.asset_impacts.get(asset.upper(), 0.0)
    
    def get_relevant_timeframes(self) -> List[str]:
        """Get list of timeframes this news affects."""
        return [tf for tf, relevant in self.timeframe_relevance.items() if relevant]


@dataclass
class NewsItem:
    """Legacy News item structure (kept for backward compat)."""
    title: str
    source: str
    url: str
    published_at: datetime
    importance: float
    posted_twitter: bool = False
    posted_telegram: bool = False
    
    # New: linked market opinions
    market_opinions: List["MarketOpinion"] = field(default_factory=list)


class NewsMonitorAgent:
    """
    Kalshi-Market-Driven News Monitor Agent.
    
    DISCOVER: Monitors crypto news feeds
    ANALYZE: Converts headlines → per-market MarketOpinions  
    CONSENSUS: Submits opinions to SwarmConsensusAggregator
    
    Key change: No longer directly posts to social media. Instead,
    generates MarketOpinions that flow through the unified consensus
    pipeline alongside momentum, RTI, and other signal sources.
    """
    
    def __init__(self, importance_threshold: float = 0.7):
        """
        Initialize news monitor agent.
        
        Args:
            importance_threshold: Minimum importance score (0-1) for processing
        """
        self.news_aggregator = AggregatedNewsFeed()
        
        self.importance_threshold = importance_threshold
        self.posted_news: List[NewsItem] = []
        self.seen_urls: set = set()
        
        self.running = False
        self.check_interval = 60  # Check every 60 seconds
        
        # Opinion tracking: ticker -> list of MarketOpinions generated
        self._market_opinions: Dict[str, List["MarketOpinion"]] = {}
        self._consensus_submitted: int = 0

        # Wired by web.startup_agents.OrchestratorAgentManager when Twitter/Telegram are available
        self.twitter_agent = _DisabledTwitter()
        self.telegram_agent = _DisabledTelegram()
        self.last_telegram_post = 0.0
        self.telegram_min_interval = 300.0
        self.telegram_queue: List[NewsItem] = []
        
        logger.info(f"NewsMonitorAgent initialized (threshold: {importance_threshold}) — Kalshi-market-driven edition")
    
    async def start_monitoring(self):
        """Start continuous news monitoring."""
        self.running = True
        logger.info("News monitoring started")
        
        while self.running:
            try:
                await self.check_and_post_news()
                await asyncio.sleep(self.check_interval)
            except Exception as exc:
                logger.error(f"Error in news monitoring loop: {exc}")
                await asyncio.sleep(self.check_interval)
    
    def stop_monitoring(self):
        """Stop news monitoring."""
        self.running = False
        logger.info("News monitoring stopped")
    
    async def check_and_post_news(self):
        """Check for new important news and post to social media."""
        try:
            # Process any queued Telegram posts first
            await self._process_telegram_queue()
            # fetch_all() uses sync httpx.Client across 4 sources — offload to
            # executor so the 4 sequential HTTP calls (~3-11s) don't block the loop.
            loop = asyncio.get_running_loop()
            all_news_articles = await loop.run_in_executor(
                None, self.news_aggregator.fetch_all, 5
            )
            
            # Convert to dict format
            all_news = [
                {
                    'title': article.headline,
                    'source': article.source,
                    'url': article.url,
                    'published_at': datetime.fromtimestamp(article.published_at, tz=timezone.utc),
                    'importance': 0.9 if article.importance == 'high' else 0.7 if article.importance == 'medium' else 0.5
                }
                for article in all_news_articles
            ]
            
            if not all_news:
                logger.debug("No news items fetched")
                return
            
            # Filter for new, important news
            new_important_news = []
            for news in all_news:
                # Skip if already seen
                if news['url'] in self.seen_urls:
                    continue
                
                # Check importance threshold
                if news['importance'] >= self.importance_threshold:
                    news_item = NewsItem(
                        title=news['title'],
                        source=news['source'],
                        url=news['url'],
                        published_at=news['published_at'],
                        importance=news['importance']
                    )
                    new_important_news.append(news_item)
                    self.seen_urls.add(news['url'])
            
            # Post new important news
            for news_item in new_important_news:
                await self.post_breaking_news(news_item)
                # Rate limiting between posts
                await asyncio.sleep(5)
            
            if new_important_news:
                logger.info(f"Posted {len(new_important_news)} breaking news items")
            
        except Exception as exc:
            logger.error(f"Error checking news: {exc}")
    
    async def post_breaking_news(self, news_item: NewsItem):
        """
        Post breaking news to X and Telegram via Simulation → Consensus → Post flow.
        
        Flow:
        1. News → Simulation Layer (process and analyze)
        2. Simulation → Consensus (weighted voting)
        3. Consensus → Post to Twitter/Telegram
        
        Args:
            news_item: News item to post
        """
        try:
            # Step 1: Run through simulation layer
            simulation_result = await self._run_news_simulation(news_item)
            
            if not simulation_result['proceed']:
                logger.info(f"News rejected by simulation: {news_item.title[:50]}...")
                return
            
            # Step 2: Get consensus from agents (using simulation results)
            consensus_result = await self._get_consensus_for_news(news_item, simulation_result)
            
            if not consensus_result['approved']:
                logger.info(f"News rejected by consensus: {news_item.title[:50]}...")
                # Store rejection in reflection layer
                await self._store_news_outcome(news_item, simulation_result, consensus_result, posted=False)
                return
            
            # Prepare full context for posting
            full_context = {
                'simulation': simulation_result,
                'consensus': consensus_result,
                'news': news_item
            }
            
            # T-066: Sanitize external content before social posting
            _sanitized_headline = self._sanitize_headline(news_item.title)
            if _sanitized_headline is None:
                logger.warning("Headline blocked by sanitization: %s", news_item.title[:80])
            else:
                # Post to Twitter (no throttle)
                if self.twitter_agent.enabled:
                    tweet_text = (
                        f"🗞️ {_sanitized_headline}\n"
                        f"via {news_item.source}\n"
                        f"#Kalshi #PredictionMarkets"
                    )
                    tweet = self.twitter_agent.post_tweet(tweet_text)
                    if tweet:
                        news_item.posted_twitter = True
                        logger.info(f"Posted to Twitter: {_sanitized_headline[:50]}...")
            
            # Post to Telegram with throttle
            if self.telegram_agent.enabled:
                current_time = time.time()
                time_since_last = current_time - self.last_telegram_post
                
                if time_since_last >= self.telegram_min_interval:
                    # Build detailed message with simulation and consensus data
                    message_text = self._build_detailed_message(
                        news_item=news_item,
                        simulation_result=simulation_result,
                        consensus_result=consensus_result
                    )
                    
                    # Send via Telegram
                    telegram_msg = await self.telegram_agent.send_message(message_text)
                    if telegram_msg:
                        news_item.posted_telegram = True
                        self.last_telegram_post = current_time
                        logger.info(f"Posted to Telegram: {news_item.title[:50]}...")
                else:
                    # Queue for later
                    self.telegram_queue.append(news_item)
                    wait_time = self.telegram_min_interval - time_since_last
                    logger.info(f"Telegram throttled. Queued news. Wait {wait_time:.0f}s")
            
            # Track posted news and store outcome
            self.posted_news.append(news_item)
            await self._store_news_outcome(news_item, simulation_result, consensus_result, posted=True)
            
        except Exception as exc:
            logger.error(f"Error posting news: {exc}")
    
    def get_recent_posts(self, limit: int = 10) -> List[NewsItem]:
        """Get recently posted news items."""
        return self.posted_news[-limit:]
    
    async def _run_news_simulation(self, news_item: NewsItem) -> Dict:
        """
        ANALYZE: Convert news headline → per-market MarketOpinions.
        
        This replaces the old abstract 'energy' simulation with concrete
        market opinions keyed to specific Kalshi tickers.
        
        Args:
            news_item: News item to analyze
            
        Returns:
            Simulation result with proceed flag and generated MarketOpinions
        """
        try:
            # Step 1: Score headline impact on each asset
            impact = self._analyze_headline_impact(news_item)
            
            # Step 2: Generate MarketOpinions for relevant markets
            opinions: List["MarketOpinion"] = []
            
            for ticker, asset, timeframe in KALSHI_CRYPTO_MARKETS:
                # Check if this asset is affected
                asset_impact = impact.get_asset_impact(asset)
                if abs(asset_impact) < 0.2:  # Skip negligible impacts
                    continue
                    
                # Check if this timeframe is relevant
                if timeframe not in impact.get_relevant_timeframes():
                    continue
                
                # Build MarketOpinion
                from merid.prediction.market_opinion import (
                    MarketOpinion, OpinionSource, OpinionDirection,
                    build_market_opinion_from_news
                )
                
                opinion = build_market_opinion_from_news(
                    ticker=ticker,
                    headline=impact.headline,
                    sentiment_score=asset_impact,
                    source=impact.source,
                    agent_id="news_monitor",
                )
                opinions.append(opinion)
                
                # Log with explicit market ID
                logger.info(opinion.format_log_line())
            
            # Store opinions on the news item
            news_item.market_opinions = opinions
            
            # Proceed if we generated any actionable opinions
            approved = len([o for o in opinions if o.is_actionable()]) > 0
            consensus = 1.0 if approved else 0.0  # Single-agent approval
            
            # Log summary with market IDs
            logger.info(
                f"News ANALYZE complete: {len(opinions)} MarketOpinions generated "
                f"for headline: {impact.headline[:50]}..."
            )
            for op in opinions:
                logger.info(f"  → {op.ticker}: {op.direction.value.upper()} @ {op.confidence:.0%}")
            
            return {
                "proceed": approved,
                "approved": approved,
                "consensus": consensus,
                "opinions": [o.to_dict() for o in opinions],
                "opinion_count": len(opinions),
            }
            
        except (ImportError, ModuleNotFoundError) as exc:
            logger.warning(f"News ANALYZE skipped (missing dependency): {exc}")
            return {
                "proceed": False,
                "approved": False,
                "consensus": 0.0,
                "opinions": [],
                "opinion_count": 0,
                "reason": "missing_dependency",
            }
        except Exception as exc:
            logger.error(f"News ANALYZE error (fail-closed): {exc}", exc_info=True)
            return {
                "proceed": False,
                "approved": False,
                "consensus": 0.0,
                "opinions": [],
                "opinion_count": 0,
                "reason": "analysis_error",
            }
    
    def _analyze_headline_impact(self, news_item: NewsItem) -> HeadlineImpact:
        """
        Score a headline for impact on each crypto asset.
        
        Uses keyword matching to determine bullish/bearish impact
        on BTC, ETH, SOL, XRP, and DOGE.
        """
        headline_lower = news_item.title.lower()
        
        # BTC-specific keywords
        btc_bullish = ["bitcoin", "btc", "etf approval", "institutional", "adoption"]
        btc_bearish = ["bitcoin ban", "mining ban", "btc crackdown"]
        
        # ETH-specific keywords
        eth_bullish = ["ethereum", "eth", "defi", "staking", "eip"]
        eth_bearish = ["ethereum delay", "eth dump"]
        
        # SOL-specific keywords
        sol_bullish = ["solana", "sol", "breakout", "nft"]
        sol_bearish = ["solana outage", "sol down", "outage", "network down", "solana down"]
        
        # XRP-specific keywords
        xrp_bullish = ["ripple", "xrp", "sec victory", "xrp etf"]
        xrp_bearish = ["xrp security", "ripple loss"]
        
        # DOGE-specific keywords
        doge_bullish = ["dogecoin", "doge", "musk", "twitter payment"]
        doge_bearish = ["doge dead", "meme coin crash"]
        
        # General crypto keywords
        general_bullish = ["bullish", "rally", "surge", "moon", " ATH", "all-time high"]
        general_bearish = ["bearish", "crash", "dump", "bear market", "regulation", "ban"]
        
        # Calculate per-asset scores
        def score_impact(bullish: List[str], bearish: List[str]) -> float:
            bull_score = sum(0.3 for kw in bullish if kw in headline_lower)
            bear_score = sum(-0.3 for kw in bearish if kw in headline_lower)
            return max(-1.0, min(1.0, bull_score + bear_score + news_item.importance * 0.2))
        
        # Build asset impacts dynamically
        asset_impacts = {
            "BTC": score_impact(btc_bullish + general_bullish, btc_bearish + general_bearish),
            "ETH": score_impact(eth_bullish + general_bullish, eth_bearish + general_bearish),
            "SOL": score_impact(sol_bullish + general_bullish, sol_bearish + general_bearish),
            "XRP": score_impact(xrp_bullish + general_bullish, xrp_bearish + general_bearish),
            "DOGE": score_impact(doge_bullish + general_bullish, doge_bearish + general_bearish),
        }
        
        # Determine timeframe relevance
        # "breaking", "alert", "just" → immediate (15m)
        affects_15m = any(kw in headline_lower for kw in ["breaking", "alert", "just", "now"])
        # Most news affects hourly and daily by default
        affects_1h = True
        affects_daily = True
        affects_weekly = False
        affects_monthly = False
        
        return HeadlineImpact(
            headline=news_item.title,
            source=news_item.source,
            url=news_item.url,
            published_at=news_item.published_at,
            importance=news_item.importance,
            asset_impacts=asset_impacts,
            timeframe_relevance={
                "15m": affects_15m,
                "1h": affects_1h,
                "daily": affects_daily,
                "weekly": affects_weekly,
                "monthly": affects_monthly,
            },
        )
    
    async def _get_consensus_for_news(self, news_item: NewsItem, simulation_result: Dict) -> Dict:
        """
        CONSENSUS: Submit MarketOpinions to SwarmConsensusAggregator.
        
        This replaces the old generic consensus with per-market aggregation.
        Each MarketOpinion is submitted to the consensus aggregator keyed by
        its Kalshi ticker, enabling market-specific consensus decisions.
        
        Args:
            news_item: News item with linked MarketOpinions
            simulation_result: Results from ANALYZE step
            
        Returns:
            Dict with approval status and per-market consensus results
        """
        try:
            opinions: List["MarketOpinion"] = news_item.market_opinions
            
            if not opinions:
                logger.info(f"News CONSENSUS: No MarketOpinions to submit for: {news_item.title[:50]}...")
                return {
                    'approved': False,
                    'confidence': 0.0,
                    'market_results': {},
                    'reasoning_summary': 'No actionable opinions generated',
                }
            
            # Submit each opinion to the SwarmConsensusAggregator
            from merid.swarm.consensus_aggregator import get_consensus_aggregator
            aggregator = get_consensus_aggregator()
            
            market_results: Dict[str, Dict] = {}
            approved_count = 0
            
            for opinion in opinions:
                # Convert to AgentProposal and submit
                proposal = opinion.to_agent_proposal()
                aggregator.submit_proposal(proposal)
                self._consensus_submitted += 1
                
                # Get current consensus for this market
                consensus = aggregator.get_consensus(opinion.asset, opinion.timeframe)
                
                if consensus:
                    market_results[opinion.ticker] = {
                        'direction': consensus.consensus_direction,
                        'probability': consensus.consensus_probability,
                        'confidence': consensus.consensus_confidence,
                        'status': consensus.status.value,
                        'voting_agents': consensus.voting_agents,
                        'size_band': consensus.size_band,
                    }
                    
                    # Log with explicit market ID
                    logger.info(
                        f"Consensus for {opinion.ticker}: "
                        f"SIM={consensus.consensus_direction.upper()} @ "
                        f"{consensus.consensus_confidence:.0%} "
                        f"from {consensus.voting_agents} agents"
                    )
                    
                    # Count as approved if consensus is READY with decent confidence
                    if consensus.status.value == "ready" and consensus.consensus_confidence >= 0.5:
                        approved_count += 1
                else:
                    market_results[opinion.ticker] = {
                        'status': 'forming',
                        'message': 'Consensus still forming (insufficient proposals)',
                    }
                    logger.info(f"Consensus for {opinion.ticker}: FORMING (insufficient proposals)")
            
            # Overall approval if any market reached consensus
            approved = approved_count > 0
            avg_confidence = sum(
                r.get('confidence', 0) for r in market_results.values() if 'confidence' in r
            ) / max(1, len([r for r in market_results.values() if 'confidence' in r]))
            
            logger.info(
                "News CONSENSUS complete: %s/%s markets met posting threshold (status=ready & "
                "confidence≥50%%) for: %s...",
                approved_count,
                len(opinions),
                news_item.title[:50],
            )
            
            return {
                'approved': approved,
                'confidence': avg_confidence,
                'market_results': market_results,
                'approved_markets': approved_count,
                'total_markets': len(opinions),
                'reasoning_summary': f"{approved_count}/{len(opinions)} markets reached consensus",
            }
            
        except (ImportError, ModuleNotFoundError) as exc:
            logger.warning(f"News CONSENSUS skipped (missing dependency): {exc}")
            return {
                'approved': False,
                'confidence': 0.0,
                'market_results': {},
                'reasoning_summary': 'Skipped - missing dependency',
                'reason': 'missing_dependency',
            }
        except Exception as exc:
            logger.error(f"News CONSENSUS error (fail-closed): {exc}")
            return {
                'approved': False,
                'confidence': 0.0,
                'market_results': {},
                'reasoning_summary': 'Error - defaulted to REJECTION (fail-closed)',
                'reason': 'consensus_error',
            }

    def _build_detailed_message(
        self,
        *,
        news_item: NewsItem,
        simulation_result: Dict[str, Any],
        consensus_result: Dict[str, Any],
    ) -> str:
        """HTML body for Telegram (parse_mode=HTML). Escapes user-controlled text."""
        h = html.escape
        title = h((news_item.title or "").strip()[:800])
        source = h(news_item.source or "unknown")
        url = (news_item.url or "").strip()
        url_line = f"🔗 <a href=\"{h(url)}\">link</a>" if url else ""

        n_op = int(simulation_result.get("opinion_count") or 0)
        approved_n = consensus_result.get("approved_markets")
        total_n = consensus_result.get("total_markets")
        if approved_n is None:
            approved_n = 1 if consensus_result.get("approved") else 0
        if total_n is None:
            total_n = n_op
        try:
            approved_n = int(approved_n)
        except (TypeError, ValueError):
            approved_n = 0
        try:
            total_n = int(total_n)
        except (TypeError, ValueError):
            total_n = n_op

        conf = float(consensus_result.get("confidence") or 0.0)
        summary = (consensus_result.get("reasoning_summary") or "").strip()
        summary_line = f"<i>{h(summary)}</i>" if summary else ""

        lines: List[str] = [
            f"🗞️ <b>{title}</b>",
            f"📰 {source}",
        ]
        if url_line:
            lines.append(url_line)
        lines.append("")
        lines.append(
            f"📊 Opinions: {n_op} · Consensus: {approved_n}/{max(1, total_n)} · avg conf {conf:.0%}"
        )
        if summary_line:
            lines.append(summary_line)

        market_results = consensus_result.get("market_results") or {}
        if market_results:
            lines.append("")
            lines.append("<b>Markets</b>")
            for ticker, res in list(market_results.items())[:15]:
                if isinstance(res, dict) and "direction" in res:
                    d = h(str(res.get("direction", "")))
                    p = float(res.get("probability") or 0.0)
                    c = float(res.get("confidence") or 0.0)
                    lines.append(f"• {h(ticker)}: {d} p={p:.0%} conf={c:.0%}")
                elif isinstance(res, dict):
                    st = h(str(res.get("status", res.get("message", "?"))))
                    lines.append(f"• {h(ticker)}: {st}")
                else:
                    lines.append(f"• {h(ticker)}: {h(str(res))}")

        out = "\n".join(lines)
        if len(out) > 3800:
            out = out[:3790] + "…"
        return out

    async def _process_telegram_queue(self):
        """Legacy: No-op in market-driven mode."""
        pass

    @staticmethod
    def _sanitize_headline(headline: str) -> Optional[str]:
        """T-066: Sanitize external headline before social posting.
        Returns sanitized headline or None if blocked.
        """
        import re as _re
        if not headline or not headline.strip():
            return None
        # Strip HTML/markdown
        clean = _re.sub(r'<[^>]+>', '', headline)
        clean = _re.sub(r'[*_~`#]', '', clean)
        # Truncate to 280 chars
        clean = clean.strip()[:280]
        # Blocklist for manipulation keywords
        _blocklist = [
            "buy now", "sell now", "guaranteed", "insider", "100x",
            "pump", "moon", "rug", "scam", "free money", "act fast",
        ]
        lower = clean.lower()
        for word in _blocklist:
            if word in lower:
                return None
        return clean if clean else None

    async def _broadcast_simulation_update(self, update_data: Dict):
        """Broadcast simulation update to WebSocket clients."""
        try:
            from web.api.streams import broadcast_simulation_update
            await broadcast_simulation_update(update_data)
        except Exception as exc:
            logger.debug(f"Could not broadcast simulation update: {exc}")
    
    async def _store_news_outcome(self, news_item: NewsItem, simulation_result: Dict, consensus_result: Dict, posted: bool):
        """Log news outcome with market IDs."""
        opinion_count = simulation_result.get('opinion_count', 0)
        approved_markets = consensus_result.get('approved_markets', 0)
        total_markets = consensus_result.get('total_markets', 0)
        
        logger.info(
            f"News outcome: {news_item.title[:50]} - "
            f"Opinions: {opinion_count}, "
            f"Consensus: {approved_markets}/{total_markets} markets, "
            f"Posted: {posted}"
        )
        
        # Log per-market results
        market_results = consensus_result.get('market_results', {})
        for ticker, result in market_results.items():
            if 'direction' in result:
                logger.info(
                    f"  → {ticker}: {result['direction'].upper()} "
                    f"@ {result.get('confidence', 0):.0%} "
                    f"({result.get('status', 'unknown')})"
                )
    
    def get_stats(self) -> Dict:
        """Get news monitoring statistics (market-driven edition)."""
        total_processed = len(self.posted_news)
        
        # Count total MarketOpinions generated
        total_opinions = sum(
            len(item.market_opinions) for item in self.posted_news
        )
        
        # Recent activity (last hour)
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_items = [n for n in self.posted_news if n.published_at >= one_hour_ago]
        recent_opinions = sum(len(item.market_opinions) for item in recent_items)
        
        # Get unique tickers we've generated opinions for
        all_tickers = set()
        for item in self.posted_news:
            for op in item.market_opinions:
                all_tickers.add(op.ticker)
        
        return {
            "running": self.running,
            "total_processed": total_processed,
            "total_opinions_generated": total_opinions,
            "consensus_submitted": self._consensus_submitted,
            "unique_tickers": len(all_tickers),
            "tickers_list": sorted(all_tickers),
            "items_last_hour": len(recent_items),
            "opinions_last_hour": recent_opinions,
            "importance_threshold": self.importance_threshold,
            "sources_monitored": 4,  # CoinDesk, CoinTelegraph, Binance, CryptoCompare
        }


# Global singleton
_news_monitor_agent: Optional[NewsMonitorAgent] = None
_news_monitor_agent_lock = threading.Lock()


def get_news_monitor_agent() -> NewsMonitorAgent:
    """Get or create news monitor agent singleton."""
    global _news_monitor_agent
    if _news_monitor_agent is None:
        with _news_monitor_agent_lock:
            if _news_monitor_agent is None:
                _news_monitor_agent = NewsMonitorAgent(importance_threshold=0.7)
    return _news_monitor_agent
