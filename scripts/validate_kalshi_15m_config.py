"""Validate canonical 15m crypto config against live Kalshi metadata.

This script:
1. Fetches actual 15m crypto markets from Kalshi
2. Compares against canonical config series tickers
3. Logs configuration parameters for each asset/tier
4. Ensures no markets are missing or mis-typed

Usage:
    python scripts/validate_kalshi_15m_config.py
"""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.kalshi_15m_crypto_config import (
    KALSHI_15M_CRYPTO_ASSETS,
    KALSHI_15M_SERIES_TICKERS,
    KALSHI_15M_TIMEFRAME,
    DEFAULT_ENTRY_POLICIES,
    EXIT_POLICY_TABLE,
    ASSET_CLASS_MAJOR,
    ASSET_CLASS_ALT,
    get_asset_class,
    get_entry_policy,
    get_exit_policy_params,
    get_base_edge_threshold,
    VolatilityTier,
    dump_config_summary,
)
from merid.event_venues.kalshi.client import KalshiVenueClient
from merid.event_venues.kalshi.market_catalog import KalshiMarketCatalog, get_market_catalog
from utils.logger import get_logger

logger = get_logger("scripts.validate_kalshi_15m_config")


async def fetch_live_15m_crypto_markets() -> dict:
    """Fetch live 15m crypto markets from Kalshi."""
    logger.info("Fetching live Kalshi markets...")
    
    catalog = get_market_catalog()
    await catalog.refresh()
    
    # Filter for 15m crypto markets
    crypto_15m_markets = catalog.get_markets_by_category("crypto", timeframe="15m")
    
    # Group by asset
    markets_by_asset = {}
    for market in crypto_15m_markets:
        asset = market.asset if hasattr(market, 'asset') else None
        if asset:
            if asset not in markets_by_asset:
                markets_by_asset[asset] = []
            markets_by_asset[asset].append(market)
    
    logger.info(f"Found {len(crypto_15m_markets)} total 15m crypto markets")
    for asset, markets in markets_by_asset.items():
        logger.info(f"  {asset}: {len(markets)} markets")
    
    return markets_by_asset


def log_config_parameters():
    """Log configuration parameters for each asset/tier."""
    logger.info("=" * 80)
    logger.info("CANONICAL 15M CRYPTO CONFIGURATION PARAMETERS")
    logger.info("=" * 80)
    
    for asset in KALSHI_15M_CRYPTO_ASSETS:
        asset_class = get_asset_class(asset)
        entry_policy = get_entry_policy(asset)
        
        logger.info(f"\n--- {asset} ({asset_class}) ---")
        logger.info(f"Series Ticker: {KALSHI_15M_SERIES_TICKERS[asset]}")
        logger.info(f"Entry Window: {entry_policy.base_window_start_minutes}m - {entry_policy.base_window_end_minutes}m before expiry")
        logger.info(f"Terminal Phase: enabled={entry_policy.terminal_config.enabled}, max={entry_policy.terminal_config.max_terminal_minutes}m")
        
        # Log exit policy parameters for each tier
        logger.info(f"\nExit Policies:")
        for tier in ["A", "B", "C"]:
            params = get_exit_policy_params(tier, asset)
            logger.info(f"  Tier {tier}:")
            logger.info(f"    TP R-multiple: {params['tp_r_multiple']}")
            logger.info(f"    SL edge multiplier: {params['sl_edge_multiplier']}")
            logger.info(f"    Trailing enabled: {params['trailing_enabled']}")
            if params['trailing_enabled']:
                logger.info(f"    Trailing activation: {params.get('trailing_activation_r_multiple')}")
                logger.info(f"    Trailing giveback: {params.get('trailing_giveback_pct')}%")
            logger.info(f"    Max hold: {params['max_hold_seconds']}s")
        
        # Log edge thresholds for each volatility tier
        logger.info(f"\nEdge Thresholds:")
        for vol_tier in [VolatilityTier.LOW, VolatilityTier.MEDIUM, VolatilityTier.HIGH]:
            threshold = get_base_edge_threshold(asset, vol_tier)
            logger.info(f"  {vol_tier.value}: {threshold:.2%}")


def extract_series_ticker_from_event(event_ticker: str) -> str:
    """Extract series ticker from event ticker (e.g., KXBTC15M-26MAR50K -> KXBTC15M)."""
    if not event_ticker:
        return None
    # Split on '-' and take the first part
    parts = event_ticker.split('-')
    return parts[0] if parts else None


