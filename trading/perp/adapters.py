"""Venue-specific perpetual adapters wired into the shared base interface."""

from __future__ import annotations

import os
import random
import time
from typing import Any, Dict, List, Optional, Sequence

from utils.logger import get_logger

try:
    from data.asset_universe import ASSET_UNIVERSE
except Exception:  # pragma: no cover - optional dependency
    ASSET_UNIVERSE = None

from .base import (
    FundingRateSnapshot,
    PerpMarketSnapshot,
    PerpVenueAdapterBase,
    WhaleSignal,
)

logger = get_logger("trading.perp.adapters")


def _flt(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class HyperliquidAdapter(PerpVenueAdapterBase):
    """Adapter for Hyperliquid public info endpoints (https://api.hyperliquid.xyz/info)."""

    venue = "hyperliquid"

    def __init__(self, *, info_url: Optional[str] = None, use_mock: bool = False) -> None:
        super().__init__(base_url=info_url or os.getenv("MERID_HYPERLIQUID_INFO_URL") or "https://api.hyperliquid.xyz/info", use_mock=use_mock)
        self._symbol_cache: List[str] = []
        self._fallback_symbols = self._derive_fallback_symbols()

    def _derive_fallback_symbols(self) -> List[str]:
        if ASSET_UNIVERSE:
            symbols = set()
            for key, asset in ASSET_UNIVERSE.items():
                name = key.split('-')[0]
                if "-PERP" in key or ':USDT' in asset.symbol:
                    symbols.add(name.upper())
            if symbols:
                return sorted(symbols)
        return ["BTC", "ETH", "SOL"]

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        try:
            meta_resp = self._client.post(self.base_url, json={"type": "meta"})
            meta = meta_resp.json()
            markets = meta.get("perpMarkets") or meta.get("perpMarketsMetadata") or []
            symbols: List[str] = []
            for entry in markets:
                if isinstance(entry, dict):
                    coin = entry.get("name") or entry.get("symbol")
                else:
                    coin = entry
                if coin:
                    symbols.append(str(coin))
            if symbols:
                self._symbol_cache = symbols
            if not symbols:
                if self._symbol_cache:
                    symbols = self._symbol_cache
                    logger.info("Hyperliquid meta empty, using cached symbols (%d)", len(symbols))
                elif self._fallback_symbols:
                    symbols = self._fallback_symbols
                    logger.info("Hyperliquid meta empty, using fallback symbols (%d)", len(symbols))
                else:
                    symbols = ["BTC", "ETH", "SOL"]
        except Exception as exc:
            logger.warning("Hyperliquid meta fetch failed: %s", exc)
            if self._symbol_cache:
                logger.info("Using cached Hyperliquid symbols after meta failure (%d)", len(self._symbol_cache))
                symbols = self._symbol_cache
            elif self._fallback_symbols:
                logger.info("Using fallback Hyperliquid symbols after meta failure (%d)", len(self._fallback_symbols))
                symbols = self._fallback_symbols
            else:
                return self._mock_markets(limit)

        snapshots: List[PerpMarketSnapshot] = []
        for coin in symbols[:limit]:
            try:
                summary_resp = self._client.post(self.base_url, json={"type": "perpSummary", "coin": coin})
                payload = summary_resp.json()
                summary = payload.get("data") or payload.get("result") or payload
                mark_px = _flt(summary.get("markPx") or summary.get("mid") or summary.get("px"))
                oracle_px = _flt(summary.get("oraclePx") or summary.get("indexPx") or mark_px)
                funding = _flt(summary.get("fundingRate") or summary.get("funding") or summary.get("perpFunding"))
                oi = _flt(summary.get("oi") or summary.get("openInterest"))
                volume = _flt(summary.get("volume24h") or summary.get("volume"))
            except Exception as exc:
                logger.debug("Hyperliquid summary error for %s: %s", coin, exc)
                continue

            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=f"{coin}-PERP",
                    price=mark_px,
                    index_price=oracle_px,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=mark_px - oracle_px,
                    metadata={"coin": coin},
                )
            )

        return snapshots

    def _fetch_funding_live(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        symbols = symbols or self._symbol_cache or self._fallback_symbols or ["BTC", "ETH", "SOL"]
        snapshots: List[FundingRateSnapshot] = []
        for coin in symbols:
            try:
                summary_resp = self._client.post(self.base_url, json={"type": "perpSummary", "coin": coin})
                payload = summary_resp.json()
                summary = payload.get("data") or payload.get("result") or payload
                funding = _flt(summary.get("fundingRate") or summary.get("funding"))
                settlement_ms = summary.get("nextFundingTimeMs") or summary.get("nextFundingTime")
                settlement_ms = float(settlement_ms) if settlement_ms else 0.0
                apr = funding * 24 * 365
            except Exception as exc:
                logger.debug("Hyperliquid funding fetch failed for %s: %s", coin, exc)
                continue

            snapshots.append(
                FundingRateSnapshot(
                    venue=self.venue,
                    symbol=f"{coin}-PERP",
                    funding_rate=funding,
                    next_settlement_ms=settlement_ms,
                    estimated_apr=apr,
                    metadata={},
                )
            )
        return snapshots


class BybitPerpAdapter(PerpVenueAdapterBase):
    """Adapter for Bybit v5 public market endpoints."""

    venue = "bybit"

    def __init__(self, *, base_url: str = "https://api.bybit.com", category: str = "linear", use_mock: bool = False) -> None:
        self.category = category
        super().__init__(base_url=base_url, use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        endpoint = f"{self.base_url}/v5/market/tickers"
        params = {"category": self.category, "limit": min(limit, 200)}
        response = self._client.get(endpoint, params=params)
        payload = response.json()
        entries = payload.get("result", {}).get("list", []) if isinstance(payload, dict) else []
        snapshots: List[PerpMarketSnapshot] = []
        for item in entries[:limit]:
            symbol = item.get("symbol")
            if not symbol:
                continue
            price = _flt(item.get("lastPrice"))
            index_price = _flt(item.get("indexPrice") or item.get("markPrice") or price)
            funding = _flt(item.get("fundingRate"))
            oi = _flt(item.get("openInterest"))
            volume = _flt(item.get("turnover24h") or item.get("volume24h"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    price=price,
                    index_price=index_price,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=price - index_price,
                    metadata={"category": self.category},
                )
            )
        return snapshots

    def _fetch_funding_live(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        snapshots: List[FundingRateSnapshot] = []
        endpoint = f"{self.base_url}/v5/market/funding/history"
        for symbol in symbols:
            params = {"category": self.category, "symbol": symbol, "limit": 1}
            try:
                response = self._client.get(endpoint, params=params)
                payload = response.json()
                data = payload.get("result", {}).get("list", [])
                if not data:
                    continue
                latest = data[0]
                funding = _flt(latest.get("fundingRate"))
                settlement_ms = float(latest.get("fundingRateTimestamp") or 0)
                apr = funding * 24 * 365
                snapshots.append(
                    FundingRateSnapshot(
                        venue=self.venue,
                        symbol=symbol,
                        funding_rate=funding,
                        next_settlement_ms=settlement_ms,
                        estimated_apr=apr,
                        metadata={},
                    )
                )
            except Exception as exc:
                logger.debug("Bybit funding fetch failed for %s: %s", symbol, exc)
        return snapshots


class BinancePerpAdapter(PerpVenueAdapterBase):
    """Adapter for Binance Futures (USDT-margined) endpoints."""

    venue = "binance"

    def __init__(self, *, base_url: str = "https://fapi.binance.com", use_mock: bool = False) -> None:
        super().__init__(base_url=base_url, use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        tickers_resp = self._client.get(f"{self.base_url}/fapi/v1/ticker/24hr")
        tickers = tickers_resp.json()
        premium_resp = self._client.get(f"{self.base_url}/fapi/v1/premiumIndex")
        premium_data = premium_resp.json()
        premium_map = {entry.get("symbol"): entry for entry in premium_data if isinstance(entry, dict)}
        snapshots: List[PerpMarketSnapshot] = []
        for item in tickers[:limit]:
            symbol = item.get("symbol")
            if not symbol:
                continue
            price = _flt(item.get("lastPrice"))
            premium_entry = premium_map.get(symbol, {})
            index_price = _flt(premium_entry.get("markPrice") or premium_entry.get("indexPrice") or price)
            funding = _flt(premium_entry.get("lastFundingRate"))
            oi = _flt(item.get("openInterest"))
            volume = _flt(item.get("quoteVolume"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    price=price,
                    index_price=index_price,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=price - index_price,
                    metadata={"contractType": item.get("contractType")},
                )
            )
        return snapshots

    def _fetch_funding_live(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        endpoint = f"{self.base_url}/fapi/v1/premiumIndex"
        if symbols:
            snapshots: List[FundingRateSnapshot] = []
            for symbol in symbols:
                try:
                    resp = self._client.get(endpoint, params={"symbol": symbol})
                    entry = resp.json()
                    funding = _flt(entry.get("lastFundingRate"))
                    settlement_ms = float(entry.get("nextFundingTime") or 0)
                    snapshots.append(
                        FundingRateSnapshot(
                            venue=self.venue,
                            symbol=symbol,
                            funding_rate=funding,
                            next_settlement_ms=settlement_ms,
                            estimated_apr=funding * 24 * 365,
                            metadata={},
                        )
                    )
                except Exception as exc:
                    logger.debug("Binance funding fetch failed for %s: %s", symbol, exc)
            return snapshots

        entries = self._client.get(endpoint).json()
        snapshots = []
        for entry in entries:
            symbol = entry.get("symbol")
            funding = _flt(entry.get("lastFundingRate"))
            settlement_ms = float(entry.get("nextFundingTime") or 0)
            snapshots.append(
                FundingRateSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    funding_rate=funding,
                    next_settlement_ms=settlement_ms,
                    estimated_apr=funding * 24 * 365,
                    metadata={},
                )
            )
        return snapshots


class CoinbasePerpAdapter(PerpVenueAdapterBase):
    """Adapter for Coinbase Advanced Trade products (PERP tickers)."""

    venue = "coinbase"

    def __init__(self, *, base_url: str = "https://api.exchange.coinbase.com", use_mock: bool = False) -> None:
        super().__init__(base_url=base_url, use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        response = self._client.get(f"{self.base_url}/products")
        products = response.json()
        snapshots: List[PerpMarketSnapshot] = []
        for product in products:
            product_id = product.get("id") or product.get("product_id") or product.get("symbol")
            if not product_id or not product_id.upper().endswith("PERP"):
                continue
            price = _flt(product.get("price"))
            oracle_price = _flt(product.get("oracle_price") or product.get("index_price") or price)
            volume = _flt(product.get("volume_24h") or product.get("quote_volume_24h"))
            oi = _flt(product.get("open_interest"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=product_id,
                    price=price,
                    index_price=oracle_price,
                    open_interest=oi,
                    funding_rate=_flt(product.get("funding_rate")),
                    volume_24h=volume,
                    basis=price - oracle_price,
                    metadata={"base_currency": product.get("base_currency")},
                )
            )
            if len(snapshots) >= limit:
                break
        return snapshots

    def _fetch_funding_live(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        # Coinbase currently exposes limited funding info; fall back to mocks.
        return []


class CryptoComPerpAdapter(PerpVenueAdapterBase):
    """Adapter for Crypto.com public derivative tickers."""

    venue = "crypto.com"

    def __init__(self, *, base_url: str = "https://api.crypto.com/v2", use_mock: bool = False) -> None:
        super().__init__(base_url=base_url, use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        endpoint = f"{self.base_url}/public/get-tickers"
        response = self._client.post(endpoint, json={"id": 11, "method": "public/get-tickers", "params": {}})
        payload = response.json()
        entries = payload.get("result", {}).get("data", [])
        snapshots: List[PerpMarketSnapshot] = []
        for entry in entries:
            instrument = entry.get("instrument_name")
            if not instrument or not instrument.endswith("PERP"):
                continue
            price = _flt(entry.get("a") or entry.get("k") or entry.get("b"))
            index_price = _flt(entry.get("mark_price") or entry.get("i") or price)
            funding = _flt(entry.get("funding_rate"))
            oi = _flt(entry.get("open_interest"))
            volume = _flt(entry.get("v"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=instrument,
                    price=price,
                    index_price=index_price,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=price - index_price,
                    metadata={"data": entry},
                )
            )
            if len(snapshots) >= limit:
                break
        return snapshots


class DyDxPerpAdapter(PerpVenueAdapterBase):
    """Adapter for dYdX v3 public REST."""

    venue = "dydx"

    def __init__(self, *, base_url: str = "https://api.dydx.exchange", use_mock: bool = False) -> None:
        super().__init__(base_url=base_url, use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        response = self._client.get(f"{self.base_url}/v3/perpetual-markets")
        payload = response.json()
        markets = payload.get("markets", {})
        snapshots: List[PerpMarketSnapshot] = []
        for symbol, entry in markets.items():
            price = _flt(entry.get("oraclePrice") or entry.get("indexPrice") or entry.get("markPrice"))
            index_price = _flt(entry.get("oraclePrice") or price)
            funding = _flt(entry.get("nextFundingRate"))
            oi = _flt(entry.get("openInterest"))
            volume = _flt(entry.get("volume24H") or entry.get("trades24H"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    price=price,
                    index_price=index_price,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=price - index_price,
                    metadata={"status": entry.get("status")},
                )
            )
            if len(snapshots) >= limit:
                break
        return snapshots

    def _fetch_funding_live(self, symbols: Optional[List[str]]) -> List[FundingRateSnapshot]:
        response = self._client.get(f"{self.base_url}/v3/perpetual-markets")
        payload = response.json()
        markets = payload.get("markets", {})
        snapshots: List[FundingRateSnapshot] = []
        symbol_set = set(symbols) if symbols else None
        for symbol, entry in markets.items():
            if symbol_set and symbol not in symbol_set:
                continue
            funding = _flt(entry.get("nextFundingRate"))
            settlement = float(entry.get("nextFundingRateTime") or 0)
            snapshots.append(
                FundingRateSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    funding_rate=funding,
                    next_settlement_ms=settlement,
                    estimated_apr=funding * 24 * 365,
                    metadata={},
                )
            )
        return snapshots


class GMXPerpAdapter(PerpVenueAdapterBase):
    """Adapter scaffold for GMX stats service (requires MERID_GMX_BASE_URL)."""

    venue = "gmx"

    def __init__(self, *, base_url: Optional[str] = None, use_mock: bool = False) -> None:
        super().__init__(base_url=base_url or os.getenv("MERID_GMX_BASE_URL"), use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        if not self.base_url:
            raise RuntimeError(
                "GMX base URL missing. Set MERID_GMX_BASE_URL (e.g., https://stats.gmx.io/api) to enable live mode."
            )
        response = self._client.get(f"{self.base_url}/perp/tickers")
        payload = response.json()
        entries = payload.get("result") or payload.get("data") or payload
        if isinstance(entries, dict):
            entries = entries.values()
        snapshots: List[PerpMarketSnapshot] = []
        for entry in entries:
            symbol = entry.get("symbol") or entry.get("market") or entry.get("name")
            if not symbol:
                continue
            price = _flt(entry.get("markPrice") or entry.get("price"))
            index_price = _flt(entry.get("indexPrice") or price)
            funding = _flt(entry.get("fundingRate"))
            oi = _flt(entry.get("openInterest"))
            volume = _flt(entry.get("volume24h"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    price=price,
                    index_price=index_price,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=price - index_price,
                    metadata={"raw": entry},
                )
            )
            if len(snapshots) >= limit:
                break
        return snapshots


class PerpetualProtocolAdapter(PerpVenueAdapterBase):
    """Adapter scaffold for Perpetual Protocol v2 (requires MERID_PERP_PROTOCOL_BASE_URL)."""

    venue = "perpetual_protocol"

    def __init__(self, *, base_url: Optional[str] = None, use_mock: bool = False) -> None:
        super().__init__(base_url=base_url or os.getenv("MERID_PERP_PROTOCOL_BASE_URL"), use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        if not self.base_url:
            raise RuntimeError(
                "Perpetual Protocol base URL missing. Set MERID_PERP_PROTOCOL_BASE_URL to enable live mode."
            )
        response = self._client.get(f"{self.base_url}/markets")
        payload = response.json()
        entries = payload.get("data") or payload.get("result") or payload
        snapshots: List[PerpMarketSnapshot] = []
        for entry in entries[:limit]:
            symbol = entry.get("symbol") or entry.get("market") or entry.get("ticker")
            price = _flt(entry.get("markPrice") or entry.get("price"))
            index_price = _flt(entry.get("indexPrice") or price)
            funding = _flt(entry.get("fundingRate"))
            oi = _flt(entry.get("openInterest"))
            volume = _flt(entry.get("volume24h"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    price=price,
                    index_price=index_price,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=price - index_price,
                    metadata={"raw": entry},
                )
            )
        return snapshots


class DriftPerpAdapter(PerpVenueAdapterBase):
    """Adapter scaffold for Drift Protocol (Solana)."""

    venue = "drift"

    def __init__(self, *, base_url: Optional[str] = None, use_mock: bool = False) -> None:
        super().__init__(base_url=base_url or os.getenv("MERID_DRIFT_BASE_URL"), use_mock=use_mock)

    def _fetch_markets_live(self, limit: int) -> List[PerpMarketSnapshot]:
        if not self.base_url:
            raise RuntimeError(
                "Drift base URL missing. Set MERID_DRIFT_BASE_URL to the Drift guardian or stats endpoint to enable live mode."
            )
        response = self._client.get(f"{self.base_url}/perp/markets")
        payload = response.json()
        entries = payload.get("data") or payload.get("result") or payload
        snapshots: List[PerpMarketSnapshot] = []
        for entry in entries[:limit]:
            symbol = entry.get("symbol") or entry.get("market")
            price = _flt(entry.get("markPrice") or entry.get("price"))
            index_price = _flt(entry.get("oraclePrice") or entry.get("indexPrice") or price)
            funding = _flt(entry.get("fundingRate"))
            oi = _flt(entry.get("openInterest"))
            volume = _flt(entry.get("volume24h"))
            snapshots.append(
                PerpMarketSnapshot(
                    venue=self.venue,
                    symbol=symbol,
                    price=price,
                    index_price=index_price,
                    open_interest=oi,
                    funding_rate=funding,
                    volume_24h=volume,
                    basis=price - index_price,
                    metadata={"raw": entry},
                )
            )
        return snapshots

    def _fetch_whales_live(self, limit: int) -> List[WhaleSignal]:
        if not self.base_url:
            return []
        endpoint = f"{self.base_url}/whales"
        try:
            response = self._client.get(endpoint, params={"limit": limit})
            payload = response.json()
            entries = payload.get("data") or payload.get("result") or payload
        except Exception as exc:
            logger.debug("Drift whale API unavailable: %s", exc)
            return []
        signals: List[WhaleSignal] = []
        for entry in entries[:limit]:
            signals.append(
                WhaleSignal(
                    venue=self.venue,
                    symbol=entry.get("symbol"),
                    direction=entry.get("direction") or "buy",
                    notional=_flt(entry.get("notional")),
                    timestamp_ms=float(entry.get("ts") or entry.get("timestamp_ms") or 0),
                    source=entry.get("source") or endpoint,
                    metadata={"raw": entry},
                )
            )
        return signals


__all__ = [
    "HyperliquidAdapter",
    "BybitPerpAdapter",
    "BinancePerpAdapter",
    "CoinbasePerpAdapter",
    "CryptoComPerpAdapter",
    "DyDxPerpAdapter",
    "GMXPerpAdapter",
    "PerpetualProtocolAdapter",
    "DriftPerpAdapter",
]
