"""MERID Social Media Sentiment Scraper.

Scrapes Reddit, Twitter/X, and other social platforms for trading sentiment.
Integrates with PRAW, Tweepy, and snscrape for comprehensive coverage.
"""

from typing import List, Dict, Any, Optional, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
import structlog
import os
import re

logger = structlog.get_logger(__name__)


@dataclass
class SocialPost:
    """Social media post/content."""
    id: str
    platform: str
    author: str
    text: str
    created_at: datetime
    tickers: List[str]
    upvotes: int
    comments: int
    sentiment_score: Optional[float]
    url: Optional[str]
    is_reply: bool


class RedditScraper:
    """Reddit scraper using PRAW."""
    
    SUBREDDITS = [
        "wallstreetbets",
        "stocks",
        "investing",
        "StockMarket",
        "options",
        "pennystocks",
        "cryptocurrency",
        "CryptoMarkets"
    ]
    
    def __init__(self):
        self.reddit = None
        self.logger = logger.bind(platform="Reddit")
        self._init_reddit()
    
    def _init_reddit(self):
        """Initialize Reddit API client."""
        try:
            import praw
            
            client_id = os.getenv("REDDIT_CLIENT_ID")
            client_secret = os.getenv("REDDIT_CLIENT_SECRET")
            user_agent = os.getenv("REDDIT_USER_AGENT", "MERID-SentimentBot/1.0")
            
            if client_id and client_secret:
                self.reddit = praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_agent=user_agent
                )
                self.logger.info("reddit_client_initialized")
            else:
                self.logger.warning("reddit_credentials_missing")
                
        except ImportError:
            self.logger.error("praw_not_installed")
        except Exception as e:
            self.logger.error("reddit_init_error", error=str(e))
    
    async def scrape_subreddit(
        self,
        subreddit: str,
        limit: int = 100,
        time_filter: str = "day"
    ) -> List[SocialPost]:
        """Scrape posts from a subreddit."""
        if not self.reddit:
            return []
        
        posts = []
        
        try:
            sub = self.reddit.subreddit(subreddit)
            
            # Get hot posts
            for submission in sub.hot(limit=limit):
                post = self._parse_submission(submission)
                if post:
                    posts.append(post)
                
                # Get top comments
                submission.comments.replace_more(limit=0)
                for comment in submission.comments[:10]:
                    comment_post = self._parse_comment(comment, submission.id)
                    if comment_post:
                        posts.append(comment_post)
            
            self.logger.info(
                "subreddit_scraped",
                subreddit=subreddit,
                count=len(posts)
            )
            
        except Exception as e:
            self.logger.error("subreddit_scrape_error", subreddit=subreddit, error=str(e))
        
        return posts
    
    async def scrape_ticker_mentions(
        self,
        ticker: str,
        subreddits: List[str] = None,
        limit: int = 100
    ) -> List[SocialPost]:
        """Scrape mentions of a specific ticker."""
        subreddits = subreddits or self.SUBREDDITS
        all_posts = []
        
        for subreddit in subreddits:
            posts = await self.scrape_subreddit(subreddit, limit=limit)
            
            # Filter for ticker mentions
            ticker_posts = [
                p for p in posts
                if ticker.upper() in [t.upper() for t in p.tickers]
            ]
            
            all_posts.extend(ticker_posts)
        
        return all_posts
    
    def _parse_submission(self, submission) -> Optional[SocialPost]:
        """Parse a Reddit submission into SocialPost."""
        from core.sentiment_nlp import TickerExtractor
        
        extractor = TickerExtractor()
        tickers = extractor.extract(submission.title + " " + (submission.selftext or ""))
        
        return SocialPost(
            id=submission.id,
            platform="reddit",
            author=str(submission.author),
            text=submission.title + "\n" + (submission.selftext or ""),
            created_at=datetime.fromtimestamp(submission.created_utc),
            tickers=tickers,
            upvotes=submission.score,
            comments=submission.num_comments,
            sentiment_score=None,
            url=f"https://reddit.com{submission.permalink}",
            is_reply=False
        )
    
    def _parse_comment(self, comment, parent_id: str) -> Optional[SocialPost]:
        """Parse a Reddit comment into SocialPost."""
        from core.sentiment_nlp import TickerExtractor
        
        extractor = TickerExtractor()
        tickers = extractor.extract(comment.body)
        
        return SocialPost(
            id=comment.id,
            platform="reddit",
            author=str(comment.author),
            text=comment.body,
            created_at=datetime.fromtimestamp(comment.created_utc),
            tickers=tickers,
            upvotes=comment.score,
            comments=0,
            sentiment_score=None,
            url=f"https://reddit.com{comment.permalink}",
            is_reply=True
        )
    
    async def get_subreddit_sentiment(
        self,
        subreddit: str,
        ticker: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get aggregated sentiment for a subreddit."""
        posts = await self.scrape_subreddit(subreddit, limit=200)
        
        if ticker:
            posts = [p for p in posts if ticker.upper() in [t.upper() for t in p.tickers]]
        
        if not posts:
            return {"sentiment": 0, "volume": 0, "posts": []}
        
        # Calculate metrics
        total_upvotes = sum(p.upvotes for p in posts)
        total_comments = sum(p.comments for p in posts)
        
        return {
            "sentiment": 0,  # Would calculate from NLP
            "volume": len(posts),
            "upvotes": total_upvotes,
            "comments": total_comments,
            "posts": posts[:10]  # Return sample
        }


class TwitterScraper:
    """Twitter/X scraper using Tweepy or snscrape."""
    
    def __init__(self):
        self.client = None
        self.logger = logger.bind(platform="Twitter")
        self._init_twitter()
    
    def _init_twitter(self):
        """Initialize Twitter API client."""
        try:
            import tweepy
            
            bearer_token = os.getenv("TWITTER_BEARER_TOKEN")
            api_key = os.getenv("TWITTER_API_KEY")
            api_secret = os.getenv("TWITTER_API_SECRET")
            access_token = os.getenv("TWITTER_ACCESS_TOKEN")
            access_secret = os.getenv("TWITTER_ACCESS_SECRET")
            
            if bearer_token:
                # v2 API
                self.client = tweepy.Client(
                    bearer_token=bearer_token,
                    consumer_key=api_key,
                    consumer_secret=api_secret,
                    access_token=access_token,
                    access_token_secret=access_secret
                )
                self.logger.info("twitter_v2_client_initialized")
            elif api_key and api_secret:
                # v1.1 API
                auth = tweepy.OAuthHandler(api_key, api_secret)
                auth.set_access_token(access_token, access_secret)
                self.api = tweepy.API(auth)
                self.logger.info("twitter_v1_client_initialized")
            else:
                self.logger.warning("twitter_credentials_missing")
                
        except ImportError:
            self.logger.error("tweepy_not_installed")
        except Exception as e:
            self.logger.error("twitter_init_error", error=str(e))
    
    async def search_tweets(
        self,
        query: str,
        limit: int = 100,
        days_back: int = 1
    ) -> List[SocialPost]:
        """Search tweets by query."""
        if not self.client:
            # Fallback to snscrape
            return await self._search_with_snscrape(query, limit, days_back)
        
        posts = []
        
        try:
            import tweepy
            
            # Calculate start time
            start_time = datetime.now() - timedelta(days=days_back)
            
            # Search tweets
            tweets = tweepy.Paginator(
                self.client.search_recent_tweets,
                query=query,
                tweet_fields=['created_at', 'public_metrics', 'author_id'],
                max_results=min(limit, 100),
                start_time=start_time
            ).flatten(limit=limit)
            
            async for tweet in tweets:
                post = self._parse_tweet(tweet)
                if post:
                    posts.append(post)
            
            self.logger.info("tweets_searched", query=query, count=len(posts))
            
        except Exception as e:
            self.logger.error("twitter_search_error", error=str(e))
        
        return posts
    
    async def search_ticker(
        self,
        ticker: str,
        limit: int = 100
    ) -> List[SocialPost]:
        """Search for ticker mentions on Twitter."""
        query = f"${ticker} OR #{ticker} -is:retweet lang:en"
        return await self.search_tweets(query, limit)
    
    async def _search_with_snscrape(
        self,
        query: str,
        limit: int,
        days_back: int
    ) -> List[SocialPost]:
        """Fallback search using snscrape (no API key needed)."""
        posts = []
        
        try:
            import snscrape.modules.twitter as sntwitter
            
            scraper = sntwitter.TwitterSearchScraper(
                f"{query} since:{days_back}d"
            )
            
            for i, tweet in enumerate(scraper.get_items()):
                if i >= limit:
                    break
                
                from core.sentiment_nlp import TickerExtractor
                extractor = TickerExtractor()
                tickers = extractor.extract(tweet.rawContent)
                
                post = SocialPost(
                    id=str(tweet.id),
                    platform="twitter",
                    author=tweet.user.username,
                    text=tweet.rawContent,
                    created_at=tweet.date,
                    tickers=tickers,
                    upvotes=tweet.likeCount or 0,
                    comments=tweet.replyCount or 0,
                    sentiment_score=None,
                    url=tweet.url,
                    is_reply=False
                )
                posts.append(post)
            
            self.logger.info("snscrape_search_complete", count=len(posts))
            
        except ImportError:
            self.logger.error("snscrape_not_installed")
        except Exception as e:
            self.logger.error("snscrape_error", error=str(e))
        
        return posts
    
    def _parse_tweet(self, tweet) -> Optional[SocialPost]:
        """Parse a tweet into SocialPost."""
        from core.sentiment_nlp import TickerExtractor
        
        extractor = TickerExtractor()
        text = tweet.text if hasattr(tweet, 'text') else str(tweet)
        tickers = extractor.extract(text)
        
        metrics = tweet.public_metrics if hasattr(tweet, 'public_metrics') else {}
        
        return SocialPost(
            id=str(tweet.id),
            platform="twitter",
            author=str(tweet.author_id),
            text=text,
            created_at=tweet.created_at if hasattr(tweet, 'created_at') else datetime.now(),
            tickers=tickers,
            upvotes=metrics.get('like_count', 0) if metrics else 0,
            comments=metrics.get('reply_count', 0) if metrics else 0,
            sentiment_score=None,
            url=f"https://twitter.com/i/web/status/{tweet.id}",
            is_reply=False
        )
    
    async def get_user_timeline(
        self,
        username: str,
        limit: int = 50
    ) -> List[SocialPost]:
        """Get tweets from a specific user."""
        if not self.client:
            return []
        
        posts = []
        
        try:
            # Get user ID
            user = self.client.get_user(username=username)
            if not user.data:
                return []
            
            # Get tweets
            tweets = self.client.get_users_tweets(
                id=user.data.id,
                max_results=min(limit, 100),
                tweet_fields=['created_at', 'public_metrics']
            )
            
            if tweets.data:
                for tweet in tweets.data:
                    post = self._parse_tweet(tweet)
                    if post:
                        posts.append(post)
            
        except Exception as e:
            self.logger.error("timeline_fetch_error", username=username, error=str(e))
        
        return posts


class SocialMediaAggregator:
    """Aggregates social media data from multiple platforms."""
    
    def __init__(self):
        self.reddit = RedditScraper()
        self.twitter = TwitterScraper()
        self.logger = logger.bind(component="SocialMediaAggregator")
    
    async def get_ticker_sentiment(
        self,
        ticker: str,
        platforms: List[str] = None
    ) -> Dict[str, Any]:
        """Get sentiment data for a ticker across platforms."""
        platforms = platforms or ["reddit", "twitter"]
        
        all_posts = []
        platform_data = {}
        
        if "reddit" in platforms:
            reddit_posts = await self.reddit.scrape_ticker_mentions(ticker, limit=100)
            all_posts.extend(reddit_posts)
            platform_data["reddit"] = {
                "count": len(reddit_posts),
                "upvotes": sum(p.upvotes for p in reddit_posts),
                "comments": sum(p.comments for p in reddit_posts)
            }
        
        if "twitter" in platforms:
            twitter_posts = await self.twitter.search_ticker(ticker, limit=100)
            all_posts.extend(twitter_posts)
            platform_data["twitter"] = {
                "count": len(twitter_posts),
                "likes": sum(p.upvotes for p in twitter_posts),
                "replies": sum(p.comments for p in twitter_posts)
            }
        
        # Sort by engagement
        all_posts.sort(key=lambda p: p.upvotes + p.comments, reverse=True)
        
        return {
            "ticker": ticker,
            "total_posts": len(all_posts),
            "platforms": platform_data,
            "top_posts": all_posts[:20],
            "timestamp": datetime.now().isoformat()
        }
    
    async def get_trending_tickers(
        self,
        subreddit: str = "wallstreetbets",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get trending tickers from a subreddit."""
        posts = await self.reddit.scrape_subreddit(subreddit, limit=limit)
        
        # Count ticker mentions
        ticker_counts = {}
        for post in posts:
            for ticker in post.tickers:
                ticker = ticker.upper()
                if ticker not in ticker_counts:
                    ticker_counts[ticker] = {
                        "mentions": 0,
                        "upvotes": 0,
                        "posts": []
                    }
                ticker_counts[ticker]["mentions"] += 1
                ticker_counts[ticker]["upvotes"] += post.upvotes
                ticker_counts[ticker]["posts"].append(post)
        
        # Sort by mentions
        sorted_tickers = sorted(
            ticker_counts.items(),
            key=lambda x: x[1]["mentions"],
            reverse=True
        )
        
        return [
            {
                "ticker": ticker,
                "mentions": data["mentions"],
                "upvotes": data["upvotes"],
                "post_count": len(data["posts"])
            }
            for ticker, data in sorted_tickers[:20]
        ]
    
    async def stream_sentiment(
        self,
        tickers: List[str],
        callback,
        interval: int = 60
    ):
        """Continuously stream sentiment updates."""
        self.logger.info("sentiment_stream_started", tickers=tickers)
        
        while True:
            try:
                for ticker in tickers:
                    data = await self.get_ticker_sentiment(ticker)
                    await callback(ticker, data)
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                self.logger.error("stream_error", error=str(e))
                await asyncio.sleep(interval)


# Singleton instances
reddit_scraper = RedditScraper()
twitter_scraper = TwitterScraper()
social_aggregator = SocialMediaAggregator()
