#!/usr/bin/env python3
"""Test imports for Kalshi venue modules to verify time shadowing fixes."""

import sys

modules_to_test = [
    "merid.event_venues.kalshi.client",
    "merid.event_venues.kalshi.ws_bridge",
    "merid.event_venues.kalshi.ws",
    "merid.event_venues.kalshi.wiring_service",
    "merid.event_venues.kalshi.venue_adapter",
    "merid.event_venues.kalshi.universe_sync",
    "merid.event_venues.kalshi.unified_market_state",
    "merid.event_venues.kalshi.trade_lifecycle",
    "merid.event_venues.kalshi.ticker_collector",
    "merid.event_venues.kalshi.settlement_poller",
    "merid.event_venues.kalshi.responsible_trading",
    "merid.event_venues.kalshi.portfolio_event_log",
    "merid.event_venues.kalshi.rate_limit_metrics",
    "merid.event_venues.kalshi.rate_limit_coordinator",
    "merid.event_venues.kalshi.position_sanity_checker",
    "merid.event_venues.kalshi.position_sizer",
    "merid.event_venues.kalshi.position_cache",
    "merid.event_venues.kalshi.order_router",
]

failed = []
for module in modules_to_test:
    try:
        __import__(module)
        print(f"✓ {module}")
    except Exception as e:
        print(f"✗ {module}: {e}")
        failed.append((module, e))

if failed:
    print(f"\n{len(failed)} module(s) failed to import")
    sys.exit(1)
else:
    print(f"\nAll {len(modules_to_test)} modules imported successfully")
    sys.exit(0)
