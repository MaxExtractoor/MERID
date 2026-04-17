"""
Kalshi Universe Loader

Fetches active Kalshi markets from the catalog API and applies filters.
"""
from typing import List, Dict, Any
from datetime import datetime
import math
from config.kalshi_universe import (
    KALSHI_PINNED_MARKETS,
    KALSHI_ALLOWED_CATEGORIES,
    KALSHI_PER_CATEGORY_CAP,
    KALSHI_UNIVERSE_LIMIT,
    KALSHI_MIN_VOLUME_24H,
    KALSHI_MAX_DAYS_TO_EXPIRY,
    KALSHI_EXCLUDED_MARKETS,
    KALSHI_ACTIVE_MARKETS_FALLBACK,
    KALSHI_INCLUDED_SERIES_PREFIXES,
    KALSHI_CRYPTO_PRODUCTS,
    KALSHI_CRYPTO_ASSETS,  # Canonical 5 assets from single source of truth
)

# Build CRYPTO_SERIES_PREFIXES dynamically from canonical assets (KXBTC, KXETH, etc.)
CRYPTO_SERIES_PREFIXES = [f"KX{asset}" for asset in KALSHI_CRYPTO_ASSETS] + ["KXXRP", "KXDOGE"]


def _in_series(ticker: str, series_list: list) -> bool:
    """True when ticker starts with any prefix in series_list."""
    return any(ticker.startswith(p) for p in series_list)


def days_to_expiry(market: Dict[str, Any]) -> int:
    """Calculate days until market expiry."""
    try:
        close_time = market.get('close_time') or market.get('expiration_date')
        if close_time:
            expiry = datetime.fromisoformat(close_time.replace('Z', '+00:00'))
            return max(0, (expiry - datetime.now(expiry.tzinfo)).days)
    except (ValueError, TypeError):
        pass
    return 0


def sort_by_volume_desc(tickers: List[str], market_data: Dict[str, Dict[str, Any]]) -> List[str]:
    """Sort tickers by 24h volume descending."""
    def get_volume(ticker: str) -> int:
        market = market_data.get(ticker, {})
        return market.get('volume_24h', 0)

    return sorted(tickers, key=get_volume, reverse=True)


def fetch_kalshi_active_markets(client) -> Dict[str, List[str]]:
    """
    Return both:
      - "all": full active markets list (as before)
      - crypto products (btc_15m / eth_15m / sol_15m subsets)
    """
    try:
        active_markets: List[str] = []
        btc_15m: List[str] = []
        eth_15m: List[str] = []
        sol_15m: List[str] = []
        xrp_15m: List[str] = []
        doge_15m: List[str] = []

        cursor = None
        while True:
            resp = client.get_events(
                status="open",
                with_nested_markets=True,
                limit=200,
                cursor=cursor,
            )

            # Support both SDK objects and plain dicts
            events = getattr(resp, "events", None) or resp.get("events", [])
            cursor = getattr(resp, "cursor", None) or resp.get("cursor")

            for ev in events:
                cat = getattr(ev, "category", None) or ev.get("category") or "other"
                if cat not in KALSHI_ALLOWED_CATEGORIES:
                    continue

                series = getattr(ev, "series_ticker", None) or ev.get("series_ticker") or ""
                markets = getattr(ev, "markets", None) or ev.get("markets", [])

                for m in markets:
                    ticker = getattr(m, "ticker", None) or m.get("ticker")
                    if not ticker or ticker in KALSHI_EXCLUDED_MARKETS:
                        continue

                    if KALSHI_INCLUDED_SERIES_PREFIXES and not any(
                        series.startswith(pfx) or ticker.startswith(pfx)
                        for pfx in KALSHI_INCLUDED_SERIES_PREFIXES
                    ):
                        continue

                    status = getattr(m, "status", None) or m.get("status")
                    if status != "open":
                        continue

                    active_markets.append(ticker)

            if not cursor:
                break

        all_markets = sorted(set(active_markets)) or KALSHI_ACTIVE_MARKETS_FALLBACK

        btc_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_15M", []))]
        btc_1h   = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_1H", []))]
        eth_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("ETH_15M", []))]
        sol_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("SOL_15M", []))]
        xrp_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("XRP_15M", []))]
        doge_15m = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("DOGE_15M", []))]

        return {
            "all": all_markets,
            "BTC_15M": btc_15m,
            "BTC_1H": btc_1h,
            "ETH_15M": eth_15m,
            "SOL_15M": sol_15m,
            "XRP_15M": xrp_15m,
            "DOGE_15M": doge_15m,
        }

    except Exception as e:
        import logging
        logging.getLogger("config.kalshi_universe_loader").info(
            "Kalshi catalog fetch unavailable (%s), using hardcoded fallback", e)
        return {
            "all": KALSHI_ACTIVE_MARKETS_FALLBACK,
            "BTC_15M": [],
            "BTC_1H": [],
            "ETH_15M": [],
            "SOL_15M": [],
            "XRP_15M": [],
            "DOGE_15M": [],
        }


