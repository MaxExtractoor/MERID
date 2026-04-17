"""H3: CoinMarketCap Context — Gainers/Losers + Market Concentration

Uses CMC v1 API (Basic tier, 10k calls/month):
  - /v1/cryptocurrency/listings/latest  → top-100 sorted by market cap
    → derive: top gainers (>20% 24h), top losers (<-20% 24h),
               market cap concentration (top-10 share of total)
  - /v1/global-metrics/quotes/latest    → BTC/ETH dominance, total mcap,
                                          volume, active pairs

Edge signals:
  - cmc_gainer_count  : # coins up >20% 24h   → high = FOMO / risk-on (contrarian)
  - cmc_loser_count   : # coins down >20% 24h  → high = panic / fear
  - cmc_top10_share   : top-10 mcap / total    → high = concentration / alt risk
  - cmc_btc_dom       : BTC dominance %
  - cmc_vol_ratio     : 24h volume / total mcap → liquidity depth

Cache: 15 minutes
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_CMC_KEY   = os.getenv("CMC_API_KEY", "")
_BASE      = "https://pro-api.coinmarketcap.com"
_CACHE_TTL = 900.0   # 15 minutes — conserves monthly quota


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class CoinEntry:
    symbol: str
    name: str
    market_cap_usd: float
    pct_change_24h: float
    volume_24h: float


@dataclass
class CMCContextSnapshot:
    btc_dominance_pct: float = 0.0
    eth_dominance_pct: float = 0.0
    total_market_cap_usd: float = 0.0
    total_volume_24h: float = 0.0
    active_cryptocurrencies: int = 0
    top10_market_cap_share: float = 0.0    # 0..1 fraction
    gainer_count: int = 0                  # coins up >20% 24h in top-100
    loser_count: int = 0                   # coins down >20% 24h in top-100
    top_gainer_symbol: str = ""
    top_gainer_pct: float = 0.0
    top_loser_symbol: str = ""
    top_loser_pct: float = 0.0
    vol_ratio: float = 0.0                 # volume / market_cap
    fetched_at: float = field(default_factory=time.time)
    source: str = "live"

    @property
    def fomo_regime(self) -> bool:
        """Many coins surging simultaneously → FOMO / late-cycle signal."""
        return self.gainer_count >= 10

    @property
    def panic_regime(self) -> bool:
        """Many coins crashing simultaneously → capitulation signal."""
        return self.loser_count >= 10

    @property
    def concentrated_market(self) -> bool:
        """Top-10 hold >70% of total mcap → alt risk elevated."""
        return self.top10_market_cap_share > 0.70

    def to_edge_features(self) -> Dict[str, float]:
        return {
            "cmc_btc_dom":         self.btc_dominance_pct,
            "cmc_gainer_count":    float(self.gainer_count),
            "cmc_loser_count":     float(self.loser_count),
            "cmc_top10_share":     self.top10_market_cap_share,
            "cmc_vol_ratio":       self.vol_ratio,
            "cmc_fomo":            float(self.fomo_regime),
            "cmc_panic":           float(self.panic_regime),
            "cmc_concentrated":    float(self.concentrated_market),
            "cmc_top_gainer_pct":  self.top_gainer_pct,
            "cmc_top_loser_pct":   self.top_loser_pct,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "btc_dominance_pct":      round(self.btc_dominance_pct, 2),
            "eth_dominance_pct":      round(self.eth_dominance_pct, 2),
            "total_market_cap_usd":   self.total_market_cap_usd,
            "total_volume_24h":       self.total_volume_24h,
            "active_cryptocurrencies": self.active_cryptocurrencies,
            "top10_market_cap_share": round(self.top10_market_cap_share, 4),
            "gainer_count":           self.gainer_count,
            "loser_count":            self.loser_count,
            "top_gainer_symbol":      self.top_gainer_symbol,
            "top_gainer_pct":         round(self.top_gainer_pct, 2),
            "top_loser_symbol":       self.top_loser_symbol,
            "top_loser_pct":          round(self.top_loser_pct, 2),
            "vol_ratio":              round(self.vol_ratio, 6),
            "fomo_regime":            self.fomo_regime,
            "panic_regime":           self.panic_regime,
            "concentrated_market":    self.concentrated_market,
            "fetched_at":             self.fetched_at,
            "source":                 self.source,
        }


# ── Fetch helpers ──────────────────────────────────────────────────────────────

async def _cmc_get(path: str, params: Dict) -> Any:
    import httpx
    headers = {
        "Accepts": "application/json",
        "X-CMC_PRO_API_KEY": _CMC_KEY,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{_BASE}{path}", params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _fetch_global() -> Dict:
    raw = await _cmc_get("/v1/global-metrics/quotes/latest", {})
    return raw.get("data", {})


async def _fetch_listings() -> List[CoinEntry]:
    raw = await _cmc_get(
        "/v1/cryptocurrency/listings/latest",
        {"limit": 100, "sort": "market_cap", "convert": "USD"},
    )
    coins = raw.get("data", [])
    result = []
    for c in coins:
        q = c.get("quote", {}).get("USD", {})
        result.append(CoinEntry(
            symbol=c.get("symbol", ""),
            name=c.get("name", ""),
            market_cap_usd=float(q.get("market_cap") or 0),
            pct_change_24h=float(q.get("percent_change_24h") or 0),
            volume_24h=float(q.get("volume_24h") or 0),
        ))
    return result


# ── Service ────────────────────────────────────────────────────────────────────

class CMCContextService:
    def __init__(self) -> None:
        self._cache: Optional[CMCContextSnapshot] = None
        self._cache_ts: float = 0.0

    async def get_snapshot(self, force: bool = False) -> CMCContextSnapshot:
        now = time.time()
        if not force and self._cache and (now - self._cache_ts) < _CACHE_TTL:
            return self._cache
        snap = await self._fetch()
        self._cache = snap
        self._cache_ts = time.time()
        return snap

    async def _fetch(self) -> CMCContextSnapshot:
        if not _CMC_KEY:
            logger.debug("cmc: no CMC_API_KEY — stub")
            return CMCContextSnapshot(source="stub")
        try:
            import asyncio
            global_data, coins = await asyncio.gather(
                _fetch_global(), _fetch_listings(), return_exceptions=True,
            )
            if isinstance(global_data, Exception):
                global_data = {}
            if isinstance(coins, Exception):
                coins = []

            quote = global_data.get("quote", {}).get("USD", {})
            btc_dom   = float(global_data.get("btc_dominance", 0))
            eth_dom   = float(global_data.get("eth_dominance", 0))
            total_mcap = float(quote.get("total_market_cap", 0) or 0)
            total_vol  = float(quote.get("total_volume_24h", 0) or 0)
            active     = int(global_data.get("active_cryptocurrencies", 0) or 0)

            gainers = [c for c in coins if c.pct_change_24h >  20.0]
            losers  = [c for c in coins if c.pct_change_24h < -20.0]
            top_gainer = max(coins, key=lambda c: c.pct_change_24h, default=None) if coins else None
            top_loser  = min(coins, key=lambda c: c.pct_change_24h, default=None) if coins else None

            top10_mcap = sum(c.market_cap_usd for c in coins[:10])
            top10_share = (top10_mcap / total_mcap) if total_mcap > 0 else 0.0
            vol_ratio   = (total_vol / total_mcap) if total_mcap > 0 else 0.0

            snap = CMCContextSnapshot(
                btc_dominance_pct=round(btc_dom, 2),
                eth_dominance_pct=round(eth_dom, 2),
                total_market_cap_usd=total_mcap,
                total_volume_24h=total_vol,
                active_cryptocurrencies=active,
                top10_market_cap_share=round(top10_share, 4),
                gainer_count=len(gainers),
                loser_count=len(losers),
                top_gainer_symbol=top_gainer.symbol if top_gainer else "",
                top_gainer_pct=round(top_gainer.pct_change_24h if top_gainer else 0, 2),
                top_loser_symbol=top_loser.symbol if top_loser else "",
                top_loser_pct=round(top_loser.pct_change_24h if top_loser else 0, 2),
                vol_ratio=round(vol_ratio, 6),
                source="live" if total_mcap > 0 else "stub",
            )
            logger.debug(
                "cmc: BTC dom=%.1f%% gainers=%d losers=%d top10_share=%.2f",
                btc_dom, len(gainers), len(losers), top10_share,
            )
            return snap
        except Exception as exc:
            logger.warning("cmc: fetch failed (%s) — stub", exc)
            return CMCContextSnapshot(source="stub")


_service: Optional[CMCContextService] = None
_svc_lock = Lock()


def get_cmc_context_service() -> CMCContextService:
    global _service
    if _service is None:
        with _svc_lock:
            if _service is None:
                _service = CMCContextService()
    return _service
