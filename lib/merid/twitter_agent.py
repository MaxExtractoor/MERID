"""Minimal wrapper around the Tweepy client used by MERID."""

from __future__ import annotations

import os
from typing import List, Union

import tweepy  # type: ignore
from dotenv import load_dotenv

load_dotenv()


class MERIDTwitterAgent:
    """Thin helper that exposes a safe `get_market_sentiment` call."""

    def __init__(self) -> None:
        self.client = tweepy.Client(
            bearer_token=os.getenv("X_BEARER_TOKEN"),
            consumer_key=os.getenv("X_API_KEY"),
            consumer_secret=os.getenv("X_API_SECRET"),
            access_token=os.getenv("X_ACCESS_TOKEN"),
            access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET"),
            wait_on_rate_limit=True,
        )

    def get_market_sentiment(self, query: str) -> Union[str, List[str]]:
        """Return recent tweet text for a query or a human-readable error."""
        try:
            search_query = f"{query} -is:retweet lang:en"
            response = self.client.search_recent_tweets(query=search_query, max_results=10)
            if not response.data:
                return "No recent discussions found."
            return [tweet.text for tweet in response.data]
        except Exception as exc:  # pragma: no cover - network code
            return f"X API Error: {exc}"