# Legacy function for backward compatibility
def fetch_kalshi_active_markets_legacy(client) -> List[str]:
    """Legacy wrapper for backward compatibility."""
    result = fetch_kalshi_active_markets(client)
    return result["all"]


def select_kalshi_universe(client) -> Dict[str, List[str]]:
    """Select active Kalshi markets using pinned + auto-selection algorithm.

    Args:
        client: Kalshi API client (must have get_events method)

    Returns:
        Dict with keys "all" and crypto subsets
    """
    try:
        # 1. Start with pinned markets
        selected = set(KALSHI_PINNED_MARKETS)

        # 2. Fetch all open events with nested markets (handle pagination)
        all_events = []
        cursor = None

        while True:
            resp = client.get_events(
                status="open",
                with_nested_markets=True,
                limit=200,
                cursor=cursor,
            )

            # Support both SDK objects and plain dicts
            events = getattr(resp, "events", None) or resp.get("events", [])
            cursor = getattr(resp, "cursor", None) or resp.get("cursor")

            all_events.extend(events)

            if not cursor:
                break

        # 3. Process events into buckets
        buckets: Dict[str, List[str]] = {cat: [] for cat in KALSHI_ALLOWED_CATEGORIES}
        market_data: Dict[str, Dict[str, Any]] = {}  # ticker -> market data

        for ev in all_events:
            cat = getattr(ev, "category", None) or ev.get("category") or "other"
            if cat not in KALSHI_ALLOWED_CATEGORIES:
                continue

            markets = getattr(ev, "markets", None) or ev.get("markets", [])

            for m in markets:
                ticker = getattr(m, "ticker", None) or m.get("ticker")
                if not ticker or ticker in KALSHI_EXCLUDED_MARKETS or ticker in selected:
                    continue

                status = getattr(m, "status", None) or m.get("status")
                if status != "open":
                    continue

                # Check volume threshold
                volume_24h = getattr(m, "volume_24h", None) or m.get("volume_24h", 0)
                if volume_24h < KALSHI_MIN_VOLUME_24H:
                    continue

                # Check expiry threshold
                if days_to_expiry(m) > KALSHI_MAX_DAYS_TO_EXPIRY:
                    continue

                # Add to bucket
                buckets.setdefault(cat, []).append(ticker)
                market_data[ticker] = m

        # 4. Apply per-category caps (sort by volume desc)
        for cat, tickers in buckets.items():
            cap = KALSHI_PER_CATEGORY_CAP.get(cat, 0)
            if cap > 0:
                sorted_tickers = sort_by_volume_desc(tickers, market_data)
                for ticker in sorted_tickers[:cap]:
                    if len(selected) >= KALSHI_UNIVERSE_LIMIT:
                        break
                    selected.add(ticker)

        all_markets = sorted(selected)
        import logging as _logging
        _log = _logging.getLogger("config.kalshi_universe_loader")
        _log.info(
            "Kalshi universe selection: %d markets (%d pinned + %d auto)",
            len(all_markets), len(KALSHI_PINNED_MARKETS),
            len(all_markets) - len(KALSHI_PINNED_MARKETS),
        )

        btc_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_15M", []))]
        btc_1h   = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_1H", []))]
        eth_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("ETH_15M", []))]
        sol_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("SOL_15M", []))]
        xrp_15m  = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("XRP_15M", []))]
        doge_15m = [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("DOGE_15M", []))]

        return {
            "all": all_markets,
            "BTC_15M": btc_15m,
            "BTC_1H": btc_1h,
            "ETH_15M": eth_15m,
            "SOL_15M": sol_15m,
            "XRP_15M": xrp_15m,
            "DOGE_15M": doge_15m,
        }

    except Exception as e:
        import logging as _logging
        _logging.getLogger("config.kalshi_universe_loader").info(
            "Kalshi universe selection failed, using fallback: %s", e)
        return fetch_kalshi_active_markets(client)