def compare_series_tickers(live_markets_by_asset: dict):
    """Compare canonical config series tickers against live markets."""
    logger.info("=" * 80)
    logger.info("SERIES TICKER VALIDATION")
    logger.info("=" * 80)
    
    canonical_series = set(KALSHI_15M_SERIES_TICKERS.values())
    live_series = set()
    
    # Debug: Log first market structure to understand available fields
    for asset, markets in live_markets_by_asset.items():
        if markets:
            logger.info(f"\nDebug: First {asset} market structure:")
            market = markets[0]
            logger.info(f"  Type: {type(market)}")
            logger.info(f"  Dir: {[a for a in dir(market) if not a.startswith('_')]}")
            if hasattr(market, 'market'):
                logger.info(f"  market type: {type(market.market)}")
                logger.info(f"  market dir: {[a for a in dir(market.market) if not a.startswith('_')][:20]}")
            break
    
    for asset, markets in live_markets_by_asset.items():
        for market in markets:
            # Try series_ticker first, fall back to extracting from event_ticker
            ticker = None
            if hasattr(market, 'series_ticker') and market.series_ticker:
                ticker = market.series_ticker
            elif hasattr(market, 'event_ticker') and market.event_ticker:
                ticker = extract_series_ticker_from_event(market.event_ticker)
            elif hasattr(market, 'market') and hasattr(market.market, 'ticker'):
                ticker = extract_series_ticker_from_event(market.market.ticker)
            
            if ticker:
                live_series.add(ticker)
    
    # Check for missing series
    missing_in_live = canonical_series - live_series
    if missing_in_live:
        logger.warning(f"Series in canonical config but NOT found in live data: {missing_in_live}")
    else:
        logger.info("✓ All canonical series tickers found in live data")
    
    # Check for extra series
    extra_in_live = live_series - canonical_series
    if extra_in_live:
        logger.warning(f"Series in live data but NOT in canonical config: {extra_in_live}")
        logger.warning("  These may be new series that should be added to the config")
    else:
        logger.info("✓ No unexpected series in live data")
    
    # Check per-asset
    logger.info("\nPer-asset validation:")
    for asset in KALSHI_15M_CRYPTO_ASSETS:
        canonical_ticker = KALSHI_15M_SERIES_TICKERS[asset]
        live_markets = live_markets_by_asset.get(asset, [])
        live_series_for_asset = set()
        for market in live_markets:
            ticker = None
            if hasattr(market, 'series_ticker') and market.series_ticker:
                ticker = market.series_ticker
            elif hasattr(market, 'event_ticker') and market.event_ticker:
                ticker = extract_series_ticker_from_event(market.event_ticker)
            elif hasattr(market, 'market') and hasattr(market.market, 'ticker'):
                ticker = extract_series_ticker_from_event(market.market.ticker)
            
            if ticker:
                live_series_for_asset.add(ticker)
        
        if canonical_ticker in live_series_for_asset:
            logger.info(f"  ✓ {asset}: {canonical_ticker} found in live data ({len(live_markets)} markets)")
        else:
            logger.error(f"  ✗ {asset}: {canonical_ticker} NOT found in live data (found: {live_series_for_asset})")


def validate_config_structure():
    """Validate the canonical config structure."""
    logger.info("=" * 80)
    logger.info("CONFIG STRUCTURE VALIDATION")
    logger.info("=" * 80)
    
    # Validate assets
    expected_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    if set(KALSHI_15M_CRYPTO_ASSETS) == expected_assets:
        logger.info("✓ All 5 expected assets present")
    else:
        logger.error(f"✗ Asset mismatch. Expected: {expected_assets}, Got: {set(KALSHI_15M_CRYPTO_ASSETS)}")
    
    # Validate timeframe
    if KALSHI_15M_TIMEFRAME == "15m":
        logger.info("✓ Timeframe is 15m")
    else:
        logger.error(f"✗ Timeframe is {KALSHI_15M_TIMEFRAME}, expected 15m")
    
    # Validate series tickers
    if all(ticker.startswith("KX") and "15M" in ticker for ticker in KALSHI_15M_SERIES_TICKERS.values()):
        logger.info("✓ All series tickers follow KX{COIN}15M pattern")
    else:
        logger.error("✗ Some series tickers do not follow KX{COIN}15M pattern")
    
    # Validate entry policies
    for asset in KALSHI_15M_CRYPTO_ASSETS:
        policy = get_entry_policy(asset)
        if policy.asset == asset and policy.base_window_start_minutes > policy.base_window_end_minutes:
            logger.info(f"✓ {asset} entry policy valid")
        else:
            logger.error(f"✗ {asset} entry policy invalid")
    
    # Validate exit policy table
    expected_combinations = {(tier, asset_class) for tier in ["A", "B", "C"] for asset_class in ["major", "alt"]}
    actual_combinations = set(EXIT_POLICY_TABLE.keys())
    if expected_combinations == actual_combinations:
        logger.info("✓ All (tier, asset_class) combinations present in exit policy table")
    else:
        missing = expected_combinations - actual_combinations
        extra = actual_combinations - expected_combinations
        if missing:
            logger.error(f"✗ Missing exit policy combinations: {missing}")
        if extra:
            logger.warning(f"  Extra exit policy combinations: {extra}")


async def main():
    """Main validation routine."""
    logger.info("Starting Kalshi 15m crypto config validation")
    logger.info("=" * 80)
    
    # 1. Validate config structure
    validate_config_structure()
    
    # 2. Log configuration parameters
    log_config_parameters()
    
    # 3. Fetch live markets and compare
    try:
        live_markets_by_asset = await fetch_live_15m_crypto_markets()
        compare_series_tickers(live_markets_by_asset)
    except Exception as e:
        logger.error(f"Failed to fetch live markets: {e}")
        logger.warning("Skipping live data comparison")
    
    # 4. Dump config summary
    logger.info("=" * 80)
    logger.info("CONFIG SUMMARY")
    logger.info("=" * 80)
    summary = dump_config_summary()
    logger.info(f"Universe: {summary['universe']}")
    logger.info(f"Entry Policies: {len(summary['entry_policies'])}")
    logger.info(f"Exit Policies: {len(summary['exit_policies'])}")
    logger.info(f"Validation: {summary['validation']}")
    
    logger.info("=" * 80)
    logger.info("Validation complete")
    logger.info("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
