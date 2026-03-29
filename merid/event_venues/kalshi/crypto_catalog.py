"""KalshiCryptoCatalog — Crypto-specific view over KalshiMarketCatalog.

Filters the full Kalshi market catalog to BTC/ETH/SOL/XRP/DOGE markets
across the four active timeframes (15m, 1h, daily, weekly), and provides
helpers for WS subscription ticker collection, coverage verification, and
asset-based ticker resolution.

All asset and timeframe definitions come from ``config.kalshi_crypto_config``
— the single source of truth.  This module never defines its own lists.

Key public API::

    catalog = KalshiCryptoCatalog(market_catalog)
    catalog.reload(markets)              # ingest list[CatalogMarket]
    tickers = catalog.iter_tickers("BTC", "15m")
    all_tickers = catalog.all_active_tickers()

    # WS subscription helpers
    ws_tickers = collect_crypto_ws_subscription_tickers(catalog)
    coverage   = summarize_crypto_ws_coverage(ws_tickers)
    assert_each_asset_represented(ws_tickers)   # raises if any asset missing
    ok, missing = check_ws_ticker_asset_coverage(ws_tickers, strict=False)
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from config.kalshi_crypto_config import (
    ACTIVE_CRYPTO_ASSETS,
    ACTIVE_CRYPTO_WS_TIMEFRAMES,
    ALL_CRYPTO_ASSETS,
    WS_TIMEFRAME_TO_FREQ,
)
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.crypto_catalog")

# Lazy import to avoid circular deps at module level
_CatalogMarket = None  # resolved on first use


def _catalog_market_type():  # noqa: ANN202
    global _CatalogMarket
    if _CatalogMarket is None:
        from merid.event_venues.kalshi.market_catalog import CatalogMarket  # noqa: PLC0415
        _CatalogMarket = CatalogMarket
    return _CatalogMarket


# ── Ticker → asset resolution patterns ─────────────────────────────────────

_TICKER_ASSET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"^KX(?:BTC|BITCOIN)", re.I), "BTC"),
    (re.compile(r"^KX(?:ETH|ETHEREUM)", re.I), "ETH"),
    (re.compile(r"^KX(?:SOL|SOLANA)", re.I), "SOL"),
    (re.compile(r"^KX(?:XRP|RIPPLE)", re.I), "XRP"),
    (re.compile(r"^KX(?:DOGE|DOGECOIN)", re.I), "DOGE"),
]


def kalshi_ticker_to_asset(ticker: str) -> Optional[str]:
    """Return the canonical asset for a Kalshi market ticker, or ``None``.

    Examples::

        kalshi_ticker_to_asset("KXBTCD-25JUN-T100000")  → "BTC"
        kalshi_ticker_to_asset("KXETH15-25JUN-T3200")   → "ETH"
        kalshi_ticker_to_asset("KXCPI-25JUN-100")       → None
    """
    for pattern, asset in _TICKER_ASSET_PATTERNS:
        if pattern.match(ticker):
            return asset
    return None


# ── KalshiCryptoCatalog ─────────────────────────────────────────────────────


class KalshiCryptoCatalog:
    """Crypto-specific filtered view over the full Kalshi market catalog.

    Holds only open markets for ``ACTIVE_CRYPTO_ASSETS × ACTIVE_CRYPTO_WS_TIMEFRAMES``.
    Refresh by calling ``reload(markets)`` with the raw list from
    ``KalshiMarketCatalog.get_all_markets()``.
    """

    def __init__(self) -> None:
        # Keyed by (asset, ws_timeframe) → list of CatalogMarket
        self._grid: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
        self._total: int = 0

    # ── Ingestion ────────────────────────────────────────────────────────

    def reload(self, markets: List[Any]) -> int:
        """Ingest a fresh list of CatalogMarket objects.

        Filters to open crypto markets in the active asset × timeframe grid.
        Returns the number of markets kept.
        """
        new_grid: Dict[Tuple[str, str], List[Any]] = defaultdict(list)
        kept = 0

        for m in markets:
            asset = getattr(m, "asset", None)
            timeframe = getattr(m, "timeframe", None)
            status = getattr(getattr(m, "market", None), "status", None)

            if asset not in ALL_CRYPTO_ASSETS:
                continue
            if timeframe not in ACTIVE_CRYPTO_WS_TIMEFRAMES:
                continue
            # status=None is treated as "open": Kalshi's live API sometimes
            # omits the status field on fresh markets.  Treating None as open
            # is intentional — we want to include markets we haven't seen a
            # status for yet rather than silently dropping them.
            if status is not None and status != "open":
                continue

            new_grid[(asset, timeframe)].append(m)
            kept += 1

        self._grid = new_grid
        self._total = kept

        logger.debug(
            "KalshiCryptoCatalog reloaded: %d markets kept "
            "(assets=%s, timeframes=%s)",
            kept,
            [a for a in ACTIVE_CRYPTO_ASSETS if any((a, tf) in new_grid for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES)],
            [tf for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES if any((a, tf) in new_grid for a in ACTIVE_CRYPTO_ASSETS)],
        )
        return kept

    # ── Queries ──────────────────────────────────────────────────────────

    def iter_tickers(self, asset: str, timeframe: str) -> List[str]:
        """Return all open market tickers for ``(asset, timeframe)``.

        ``timeframe`` must be a WS-style label (``"15m"``, ``"1h"``, ``"daily"``,
        ``"weekly"``).
        """
        markets = self._grid.get((asset, timeframe), [])
        return [m.market.ticker for m in markets if getattr(m.market, "ticker", None)]

    def all_active_tickers(self) -> List[str]:
        """Return all tickers across all active (asset, timeframe) pairs, deduplicated."""
        seen: Set[str] = set()
        result: List[str] = []
        for (asset, tf) in self._grid:
            if asset in ALL_CRYPTO_ASSETS and tf in ACTIVE_CRYPTO_WS_TIMEFRAMES:
                for ticker in self.iter_tickers(asset, tf):
                    if ticker not in seen:
                        seen.add(ticker)
                        result.append(ticker)
        return result

    def assets_covered(self) -> List[str]:
        """Return which assets have at least one market in the catalog."""
        return [a for a in ACTIVE_CRYPTO_ASSETS if any(self._grid.get((a, tf)) for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES)]

    def grid_summary(self) -> Dict[str, Dict[str, int]]:
        """Return per-(asset, timeframe) market counts."""
        summary: Dict[str, Dict[str, int]] = {}
        for asset in ACTIVE_CRYPTO_ASSETS:
            summary[asset] = {tf: len(self._grid.get((asset, tf), [])) for tf in ACTIVE_CRYPTO_WS_TIMEFRAMES}
        return summary

    def __len__(self) -> int:
        return self._total


# ── Catalog builder ─────────────────────────────────────────────────────────


def build_kalshi_crypto_catalog_from_catalog_markets(markets: List[Any]) -> KalshiCryptoCatalog:
    """Build a KalshiCryptoCatalog from a list of CatalogMarket objects.

    This is the preferred factory.  Pass ``KalshiMarketCatalog.get_all_markets()``
    and receive a crypto-filtered catalog ready for WS subscription.
    """
    crypto_catalog = KalshiCryptoCatalog()
    crypto_catalog.reload(markets)
    return crypto_catalog


# ── WS subscription helpers ─────────────────────────────────────────────────

#: Maximum tickers per WS subscription batch message.
KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE: int = 50


def collect_crypto_ws_subscription_tickers(catalog: KalshiCryptoCatalog) -> List[str]:
    """Return the WS ticker list derived from *catalog*.

    Tickers are ordered asset-first then timeframe, deduplicated, and
    capped at 500 total (more than sufficient for five assets × four
    timeframes × ~20 strikes each).
    """
    tickers = catalog.all_active_tickers()
    if not tickers:
        logger.warning(
            "collect_crypto_ws_subscription_tickers: no tickers in crypto catalog. "
            "Has the catalog been loaded? Returning empty list."
        )
    return tickers[:500]


def summarize_crypto_ws_coverage(tickers: List[str]) -> Dict[str, Any]:
    """Return a JSON-friendly coverage dict for diagnostics and health checks.

    Counts how many tickers map to each asset, and which assets are missing.
    """
    counts: Dict[str, int] = {a: 0 for a in ACTIVE_CRYPTO_ASSETS}
    unknown: int = 0
    for ticker in tickers:
        asset = kalshi_ticker_to_asset(ticker)
        if asset and asset in counts:
            counts[asset] += 1
        else:
            unknown += 1

    missing = [a for a, cnt in counts.items() if cnt == 0]
    return {
        "total_tickers": len(tickers),
        "by_asset": counts,
        "missing_assets": missing,
        "unknown_tickers": unknown,
        "coverage_complete": len(missing) == 0,
    }


def assert_each_asset_represented(tickers: List[str]) -> None:
    """Raise ``RuntimeError`` if any active crypto asset has zero subscribed tickers.

    Intended for use at application startup to fail-fast when discovery is
    incomplete.

    Args:
        tickers: List of WS subscription tickers from
                 ``collect_crypto_ws_subscription_tickers``.

    Raises:
        RuntimeError: If one or more assets have no tickers.
    """
    coverage = summarize_crypto_ws_coverage(tickers)
    missing = coverage["missing_assets"]
    if missing:
        raise RuntimeError(
            f"Discover invariant violated: no open Kalshi markets found for "
            f"{missing}. Cannot start WS subscriptions with incomplete coverage."
        )
    logger.info(
        "WS coverage OK: all five crypto assets represented (%d total tickers)",
        len(tickers),
    )


def check_ws_ticker_asset_coverage(
    tickers: List[str],
    *,
    strict: bool = False,
) -> Tuple[bool, List[str]]:
    """Check that all five crypto assets are covered in *tickers*.

    Args:
        tickers: WS subscription ticker list.
        strict:  If ``True``, raise ``RuntimeError`` on missing assets
                 (identical to ``assert_each_asset_represented``).
                 If ``False``, log a warning and return ``(False, missing)``.

    Returns:
        ``(ok, missing_assets)`` — ``ok`` is ``True`` when all five are present.
    """
    coverage = summarize_crypto_ws_coverage(tickers)
    missing = coverage["missing_assets"]
    ok = len(missing) == 0

    if not ok:
        msg = (
            f"WS ticker coverage incomplete: {missing} have no subscribed markets. "
            f"Total tickers: {len(tickers)}."
        )
        if strict:
            raise RuntimeError(msg)
        logger.warning(msg)

    return ok, missing