def get_crypto_subsets(client) -> Dict[str, List[str]]:
    """Get per-asset crypto market subsets from the universe.

    Returns dict with keys like 'BTC_15M', 'ETH_15M', etc.
    Uses KALSHI_CRYPTO_PRODUCTS as the single source of truth for series prefixes
    so that any prefix change is automatically reflected here.
    """
    full_universe = select_kalshi_universe(client)
    all_markets = full_universe["all"]

    subsets = {
        "BTC_15M":  [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_15M", []))],
        "BTC_1H":   [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("BTC_1H", []))],
        "ETH_15M":  [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("ETH_15M", []))],
        "SOL_15M":  [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("SOL_15M", []))],
        "XRP_15M":  [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("XRP_15M", []))],
        "DOGE_15M": [m for m in all_markets if _in_series(m, KALSHI_CRYPTO_PRODUCTS.get("DOGE_15M", []))],
        # Daily/range products are not yet in KALSHI_CRYPTO_PRODUCTS; filter by known structural patterns.
        "BTC_DAILY": [m for m in all_markets if m.startswith("KXBT") and ("PRICE" in m or "RANGE" in m)],
        "ETH_DAILY": [m for m in all_markets if m.startswith("KXETH") and ("PRICE" in m or "RANGE" in m)],
        "SOL_DAILY": [m for m in all_markets if m.startswith("KXSOL") and ("PRICE" in m or "RANGE" in m)],
    }

    return subsets


# CRYPTO_SERIES_PREFIXES defined at module top from canonical KALSHI_CRYPTO_ASSETS


def fetch_kalshi_crypto_markets(client) -> List[str]:
    """Fetch active Kalshi crypto markets with focused selection logic.

    Filters for crypto category, BTC/ETH series, with liquidity/expiry guards.

    Args:
        client: Kalshi API client

    Returns:
        List of crypto market tickers
    """
    try:
        tickers: List[str] = []
        cursor = None

        while True:
            resp = client.get_events(
                status="open",
                with_nested_markets=True,
                limit=200,
                cursor=cursor,
            )

            # Support both SDK objects and plain dicts
            events = getattr(resp, "events", None) or resp.get("events", [])
            cursor = getattr(resp, "cursor", None) or resp.get("cursor")

            for ev in events:
                cat = getattr(ev, "category", None) or ev.get("category") or "other"
                if cat != "crypto":
                    continue

                series = getattr(ev, "series_ticker", None) or ev.get("series_ticker") or ""
                markets = getattr(ev, "markets", None) or ev.get("markets", [])

                for m in markets:
                    ticker = getattr(m, "ticker", None) or m.get("ticker")
                    if not ticker:
                        continue

                    status = getattr(m, "status", None) or m.get("status")
                    if status != "open":
                        continue

                    if not any(ticker.startswith(p) or series.startswith(p) for p in CRYPTO_SERIES_PREFIXES):
                        continue

                    # Basic liquidity/expiry filters (tunable)
                    volume_24h = getattr(m, "volume_24h", None) or m.get("volume_24h", 0)
                    if volume_24h < 500:
                        continue

                    if days_to_expiry(m) > 30:
                        continue

                    tickers.append(ticker)

            if not cursor:
                break

        return sorted(set(tickers))

    except Exception as e:
        import logging as _logging
        _logging.getLogger("config.kalshi_universe_loader").info(
            "Kalshi crypto fetch failed: %s", e)
        return []
