"""
Intelligence API - Institutional-Grade Multi-Source News Aggregation
Bloomberg Terminal-grade intelligence feed with sentiment analysis

Sources:
- CoinGecko News API
- CryptoPanic API
- CoinDesk RSS
- CoinTelegraph RSS
- Decrypt RSS
- TheBlock RSS
- Messari API
- DeFi Pulse
"""

from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
import httpx
import re
import os

from web.api.auth import get_current_session
from utils.logger import get_logger
logger = get_logger("intelligence")

# P1 FIX: Semaphore to limit concurrent sentiment analysis (prevents CPU spikes during RSS processing)
_SENTIMENT_SEMAPHORE = asyncio.Semaphore(5)


# ═══════════════════════════════════════════════════════════════════════════
# Sentiment Analysis Functions (defined early to avoid scope issues)
# ═══════════════════════════════════════════════════════════════════════════

def analyze_sentiment(text: str) -> float:
    """Simple sentiment analysis based on keywords.

    Returns a sentiment score between -1.0 (very negative) and +1.0 (very positive).
    """
    if not text:
        return 0.0

    # Positive crypto keywords
    positive_keywords = [
        'bull', 'bullish', 'surge', 'rally', 'moon', 'rocket', ' ATH', 'all-time high',
        'breakout', 'adoption', 'partnership', 'upgrade', 'launch', 'mainnet',
        'staking', 'defi', 'nft', 'metaverse', 'institutional', 'etf', 'approval',
        'regulated', 'compliant', 'secure', 'fast', 'scalable', 'innovation',
        'growth', 'profit', 'gain', 'success', 'milestone', 'victory'
    ]

    # Negative crypto keywords
    negative_keywords = [
        'bear', 'bearish', 'crash', 'dump', 'rug', 'hack', 'exploit', 'vulnerability',
        'security breach', 'investigation', 'lawsuit', 'sec', 'regulatory action',
        'ban', 'prohibition', 'fraud', 'scam', 'ponzi', 'collapse', 'liquidation',
        'delist', 'delisting', 'delay', 'postponed', 'failed', 'failure', 'death',
        'dead', 'bear market', 'recession', 'inflation crisis', 'bankruptcy'
    ]

    text_lower = text.lower()

    # Count keyword matches
    positive_count = sum(1 for keyword in positive_keywords if keyword in text_lower)
    negative_count = sum(1 for keyword in negative_keywords if keyword in text_lower)

    total = positive_count + negative_count
    if total == 0:
        return 0.0

    # Calculate normalized sentiment score
    sentiment_score = (positive_count - negative_count) / max(total, 3)
    return max(-1.0, min(1.0, sentiment_score))


async def analyze_sentiment_async(text: str) -> float:
    """Async wrapper for sentiment analysis with semaphore-based rate limiting.

    This function wraps the synchronous analyze_sentiment() for use in async
    contexts (RSS feed processing). Uses a semaphore to limit concurrent sentiment
    analysis and prevent CPU spikes during bulk processing.

    Args:
        text: Input text to analyze

    Returns:
        Float sentiment score in range [-1.0, 1.0], or 0.0 on any error
    """
    if not text or not text.strip():
        return 0.0

    try:
        # Use semaphore to limit concurrent sentiment analysis
        async with _SENTIMENT_SEMAPHORE:
            # Run sync function in thread pool to not block event loop
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, analyze_sentiment, text)
            return float(result) if result is not None else 0.0
    except Exception as exc:
        # Log at DEBUG level - sentiment failures are non-critical
        logger.debug(f'[INTEL-SENTIMENT] Sentiment analysis failed (returning neutral): {exc}')
        return 0.0


