"""G3: Messari Crypto Fundamentals Context

Fetches on-chain and market fundamentals for BTC and ETH from the Messari
free-tier API. Key signals:

  - BTC market dominance %   → risk-on/off regime (high dominance = alt selloff)
  - BTC/ETH 24h price change → short-term momentum
  - BTC/ETH 30d volume trend → liquidity signal
  - BTC NVT ratio            → network value vs transaction value (over/undervalued)

Free tier: 20 req/min, no daily cap.  Cache: 15 minutes.

Environment
-----------
MESSARI_API_KEY — already set in .env; header: x-messari-api-key
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_MESSARI_KEY = os.getenv("MESSARI_API_KEY", "")
_BASE        = "https://data.messari.io/api/v1"
_CACHE_TTL   = 900.0   # 15 min


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class AssetMetrics:
    symbol: str
    price_usd: float = 0.0
    market_cap_usd: float = 0.0
    volume_24h: float = 0.0
    pct_change_1h: float = 0.0
    pct_change_24h: float = 0.0
    pct_change_7d: float = 0.0
    dominance_pct: float = 0.0   # % of total crypto market cap
    nvt_ratio: float = 0.0       # Network Value / Daily Tx Volume (BTC only)
    supply_pct_circulating: float = 0.0


@dataclass
class MessariContextSnapshot:
    btc: AssetMetrics = field(default_factory=lambda: AssetMetrics("BTC"))
    eth: AssetMetrics = field(default_factory=lambda: AssetMetrics("ETH"))
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    @property
    def btc_dominance_high(self) -> bool:
        return self.btc.dominance_pct > 55.0

    @property
    def btc_momentum_strong(self) -> bool:
        return self.btc.pct_change_24h > 2.0

    @property
    def market_trending_up(self) -> bool:
        return self.btc.pct_change_7d > 3.0 and self.eth.pct_change_7d > 3.0

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "messari_btc_24h":         self.btc.pct_change_24h,
            "messari_btc_7d":          self.btc.pct_change_7d,
            "messari_eth_24h":         self.eth.pct_change_24h,
            "messari_eth_7d":          self.eth.pct_change_7d,
            "messari_btc_dominance":   self.btc.dominance_pct,
            "messari_btc_nvt":         self.btc.nvt_ratio,
            "messari_btc_dom_high":    float(self.btc_dominance_high),
            "messari_btc_momentum":    float(self.btc_momentum_strong),
            "messari_market_up":       float(self.market_trending_up),
        }

    def to_dict(self) -> Dict[str, Any]:
        def _asset(a: AssetMetrics) -> Dict:
            return {
                "price_usd": a.price_usd,
                "pct_change_24h": a.pct_change_24h,
                "pct_change_7d": a.pct_change_7d,
                "dominance_pct": a.dominance_pct,
                "nvt_ratio": a.nvt_ratio,
                "volume_24h": a.volume_24h,
            }
        return {
            "btc": _asset(self.btc),
            "eth": _asset(self.eth),
            "btc_dominance_high": self.btc_dominance_high,
            "market_trending_up": self.market_trending_up,
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _get_json(url: str) -> Any:
    import httpx
    headers = {"x-messari-api-key": _MESSARI_KEY} if _MESSARI_KEY else {}
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _fetch_asset(slug: str) -> AssetMetrics:
    symbol = slug.upper()
    try:
        raw  = await _get_json(f"{_BASE}/assets/{slug}/metrics")
        data = raw.get("data", {})
        mkt  = data.get("market_data", {})
        roi  = data.get("roi_data", {})
        mcap = data.get("marketcap", {})
        on_chain = data.get("on_chain_data", {})

        return AssetMetrics(
            symbol=symbol,
            price_usd=float(mkt.get("price_usd") or 0),
            market_cap_usd=float(mcap.get("current_marketcap_usd") or 0),
            volume_24h=float(mkt.get("volume_last_24_hours") or 0),
            pct_change_1h=float(mkt.get("percent_change_usd_last_1_hour") or 0),
            pct_change_24h=float(mkt.get("percent_change_usd_last_24_hours") or 0),
            pct_change_7d=float(roi.get("percent_change_last_1_week") or 0),
            dominance_pct=float(mcap.get("marketcap_dominance_percent") or 0),
            nvt_ratio=float(on_chain.get("nvt_20d_ma") or 0),
            supply_pct_circulating=float(
                data.get("supply", {}).get("percent_in_circulation") or 0),
        )
    except Exception as exc:
        logger.debug("messari: %s fetch failed: %s", slug, exc)
        return AssetMetrics(symbol)


# ── Service class ──────────────────────────────────────────────────────────────

class MessariContextService:
    def __init__(self) -> None:
        self._cache: Optional[MessariContextSnapshot] = None
        self._cache_ts: float = 0.0
        self._lock = __import__("asyncio").Lock()

    async def get_snapshot(self, force: bool = False) -> MessariContextSnapshot:
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache
        async with self._lock:
            if not force and self._cache and (time.time() - self._cache_ts) < _CACHE_TTL:
                return self._cache
            snap = await self._fetch()
            self._cache = snap
            self._cache_ts = time.time()
            return snap

    async def _fetch(self) -> MessariContextSnapshot:
        import asyncio
        try:
            btc, eth = await asyncio.gather(
                _fetch_asset("bitcoin"),
                _fetch_asset("ethereum"),
                return_exceptions=True,
            )
            if isinstance(btc, Exception):
                btc = AssetMetrics("BTC")
            if isinstance(eth, Exception):
                eth = AssetMetrics("ETH")
            has_data = btc.price_usd > 0 or eth.price_usd > 0
            snap = MessariContextSnapshot(
                btc=btc, eth=eth,
                source="live" if has_data else "stub",
            )
            logger.debug(
                "messari: BTC=%.0f (%.1f%%) dom=%.1f%% ETH=%.0f (%.1f%%)",
                btc.price_usd, btc.pct_change_24h, btc.dominance_pct,
                eth.price_usd, eth.pct_change_24h,
            )
            return snap
        except Exception as exc:
            logger.warning("messari: context fetch failed (%s) — stub", exc)
            return MessariContextSnapshot(source="stub")


_service: Optional[MessariContextService] = None
_svc_lock = Lock()


def get_messari_context_service() -> MessariContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = MessariContextService()
    return _service
