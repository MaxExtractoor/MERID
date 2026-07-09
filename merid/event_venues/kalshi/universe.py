"""KalshiUniverse — Market pool abstraction over KalshiMarketCatalog.

Provides category-sliced, liquidity-filtered pools of CatalogMarket objects
so agents can iterate the full Kalshi universe without hardcoding tickers.

Pools:
  all_open          — Every active Kalshi market above liquidity floor.
  by_category[cat]  — Markets in a single Kalshi category.
  sweep(tag)        — Markets matching a strategy tag (category or asset).

Configuration (env vars, all optional):
  MERID_UNIVERSE_MIN_VOLUME       — Min contracts volume (default 0).
  MERID_UNIVERSE_MIN_OI           — Min open interest (default 0).
  MERID_UNIVERSE_MAX_SPREAD_CENTS — Max bid-ask spread in cents (default 99).
  MERID_UNIVERSE_MAX_PER_AGENT    — Hard cap: max markets per agent sweep (default 50).
  MERID_UNIVERSE_CATEGORIES       — Comma-separated category whitelist (empty = all).

Per-category mode overrides (paper vs live):
  MERID_UNIVERSE_MODE_<CAT>  — "paper" or "live", e.g. MERID_UNIVERSE_MODE_CRYPTO=live

Usage::

    universe = get_kalshi_universe()
    pool = universe.get_pool("crypto")
    for cm in pool:
        intent = agent.evaluate(cm)
        if intent:
            route_order(intent)
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional

from merid.event_venues.kalshi.market_catalog import CatalogMarket, get_market_catalog
from merid.event_venues.kalshi.risk_parameters import (
    UNIVERSE_MIN_VOLUME_DEFAULT,
    UNIVERSE_MIN_OPEN_INTEREST_DEFAULT,
    UNIVERSE_MAX_SPREAD_CENTS_DEFAULT,
    UNIVERSE_MAX_PER_AGENT_DEFAULT,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.universe")


# ── Config ────────────────────────────────────────────────────────────────

@dataclass
class UniverseConfig:
    """Liquidity and scope gates for the universe pools.

    CRITICAL FIX: Read from profile YAML instead of environment variables (single source of truth)
    Profile values: min_volume=5, min_open_interest=1, max_spread_cents=40 (from kalshi_crypto_15m_v2.yaml)
    Fallback to risk_parameters defaults if profile not available.
    """
    # Read from profile YAML (single source of truth)
    try:
        from merid.risk.profiles.crypto_15m_profile import Crypto15mProfileAdapter
        profile_adapter = Crypto15mProfileAdapter()
        profile = profile_adapter.profile
        
        min_volume = getattr(profile, 'universe_min_volume', UNIVERSE_MIN_VOLUME_DEFAULT)
        min_open_interest = getattr(profile, 'universe_min_open_interest', UNIVERSE_MIN_OPEN_INTEREST_DEFAULT)
        max_spread_cents = getattr(profile, 'universe_max_spread_cents', UNIVERSE_MAX_SPREAD_CENTS_DEFAULT)
    except Exception as e:
        # Fallback to risk_parameters defaults if profile not available
        logger.warning(
            "[universe] Failed to load universe config from profile: %s (using risk_parameters defaults)",
            e
        )
        min_volume = int(os.getenv("MERID_UNIVERSE_MIN_VOLUME", str(UNIVERSE_MIN_VOLUME_DEFAULT)))
        min_open_interest = int(os.getenv("MERID_UNIVERSE_MIN_OI", str(UNIVERSE_MIN_OPEN_INTEREST_DEFAULT)))
        max_spread_cents = int(os.getenv("MERID_UNIVERSE_MAX_SPREAD_CENTS", str(UNIVERSE_MAX_SPREAD_CENTS_DEFAULT)))
    
    # Allow env var override for testing (but profile is primary source)
    min_volume = int(os.getenv("MERID_UNIVERSE_MIN_VOLUME", str(min_volume)))
    min_open_interest = int(os.getenv("MERID_UNIVERSE_MIN_OI", str(min_open_interest)))
    max_spread_cents = int(os.getenv("MERID_UNIVERSE_MAX_SPREAD_CENTS", str(max_spread_cents)))
    max_per_agent = int(os.getenv("MERID_UNIVERSE_MAX_PER_AGENT", str(UNIVERSE_MAX_PER_AGENT_DEFAULT)))
    allowed_categories: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        _env = os.getenv("MERID_UNIVERSE_CATEGORIES", "")
        if _env:
            self.allowed_categories = [c.strip().lower() for c in _env.split(",") if c.strip()]

    def category_allowed(self, category: Optional[str]) -> bool:
        if not self.allowed_categories:
            return True
        normalized = [c.lower() for c in self.allowed_categories]
        return (category or "other").lower() in normalized


# ── Per-category mode config ──────────────────────────────────────────────

KNOWN_CATEGORIES = (
    "cross_category", "crypto", "economics", "macro", "financials", "politics",
    "climate", "sports", "tech", "culture", "science", "equities", "other",
)


def get_category_mode(category: str) -> str:
    """Return 'paper' or 'live' for a category.

    Checks MERID_UNIVERSE_MODE_<CATEGORY> env var first, then falls back
    to the global MERID_PM_TRADING_MODE setting.
    """
    env_key = f"MERID_UNIVERSE_MODE_{category.upper()}"
    override = os.getenv(env_key, "").strip().lower()
    if override in ("paper", "live"):
        return override
    try:
        from merid.settings import settings as _s
        return _s.MERID_PM_TRADING_MODE.lower()
    except Exception:
        return os.getenv("MERID_PM_TRADING_MODE", "paper").lower()


def get_all_category_modes() -> Dict[str, str]:
    """Return a dict of {category: mode} for every known category."""
    return {cat: get_category_mode(cat) for cat in KNOWN_CATEGORIES}


# ── Liquidity filter ──────────────────────────────────────────────────────

def _passes_liquidity(cm: CatalogMarket, cfg: UniverseConfig) -> bool:
    """Return True if the market meets the universe liquidity floor."""
    mkt = cm.market
    volume = float(mkt.volume) if mkt.volume else 0.0
    oi = float(mkt.open_interest) if mkt.open_interest else 0.0

    # CRITICAL FIX: Handle nested raw_data access safely
    raw = getattr(mkt, "raw_data", None) or {}
    bid = int(raw.get("yes_bid", 0) or 0)
    ask = int(raw.get("yes_ask", 0) or 0)
    spread = ask - bid if bid > 0 and ask > 0 else None

    reasons = []

    if cfg.min_volume > 0 and volume < cfg.min_volume:
        reasons.append(f"volume={volume} < min_volume={cfg.min_volume}")
    if cfg.min_open_interest > 0 and oi < cfg.min_open_interest:
        reasons.append(f"oi={oi} < min_open_interest={cfg.min_open_interest}")
    if spread is not None and spread > cfg.max_spread_cents:
        reasons.append(f"spread={spread} > max_spread_cents={cfg.max_spread_cents}")

    if reasons:
        logger.warning(
            "[UNIVERSE-FILTER] market=%s asset=%s REJECTED: %s",
            getattr(mkt, "market_id", getattr(mkt, "ticker", "NA")),
            getattr(cm, "asset", None),
            "; ".join(reasons),
        )
        return False

    return True


# ── Universe ──────────────────────────────────────────────────────────────

class KalshiUniverse:
    """Market pool abstraction wrapping KalshiMarketCatalog.

    All pool methods return a fresh slice of the current catalog snapshot —
    no staleness beyond the catalog's own refresh interval.
    """

    def __init__(self, config: Optional[UniverseConfig] = None) -> None:
        self._config = config or UniverseConfig()

    @property
    def config(self) -> UniverseConfig:
        return self._config

    # ── Core pool methods ─────────────────────────────────────────────────

    def get_pool(
        self,
        category: Optional[str] = None,
        *,
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        min_volume: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> List[CatalogMarket]:
        """Return markets matching the given filters, liquidity-filtered.

        Args:
            category:   Kalshi category string (None = all allowed categories).
            asset:      MERID asset tag (BTC, CPI, …).
            timeframe:  MERID timeframe tag (15m, 1h, daily, …).
            min_volume: Per-call volume override (uses config default if None).
            limit:      Max results; falls back to config.max_per_agent.
        """
        catalog = get_market_catalog()
        cfg = self._config

        if category:
            if not cfg.category_allowed(category):
                logger.debug("universe.get_pool: category %s not in allowlist", category)
                return []
            markets = catalog.get_markets_by_category(
                category, timeframe=timeframe, asset=asset
            )
        elif asset:
            markets = catalog.get_markets_by_asset(asset, timeframe=timeframe)
        else:
            markets = [
                cm for cm in catalog.get_all_markets()
                if cfg.category_allowed(cm.category)
            ]

        vol_floor = min_volume if min_volume is not None else cfg.min_volume
        liq_cfg = (
            UniverseConfig(
                min_volume=vol_floor,
                min_open_interest=cfg.min_open_interest,
                max_spread_cents=cfg.max_spread_cents,
                max_per_agent=cfg.max_per_agent,
            )
            if vol_floor != cfg.min_volume
            else cfg
        )

        filtered = [cm for cm in markets if _passes_liquidity(cm, liq_cfg)]
        cap = limit if limit is not None else cfg.max_per_agent
        
        # Log universe pool result for diagnostics
        logger.info(
            "UNIVERSE-POOL-RESULT",
            extra={
                "category": category,
                "asset": asset,
                "timeframe": timeframe,
                "raw_count": len(markets),
                "filtered_count": len(filtered),
                "min_volume": liq_cfg.min_volume,
                "min_open_interest": liq_cfg.min_open_interest,
                "max_spread_cents": liq_cfg.max_spread_cents,
            },
        )
        
        # Guard: warn if markets exist but all were filtered out
        if markets and not filtered:
            logger.warning(
                "[UNIVERSE-EMPTY-AFTER-FILTER] category=%s asset=%s timeframe=%s raw_count=%d filtered_count=%d min_volume=%d min_open_interest=%d max_spread_cents=%d",
                category, asset, timeframe, len(markets), len(filtered),
                liq_cfg.min_volume, liq_cfg.min_open_interest, liq_cfg.max_spread_cents
            )
        
        return filtered[:cap]

    def get_all_open(self, limit: Optional[int] = None) -> List[CatalogMarket]:
        """Return all active, liquidity-passing markets across every allowed category."""
        return self.get_pool(limit=limit)

    def iter_categories(self) -> Iterator[tuple]:
        """Yield (category, mode, pool) tuples for every allowed category with markets.

        Useful for sweeping across all categories in the decision loop.
        """
        for cat in KNOWN_CATEGORIES:
            if not self._config.category_allowed(cat):
                continue
            pool = self.get_pool(cat)
            if pool:
                mode = get_category_mode(cat)
                yield cat, mode, pool

    def coverage_summary(self) -> Dict[str, object]:
        """Return a summary dict: total markets, per-category counts, modes."""
        catalog = get_market_catalog()
        all_markets = catalog.get_all_markets()
        liq_pass = [cm for cm in all_markets if _passes_liquidity(cm, self._config)]

        by_cat: Dict[str, int] = {}
        for cm in liq_pass:
            cat = (cm.category or "other").lower()
            by_cat[cat] = by_cat.get(cat, 0) + 1

        return {
            "total_active": len(all_markets),
            "total_liquid": len(liq_pass),
            "by_category": by_cat,
            "category_modes": get_all_category_modes(),
            "allowed_categories": self._config.allowed_categories or list(KNOWN_CATEGORIES),
            "max_per_agent": self._config.max_per_agent,
        }


# ── Singleton ─────────────────────────────────────────────────────────────
#
# BUG-06 fix: the original singleton ignored the ``config`` argument after the
# first call, causing every agent to share the universe of whichever agent
# happened to create it first.  The KalshiMarketCatalog (expensive, API-backed)
# remains a true singleton via get_market_catalog().  KalshiUniverse itself is
# just a lightweight filter wrapper, so we key it by the frozenset of allowed
# categories.  Agents with no category restriction still share one instance
# (the empty-key slot) so the common case has no overhead.

_universe_cache: dict = {}
_universe_lock = threading.Lock()
# Default-slot instance (tests / introspection); updated when cache_key is empty.
_universe: Optional[KalshiUniverse] = None


def get_kalshi_universe(config: Optional[UniverseConfig] = None) -> KalshiUniverse:
    """Return a KalshiUniverse for the given config.

    Instances are cached by allowed_categories so each distinct category set
    gets its own filter wrapper while all instances share the same underlying
    KalshiMarketCatalog singleton.
    
    If kalshi_crypto_15m_v2 profile is active, universe config is loaded from profile
    to use relaxed thresholds suitable for the 5-market 15m crypto universe.
    """
    # Check if kalshi_crypto_15m_v2 profile is active and load universe config from profile
    if config is None:
        try:
            from merid.risk.profiles.crypto_15m_profile import is_profile_active, get_active_profile
            if is_profile_active():
                adapter = get_active_profile()
                profile = adapter.profile
                config = UniverseConfig(
                    min_volume=profile.universe_min_volume,
                    min_open_interest=profile.universe_min_open_interest,
                    max_spread_cents=profile.universe_max_spread_cents,
                )
                logger.info(
                    "[UNIVERSE-PROFILE] Loaded universe config from kalshi_crypto_15m_v2 profile: "
                    f"min_volume={config.min_volume}, min_open_interest={config.min_open_interest}, "
                    f"max_spread_cents={config.max_spread_cents}"
                )
        except Exception as e:
            logger.debug(f"[UNIVERSE-PROFILE] Failed to load profile universe config, using defaults: {e}")
            config = UniverseConfig()
    
    effective_config = config or UniverseConfig()
    cache_key = frozenset(c.lower() for c in (effective_config.allowed_categories or []))

    if cache_key not in _universe_cache:
        with _universe_lock:
            if cache_key not in _universe_cache:
                _universe_cache[cache_key] = KalshiUniverse(effective_config)
    inst = _universe_cache[cache_key]
    global _universe
    if cache_key == frozenset():
        _universe = inst
    return inst
