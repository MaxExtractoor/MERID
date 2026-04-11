"""
Kalshi Ticker Catalog — validation and quarantine.

Pre-flight contract validation
================================
Before placing any order the execution pipeline calls
``TickerCatalog.validate_ticker()``.  A ticker is **valid** if:

  1. It appears in the latest catalog snapshot (fetched from the Kalshi REST
     API every ``refresh_interval_seconds`` seconds), AND
  2. Its market status is ``"active"`` (not ``"settled"`` or ``"closed"``), AND
  3. It has not been quarantined due to a previous 400 or 404 response.

Quarantine
==========
When the REST client raises ``KalshiInvalidParametersError`` (HTTP 400) or
``KalshiTickerNotFoundError`` (HTTP 404), the execution pipeline calls
``TickerCatalog.quarantine(ticker, reason)`` once.  Quarantined tickers are:

  * blocked from further order submission (``validate_ticker`` returns False)
  * logged with severity ERROR exactly once per ticker (not on every cycle)
  * tracked in ``quarantined_tickers`` for monitoring/alerting

This prevents repeated 400/404 floods while a mapping bug is being fixed.

Error Taxonomy (halt counter impact)
=====================================
* 400 invalid_parameters  → CRITICAL (increments halt counter once)
* 404 not found            → CRITICAL (increments halt counter once)
* Quarantine block         → does NOT re-increment the halt counter
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, Set

logger = logging.getLogger(__name__)

# How long (seconds) to cache the catalog before re-fetching
_DEFAULT_REFRESH_INTERVAL = 300  # 5 minutes


@dataclass
class _MarketEntry:
    """Minimal market metadata cached from the Kalshi catalog."""
    ticker: str
    status: str          # "active", "settled", "closed", …
    title: str = ""
    category: str = ""
    last_refreshed: float = field(default_factory=time.time)


@dataclass
class _QuarantineEntry:
    """Record of why a ticker was quarantined."""
    ticker: str
    reason: str          # "400_invalid_parameters" | "404_not_found" | custom
    error_body: str = ""
    quarantined_at: float = field(default_factory=time.time)


class TickerCatalog:
    """Thread-safe Kalshi ticker catalog with pre-flight validation and quarantine.

    Usage::

        catalog = TickerCatalog()
        catalog.refresh(rest_client)          # populate from Kalshi REST

        ok, reason = catalog.validate_ticker("KXBTC-26APR1117-T81249.99")
        if not ok:
            logger.warning("Skipping order: %s", reason)
        else:
            # place order …

        # On 400/404 from the exchange:
        catalog.quarantine("KXBTC-26APR1117-T81249.99", "400_invalid_parameters",
                           error_body=response_body)
    """

    def __init__(self, refresh_interval_seconds: float = _DEFAULT_REFRESH_INTERVAL) -> None:
        self._refresh_interval = refresh_interval_seconds
        self._lock = threading.Lock()
        self._markets: Dict[str, _MarketEntry] = {}
        self._quarantine: Dict[str, _QuarantineEntry] = {}
        self._last_refresh: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_ticker(self, ticker: str) -> tuple[bool, str]:
        """Return (valid, reason) for a ticker before placing an order.

        Valid means: in catalog, status==active, not quarantined.
        """
        with self._lock:
            # 1. Quarantine check — highest priority
            if ticker in self._quarantine:
                q = self._quarantine[ticker]
                return False, f"ticker_quarantined:{q.reason}"

            # 2. Catalog presence check
            if not self._markets:
                # Catalog has never been populated — allow with a warning
                # so trading is not blocked purely by missing catalog fetch.
                logger.warning(
                    "TickerCatalog has no snapshot yet; allowing %s without validation", ticker
                )
                return True, "catalog_empty_allow"

            entry = self._markets.get(ticker)
            if entry is None:
                return False, "ticker_not_in_catalog"

            # 3. Market status check
            if entry.status not in ("active", "open"):
                return False, f"market_status:{entry.status}"

        return True, "ok"

    def quarantine(
        self,
        ticker: str,
        reason: str,
        error_body: str = "",
    ) -> None:
        """Mark *ticker* as quarantined.  Idempotent — logs only on first call."""
        with self._lock:
            if ticker in self._quarantine:
                return  # already quarantined, suppress duplicate log
            entry = _QuarantineEntry(ticker=ticker, reason=reason, error_body=error_body)
            self._quarantine[ticker] = entry

        logger.error(
            "TICKER QUARANTINED — ticker=%s reason=%s  "
            "No further orders will be placed for this ticker until catalog re-sync. "
            "body_excerpt=%.200s",
            ticker, reason, error_body,
        )

    def unquarantine(self, ticker: str) -> None:
        """Remove a ticker from quarantine (e.g., after a catalog re-sync confirms it)."""
        with self._lock:
            removed = self._quarantine.pop(ticker, None)
        if removed:
            logger.info("Ticker %s removed from quarantine", ticker)

    def clear_quarantine(self) -> None:
        """Remove all quarantine entries (used after a full catalog re-sync)."""
        with self._lock:
            count = len(self._quarantine)
            self._quarantine.clear()
        if count:
            logger.info("Cleared %d quarantine entries after catalog re-sync", count)

    @property
    def quarantined_tickers(self) -> Set[str]:
        """Return the set of currently quarantined tickers (snapshot)."""
        with self._lock:
            return set(self._quarantine)

    @property
    def known_tickers(self) -> Set[str]:
        """Return the set of tickers in the current catalog snapshot."""
        with self._lock:
            return set(self._markets)

    def is_stale(self) -> bool:
        """Return True if the catalog needs a refresh."""
        return (time.time() - self._last_refresh) > self._refresh_interval

    def refresh(self, rest_client: Optional[object] = None) -> int:
        """Populate the catalog from the Kalshi REST API.

        Fetches all active markets (paginated) and updates the internal
        snapshot.  Returns the number of markets loaded.

        If *rest_client* is None or the fetch fails, the existing snapshot
        is preserved and a warning is logged.
        """
        if rest_client is None:
            logger.debug("TickerCatalog.refresh: no client provided, skipping")
            return len(self._markets)

        try:
            markets = self._fetch_all_markets(rest_client)
        except Exception as exc:
            logger.warning(
                "TickerCatalog refresh failed — keeping existing snapshot (%d tickers): %s",
                len(self._markets), exc,
            )
            return len(self._markets)

        new_map: Dict[str, _MarketEntry] = {}
        for m in markets:
            ticker = m.get("ticker", "")
            if not ticker:
                continue
            new_map[ticker] = _MarketEntry(
                ticker=ticker,
                status=m.get("status", ""),
                title=m.get("title", ""),
                category=m.get("category", ""),
            )

        with self._lock:
            self._markets = new_map
            self._last_refresh = time.time()
            # Remove quarantine for tickers that now appear as active
            to_unquarantine = [
                t for t in list(self._quarantine)
                if t in new_map and new_map[t].status in ("active", "open")
            ]
            for t in to_unquarantine:
                del self._quarantine[t]

        if to_unquarantine:
            logger.info(
                "Catalog re-sync cleared quarantine for %d tickers: %s",
                len(to_unquarantine), to_unquarantine,
            )

        logger.info(
            "TickerCatalog refreshed: %d markets loaded, %d quarantined",
            len(new_map), len(self._quarantine),
        )
        return len(new_map)

    def summary(self) -> Dict[str, object]:
        """Return a dict suitable for health/monitoring endpoints."""
        with self._lock:
            return {
                "total_markets": len(self._markets),
                "quarantined_count": len(self._quarantine),
                "quarantined_tickers": list(self._quarantine),
                "last_refresh_age_seconds": round(time.time() - self._last_refresh, 1),
                "is_stale": self.is_stale(),
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_all_markets(rest_client: object) -> list:
        """Fetch all markets from Kalshi via paginated REST calls."""
        markets: list = []
        cursor: Optional[str] = None

        while True:
            params: Dict[str, object] = {"limit": 200}
            if cursor:
                params["cursor"] = cursor

            result = rest_client._request("GET", "/markets", params=params)  # type: ignore[attr-defined]
            page = result.get("markets", [])
            markets.extend(page)

            cursor = result.get("cursor")
            if not cursor or not page:
                break

        return markets


# Module-level singleton — shared by execution pipeline and any other consumer.
_catalog: Optional[TickerCatalog] = None
_catalog_lock = threading.Lock()


def get_ticker_catalog() -> TickerCatalog:
    """Return the module-level TickerCatalog singleton."""
    global _catalog
    with _catalog_lock:
        if _catalog is None:
            _catalog = TickerCatalog()
    return _catalog
