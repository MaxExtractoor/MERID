"""
Streaming workers package.

All continuous data ingestion workers live here.
"""

from streams.market_stream import market_stream, start_market_stream, stop_market_stream, MarketDataStream as MarketStream
from streams.news_stream import news_stream, start_news_stream, stop_news_stream, NewsStream

PriceStream = MarketStream

__all__ = [
    'market_stream',
    'start_market_stream',
    'stop_market_stream',
    'news_stream',
    'start_news_stream',
    'stop_news_stream',
    'MarketStream',
    'NewsStream',
    'PriceStream',
]
