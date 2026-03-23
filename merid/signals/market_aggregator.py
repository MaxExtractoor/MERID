"""Kalshi Market Data Aggregator.

Aggregates Kalshi market data + features into MarketConsensusSnapshot objects.

Flow:
1. Fetch current Kalshi market state (prices, liquidity, volume)
2. Collect features from various sources (news, on-chain, technicals)
3. Construct MarketConsensusSnapshot ready for agent voting

This module replaces the "news item" as the unit of consensus.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.signals.market_consensus import (
    MarketData,
    MarketFeatures,
    MarketConsensusSnapshot,
    TradingAction,
)
from utils.logger import get_logger

logger = get_logger("merid.signals.market_aggregator")


class KalshiMarketAggregator:
    """Aggregates Kalshi market data and features into consensus snapshots.

    This is the entry point for creating MarketConsensusSnapshot objects
    that agents will vote on.
    """

    def __init__(self):
        self._last_snapshots: Dict[str, MarketConsensusSnapshot] = {}
        self._news_feature_cache: Dict[str, float] = {}  # asset -> sentiment score

    async def create_snapshot(
        self,
        ticker: str,
        asset: str = "",
        timeframe: str = "",
        include_features: bool = True,
    ) -> Optional[MarketConsensusSnapshot]:
        """Create a MarketConsensusSnapshot for a specific Kalshi market.

        Args:
            ticker: Kalshi ticker/contract ID
            asset: Asset symbol (BTC, ETH, etc.)
            timeframe: Timeframe (15m, 1h, 24h, etc.)
            include_features: Whether to fetch and include features

        Returns:
            MarketConsensusSnapshot or None if market data unavailable
        """
        try:
            # Step 1: Fetch market data from Kalshi
            market_data = await self._fetch_market_data(ticker)
            if not market_data:
                logger.warning(f"No market data available for {ticker}")
                return None

            # Step 2: Fetch features if requested
            features = None
            if include_features:
                features = await self._fetch_features(asset, timeframe, ticker)

            # Step 3: Construct snapshot
            snapshot = MarketConsensusSnapshot(
                contract_id=ticker,
                event_id=ticker.split("-")[0] if "-" in ticker else ticker,
                asset=asset or self._extract_asset(ticker),
                timeframe=timeframe or self._extract_timeframe(ticker),
                market_data=market_data,
                features=features,
                timestamp=time.time(),
            )

            # Cache for later retrieval
            self._last_snapshots[ticker] = snapshot

            logger.info(
                f"Created snapshot for {ticker}: "
                f"mid={market_data.mid_price}, spread={market_data.spread_pct:.2f}%, "
                f"depth={market_data.total_depth}"
            )

            return snapshot

        except Exception as exc:
            logger.error(f"Failed to create snapshot for {ticker}: {exc}")
            return None

    async def create_snapshots_for_assets(
        self,
        assets: List[str],
        timeframes: List[str],
        limit_per_asset: int = 5,
    ) -> List[MarketConsensusSnapshot]:
        """Create snapshots for multiple assets and timeframes.

        Args:
            assets: List of assets (e.g., ["BTC", "ETH", "SOL"])
            timeframes: List of timeframes (e.g., ["15m", "1h"])
            limit_per_asset: Max snapshots per asset

        Returns:
            List of MarketConsensusSnapshot objects
        """
        snapshots = []

        for asset in assets:
            for timeframe in timeframes:
                # Get active markets for this asset/timeframe
                tickers = await self._find_active_markets(asset, timeframe, limit=limit_per_asset)

                for ticker in tickers:
                    snapshot = await self.create_snapshot(ticker, asset, timeframe)
                    if snapshot:
                        snapshots.append(snapshot)

        logger.info(f"Created {len(snapshots)} snapshots for {len(assets)} assets")
        return snapshots

    def get_cached_snapshot(self, ticker: str) -> Optional[MarketConsensusSnapshot]:
        """Retrieve cached snapshot for a ticker."""
        return self._last_snapshots.get(ticker)

    def update_news_features(self, asset: str, sentiment_score: float):
        """Update news sentiment cache for an asset.

        Called by news_monitor_agent when new headlines are processed.

        Args:
            asset: Asset symbol (BTC, ETH, etc.)
            sentiment_score: -1 to +1 sentiment
        """
        self._news_feature_cache[asset] = sentiment_score
        logger.debug(f"Updated news sentiment for {asset}: {sentiment_score:.2f}")

    # ── Internal helpers ──────────────────────────────────────────────────

    async def _fetch_market_data(self, ticker: str) -> Optional[MarketData]:
        """Fetch current market data from Kalshi for a ticker."""
        try:
            # Use kalshi_tools to fetch market state
            from merid.prediction.kalshi_tools import _kalshi_get_market_state

            result = await _kalshi_get_market_state(ticker=ticker)
            if not result.success:
                logger.warning(f"Failed to fetch market data for {ticker}: {result.error}")
                return None

            payload = result.payload
            market = payload.get("market", {})
            outcomes = market.get("outcomes", [])

            # Find YES outcome
            yes_outcome = next((o for o in outcomes if o.get("id") == "yes"), None)
            if not yes_outcome:
                logger.warning(f"No YES outcome found for {ticker}")
                return None

            best_bid = Decimal(yes_outcome.get("best_bid", "0"))
            best_ask = Decimal(yes_outcome.get("best_ask", "0"))
            mid = (best_bid + best_ask) / 2 if best_bid and best_ask else Decimal("0")
            spread = best_ask - best_bid if best_ask and best_bid else Decimal("0")
            spread_pct = float(spread / mid * 100) if mid > 0 else 0.0

            # Parse expiry
            expiry_time = None
            end_date_str = market.get("end_date")
            if end_date_str:
                try:
                    expiry_time = datetime.fromisoformat(end_date_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            time_to_expiry_hours = 0.0
            if expiry_time:
                delta = expiry_time - datetime.now(timezone.utc)
                time_to_expiry_hours = delta.total_seconds() / 3600

            return MarketData(
                ticker=ticker,
                question=market.get("question", ""),
                best_bid=best_bid,
                best_ask=best_ask,
                mid_price=mid,
                last_price=Decimal(yes_outcome.get("last_price", "0")),
                implied_prob=float(mid) / 100.0 if mid > 0 else 0.0,
                spread_cents=spread,
                spread_pct=spread_pct,
                bid_depth=int(yes_outcome.get("bid_depth", 0)),
                ask_depth=int(yes_outcome.get("ask_depth", 0)),
                total_depth=int(yes_outcome.get("bid_depth", 0)) + int(yes_outcome.get("ask_depth", 0)),
                volume_24h=int(market.get("volume_24h", 0)),
                trade_count_24h=int(market.get("trade_count", 0)),
                open_interest=int(market.get("open_interest", 0)),
                expiry_time=expiry_time,
                time_to_expiry_hours=time_to_expiry_hours,
                active=market.get("active", True),
                timestamp=time.time(),
            )

        except Exception as exc:
            logger.error(f"Error fetching market data for {ticker}: {exc}")
            return None

    async def _fetch_features(
        self,
        asset: str,
        timeframe: str,
        ticker: str,
    ) -> MarketFeatures:
        """Fetch features from various sources for this market.

        Features include:
        - News sentiment (from news_monitor_agent cache)
        - On-chain signals (if available)
        - Technical indicators
        - Volume anomalies
        - Kalshi-specific metrics
        """
        features = MarketFeatures(timestamp=time.time())

        # News sentiment from cache
        sentiment = self._news_feature_cache.get(asset, 0.0)
        if sentiment > 0:
            features.news_bullish_score = sentiment
            features.news_regime = "risk_on" if sentiment > 0.3 else "neutral"
        elif sentiment < 0:
            features.news_bearish_score = abs(sentiment)
            features.news_regime = "risk_off" if sentiment < -0.3 else "neutral"

        # TODO: Fetch on-chain signals
        # features.onchain_signal = await self._fetch_onchain_signal(asset)

        # TODO: Fetch technical indicators
        # features.rsi_14 = await self._fetch_rsi(asset, timeframe)
        # features.ema_cross = await self._fetch_ema_cross(asset, timeframe)

        # TODO: Fetch Kalshi-specific metrics
        # features.kalshi_liquidity_score = await self._compute_liquidity_score(ticker)

        return features

    async def _find_active_markets(
        self,
        asset: str,
        timeframe: str,
        limit: int = 5,
    ) -> List[str]:
        """Find active Kalshi markets for an asset and timeframe."""
        try:
            from merid.prediction.kalshi_tools import _kalshi_list_markets

            result = await _kalshi_list_markets(
                category="crypto",
                asset=asset,
                timeframe=timeframe,
                limit=limit,
            )

            if not result.success:
                logger.warning(f"Failed to list markets for {asset}/{timeframe}")
                return []

            markets = result.payload.get("markets", [])
            return [m["ticker"] for m in markets if m.get("active", True)]

        except Exception as exc:
            logger.error(f"Error finding markets for {asset}/{timeframe}: {exc}")
            return []

    def _extract_asset(self, ticker: str) -> str:
        """Extract asset from ticker."""
        parts = ticker.split("-")
        if parts:
            asset = parts[0].upper()
            if asset in ("BTC", "ETH", "SOL", "DOGE", "XRP", "ADA", "KXBTCD"):
                return "BTC" if asset == "KXBTCD" else asset
        return "UNKNOWN"

    def _extract_timeframe(self, ticker: str) -> str:
        """Extract timeframe from ticker."""
        ticker_lower = ticker.lower()
        if "15m" in ticker_lower:
            return "15m"
        if "1h" in ticker_lower or "hourly" in ticker_lower:
            return "1h"
        if "24h" in ticker_lower or "daily" in ticker_lower:
            return "24h"
        if "weekly" in ticker_lower or "week" in ticker_lower:
            return "weekly"
        return "unknown"


# ── Singleton ─────────────────────────────────────────────────────────────

_aggregator: Optional[KalshiMarketAggregator] = None


def get_market_aggregator() -> KalshiMarketAggregator:
    """Get or create the singleton market aggregator."""
    global _aggregator
    if _aggregator is None:
        _aggregator = KalshiMarketAggregator()
    return _aggregator


def reset_market_aggregator() -> None:
    """Reset singleton (for testing)."""
    global _aggregator
    _aggregator = None
