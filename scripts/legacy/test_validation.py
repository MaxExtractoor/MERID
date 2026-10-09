#!/usr/bin/env python3
"""Test script to validate trading scope functions"""

import sys
sys.path.append('.')

from config.trading_scope import validate_asset_for_trading, validate_series_ticker_for_trading

# Test the validation functions
test_tickers = [
    'KXETH15M-26JUN041145-45',
    'KXBTC15M-26JUN041145-45',
    'KXSOL15M-26JUN041145-45',
    'KXXRP15M-26JUN041145-45',
    'KXDOGE15M-26JUN041145-45'
]

test_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']

print('=== Testing Asset Validation ===')
for asset in test_assets:
    result = validate_asset_for_trading(asset)
    print(f'Asset {asset}: {result}')

print('\n=== Testing Series Ticker Validation ===')
for ticker in test_tickers:
    result = validate_series_ticker_for_trading(ticker)
    print(f'Ticker {ticker}: {result}')
