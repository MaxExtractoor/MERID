"""H2: CoinGecko Market Context — Global Crypto Metrics + Trending

Uses the CoinGecko free public API (no key required, ~30 req/min):
  - /global          → total market cap, BTC dominance, market cap change
  - /search/trending → top-7 trending coins (retail attention signal)
  - /coins/markets   → top-20 by market cap (momentum, volume leaders)

Edge signals derived:
  - btc_dominance change → risk-on/off shift
  - total_market_cap change 24h → macro crypto sentiment
  - trending_non_btc_count → alt season indicator
  - top_gainer_pct → momentum signal (high values = FOMO regime)

Cache: 10 minutes (CoinGecko free tier is generous but respect rate limits)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_BASE      = "https://api.coingecko.com/api/v3"
_CACHE_TTL = 600.0   # 10 minutes


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class TrendingCoin:
    name: str
    symbol: str
    market_cap_rank: int = 0
    score: int = 0        # trending score (0=highest)


@dataclass
class CoinGeckoContextSnapshot:
    btc_dominance_pct: float = 0.0
    eth_dominance_pct: float = 0.0
    total_market_cap_usd: float = 0.0
    total_market_cap_change_24h: float = 0.0   # percent
    total_volume_24h: float = 0.0
    active_coins: int = 0
    trending: List[TrendingCoin] = field(default_factory=list)
    top_gainer_symbol: str = ""
    top_gainer_pct: float = 0.0
    top_loser_pct: float = 0.0
    alt_season: bool = False          # BTC dom falling + altcoins up
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    @property
    def market_expanding(self) -> bool:
        return self.total_market_cap_change_24h > 2.0

    @property
    def market_contracting(self) -> bool:
        return self.total_market_cap_change_24h < -2.0

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "cg_btc_dom":          self.btc_dominance_pct,
            "cg_market_change_24h": self.total_market_cap_change_24h,
            "cg_top_gainer":       self.top_gainer_pct,
            "cg_top_loser":        self.top_loser_pct,
            "cg_alt_season":       float(self.alt_season),
            "cg_market_expanding": float(self.market_expanding),
            "cg_market_contracting": float(self.market_contracting),
            "cg_trending_count":   float(len(self.trending)),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "btc_dominance_pct": round(self.btc_dominance_pct, 2),
            "eth_dominance_pct": round(self.eth_dominance_pct, 2),
            "total_market_cap_usd": self.total_market_cap_usd,
            "total_market_cap_change_24h": round(self.total_market_cap_change_24h, 2),
            "total_volume_24h": self.total_volume_24h,
            "alt_season": self.alt_season,
            "market_expanding": self.market_expanding,
            "top_gainer_symbol": self.top_gainer_symbol,
            "top_gainer_pct": round(self.top_gainer_pct, 2),
            "top_loser_pct": round(self.top_loser_pct, 2),
            "trending": [{"name": t.name, "symbol": t.symbol, "rank": t.market_cap_rank}
                         for t in self.trending],
            "fetched_at": self.fetched_at,
            "source": self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _get_json(path: str) -> Any:
    import httpx
    headers = {"Accept": "application/json"}
    async with httpx.AsyncClient(timeout=8.0) as client:
        resp = await client.get(f"{_BASE}{path}", headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _fetch_global() -> Dict:
    raw = await _get_json("/global")
    return raw.get("data", {})


async def _fetch_trending() -> List[TrendingCoin]:
    raw = await _get_json("/search/trending")
    coins = raw.get("coins", [])
    result = []
    for i, item in enumerate(coins[:7]):
        c = item.get("item", {})
        result.append(TrendingCoin(
            name=c.get("name", ""),
            symbol=c.get("symbol", ""),
            market_cap_rank=int(c.get("market_cap_rank") or 0),
            score=i,
        ))
    return result


async def _fetch_top_markets() -> tuple:
    """Returns (top_gainer_symbol, top_gainer_pct, top_loser_pct)."""
    raw = await _get_json(
        "/coins/markets?vs_currency=usd&order=market_cap_desc"
        "&per_page=30&page=1&price_change_percentage=24h"
    )
    if not raw:
        return "", 0.0, 0.0
    changes = [
        (c.get("symbol", ""), float(c.get("price_change_percentage_24h") or 0))
        for c in raw
    ]
    top_gainer = max(changes, key=lambda x: x[1], default=("", 0.0))
    top_loser  = min(changes, key=lambda x: x[1], default=("", 0.0))
    return top_gainer[0], top_gainer[1], top_loser[1]


# ── Service class ──────────────────────────────────────────────────────────────

class CoinGeckoContextService:
    def __init__(self) -> None:
        self._cache: Optional[CoinGeckoContextSnapshot] = None
        self._cache_ts: float = 0.0

    async def get_snapshot(self, force: bool = False) -> CoinGeckoContextSnapshot:
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache
        snap = await self._fetch()
        self._cache = snap
        self._cache_ts = time.time()
        return snap

    async def _fetch(self) -> CoinGeckoContextSnapshot:
        import asyncio
        try:
            global_data, trending, top_markets = await asyncio.gather(
                _fetch_global(), _fetch_trending(), _fetch_top_markets(),
                return_exceptions=True,
            )
            if isinstance(global_data, Exception):
                global_data = {}
            if isinstance(trending, Exception):
                trending = []
            if isinstance(top_markets, Exception):
                gainer_sym, gainer_pct, loser_pct = "", 0.0, 0.0
            else:
                gainer_sym, gainer_pct, loser_pct = top_markets

            mkt_caps   = global_data.get("market_cap_percentage", {})
            btc_dom    = float(mkt_caps.get("btc", 0))
            eth_dom    = float(mkt_caps.get("eth", 0))
            total_mcap = float(global_data.get("total_market_cap", {}).get("usd", 0) or 0)
            mcap_chg   = float(global_data.get("market_cap_change_percentage_24h_usd", 0) or 0)
            vol_24h    = float(global_data.get("total_volume", {}).get("usd", 0) or 0)
            active     = int(global_data.get("active_cryptocurrencies", 0) or 0)

            # Alt season: BTC dom < 50% AND market expanding
            alt_season = btc_dom < 50.0 and mcap_chg > 1.5

            snap = CoinGeckoContextSnapshot(
                btc_dominance_pct=round(btc_dom, 2),
                eth_dominance_pct=round(eth_dom, 2),
                total_market_cap_usd=total_mcap,
                total_market_cap_change_24h=round(mcap_chg, 2),
                total_volume_24h=vol_24h,
                active_coins=active,
                trending=trending or [],
                top_gainer_symbol=gainer_sym,
                top_gainer_pct=round(gainer_pct, 2),
                top_loser_pct=round(loser_pct, 2),
                alt_season=alt_season,
                source="live" if total_mcap > 0 else "stub",
            )
            logger.debug(
                "coingecko: BTC dom=%.1f%% mkt_chg=%.2f%% alt_season=%s",
                btc_dom, mcap_chg, alt_season,
            )
            return snap
        except Exception as exc:
            logger.warning("coingecko: fetch failed (%s) — stub", exc)
            return CoinGeckoContextSnapshot(source="stub")


_service: Optional[CoinGeckoContextService] = None
_svc_lock = Lock()


def get_coingecko_context_service() -> CoinGeckoContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = CoinGeckoContextService()
    return _service
