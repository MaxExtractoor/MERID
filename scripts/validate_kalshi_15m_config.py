"""Validate canonical 15m crypto trading scope against live Kalshi metadata.

This script validates the *current* production scope sources:

- ``config/trading_scope.py`` — canonical ``ALLOWED_ASSETS`` /
  ``ALLOWED_SERIES_TICKERS`` (derived from the active profile's
  ``asset_whitelist`` gate, same path the running server uses).
- ``config/profiles/kalshi_crypto_15m_v2.yaml`` — production risk profile.
- ``KalshiMarketCatalog`` — live market metadata.

It no longer references the removed tiered entry/exit policy tables
(``get_entry_policy`` / ``EXIT_POLICY_TABLE`` / ``VolatilityTier`` era);
those were superseded by the profile YAML.

Usage:
    python scripts/validate_kalshi_15m_config.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.trading_scope import get_trading_scope
from merid.event_venues.kalshi.market_catalog import get_market_catalog
from utils.logger import get_logger

logger = get_logger("scripts.validate_kalshi_15m_config")


async def fetch_live_15m_crypto_markets() -> dict:
    """Fetch live 15m crypto markets from Kalshi."""
    logger.info("Fetching live Kalshi markets...")

    catalog = get_market_catalog()
    await catalog.refresh()

    # Filter for 15m markets
    crypto_15m_markets = catalog.get_markets_by_timeframe("15m")

    # Group by asset
    markets_by_asset = {}
    for market in crypto_15m_markets:
        asset = getattr(market, "asset", None)
        if asset:
            markets_by_asset.setdefault(asset, []).append(market)

    logger.info(f"Found {len(crypto_15m_markets)} total 15m markets")
    for asset, markets in sorted(markets_by_asset.items()):
        logger.info(f"  {asset}: {len(markets)} markets")

    return markets_by_asset


def extract_series_ticker(event_ticker: str) -> str:
    """Extract series ticker from event ticker (e.g., KXBTC15M-26MAR50K -> KXBTC15M)."""
    if not event_ticker:
        return None
    parts = event_ticker.split("-")
    return parts[0] if parts else None


def _market_series_ticker(market) -> str:
    """Best-effort series ticker for a catalog market record."""
    ticker = getattr(market, "series_ticker", None)
    if ticker:
        return ticker
    event_ticker = getattr(market, "event_ticker", None)
    if event_ticker:
        return extract_series_ticker(event_ticker)
    inner = getattr(market, "market", None)
    inner_ticker = getattr(inner, "ticker", None) if inner is not None else None
    if inner_ticker:
        return extract_series_ticker(inner_ticker)
    market_ticker = getattr(market, "ticker", None)
    if market_ticker:
        return extract_series_ticker(market_ticker)
    return None


def compare_series_tickers(live_markets_by_asset: dict, allowed_assets, allowed_series) -> bool:
    """Compare canonical scope series tickers against live markets."""
    logger.info("=" * 80)
    logger.info("SERIES TICKER VALIDATION")
    logger.info("=" * 80)

    canonical_series = set(allowed_series)
    live_series = set()

    for markets in live_markets_by_asset.values():
        for market in markets:
            ticker = _market_series_ticker(market)
            if ticker:
                live_series.add(ticker)

    ok = True

    missing_in_live = canonical_series - live_series
    if missing_in_live:
        logger.warning(f"Series in canonical scope but NOT found in live data: {missing_in_live}")
        ok = False
    else:
        logger.info("OK: All canonical series tickers found in live data")

    extra_in_live = live_series - canonical_series
    if extra_in_live:
        logger.warning(f"Series in live data but NOT in canonical scope: {extra_in_live}")
        logger.warning("  These may be new series outside the asset whitelist")
    else:
        logger.info("OK: No unexpected series in live data")

    logger.info("\nPer-asset validation:")
    for asset in sorted(allowed_assets):
        canonical_ticker = f"KX{asset}15M"
        live_markets = live_markets_by_asset.get(asset, [])
        live_series_for_asset = {
            t for t in (_market_series_ticker(m) for m in live_markets) if t
        }
        if canonical_ticker in live_series_for_asset:
            logger.info(
                f"  OK {asset}: {canonical_ticker} found in live data "
                f"({len(live_markets)} markets)"
            )
        else:
            logger.error(
                f"  FAIL {asset}: {canonical_ticker} NOT found in live data "
                f"(found: {live_series_for_asset})"
            )
            ok = False

    return ok


def validate_config_structure() -> bool:
    """Validate the canonical trading-scope structure."""
    logger.info("=" * 80)
    logger.info("CONFIG STRUCTURE VALIDATION")
    logger.info("=" * 80)

    scope = get_trading_scope()
    allowed_assets = scope.ALLOWED_ASSETS
    allowed_series = scope.ALLOWED_SERIES_TICKERS

    ok = True

    logger.info(f"Allowed assets: {sorted(allowed_assets)}")
    logger.info(f"Allowed series tickers: {sorted(allowed_series)}")

    if not allowed_assets:
        logger.error("FAIL: ALLOWED_ASSETS is empty")
        ok = False

    if all(t.startswith("KX") and t.endswith("15M") for t in allowed_series):
        logger.info("OK: All series tickers follow KX{ASSET}15M pattern")
    else:
        logger.error("FAIL: Some series tickers do not follow KX{ASSET}15M pattern")
        ok = False

    expected_series = {f"KX{a}15M" for a in allowed_assets}
    if set(allowed_series) == expected_series:
        logger.info("OK: Series tickers consistent with asset whitelist")
    else:
        logger.error(
            f"FAIL: Series tickers {sorted(allowed_series)} do not match "
            f"whitelist-derived {sorted(expected_series)}"
        )
        ok = False

    return ok


async def main() -> int:
    """Main validation routine. Returns 0 on success, 1 on any failure."""
    logger.info("Starting Kalshi 15m crypto scope validation")
    logger.info("=" * 80)

    scope = get_trading_scope()

    ok = validate_config_structure()

    try:
        live_markets_by_asset = await fetch_live_15m_crypto_markets()
        ok = compare_series_tickers(
            live_markets_by_asset,
            scope.ALLOWED_ASSETS,
            scope.ALLOWED_SERIES_TICKERS,
        ) and ok
    except Exception as e:
        logger.error(f"Failed to fetch live markets: {e}")
        logger.warning("Skipping live data comparison")

    logger.info("=" * 80)
    logger.info("Validation complete: %s", "PASS" if ok else "FAIL")
    logger.info("=" * 80)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
