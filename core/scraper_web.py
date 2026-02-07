"""MERID Web Scraping Module for Financial Sentiment.

Scrapes financial news, headlines, and data from sites like FinViz, Yahoo Finance,
and StockTwits for sentiment analysis.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import asyncio
import structlog
import random
import time

logger = structlog.get_logger(__name__)


@dataclass
class ScrapedArticle:
    """Scraped financial article/headline."""
    title: str
    source: str
    url: Optional[str]
    timestamp: datetime
    tickers: List[str]
    content: Optional[str]
    sentiment_hint: Optional[str]  # Some sites provide sentiment indicators


class FinVizScraper:
    """Scraper for FinViz financial news."""
    
    def __init__(self, delay_range: tuple = (1, 3)):
        self.base_url = "https://finviz.com"
        self.news_url = "https://finviz.com/news.ashx"
        self.quote_url = "https://finviz.com/quote.ashx"
        self.delay_range = delay_range
        self.logger = logger.bind(scraper="FinViz")
        
        # Headers to mimic browser
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
        }
    
    async def scrape_ticker_news(
        self,
        ticker: str,
        use_playwright: bool = True
    ) -> List[ScrapedArticle]:
        """Scrape news for a specific ticker."""
        url = f"{self.quote_url}?t={ticker}"
        
        self.logger.info("scraping_ticker", ticker=ticker)
        
        try:
            if use_playwright:
                headlines = await self._scrape_with_playwright(url, ticker)
            else:
                headlines = await self._scrape_with_requests(url, ticker)
            
            # Respect rate limits
            await asyncio.sleep(random.uniform(*self.delay_range))
            
            return headlines
            
        except Exception as e:
            self.logger.error("scrape_error", ticker=ticker, error=str(e))
            return []
    
    async def _scrape_with_playwright(
        self,
        url: str,
        ticker: str
    ) -> List[ScrapedArticle]:
        """Scrape using Playwright for JS-rendered content."""
        try:
            from playwright.async_api import async_playwright
            
            articles = []
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent=self.headers["User-Agent"]
                )
                page = await context.new_page()
                
                await page.goto(url, wait_until="networkidle")
                
                # Wait for news table to load
                await page.wait_for_selector(".news-table", timeout=10000)
                
                # Extract headlines
                rows = await page.locator(".news-table tr").all()
                
                for row in rows[:20]:  # Limit to 20 most recent
                    try:
                        # Extract date/time
                        date_cell = await row.locator("td").nth(0).text_content()
                        
                        # Extract headline link
                        link = row.locator("a").nth(0)
                        title = await link.text_content()
                        href = await link.get_attribute("href")
                        
                        article = ScrapedArticle(
                            title=title.strip(),
                            source="FinViz",
                            url=href,
                            timestamp=datetime.now(),
                            tickers=[ticker],
                            content=None,
                            sentiment_hint=None
                        )
                        articles.append(article)
                        
                    except Exception:
                        continue
                
                await browser.close()
            
            self.logger.info("playwright_scrape_complete", count=len(articles))
            return articles
            
        except ImportError:
            self.logger.warning("playwright_not_installed")
            return []
    
    async def _scrape_with_requests(
        self,
        url: str,
        ticker: str
    ) -> List[ScrapedArticle]:
        """Scrape using requests + BeautifulSoup."""
        try:
            import requests
            from bs4 import BeautifulSoup
            
            articles = []
            
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find news table
            news_table = soup.find("table", class_="fullview-news-outer")
            if news_table:
                rows = news_table.find_all("tr")
                
                for row in rows[:20]:
                    try:
                        link = row.find("a")
                        if link:
                            article = ScrapedArticle(
                                title=link.text.strip(),
                                source="FinViz",
                                url=link.get("href"),
                                timestamp=datetime.now(),
                                tickers=[ticker],
                                content=None,
                                sentiment_hint=None
                            )
                            articles.append(article)
                    except Exception:
                        continue
            
            self.logger.info("requests_scrape_complete", count=len(articles))
            return articles
            
        except ImportError:
            self.logger.warning("requests/beautifulsoup_not_installed")
            return []
    
    async def scrape_market_news(self) -> List[ScrapedArticle]:
        """Scrape general market news."""
        return await self._scrape_with_playwright(self.news_url, "MARKET")


class YahooFinanceScraper:
    """Scraper for Yahoo Finance news."""
    
    def __init__(self):
        self.base_url = "https://finance.yahoo.com"
        self.logger = logger.bind(scraper="YahooFinance")
    
    async def scrape_ticker_news(self, ticker: str) -> List[ScrapedArticle]:
        """Scrape news for a ticker from Yahoo Finance."""
        url = f"{self.base_url}/quote/{ticker}/news"
        
        self.logger.info("scraping_yahoo", ticker=ticker)
        
        try:
            from playwright.async_api import async_playwright
            
            articles = []
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto(url, wait_until="networkidle")
                
                # Yahoo Finance news selectors
                news_items = await page.locator("[data-test='news-stream-item']").all()
                
                for item in news_items[:15]:
                    try:
                        title = await item.locator("h3").text_content()
                        link = item.locator("a").nth(0)
                        href = await link.get_attribute("href")
                        
                        # Make absolute URL
                        if href and href.startswith("/"):
                            href = f"{self.base_url}{href}"
                        
                        article = ScrapedArticle(
                            title=title.strip(),
                            source="Yahoo Finance",
                            url=href,
                            timestamp=datetime.now(),
                            tickers=[ticker],
                            content=None,
                            sentiment_hint=None
                        )
                        articles.append(article)
                        
                    except Exception:
                        continue
                
                await browser.close()
            
            await asyncio.sleep(random.uniform(1, 2))
            return articles
            
        except Exception as e:
            self.logger.error("yahoo_scrape_error", error=str(e))
            return []


class StockTwitsScraper:
    """Scraper for StockTwits sentiment."""
    
    def __init__(self):
        self.base_url = "https://stocktwits.com"
        self.logger = logger.bind(scraper="StockTwits")
    
    async def scrape_sentiment(self, ticker: str) -> Dict[str, Any]:
        """Scrape StockTwits sentiment for a ticker."""
        url = f"{self.base_url}/symbol/{ticker}"
        
        self.logger.info("scraping_stocktwits", ticker=ticker)
        
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto(url, wait_until="networkidle")
                
                # Extract sentiment indicator if available
                sentiment = {}
                
                try:
                    bullish = await page.locator("[data-test='bullish-count']").text_content()
                    bearish = await page.locator("[data-test='bearish-count']").text_content()
                    
                    sentiment = {
                        "bullish_count": int(bullish.replace(",", "")) if bullish else 0,
                        "bearish_count": int(bearish.replace(",", "")) if bearish else 0,
                    }
                except Exception:
                    pass
                
                # Extract recent messages
                messages = []
                message_elements = await page.locator("[data-test='stream-item']").all()
                
                for msg in message_elements[:20]:
                    try:
                        text = await msg.text_content()
                        if text:
                            messages.append(text.strip())
                    except Exception:
                        continue
                
                await browser.close()
                
                sentiment["messages"] = messages
                sentiment["timestamp"] = datetime.now().isoformat()
                
                return sentiment
                
        except Exception as e:
            self.logger.error("stocktwits_scrape_error", error=str(e))
            return {"messages": [], "error": str(e)}


class NewsAggregatorScraper:
    """Aggregates news from multiple financial sources."""
    
    def __init__(self):
        self.scrapers = {
            "finviz": FinVizScraper(),
            "yahoo": YahooFinanceScraper(),
            "stocktwits": StockTwitsScraper()
        }
        self.logger = logger.bind(component="NewsAggregator")
    
    async def scrape_all_for_ticker(
        self,
        ticker: str,
        sources: List[str] = None
    ) -> Dict[str, List[ScrapedArticle]]:
        """Scrape news from all sources for a ticker."""
        sources = sources or list(self.scrapers.keys())
        results = {}
        
        tasks = []
        for source in sources:
            if source in self.scrapers:
                if source == "stocktwits":
                    # StockTwits has different API
                    continue
                else:
                    tasks.append((source, self.scrapers[source].scrape_ticker_news(ticker)))
        
        # Execute concurrently
        for source, task in tasks:
            try:
                articles = await task
                results[source] = articles
                self.logger.info("source_scraped", source=source, count=len(articles))
            except Exception as e:
                self.logger.error("source_scrape_failed", source=source, error=str(e))
                results[source] = []
        
        return results
    
    async def scrape_with_sentiment(
        self,
        ticker: str,
        sentiment_pipeline
    ) -> List[Dict[str, Any]]:
        """Scrape and analyze sentiment in one pass."""
        from core.sentiment_nlp import SentimentSource
        
        all_articles = []
        results = await self.scrape_all_for_ticker(ticker)
        
        for source_name, articles in results.items():
            source_map = {
                "finviz": SentimentSource.NEWS,
                "yahoo": SentimentSource.NEWS,
                "stocktwits": SentimentSource.STOCKTWITS
            }
            
            source = source_map.get(source_name, SentimentSource.NEWS)
            
            for article in articles:
                # Analyze sentiment
                sentiment = sentiment_pipeline.analyze_text(
                    article.title,
                    source=source
                )
                
                all_articles.append({
                    "article": article,
                    "sentiment": sentiment
                })
        
        return all_articles
    
    def get_combined_headlines(self, results: Dict[str, List[ScrapedArticle]]) -> List[str]:
        """Extract just the headlines from all sources."""
        headlines = []
        for source_articles in results.values():
            for article in source_articles:
                headlines.append(article.title)
        return headlines


# Rate limiter for ethical scraping
class RateLimiter:
    """Rate limiter for web scraping."""
    
    def __init__(self, requests_per_minute: int = 30):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0
        self.logger = logger.bind(component="RateLimiter")
    
    async def acquire(self):
        """Acquire permission to make a request."""
        now = time.time()
        elapsed = now - self.last_request_time
        
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            self.logger.debug("rate_limit_waiting", seconds=wait_time)
            await asyncio.sleep(wait_time)
        
        self.last_request_time = time.time()


# Singleton scraper instances
finviz_scraper = FinVizScraper()
yahoo_scraper = YahooFinanceScraper()
news_aggregator = NewsAggregatorScraper()
rate_limiter = RateLimiter()
