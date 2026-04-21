"""C6: Perp Cross-Venue Context — Binance funding rate + implied volatility.

Fetches BTC and ETH perpetual futures data from Binance public REST APIs and
exposes a unified ``PerpContext`` snapshot that the EdgeModel can consume as
additional features for probability calibration.

No API key required for funding rate and mark-price endpoints.

Usage
-----
    ctx = get_perp_context_service()
    snap = await ctx.get_snapshot()   # PerpContextSnapshot (cached, TTL=60s)
    features = snap.to_edge_features()
    # → { "btc_funding_rate": 0.0001, "eth_funding_rate": ..., "btc_iv_30d": ... }
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL = 60.0  # seconds between Binance refreshes

_BINANCE_BASE  = "https://fapi.binance.com"
_FUNDING_URL   = _BINANCE_BASE + "/fapi/v1/premiumIndex?symbol={symbol}"
_KLINES_URL    = _BINANCE_BASE + "/fapi/v1/klines?symbol={symbol}&interval=1d&limit=30"

# D3: Deribit public endpoints for real implied volatility (no auth required)
_DERIBIT_BASE  = "https://www.deribit.com/api/v2/public"
_DERIBIT_VOL   = _DERIBIT_BASE + "/get_volatility_index_data?currency={currency}&resolution=3600&amount=1"


# ── Dataclass ──────────────────────────────────────────────────────────────────

@dataclass
class AssetPerpData:
    symbol: str                   # e.g. "BTCUSD"
    funding_rate: float = 0.0     # current 8h funding rate (signed)
    mark_price: float = 0.0
    index_price: float = 0.0
    next_funding_ts: float = 0.0
    iv_30d: float = 0.0           # annualised realised vol as IV proxy


@dataclass
class PerpContextSnapshot:
    btc: AssetPerpData = field(default_factory=lambda: AssetPerpData("BTCUSD"))
    eth: AssetPerpData = field(default_factory=lambda: AssetPerpData("ETHUSD"))
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"          # "live" | "stub"

    def to_edge_features(self) -> Dict[str, float]:
        """Return a flat dict of edge-model features."""
        return {
            "btc_funding_rate": self.btc.funding_rate,
            "eth_funding_rate": self.eth.funding_rate,
            "btc_mark_price": self.btc.mark_price,
            "eth_mark_price": self.eth.mark_price,
            "btc_iv_30d": self.btc.iv_30d,
            "eth_iv_30d": self.eth.iv_30d,
            "perp_context_age_s": round(time.time() - self.fetched_at, 1),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "btc": {
                "funding_rate": self.btc.funding_rate,
                "mark_price": self.btc.mark_price,
                "index_price": self.btc.index_price,
                "next_funding_ts": self.btc.next_funding_ts,
                "iv_30d": self.btc.iv_30d,
            },
            "eth": {
                "funding_rate": self.eth.funding_rate,
                "mark_price": self.eth.mark_price,
                "index_price": self.eth.index_price,
                "next_funding_ts": self.eth.next_funding_ts,
                "iv_30d": self.eth.iv_30d,
            },
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _fetch_json(url: str) -> Any:
    import httpx
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def _fetch_premium_index(symbol: str) -> AssetPerpData:
    """GET /fapi/v1/premiumIndex → funding rate + mark/index price."""
    data = await _fetch_json(_FUNDING_URL.format(symbol=symbol))
    return AssetPerpData(
        symbol=symbol,
        funding_rate=float(data.get("lastFundingRate") or 0),
        mark_price=float(data.get("markPrice") or 0),
        index_price=float(data.get("indexPrice") or 0),
        next_funding_ts=float(data.get("nextFundingTime") or 0) / 1000,
    )


def _realized_vol_annualised(closes: list[float]) -> float:
    """30-day realized vol as IV fallback (log-return std * sqrt(365))."""
    if len(closes) < 2:
        return 0.0
    log_returns = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes)) if closes[i - 1] > 0]
    if not log_returns:
        return 0.0
    n = len(log_returns)
    mean = sum(log_returns) / n
    variance = sum((r - mean) ** 2 for r in log_returns) / n
    return round(math.sqrt(variance) * math.sqrt(365), 4)


async def _fetch_deribit_iv(currency: str) -> float:
    """D3: Fetch real implied volatility from Deribit volatility index (DVOL).

    ``currency`` is ``"BTC"`` or ``"ETH"``.
    Returns annualised IV (e.g. 0.65 = 65%).  Falls back to 0.0 on error.
    """
    try:
        url = _DERIBIT_VOL.format(currency=currency)
        raw = await _fetch_json(url)
        data = raw.get("result", {}).get("data", [])
        if data:
            # Each entry: [timestamp_ms, open, high, low, close]
            latest_close = float(data[-1][4]) if len(data[-1]) >= 5 else 0.0
            # Deribit DVOL is already annualised percentage (e.g. 65.0 = 65%)
            return round(latest_close / 100.0, 4)
    except Exception as exc:
        logger.debug("perp_context: Deribit IV failed for %s: %s", currency, exc)
    return 0.0


async def _fetch_iv(symbol: str) -> float:
    """Try Deribit real IV first; fall back to realized-vol proxy from Binance klines."""
    currency = "BTC" if "BTC" in symbol else "ETH"
    iv = await _fetch_deribit_iv(currency)
    if iv > 0:
        return iv
    # Fallback: realized vol from Binance futures klines
    try:
        raw = await _fetch_json(_KLINES_URL.format(symbol=symbol))
        closes = [float(k[4]) for k in raw if k[4]]
        return _realized_vol_annualised(closes)
    except Exception as exc:
        logger.debug("perp_context: realized-vol fallback failed for %s: %s", symbol, exc)
        return 0.0


# ── Service class ──────────────────────────────────────────────────────────────

class PerpContextService:
    """Cache-backed service that fetches BTC/ETH perp data from Binance."""

    def __init__(self) -> None:
        self._cache: Optional[PerpContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = asyncio.Lock()

    async def get_snapshot(self, force: bool = False) -> PerpContextSnapshot:
        """Return a fresh-or-cached PerpContextSnapshot.

        Falls back to a stub snapshot on any network/parse error.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache

        async with self._lock:
            # Double-check after acquiring lock
            if not force and self._cache and (time.time() - self._cache_ts) < _CACHE_TTL:
                return self._cache
            snap = await self._fetch(now)
            self._cache = snap
            self._cache_ts = time.time()
            return snap

    async def _fetch(self, ts: float) -> PerpContextSnapshot:
        try:
            btc_task, eth_task = asyncio.gather(
                _fetch_premium_index("BTCUSD"),
                _fetch_premium_index("ETHUSD"),
            ), asyncio.gather(
                _fetch_iv("BTCUSD"),
                _fetch_iv("ETHUSD"),
            )
            (btc, eth), (btc_iv, eth_iv) = await asyncio.gather(btc_task, eth_task)
            btc.iv_30d = btc_iv   # Deribit DVOL or realized-vol fallback
            eth.iv_30d = eth_iv
            logger.debug(
                "perp_context: BTC fund=%.5f iv=%.3f  ETH fund=%.5f iv=%.3f",
                btc.funding_rate, btc.iv_30d, eth.funding_rate, eth.iv_30d,
            )
            return PerpContextSnapshot(btc=btc, eth=eth, fetched_at=ts, source="live")
        except Exception as exc:
            logger.warning("perp_context: Binance fetch failed (%s) — using stub", exc)
            return PerpContextSnapshot(
                btc=AssetPerpData("BTCUSD"),
                eth=AssetPerpData("ETHUSD"),
                fetched_at=ts,
                source="stub",
            )


# ── Singleton ──────────────────────────────────────────────────────────────────

_service: Optional[PerpContextService] = None
_svc_lock = Lock()


def get_perp_context_service() -> PerpContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = PerpContextService()
    return _service
