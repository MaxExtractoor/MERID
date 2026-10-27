#!/usr/bin/env python3
"""Validate config.kalshi_crypto_series_meta against expectations (offline).

With Kalshi API credentials, extend this script to call get_series_by_ticker
for each series_ticker and assert frequency/category match.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.kalshi_crypto_series_meta import (  # noqa: E402
    SERIES_META_BY_TICKER,
    build_kalshi_crypto_products,
    all_series_tickers,
)


def main() -> int:
    products = build_kalshi_crypto_products()
    required = ["BTC_15M", "DOGE_15M", "ETH_1H", "XRP_DAILY"]
    for k in required:
        if k not in products or not products[k]:
            print(f"FAIL: missing {k} in KALSHI_CRYPTO_PRODUCTS")
            return 1
    if "KXBTCH1" in all_series_tickers():
        print("FAIL: obsolete KXBTCH1 must not appear in canonical meta")
        return 1
    if SERIES_META_BY_TICKER.get("KXBTC") is None:
        print("FAIL: KXBTC missing from SERIES_META_BY_TICKER")
        return 1
    print(f"OK: {len(SERIES_META_BY_TICKER)} series tickers, {len(products)} product keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