def categorize_news(text: str) -> str:
    """Categorize news based on content."""
    text_lower = text.lower()

    categories = {
        'regulation': ['regulation', 'sec', 'regulatory', 'compliance', 'legal', 'lawsuit', 'court'],
        'technology': ['upgrade', 'protocol', 'network', 'blockchain', 'technology', 'development', 'launch'],
        'market': ['price', 'market', 'trading', 'volume', 'rally', 'crash', 'surge', 'drop'],
        'defi': ['defi', 'lending', 'yield', 'liquidity', 'dex', 'swap', 'pool'],
        'nft': ['nft', 'collectible', 'metaverse', 'gaming', 'art'],
        'adoption': ['adoption', 'partnership', 'integration', 'payment', 'merchant', 'institutional'],
        'security': ['hack', 'security', 'vulnerability', 'exploit', 'breach', 'attack']
    }

    for category, keywords in categories.items():
        if any(keyword in text_lower for keyword in keywords):
            return category

    return 'general'


router = APIRouter(prefix="/api/v1/intelligence", tags=["intelligence"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

# Global caches
_news_cache: List[dict] = []
_defi_cache: Dict = {}
_market_signals_cache: List[dict] = []
_last_news_update = datetime.now(timezone.utc)
_last_defi_update = datetime.now(timezone.utc)

# API Keys from environment
MESSARI_API_KEY = os.getenv("MESSARI_API_KEY", "")



async def fetch_coingecko_news():
    """Fetch news from CoinGecko."""
    try:
        
        def sync_fetch():
            with httpx.Client(timeout=15.0, verify=False) as client:
                # v3/news deprecated (422) — use search/trending instead
                url = "https://api.coingecko.com/api/v3/search/trending"
                return client.get(url)
        
        response = await asyncio.get_running_loop().run_in_executor(None, sync_fetch)
        
        if response.status_code == 200:
            data = response.json()
            coins = data.get('coins', [])
            logger.info(f"[Intelligence] CoinGecko trending: {len(coins)} coins")
            return [
                {
                    'title': f"{c.get('item', {}).get('name', '?')} ({c.get('item', {}).get('symbol', '?')}) trending on CoinGecko",
                    'description': f"Market cap rank #{c.get('item', {}).get('market_cap_rank', '?')} — score {c.get('item', {}).get('score', 0)}",
                    'url': f"https://www.coingecko.com/en/coins/{c.get('item', {}).get('id', '')}",
                    'source': 'CoinGecko',
                    'author': 'CoinGecko Trending',
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'sentiment': 0.3,
                    'category': 'trending'
                }
                for c in coins[:20]
            ]
        else:
            logger.debug(f"[Intelligence] CoinGecko returned status {response.status_code}")
    except Exception as e:
        import traceback
        logger.error(f"[Intelligence] Error fetching CoinGecko news: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
    return []


async def fetch_cryptopanic_news():
    """Fetch news from CryptoPanic (free tier)."""
    try:
        
        def sync_fetch():
            with httpx.Client(timeout=15.0, verify=False) as client:
                url = "https://cryptopanic.com/api/v1/posts/?auth_token=free&public=true"
                return client.get(url)
        
        response = await asyncio.get_running_loop().run_in_executor(None, sync_fetch)
        
        if response.status_code == 200:
            data = response.json()
            return [
                {
                    'title': item.get('title', 'No title'),
                    'description': item.get('title', '')[:300],
                    'url': item.get('url', ''),
                    'source': 'CryptoPanic',
                    'author': item.get('source', {}).get('title', 'Unknown'),
                    'timestamp': item.get('published_at', datetime.now(timezone.utc).isoformat()),
                    'sentiment': analyze_sentiment(item.get('title', '')),
                    'category': categorize_news(item.get('title', '')),
                    'votes': {
                        'positive': item.get('votes', {}).get('positive', 0),
                        'negative': item.get('votes', {}).get('negative', 0),
                        'important': item.get('votes', {}).get('important', 0)
                    }
                }
                for item in data.get('results', [])[:20]
            ]
    except Exception as e:
        logger.error(f"[Intelligence] Error fetching CryptoPanic news: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
    return []


async def fetch_rss_feed(url: str, source_name: str):
    """Generic RSS feed fetcher with hardened per-article error handling.

    Each article is processed in its own try/except block so that one malformed
    article or sentiment analysis failure doesn't break the entire feed.
    Errors are logged at DEBUG level (not ERROR) to avoid spamming error budget.
    """
    try:

        def sync_fetch():
            with httpx.Client(timeout=15.0, verify=False) as client:
                return client.get(url)

        response = await asyncio.get_running_loop().run_in_executor(None, sync_fetch)

        if response.status_code == 200:
            content = response.text
            root = ET.fromstring(content)
            items = []
            article_errors = 0

            for item in root.findall('.//item')[:15]:
                try:
                    title = item.find('title')
                    desc = item.find('description')
                    link = item.find('link')
                    pub_date = item.find('pubDate')

                    title_text = title.text if title is not None else 'No title'
                    desc_text = desc.text if desc is not None else ''
                    # Clean HTML from description
                    desc_text = re.sub(r'<[^>]+>', '', desc_text)[:300]

                    # P1 FIX: Use async sentiment analysis with semaphore rate limiting
                    # Any exception here is caught and returns 0.0 (neutral)
                    sentiment_score = await analyze_sentiment_async(title_text + ' ' + desc_text)

                    items.append({
                        'title': title_text,
                        'description': desc_text,
                        'url': link.text if link is not None else '',
                        'source': source_name,
                        'author': source_name,
                        'timestamp': pub_date.text if pub_date is not None else datetime.now(timezone.utc).isoformat(),
                        'sentiment': sentiment_score,
                        'category': categorize_news(title_text + ' ' + desc_text)
                    })
                except Exception as article_exc:
                    # Per-article error handling - don't let one bad article break the feed
                    article_errors += 1
                    logger.debug(f"[INTEL-RSS] Skipped malformed article from {source_name}: {article_exc}")
                    continue

            # Log summary if there were article-level errors (but feed still succeeded)
            if article_errors > 0:
                logger.debug(f"[INTEL-RSS] {source_name}: processed {len(items)} articles, skipped {article_errors} malformed")

            return items
        else:
            # Non-200 response - log at DEBUG (not ERROR) to avoid budget spam
            logger.debug(f"[INTEL-RSS] {source_name} returned status {response.status_code}")
    except Exception as e:
        # Feed-level errors logged at WARNING (not ERROR) - RSS failures are non-critical
        logger.warning(f"[INTEL-RSS] Feed fetch failed for {source_name}: {type(e).__name__}")
    return []


async def fetch_coindesk_news():
    """Fetch news from CoinDesk RSS."""
    return await fetch_rss_feed('https://www.coindesk.com/arc/outboundfeeds/rss/', 'CoinDesk')


async def fetch_cointelegraph_news():
    """Fetch news from CoinTelegraph RSS."""
    return await fetch_rss_feed('https://cointelegraph.com/rss', 'CoinTelegraph')


async def fetch_decrypt_news():
    """Fetch news from Decrypt RSS."""
    return await fetch_rss_feed('https://decrypt.co/feed', 'Decrypt')


async def fetch_theblock_news():
    """Fetch news from TheBlock RSS."""
    return await fetch_rss_feed('https://www.theblock.co/rss.xml', 'TheBlock')


async def fetch_messari_news():
    """Fetch news/research from Messari API."""
    if not MESSARI_API_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:
            headers = {'x-messari-api-key': MESSARI_API_KEY}
            url = 'https://data.messari.io/api/v1/news'
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                data = response.json()
                return [
                    {
                        'title': item.get('title', 'No title'),
                        'description': item.get('content', '')[:300],
                        'url': item.get('url', ''),
                        'source': 'Messari',
                        'author': item.get('author', {}).get('name', 'Messari Research'),
                        'timestamp': item.get('published_at', datetime.now(timezone.utc).isoformat()),
                        'sentiment': analyze_sentiment(item.get('title', '')),
                        'category': 'research',
                        'tags': item.get('tags', [])
                    }
                    for item in data.get('data', [])[:15]
                ]
    except Exception as e:
        logger.debug(f"[Intelligence] Messari news skipped: {type(e).__name__}: {e}")
    return []


async def fetch_defi_pulse_data():
    """Fetch DeFi protocol TVL data."""
    global _defi_cache, _last_defi_update
    try:
        
        def sync_fetch():
            with httpx.Client(timeout=30.0, verify=False) as client:
                url = 'https://api.llama.fi/protocols'
                return client.get(url)
        
        response = await asyncio.get_running_loop().run_in_executor(None, sync_fetch)
        
        if response.status_code == 200:
            data = response.json()
            # Get top 50 protocols by TVL
            protocols = sorted(data, key=lambda x: x.get('tvl') or 0, reverse=True)[:50]
            _defi_cache = {
                'protocols': [
                    {
                        'name': p.get('name'),
                        'symbol': p.get('symbol'),
                        'tvl': p.get('tvl') or 0,
                        'tvl_change_24h': p.get('change_1d') or 0,
                        'tvl_change_7d': p.get('change_7d') or 0,
                        'category': p.get('category', 'Unknown'),
                        'chain': p.get('chain', 'Multi'),
                        'chains': p.get('chains', []),
                        'url': p.get('url', '')
                    }
                    for p in protocols
                ],
                'total_tvl': sum(p.get('tvl') or 0 for p in protocols),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            _last_defi_update = datetime.now(timezone.utc)
            logger.info(f"[Intelligence] Fetched {len(protocols)} DeFi protocols")
            return _defi_cache
    except Exception as e:
        logger.error(f"[Intelligence] Error fetching DeFi data: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
    return _defi_cache


async def fetch_fear_greed_index():
    """Fetch Crypto Fear & Greed Index."""
    try:
        
        def sync_fetch():
            with httpx.Client(timeout=15.0, verify=False) as client:
                url = 'https://api.alternative.me/fng/?limit=30'
                return client.get(url)
        
        response = await asyncio.get_running_loop().run_in_executor(None, sync_fetch)
        
        if response.status_code == 200:
            data = response.json()
            return {
                'current': data.get('data', [{}])[0],
                'history': data.get('data', [])[:30]
            }
    except Exception as e:
        logger.error(f"[Intelligence] Error fetching Fear & Greed: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
    return {'current': {}, 'history': []}


async def fetch_global_market_data():
    """Fetch global crypto market data from CoinGecko."""
    try:
        
        def sync_fetch():
            with httpx.Client(timeout=15.0, verify=False) as client:
                url = 'https://api.coingecko.com/api/v3/global'
                return client.get(url)
        
        response = await asyncio.get_running_loop().run_in_executor(None, sync_fetch)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('data', {})
    except Exception as e:
        logger.error(f"[Intelligence] Error fetching global market data: {e}")
    return {}


async def fetch_trending_coins():
    """Fetch trending coins from CoinGecko."""
    try:
        
        def sync_fetch():
            with httpx.Client(timeout=15.0, verify=False) as client:
                url = 'https://api.coingecko.com/api/v3/search/trending'
                return client.get(url)
        
        response = await asyncio.get_running_loop().run_in_executor(None, sync_fetch)
        
        if response.status_code == 200:
            data = response.json()
            return data.get('coins', [])
    except Exception as e:
        logger.error(f"[Intelligence] Error fetching trending coins: {type(e).__name__}: {str(e)}")
        logger.error(traceback.format_exc())
    return []


async def aggregate_news():
    """Aggregate news from all institutional-grade sources."""
    global _news_cache, _last_news_update
    
    logger.info("[Intelligence] Aggregating news from 8 institutional sources...")
    # Fetch from all sources in parallel
    results = await asyncio.gather(
        fetch_coingecko_news(),
        fetch_cryptopanic_news(),
        fetch_coindesk_news(),
        fetch_cointelegraph_news(),
        fetch_decrypt_news(),
        fetch_theblock_news(),
        fetch_messari_news(),
        return_exceptions=True
    )
    
    # Combine results
    all_news = []
    source_counts = {}
    for result in results:
        if isinstance(result, list):
            for item in result:
                source = item.get('source', 'Unknown')
                source_counts[source] = source_counts.get(source, 0) + 1
            all_news.extend(result)
    
    # Remove duplicates based on title similarity
    unique_news = []
    seen_titles = set()
    
    for news in all_news:
        title_key = news['title'].lower()[:50]
        if title_key not in seen_titles:
            seen_titles.add(title_key)
            unique_news.append(news)
    
    # Sort by timestamp (newest first)
    if not unique_news:
        logger.info("[Intelligence] No news available from remote sources")
    else:
        logger.info(f"[Intelligence] Sources: {source_counts}")
    unique_news.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    _news_cache = unique_news[:100]  # Keep top 100 for institutional coverage
    _last_news_update = datetime.now(timezone.utc)
    
    logger.info(f"[Intelligence] Aggregated {len(_news_cache)} unique news items from {len(source_counts)} sources")
@router.get("/news")
async def get_news(
    category: Optional[str] = Query(None, description="Filter by category: regulation, technology, market, defi, nft, adoption, security, general"),
    sentiment: Optional[str] = Query(None, description="Filter by sentiment: positive, negative, neutral"),
    source: Optional[str] = Query(None, description="Filter by source: CoinGecko, CryptoPanic"),
    limit: Optional[int] = Query(50, description="Limit number of results")
):
    """Get aggregated news with filtering."""
    # Update if cache is stale (older than 5 minutes)
    if not _news_cache or (datetime.now(timezone.utc) - _last_news_update).total_seconds() > 300:
        await aggregate_news()
    
    news = list(_news_cache)
    
    # Apply filters
    if category:
        news = [n for n in news if n.get('category') == category]
    
    if sentiment:
        news = [n for n in news if n.get('sentiment', {}).get('label') == sentiment]
    
    if source:
        news = [n for n in news if n.get('source') == source]
    
    # Apply limit
    news = news[:limit]
    
    return {
        'status': 'success',
        'news': news,
        'count': len(news),
        'total_cached': len(_news_cache),
        'last_update': _last_news_update.isoformat(),
        'filters': {
            'category': category,
            'sentiment': sentiment,
            'source': source,
            'limit': limit
        }
    }


@router.get("/news/categories")
async def get_news_categories():
    """Get available news categories with counts."""
    if not _news_cache:
        await aggregate_news()
    
    categories = {}
    sentiments = {}
    sources = {}
    
    for news in _news_cache:
        cat = news.get('category', 'general')
        categories[cat] = categories.get(cat, 0) + 1
        
        sent = news.get('sentiment', {}).get('label', 'neutral')
        sentiments[sent] = sentiments.get(sent, 0) + 1
        
        src = news.get('source', 'Unknown')
        sources[src] = sources.get(src, 0) + 1
    
    return {
        'status': 'success',
        'categories': categories,
        'sentiments': sentiments,
        'sources': sources
    }


@router.get("/news/trending")
async def get_trending_topics():
    """Get trending topics from news."""
    if not _news_cache:
        await aggregate_news()
    
    # Extract keywords from titles
    word_freq = {}
    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'be', 'been', 'being'}
    
    for news in _news_cache:
        title = news.get('title', '').lower()
        words = re.findall(r'\b[a-z]{3,}\b', title)
        for word in words:
            if word not in stop_words:
                word_freq[word] = word_freq.get(word, 0) + 1
    
    # Get top 20 trending words
    trending = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:20]
    
    return {
        'status': 'success',
        'trending': [{'word': word, 'count': count} for word, count in trending]
    }


@router.get("/news/sentiment/overview")
async def get_sentiment_overview():
    """Get overall sentiment analysis."""
    if not _news_cache:
        await aggregate_news()
    
    sentiments = {'positive': 0, 'negative': 0, 'neutral': 0}
    total_score = 0
    
    for news in _news_cache:
        sentiment = news.get('sentiment', {})
        label = sentiment.get('label', 'neutral')
        score = sentiment.get('score', 0)
        
        sentiments[label] = sentiments.get(label, 0) + 1
        total_score += score
    
    total = len(_news_cache)
    avg_sentiment = total_score / total if total > 0 else 0
    
    return {
        'status': 'success',
        'overview': {
            'total_articles': total,
            'sentiment_distribution': sentiments,
            'average_sentiment': avg_sentiment,
            'market_mood': 'bullish' if avg_sentiment > 0.2 else 'bearish' if avg_sentiment < -0.2 else 'neutral'
        }
    }


@router.post("/news/refresh")
async def refresh_news():
    """Force refresh news from all sources."""
    await aggregate_news()
    
    return {
        'status': 'success',
        'message': 'News refreshed',
        'count': len(_news_cache),
        'timestamp': datetime.now(timezone.utc).isoformat()
    }


@router.get("/defi")
async def get_defi_data():
    """Get DeFi protocol TVL data from DefiLlama."""
    global _defi_cache, _last_defi_update
    
    # Update if cache is stale (older than 10 minutes)
    if not _defi_cache or (datetime.now(timezone.utc) - _last_defi_update).total_seconds() > 600:
        await fetch_defi_pulse_data()
    
    return {
        'status': 'success',
        'data': _defi_cache,
        'last_update': _last_defi_update.isoformat()
    }


@router.get("/market/fear-greed")
async def get_fear_greed():
    """Get Crypto Fear & Greed Index."""
    data = await fetch_fear_greed_index()
    return {
        'status': 'success',
        'data': data
    }


@router.get("/market/global")
async def get_global_market():
    """Get global crypto market data."""
    data = await fetch_global_market_data()
    return {
        'status': 'success',
        'data': data
    }


@router.get("/market/trending")
async def get_trending():
    """Get trending coins."""
    data = await fetch_trending_coins()
    return {
        'status': 'success',
        'coins': data
    }


@router.get("/dashboard")
async def get_intelligence_dashboard():
    """Get comprehensive intelligence dashboard data."""
    # Fetch all data in parallel
    news_task = aggregate_news() if not _news_cache else asyncio.sleep(0)
    defi_task = fetch_defi_pulse_data() if not _defi_cache else asyncio.sleep(0)
    
    fear_greed, global_market, trending = await asyncio.gather(
        fetch_fear_greed_index(),
        fetch_global_market_data(),
        fetch_trending_coins(),
        return_exceptions=True
    )
    
    # Calculate sentiment overview
    sentiments = {'positive': 0, 'negative': 0, 'neutral': 0}
    for news in _news_cache:
        label = news.get('sentiment', {}).get('label', 'neutral')
        sentiments[label] = sentiments.get(label, 0) + 1
    
    return {
        'status': 'success',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'news': {
            'count': len(_news_cache),
            'latest': _news_cache[:10],
            'sentiment_distribution': sentiments
        },
        'defi': {
            'total_tvl': _defi_cache.get('total_tvl', 0) if _defi_cache else 0,
            'top_protocols': _defi_cache.get('protocols', [])[:10] if _defi_cache else []
        },
        'market': {
            'fear_greed': fear_greed if not isinstance(fear_greed, Exception) else {},
            'global': global_market if not isinstance(global_market, Exception) else {},
            'trending': trending if not isinstance(trending, Exception) else []
        }
    }
