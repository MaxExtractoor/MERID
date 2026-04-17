"""Runtime inspection helper: prints Kalshi catalog and WS bridge summaries.

Run this inside the MERID workspace to gather quick diagnostics about
catalog population, per-agent series→market resolution, and WS bridge
subscription / orderbook snapshot state.

Usage:
  python scripts/inspect_kalshi_runtime.py
"""
from __future__ import annotations

import asyncio
import json
import sys


async def main() -> int:
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        from merid.event_venues.kalshi.ws_bridge import get_ws_bridge, get_live_prices
        from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP, get_agent_market_tickers
    except Exception as exc:
        print("Import error:", exc)
        return 2

    catalog = get_market_catalog()
    if not catalog.get_all_markets():
        print("Catalog empty — running refresh() (may require network/credentials)")
        try:
            await catalog.refresh()
        except Exception as exc:
            print("Catalog refresh failed:", exc)

    print("CATALOG SUMMARY:")
    try:
        print(json.dumps(catalog.summary(), indent=2))
    except Exception:
        print(str(catalog.summary()))

    # Per-agent series resolution counts
    print("\nAGENT SERIES RESOLUTION:\n")
    for agent in sorted(AGENT_SERIES_MAP.keys()):
        try:
            tickers = await get_agent_market_tickers(agent)
            print(f"{agent}: series={len(AGENT_SERIES_MAP[agent])} -> markets={len(tickers)}")
        except Exception as exc:
            print(f"{agent}: resolution error: {exc}")

    # WS bridge summary
    print("\nWS BRIDGE SUMMARY:")
    try:
        bridge = get_ws_bridge()
        print(json.dumps(bridge.summary(), indent=2))
    except Exception as exc:
        print("WS bridge summary failed:", exc)

    # Show live prices for a sample resolved ticker (if any)
    sample_ticker = None
    try:
        for agent in sorted(AGENT_SERIES_MAP.keys()):
            tickers = await get_agent_market_tickers(agent)
            if tickers:
                sample_ticker = tickers[0]
                break
    except Exception:
        pass

    if sample_ticker:
        print(f"\nLIVE PRICES SAMPLE for {sample_ticker}:")
        try:
            lp = get_live_prices(sample_ticker)
            print(json.dumps(lp, indent=2))
        except Exception as exc:
            print("get_live_prices failed:", exc)
    else:
        print("\nNo resolved tickers found to sample live prices.")

        # Additional diagnostics: show sample of 15m markets and BTC markets
        try:
            print("\nSAMPLE 15m / BTC MARKETS (first 20):")
            snap = catalog.snapshot()
            count = 0
            for cm in snap.markets:
                if count >= 20:
                    break
                if cm.timeframe == "15m" or (cm.asset and cm.asset.upper() == "BTC") or cm.market.market_id.upper().startswith("KXBTC"):
                    rd = cm.market.raw_data or {}
                    print(json.dumps({
                        "market_id": cm.market.market_id,
                        "asset": cm.asset,
                        "timeframe": cm.timeframe,
                        "series_ticker": cm.series_ticker,
                        "event_ticker": cm.event_ticker,
                        "raw_series": rd.get("series_ticker"),
                        "raw_event": rd.get("event_ticker"),
                    }, indent=2))
                    count += 1
        except Exception as _exc:
            print("Sample diagnostics failed:", _exc)
        try:
            tf15 = catalog.get_markets_by_timeframe("15m")
            print(f"\nget_markets_by_timeframe('15m') -> {len(tf15)} markets (showing first 20):")
            for cm in tf15[:20]:
                rd = cm.market.raw_data or {}
                print(json.dumps({
                    "market_id": cm.market.market_id,
                    "series_ticker_enriched": cm.series_ticker,
                    "raw_series": rd.get("series_ticker"),
                    "raw_event": rd.get("event_ticker"),
                }))
        except Exception as _exc:
            print("timeframe diagnostic failed:", _exc)
        try:
            # Collect raw series_ticker values from the catalog to inspect naming
            raw_series_vals = set()
            for cm in catalog.get_all_markets()[:500]:
                rd = cm.market.raw_data or {}
                if rd.get("series_ticker"):
                    raw_series_vals.add(str(rd.get("series_ticker")))
            print("\nUnique raw series_ticker samples (<=500 markets scanned):")
            i = 0
            for v in sorted(raw_series_vals):
                print(v)
                i += 1
                if i >= 50:
                    break
            if not raw_series_vals:
                print("(no raw series_ticker values present in scanned markets)")
        except Exception as _exc:
            print("raw series aggregation failed:", _exc)

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
