"""Kalshi Historical Data Collector — Fetch closed markets and trade history.

Orchestrates the pipeline: list closed BTC/ETH hourly markets via the
KalshiVenueClient, fetch trade history for each, and pipe into the
SnapshotArchiver for replay through the backtest engine.

Usage::

    collector = HistoricalCollector(client, archiver)
    result = await collector.collect_closed_hourlies("BTC")
    print(result)  # {"markets_found": 48, "trades_archived": 1200, ...}

The collector is designed to be run as a nightly job or on-demand to
backfill historical data for backtesting.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from merid.event_venues.kalshi.archiver import SnapshotArchiver
from merid.event_venues.kalshi.backtest import MarketSnapshot
from merid.event_venues.kalshi.crypto_markets import CRYPTO_SERIES
from merid.event_venues.kalshi.historical_sim import HistoricalTrade
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.collector")

# Timeframe labels for series matching
TIMEFRAME_SERIES_SUFFIXES = {
    "hourly": "",       # e.g. KXBTC
    "15m": "-15M",      # e.g. KXBTC-15M
    "daily": "-D",
    "weekly": "-W",
}


@dataclass
class CollectorConfig:
    """Configuration for the historical data collector."""
    # Max markets to fetch per collection run
    max_markets_per_run: int = 200

    # Delay between API calls (seconds) to stay within rate limits
    inter_request_delay: float = 0.2

    # Max trades to fetch per market
    max_trades_per_market: int = 5000

    # Only collect markets that closed within this many days
    lookback_days: int = 30


DEFAULT_COLLECTOR_CONFIG = CollectorConfig()


@dataclass
class CollectionResult:
    """Result of a collection run."""
    asset: str
    timeframe: str
    markets_found: int = 0
    markets_processed: int = 0
    trades_archived: int = 0
    snapshots_created: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    error_details: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "timeframe": self.timeframe,
            "markets_found": self.markets_found,
            "markets_processed": self.markets_processed,
            "trades_archived": self.trades_archived,
            "snapshots_created": self.snapshots_created,
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 2),
            "error_details": self.error_details[:10],
        }


class HistoricalCollector:
    """Fetches closed Kalshi crypto hourly markets and archives their trades.

    Uses the KalshiVenueClient for API access and SnapshotArchiver for
    persistent storage.  Trades are converted to MarketSnapshot objects
    for compatibility with the snapshot-based backtest engine, and also
    stored as raw HistoricalTrade objects for the trade-interleaved
    simulator.
    """

    def __init__(
        self,
        client: Any,
        archiver: SnapshotArchiver,
        config: Optional[CollectorConfig] = None,
    ) -> None:
        self._client = client
        self._archiver = archiver
        self._config = config or DEFAULT_COLLECTOR_CONFIG

    async def collect_closed_hourlies(
        self,
        asset: str,
        timeframe: str = "hourly",
    ) -> CollectionResult:
        """Collect closed hourly markets for an asset and archive trades.

        Args:
            asset: Asset symbol (e.g. "BTC", "ETH")
            timeframe: Timeframe label (e.g. "hourly", "15m")

        Returns:
            CollectionResult with counts and any errors.
        """
        start = time.time()
        result = CollectionResult(asset=asset, timeframe=timeframe)

        series = CRYPTO_SERIES.get(asset.upper())
        if not series:
            result.error_details.append(f"Unknown asset: {asset}")
            result.errors = 1
            return result

        suffix = TIMEFRAME_SERIES_SUFFIXES.get(timeframe, "")
        series_ticker = f"{series}{suffix}"

        # Step 1: List closed markets for this series
        markets = await self._fetch_closed_markets(series_ticker)
        result.markets_found = len(markets)

        if not markets:
            logger.info(f"[collector] No closed markets found for {series_ticker}")
            result.duration_seconds = time.time() - start
            return result

        # Step 2: For each market, fetch trades and archive
        for market in markets[:self._config.max_markets_per_run]:
            try:
                ticker = market.get("ticker", market.get("market_id", ""))
                if not ticker:
                    continue

                trades = await self._fetch_market_trades(ticker)
                if not trades:
                    continue

                # Convert to snapshots and archive
                snapshots = self._trades_to_snapshots(trades, ticker)
                self._archiver.record_many(snapshots)

                result.markets_processed += 1
                result.trades_archived += len(trades)
                result.snapshots_created += len(snapshots)

                # Rate limit courtesy
                await asyncio.sleep(self._config.inter_request_delay)

            except Exception as exc:
                result.errors += 1
                result.error_details.append(f"{ticker}: {exc}")
                logger.warning(f"[collector] Error processing {ticker}: {exc}")

        result.duration_seconds = time.time() - start
        logger.info(
            f"[collector] {asset} {timeframe}: "
            f"{result.markets_processed}/{result.markets_found} markets, "
            f"{result.trades_archived} trades archived in {result.duration_seconds:.1f}s"
        )
        return result

    async def collect_all_crypto(
        self,
        assets: Optional[List[str]] = None,
        timeframe: str = "hourly",
    ) -> List[CollectionResult]:
        """Collect closed markets for all crypto assets.

        Args:
            assets: List of asset symbols (default: all 5 crypto assets)
            timeframe: Timeframe label

        Returns:
            List of CollectionResult, one per asset.
        """
        assets = assets or list(CRYPTO_SERIES.keys())
        results = []
        for asset in assets:
            r = await self.collect_closed_hourlies(asset, timeframe)
            results.append(r)
        return results

    # ── Internal methods ─────────────────────────────────────────────

    async def _fetch_closed_markets(self, series_ticker: str) -> List[Dict[str, Any]]:
        """Fetch closed markets for a series ticker.

        Uses the client's list_markets with series_ticker filter and
        status=closed.
        """
        try:
            from merid.event_venues.base import MarketFilter
            filter_params = MarketFilter(
                search=series_ticker,
                active_only=False,
                limit=self._config.max_markets_per_run,
            )
            result = await self._client.list_markets_result(filter_params)
            if not result.success:
                logger.warning(f"[collector] Failed to list markets for {series_ticker}: {result.error}")
                return []

            # Filter to only settled/closed markets
            closed = []
            for market in result.data:
                if hasattr(market, "resolved") and market.resolved:
                    closed.append({
                        "ticker": market.market_id,
                        "market_id": market.market_id,
                        "question": market.question,
                        "end_date": market.end_date,
                        "category": market.category,
                    })
                elif hasattr(market, "active") and not market.active:
                    closed.append({
                        "ticker": market.market_id,
                        "market_id": market.market_id,
                        "question": getattr(market, "question", ""),
                        "end_date": getattr(market, "end_date", None),
                        "category": getattr(market, "category", None),
                    })

            return closed

        except Exception as exc:
            logger.error(f"[collector] Error fetching markets for {series_ticker}: {exc}")
            return []

    async def _fetch_market_trades(self, ticker: str) -> List[Dict[str, Any]]:
        """Fetch trade history for a specific market ticker.

        Uses the client's _request_with_resilience to hit the trades
        endpoint with pagination.
        """
        all_trades: List[Dict[str, Any]] = []
        cursor = None

        while len(all_trades) < self._config.max_trades_per_market:
            try:
                params: Dict[str, Any] = {
                    "ticker": ticker,
                    "limit": min(1000, self._config.max_trades_per_market - len(all_trades)),
                }
                if cursor:
                    params["cursor"] = cursor

                result = await self._client._request_with_resilience(
                    "GET", "/trades", params=params,
                    operation_name=f"collect_trades({ticker})",
                )

                if not result.success:
                    logger.debug(f"[collector] Trade fetch failed for {ticker}: {result.error}")
                    break

                trades = result.data.get("trades", [])
                if not trades:
                    break

                all_trades.extend(trades)
                cursor = result.data.get("cursor")
                if not cursor:
                    break

                await asyncio.sleep(self._config.inter_request_delay)

            except Exception as exc:
                logger.warning(f"[collector] Error fetching trades for {ticker}: {exc}")
                break

        return all_trades

    def _trades_to_snapshots(
        self,
        raw_trades: List[Dict[str, Any]],
        ticker: str,
    ) -> List[MarketSnapshot]:
        """Convert raw trade dicts to MarketSnapshot objects for archiving.

        Each trade becomes a snapshot with the trade price as
        last_trade_price and a synthetic single-level book.
        """
        snapshots = []
        for trade in raw_trades:
            try:
                ts = self._parse_ts(trade)
                price_cents = int(trade.get("price", trade.get("yes_price", 50)))
                size = int(trade.get("count", trade.get("size", 1)))

                snap = MarketSnapshot(
                    ts=ts,
                    ticker=ticker,
                    yes_book=[[price_cents, size]],
                    no_book=[[100 - price_cents, size]],
                    last_trade_price=price_cents,
                    volume=size,
                )
                snapshots.append(snap)
            except (ValueError, TypeError, KeyError) as exc:
                logger.debug(f"[collector] Skipping malformed trade: {exc}")

        return snapshots

    def trades_to_historical(
        self,
        raw_trades: List[Dict[str, Any]],
        ticker: str,
    ) -> List[HistoricalTrade]:
        """Convert raw trade dicts to HistoricalTrade objects for the
        trade-interleaved simulator.
        """
        from decimal import Decimal

        result = []
        for trade in raw_trades:
            try:
                ts = self._parse_ts(trade)
                price_cents = int(trade.get("price", trade.get("yes_price", 50)))
                size = int(trade.get("count", trade.get("size", 1)))
                side = trade.get("taker_side", trade.get("side", "buy"))

                result.append(HistoricalTrade(
                    ts=int(ts),
                    price=Decimal(price_cents) / Decimal(100),
                    size=size,
                    side=side,
                    ticker=ticker,
                ))
            except (ValueError, TypeError, KeyError) as exc:
                logger.debug(f"[collector] Skipping malformed trade: {exc}")

        return result

    @staticmethod
    def _parse_ts(trade: Dict[str, Any]) -> float:
        """Extract epoch timestamp from a trade dict."""
        ts = trade.get("created_time") or trade.get("ts") or trade.get("created_at")
        if ts is None:
            return time.time()
        if isinstance(ts, (int, float)):
            # If > 1e12, assume milliseconds
            return ts / 1000.0 if ts > 1e12 else float(ts)
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        return time.time()
