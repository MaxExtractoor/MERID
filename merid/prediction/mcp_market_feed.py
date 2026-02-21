"""MCP Market Data Feed — Sprint R.

Integration with external MCP (Model Context Protocol) servers for
supplementary market data. Provides a pluggable adapter that can connect
to MCP market data providers (e.g. mcpmarket.com Kalshi MCP server)
as an alternative/supplementary data source.

Architecture:
- MCPMarketFeed: async client that connects to MCP servers via HTTP/SSE
- MCPMarketConfig: configurable server URLs, auth, polling interval
- Publishes market snapshots to the StreamingBus MARKET_DATA channel
- Falls back gracefully if MCP server is unavailable

Usage::

    feed = get_mcp_market_feed()
    feed.configure(server_url="https://api.mcpmarket.com/kalshi")
    await feed.start()  # Begins polling
    # Or one-shot:
    markets = await feed.fetch_markets(category="crypto")

Environment variables:
    MCP_MARKET_SERVER_URL — MCP server base URL
    MCP_MARKET_API_KEY — API key for authentication (optional)
    MCP_MARKET_POLL_INTERVAL — Poll interval in seconds (default: 60)
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.mcp_market_feed")


@dataclass
class MCPMarketConfig:
    """Configuration for MCP market data server."""
    server_url: str = ""
    api_key: str = ""
    poll_interval_s: float = 60.0
    timeout_s: float = 10.0
    max_retries: int = 3
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "MCPMarketConfig":
        """Load configuration from environment variables."""
        url = os.environ.get("MCP_MARKET_SERVER_URL", "")
        return cls(
            server_url=url,
            api_key=os.environ.get("MCP_MARKET_API_KEY", ""),
            poll_interval_s=float(os.environ.get("MCP_MARKET_POLL_INTERVAL", "60")),
            enabled=bool(url),
        )


@dataclass
class MCPMarketSnapshot:
    """Market data received from an MCP server."""
    market_id: str
    title: str
    category: str
    yes_bid: float
    yes_ask: float
    volume: float
    open_interest: float
    close_time: Optional[str] = None
    source: str = "mcp"
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "title": self.title,
            "category": self.category,
            "yes_bid": self.yes_bid,
            "yes_ask": self.yes_ask,
            "volume": self.volume,
            "open_interest": self.open_interest,
            "close_time": self.close_time,
            "source": self.source,
            "timestamp": self.timestamp,
        }


class MCPMarketFeed:
    """Async client for MCP market data servers.

    Connects to MCP-compatible market data providers and fetches
    supplementary market snapshots. Data is published to the
    StreamingBus for consumption by forecasters and the trading agent.
    """

    def __init__(self, config: Optional[MCPMarketConfig] = None):
        self._config = config or MCPMarketConfig.from_env()
        self._task: Optional[asyncio.Task] = None
        self._shutdown = asyncio.Event()
        self._last_fetch: float = 0.0
        self._fetch_count: int = 0
        self._error_count: int = 0
        self._last_snapshots: List[MCPMarketSnapshot] = []

    def configure(
        self,
        server_url: Optional[str] = None,
        api_key: Optional[str] = None,
        poll_interval: Optional[float] = None,
    ) -> None:
        """Update configuration."""
        if server_url is not None:
            self._config.server_url = server_url
            self._config.enabled = bool(server_url)
        if api_key is not None:
            self._config.api_key = api_key
        if poll_interval is not None:
            self._config.poll_interval_s = poll_interval

    async def start(self) -> None:
        """Start periodic MCP market data polling."""
        if not self._config.enabled:
            logger.info("MCP market feed disabled (no server URL configured)")
            return

        self._shutdown.clear()
        self._task = asyncio.create_task(
            self._poll_loop(), name="mcp-market-feed"
        )
        logger.info(
            f"MCP market feed started: {self._config.server_url} "
            f"(interval={self._config.poll_interval_s}s)"
        )

    async def stop(self) -> None:
        """Stop the MCP market feed."""
        self._shutdown.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MCP market feed stopped")

    async def _poll_loop(self) -> None:
        """Periodic polling loop."""
        while not self._shutdown.is_set():
            try:
                snapshots = await self.fetch_markets()
                if snapshots:
                    self._last_snapshots = snapshots
                    await self._publish_to_bus(snapshots)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._error_count += 1
                logger.warning(f"MCP fetch error: {exc}")

            try:
                await asyncio.wait_for(
                    self._shutdown.wait(),
                    timeout=self._config.poll_interval_s,
                )
                break
            except asyncio.TimeoutError:
                pass

    async def fetch_markets(
        self,
        category: Optional[str] = None,
    ) -> List[MCPMarketSnapshot]:
        """Fetch markets from the MCP server.

        Uses aiohttp if available, falls back to urllib for basic HTTP.
        """
        if not self._config.server_url:
            return []

        url = f"{self._config.server_url.rstrip('/')}/markets"
        params: Dict[str, str] = {}
        if category:
            params["category"] = category

        headers: Dict[str, str] = {"Accept": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        snapshots: List[MCPMarketSnapshot] = []

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=self._config.timeout_s),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        snapshots = self._parse_response(data)
                        self._fetch_count += 1
                        self._last_fetch = time.time()
                    else:
                        self._error_count += 1
                        logger.warning(f"MCP server returned {resp.status}")
        except ImportError:
            # aiohttp not available — use synchronous fallback
            try:
                import urllib.request
                import json
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=self._config.timeout_s) as resp:
                    data = json.loads(resp.read().decode())
                    snapshots = self._parse_response(data)
                    self._fetch_count += 1
                    self._last_fetch = time.time()
            except Exception as exc:
                self._error_count += 1
                logger.debug(f"MCP fallback fetch failed: {exc}")
        except Exception as exc:
            self._error_count += 1
            logger.debug(f"MCP aiohttp fetch failed: {exc}")

        return snapshots

    def _parse_response(self, data: Any) -> List[MCPMarketSnapshot]:
        """Parse MCP server JSON response into snapshots."""
        snapshots = []
        markets = data if isinstance(data, list) else data.get("markets", [])

        for m in markets:
            try:
                snapshots.append(MCPMarketSnapshot(
                    market_id=m.get("ticker", m.get("market_id", "")),
                    title=m.get("title", m.get("question", "")),
                    category=m.get("category", "unknown"),
                    yes_bid=float(m.get("yes_bid", m.get("last_price", 50))) / 100,
                    yes_ask=float(m.get("yes_ask", m.get("last_price", 50))) / 100,
                    volume=float(m.get("volume", 0)),
                    open_interest=float(m.get("open_interest", 0)),
                    close_time=m.get("close_time", m.get("expiration_time")),
                ))
            except (KeyError, ValueError, TypeError) as exc:
                logger.debug(f"Skipping malformed MCP market: {exc}")

        return snapshots

    async def _publish_to_bus(self, snapshots: List[MCPMarketSnapshot]) -> None:
        """Publish MCP snapshots to the StreamingBus."""
        try:
            from core.streaming_bus import get_streaming_bus, StreamEvent, EventChannel
            bus = get_streaming_bus()
            for snap in snapshots[:50]:  # Cap at 50 per batch
                event = StreamEvent(
                    channel=EventChannel.MARKET_DATA,
                    event_type="mcp_market_snapshot",
                    data=snap.to_dict(),
                )
                await bus.publish(event)
        except Exception as exc:
            logger.debug(f"Bus publish failed: {exc}")

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            "enabled": self._config.enabled,
            "server_url": self._config.server_url or "(not configured)",
            "fetch_count": self._fetch_count,
            "error_count": self._error_count,
            "last_fetch": self._last_fetch,
            "last_snapshot_count": len(self._last_snapshots),
        }

    @property
    def last_snapshots(self) -> List[Dict[str, Any]]:
        return [s.to_dict() for s in self._last_snapshots]


# ── Singleton ────────────────────────────────────────────────────────────

_feed: Optional[MCPMarketFeed] = None


def get_mcp_market_feed() -> MCPMarketFeed:
    """Get or create the singleton MCPMarketFeed."""
    global _feed
    if _feed is None:
        _feed = MCPMarketFeed()
    return _feed
