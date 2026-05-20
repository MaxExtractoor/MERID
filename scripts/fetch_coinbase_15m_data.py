"""
Fetch 15m OHLCV Data from Kraken USD Pairs

Fetches historical 15-minute OHLCV data for BTC, ETH, SOL, XRP, DOGE
from Kraken public API using USD pairs (no USDT).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.strategies.binance_us_data import (
    fetch_crypto_majors_15m,
    validate_data_quality,
    save_data_to_csv,
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    """Fetch and save 15m OHLCV data for all crypto majors."""
    logger.info("Starting Kraken USD 15m historical data fetch")
    
    try:
        # Fetch historical data for all assets (10000 bars = ~100 days of 15m data)
        # For multi-year backtesting, we'd need even more data, but Kraken API limits
        data = fetch_crypto_majors_15m(historical=True, total_bars=10000, timeout=30)
        
        # Validate each asset's data
        all_valid = True
        for asset, df in data.items():
            validation = validate_data_quality(df, asset)
            logger.info(f"{asset} validation: {validation['stats']}")
            
            if validation['warnings']:
                logger.warning(f"{asset} warnings: {validation['warnings']}")
                if not validation['valid']:
                    all_valid = False
        
        if all_valid:
            logger.info("All data validation passed")
        else:
            logger.warning("Some data validation failed, but proceeding")
        
        # Save to CSV
        filenames = save_data_to_csv(data, prefix="kraken_historical_")
        logger.info(f"Data saved: {filenames}")
        
        # Print summary
        logger.info("=" * 60)
        logger.info("Data Fetch Summary")
        logger.info("=" * 60)
        for asset, df in data.items():
            latest_price = df['close'].iloc[-1] if not df.empty else 0
            logger.info(f"{asset}: {len(df)} bars, latest price ${latest_price:.2f}")
        logger.info("=" * 60)
        
        return filenames
        
    except Exception as e:
        logger.error(f"Failed to fetch data: {e}")
        raise

if __name__ == "__main__":
    main()
