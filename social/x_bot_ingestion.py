from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from core.env import capabilities
from social.social_aware_quant import get_social_bot_health_monitor
from social.social_data_quality import get_social_data_quality_monitor
from social.x_bot_interface import XBotService
from utils.logger import get_logger


logger = get_logger("social.x_bot.ingestion")

MENTIONS_URL = "https://api.twitter.com/2/users/{user_id}/mentions"


@dataclass
class RateLimitWindow:
    remaining: int = 0
    reset_epoch: float = 0.0


class XBotMentionFetcher:
    """Polls the X API for mentions with rate-limit aware backoff."""

    def __init__(
        self,
        user_id: Optional[str] = None,
        bearer_token: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        monitor_component: str = "x_ingestion",
    ) -> None:
        self._user_id = user_id or capabilities.x_bot_account_id
        self._bearer_token = bearer_token or capabilities.x_bearer_token
        self._client = client or httpx.AsyncClient(timeout=20.0)
        self._rate_window = RateLimitWindow()
        self._last_mention_id: Optional[str] = None
        self._pending_sleep: float = 0.0
        self._monitor = get_social_bot_health_monitor()
        self._component_name = monitor_component
        self._quality = get_social_data_quality_monitor()

    async def close(self) -> None:
        await self._client.aclose()
        self._monitor.update_heartbeat(self._component_name, status="stopped")

    async def fetch_mentions(self) -> List[Dict[str, Any]]:
        """Fetch latest mentions since the last processed ID."""
        if not self._user_id or not self._bearer_token:
            logger.warning("X bot credentials missing; mention fetch skipped")
            self._monitor.record_failure(self._component_name, "missing_credentials", recoverable=False)
            await asyncio.sleep(5)
            return []

        now = time.time()
        if now < self._rate_window.reset_epoch:
            logger.debug("Rate limit active; sleeping until reset")
            await asyncio.sleep(self._rate_window.reset_epoch - now)
            return []

        params = {
            "max_results": 50,
            "tweet.fields": "created_at,author_id,public_metrics,entities",
            "expansions": "author_id",
            "user.fields": "name,username",
        }
        if self._last_mention_id:
            params["since_id"] = self._last_mention_id

        url = MENTIONS_URL.format(user_id=self._user_id)
        headers = {
            "Authorization": f"Bearer {self._bearer_token}",
        }

        start = time.time()
        try:
            response = await self._client.get(url, headers=headers, params=params)
            self._update_rate_limit(response.headers)

            if response.status_code == 429:
                logger.warning("Hit Twitter rate limit; backing off")
                self._monitor.record_failure(self._component_name, "rate_limit", recoverable=True)
                self._quality.record_error(self._component_name)
                return []

            response.raise_for_status()
            body = response.json()
            mentions = self._transform_mentions(body)
            if mentions:
                self._last_mention_id = mentions[0]["id"]
            logger.debug("Fetched %d mentions", len(mentions))
            latency_ms = (time.time() - start) * 1000
            self._quality.record_batch(
                self._component_name,
                count=len(mentions),
                latency_ms=latency_ms,
                metadata={"last_id": self._last_mention_id},
            )
            self._monitor.update_heartbeat(
                self._component_name,
                metadata={
                    "batch_count": len(mentions),
                    "last_id": self._last_mention_id,
                },
            )
            return mentions
        except httpx.HTTPError as exc:
            logger.error("Mention fetch failed: %s", exc)
            self._monitor.record_failure(self._component_name, f"http_error:{exc}", recoverable=True)
            self._quality.record_error(self._component_name)
            await asyncio.sleep(10)
            return []

    def _update_rate_limit(self, headers: httpx.Headers) -> None:
        try:
            remaining = int(headers.get("x-rate-limit-remaining", "1"))
            reset = int(headers.get("x-rate-limit-reset", "0"))
            self._rate_window.remaining = remaining
            self._rate_window.reset_epoch = float(reset)
        except ValueError:
            self._rate_window.remaining = 0
            self._rate_window.reset_epoch = 0.0

    def _transform_mentions(self, payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = payload.get("data", [])
        includes = payload.get("includes", {})
        users = {user["id"]: user for user in includes.get("users", [])}

        mentions: List[Dict[str, Any]] = []
        for tweet in sorted(data, key=lambda t: t["id"], reverse=True):
            author_id = tweet.get("author_id")
            user_info = users.get(author_id, {})
            metrics = tweet.get("public_metrics", {})
            mentions.append(
                {
                    "id": tweet.get("id"),
                    "user_id": author_id,
                    "handle": user_info.get("username", ""),
                    "text": tweet.get("text", ""),
                    "timestamp": tweet.get("created_at"),
                    "engagement": {
                        "likes": metrics.get("like_count", 0),
                        "retweets": metrics.get("retweet_count", 0),
                        "replies": metrics.get("reply_count", 0),
                    },
                    "assets": self._extract_assets(tweet),
                    "metadata": {
                        "author_name": user_info.get("name"),
                        "raw_entities": tweet.get("entities", {}),
                    },
                }
            )
        return mentions

    def _extract_assets(self, tweet: Dict[str, Any]) -> List[str]:
        entities = tweet.get("entities", {})
        hashtags = entities.get("hashtags", [])
        return [tag.get("tag").upper() for tag in hashtags if tag.get("tag")]


async def start_x_bot_ingestion(
    bot_service: XBotService,
    fetcher: Optional[XBotMentionFetcher] = None,
    interval: float = 45.0,
) -> None:
    """Start the ingestion loop which feeds mentions into the bot service."""
    mention_fetcher = fetcher or XBotMentionFetcher()
    monitor = get_social_bot_health_monitor()
    monitor.register_component(
        "x_ingestion",
        component_type="ingestion",
        auto_recover=False,
        heartbeat_interval=interval,
    )
    monitor.update_heartbeat("x_ingestion", status="starting")
    try:
        await bot_service.run_polling_loop(mention_fetcher.fetch_mentions, interval=interval)
    finally:
        await mention_fetcher.close()
        monitor.update_heartbeat("x_ingestion", status="stopped")
