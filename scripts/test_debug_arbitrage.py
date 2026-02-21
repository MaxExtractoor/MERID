#!/usr/bin/env python3
"""Debug script to test arbitrage functionality."""

import time
import logging
from unittest.mock import patch, Mock
from monitoring.prediction_markets import (
    PredictionMarket, 
    PredictionPlatform, 
    MarketCategory, 
    ResolutionStatus
)
from monitoring.prediction_analytics import get_arbitrage_opportunities

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Create test data
markets = [
    PredictionMarket(
        market_id="poly_btc_100k",
        platform=PredictionPlatform.POLYMARKET,
        question="Will Bitcoin reach $100k by end of 2024?",
        category=MarketCategory.CRYPTO,
        yes_price=0.65,
        no_price=0.35,
        volume_24h=1000000.0,
        total_volume=5000000.0,
        liquidity=250000.0,
        resolution_date=time.time() + 86400 * 30,
        status=ResolutionStatus.OPEN,
    ),
    PredictionMarket(
        market_id="kalshi_btc_100k",
        platform=PredictionPlatform.KALSHI,
        question="Will Bitcoin reach $100,000 by end of 2024?",
        category=MarketCategory.CRYPTO,
        yes_price=0.52,
        no_price=0.48,
        volume_24h=800000.0,
        total_volume=4000000.0,
        liquidity=200000.0,
        resolution_date=time.time() + 86400 * 30,
        status=ResolutionStatus.OPEN,
    ),
]

# Create mock aggregator
aggregator = Mock()
aggregator.get_all_markets.return_value = markets
aggregator.get_status.return_value = {
    "running": True,
    "total_markets": len(markets),
    "platforms": ["polymarket", "kalshi"],
}
aggregator._all_markets = {m.market_id: m for m in markets}

# Test the analytics function directly
print(f"Testing with {len(markets)} markets:")
for i, market in enumerate(markets):
    print(f"  {i+1}. {market.platform.value}: {market.question} -> {market.implied_probability}")

opportunities = get_arbitrage_opportunities(min_spread=0.01, aggregator=aggregator)

print(f"Found {len(opportunities)} opportunities:")
for i, opp in enumerate(opportunities):
    print(f"  {i+1}. {opp.canonical_question}")
    print(f"     Max: {opp.max_probability} ({opp.max_probability_venue})")
    print(f"     Min: {opp.min_probability} ({opp.min_probability_venue})")
    print(f"     Spread: {opp.spread_probability}")
    print(f"     Markets: {len(opp.markets)}")
    for market in opp.markets:
        print(f"       - {market['venue']}: {market['implied_probability']}")

# Test the grouping function directly
from monitoring.prediction_analytics import _group_markets_by_question
groups = _group_markets_by_question(markets)
print(f"\nGrouped into {len(groups)} canonical questions:")
for canonical, group in groups.items():
    venues = set(m.platform for m in group)
    print(f"  '{canonical}': {len(group)} markets, venues: {venues}")
