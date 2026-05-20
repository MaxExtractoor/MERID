"""Kalshi 15-minute crypto market test fixtures.

This module provides synthetic 15m market fixtures for BTC/ETH/SOL/XRP/DOGE
that match Kalshi's actual market structure. These fixtures are used for:
- Catalog discovery tests
- Agent window selection tests
- Risk + execution smoke tests

Each market includes:
- series_ticker: The 15M series ticker (KXBTC15M, etc.)
- ticker: Full market ticker
- close_time: Expiration time in ~15m cadence
- strike_price: Strike price in USD (for level-based markets)
- category: Market category (crypto)
- subtitle: Market subtitle (e.g., "BTC > 95000")
- market_state: Market state (open/closed)
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class KalshiMarketFixture:
    """Synthetic Kalshi market fixture for testing."""
    
    ticker: str
    series_ticker: str
    title: str
    subtitle: str
    category: str
    close_time: datetime
    strike_price: float
    market_state: str = "open"
    tick_size: int = 1  # cents
    minimum_tick_size: int = 1  # cents


def make_15m_market(
    asset: str,
    strike: float,
    base_time: datetime,
    offset_minutes: int = 0,
) -> KalshiMarketFixture:
    """Create a synthetic 15m market fixture.
    
    Args:
        asset: Asset code (BTC, ETH, SOL, XRP, DOGE)
        strike: Strike price in USD
        base_time: Base time for market expiration
        offset_minutes: Offset from base time in minutes (creates cadence)
    
    Returns:
        KalshiMarketFixture: Synthetic market
    """
    series_ticker = f"KX{asset}15M"
    close_time = base_time + timedelta(minutes=15 + offset_minutes)
    
    return KalshiMarketFixture(
        ticker=f"{series_ticker}-{close_time.strftime('%y%m%d%H%M')}",
        series_ticker=series_ticker,
        title=f"{asset} 15-Minute",
        subtitle=f"{asset} > {strike}",
        category="crypto",
        close_time=close_time,
        strike_price=strike,
        market_state="open",
    )


def get_15m_market_fixtures(base_time: datetime = None) -> List[KalshiMarketFixture]:
    """Get all 5 synthetic 15m market fixtures.
    
    Creates one market per asset with realistic strike prices and
    ~15-minute expiration cadence starting from base_time.
    
    Args:
        base_time: Base time for market creation (defaults to now UTC)
    
    Returns:
        List of 5 KalshiMarketFixture objects (BTC, ETH, SOL, XRP, DOGE)
    
    Example:
        >>> fixtures = get_15m_market_fixtures()
        >>> len(fixtures)
        5
        >>> fixtures[0].series_ticker
        'KXBTC15M'
    """
    if base_time is None:
        base_time = datetime.now(timezone.utc)
    
    # Realistic strike prices for each asset (as of 2026)
    strikes = {
        "BTC": 95000.0,
        "ETH": 3500.0,
        "SOL": 150.0,
        "XRP": 2.5,
        "DOGE": 0.15,
    }
    
    fixtures = []
    for i, (asset, strike) in enumerate(strikes.items()):
        # Offset each market by 1 minute to create a staggered cadence
        fixture = make_15m_market(asset, strike, base_time, offset_minutes=i)
        fixtures.append(fixture)
    
    return fixtures


def get_15m_market_dict(base_time: datetime = None) -> Dict[str, KalshiMarketFixture]:
    """Get 15m market fixtures as a dict keyed by ticker.
    
    Args:
        base_time: Base time for market creation (defaults to now UTC)
    
    Returns:
        Dict mapping ticker -> KalshiMarketFixture
    """
    fixtures = get_15m_market_fixtures(base_time)
    return {f.ticker: f for f in fixtures}


def get_series_to_markets_map(base_time: datetime = None) -> Dict[str, List[KalshiMarketFixture]]:
    """Get mapping of series ticker to list of markets.
    
    Args:
        base_time: Base time for market creation (defaults to now UTC)
    
    Returns:
        Dict mapping series_ticker -> List[KalshiMarketFixture]
    
    Example:
        >>> mapping = get_series_to_markets_map()
        >>> mapping["KXBTC15M"][0].series_ticker
        'KXBTC15M'
    """
    fixtures = get_15m_market_fixtures(base_time)
    mapping: Dict[str, List[KalshiMarketFixture]] = {}
    
    for fixture in fixtures:
        if fixture.series_ticker not in mapping:
            mapping[fixture.series_ticker] = []
        mapping[fixture.series_ticker].append(fixture)
    
    return mapping


# Expected series tickers for 15m crypto
EXPECTED_15M_SERIES = [
    "KXBTC15M",
    "KXETH15M",
    "KXSOL15M",
    "KXXRP15M",
    "KXDOGE15M",
]


# Expected agent names for 15m crypto
EXPECTED_15M_AGENTS = [
    "BTC_15M",
    "ETH_15M",
    "SOL_15M",
    "XRP_15M",
    "DOGE_15M",
]


# Series to agent mapping
SERIES_TO_AGENT = {
    "KXBTC15M": "BTC_15M",
    "KXETH15M": "ETH_15M",
    "KXSOL15M": "SOL_15M",
    "KXXRP15M": "XRP_15M",
    "KXDOGE15M": "DOGE_15M",
}


# Agent to series mapping
AGENT_TO_SERIES = {
    "BTC_15M": ["KXBTC15M"],
    "ETH_15M": ["KXETH15M"],
    "SOL_15M": ["KXSOL15M"],
    "XRP_15M": ["KXXRP15M"],
    "DOGE_15M": ["KXDOGE15M"],
}
