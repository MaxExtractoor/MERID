# Calibration Data Requirements

## Overview
This document specifies the data requirements for fitting per-asset calibration parameters for the unified edge system.

## Data Sources

### 1. Kalshi Contract Data
**Source:** Kalshi API historical data
**Required Fields:**
- market_id
- series_ticker (e.g., KXBTC15M)
- strike_price
- close_time (expiry)
- title (Up/Down)
- subtitle
- outcome (YES/NO) - settlement result
- time series of contract prices (bid/ask/mid) during 15m window

**Time Period:** 30+ days of historical data
**Frequency:** 15-minute windows (continuous)

**Collection Method:**
```python
# Use Kalshi client to fetch historical markets
from merid.event_venues.kalshi.client import KalshiClient
client = KalshiClient()
markets = client.get_markets(series_ticker="KXBTC15M", limit=1000)
```

### 2. CF Benchmarks RTI Data
**Source:** CF Benchmarks API
**Required Fields:**
- Asset (BTC, ETH, SOL, XRP, DOGE)
- Timestamp
- RTI 60-second average
- Underlying exchange prices

**Time Period:** 30+ days of historical data
**Frequency:** 60-second averages (matching Kalshi settlement)

**Collection Method:**
```python
# TODO: Integrate CF Benchmarks API
# Placeholder implementation in cfb_spot_proxy.py
```

**API Reference:**
- CF Benchmarks: https://www.cfbenchmarks.com/
- RTI methodology: Real-Time Index (last 60 seconds average)

### 3. Spot Price Data
**Source:** Composite from multiple exchanges
**Required Fields:**
- Asset (BTC, ETH, SOL, XRP, DOGE)
- Timestamp
- Spot price (USD)
- Exchange source

**Exchanges:**
- Binance
- Coinbase
- Kraken
- Bitstamp
- OKX

**Time Period:** 30+ days of historical data
**Frequency:** 1-second or higher (to compute 60-second averages)

**Collection Method:**
```python
# Use exchange APIs or composite feed
# For now, use existing spot price feed
```

### 4. Order Book Data
**Source:** Kalshi order book snapshots
**Required Fields:**
- market_id
- best_bid
- best_ask
- best_bid_size
- best_ask_size
- spread_cents
- timestamp

**Time Period:** 30+ days of historical data
**Frequency:** Per market (when markets are active)

**Collection Method:**
```python
# Use Kalshi market state store
from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
state_store = get_kalshi_market_state_store()
state = state_store.get(market_id)
```

### 5. Slippage Data
**Source:** Execution logs
**Required Fields:**
- market_id
- order_price (expected)
- fill_price (actual)
- order_size
- timestamp
- side (YES/NO)

**Time Period:** 30+ days of historical data
**Frequency:** Per fill

**Collection Method:**
```python
# Use position cache fill logs
from merid.event_venues.kalshi.position_cache import get_position_cache
position_cache = get_position_cache()
fills = position_cache.get_fills()
```

## Data Processing

### Step 1: Data Alignment
- Align spot data with contract windows (15m intervals)
- Compute RTI-like 60-second averages from spot data
- Align order book snapshots with contract windows
- Align slippage data with fills

### Step 2: Feature Engineering
For each contract window, compute:
- spot_move_pct = (spot_final - spot_initial) / strike
- spot_volatility = std(spot_returns)
- time_to_expiry = seconds_until_expiry
- initial_spread = initial_bid_ask_spread
- avg_depth = average_orderbook_depth
- price_path_features = max_drawdown, etc.

### Step 3: Model Fitting
Fit per-asset models:
- f_a(S, strike, τ) → q_a(t) (spot-contract mapping)
- σ_a (15m volatility)
- slippage_model(spread, depth, size) → expected_slippage

### Step 4: Validation
- Validate on hold-out set (20% of data)
- Compute Brier score (probability calibration)
- Compute ROC AUC (discrimination)
- Check edge distribution (should be centered around 0)
- Check alignment gaps (should be < 50 cents)

## Data Quality Checks

### Required Quality Metrics
- **Completeness:** > 95% of contract windows have all required fields
- **Accuracy:** Spot prices within 0.1% of exchange prices
- **Timeliness:** Data latency < 1 second
- **Consistency:** No gaps > 5 minutes in time series

### Validation Checks
- Spot prices are positive and reasonable
- Strike prices are positive and reasonable
- Time to expiry is between 0 and 900 seconds
- Bid/ask are valid (bid < ask, both > 0)
- Spreads are reasonable (< 5 cents for liquid assets)
- Outcomes are binary (YES/NO)

## Storage Requirements

### Estimated Data Volume
- Kalshi contract data: ~100 MB per month (5 assets × 15m windows)
- CF Benchmarks RTI data: ~50 MB per month (5 assets × 60s averages)
- Spot price data: ~200 MB per month (5 assets × 1s data)
- Order book data: ~150 MB per month (5 assets × per market)
- Slippage data: ~10 MB per month (fills only)

**Total:** ~500 MB per month for 5 assets

### Storage Format
- Parquet files for efficient compression
- Partitioned by asset and date
- Versioned with calibration version

## Data Collection Timeline

### Phase 1: Initial Collection (Week 1)
- Set up data collection pipelines
- Collect 7 days of historical data
- Validate data quality
- Fix any collection issues

### Phase 2: Extended Collection (Weeks 2-4)
- Collect 30 days of historical data
- Fit initial calibration parameters
- Validate on hold-out set
- Iterate on model fitting

### Phase 3: Ongoing Collection (Ongoing)
- Continuous data collection
- Weekly model re-fitting
- Monthly model re-fitting
- Monitor for calibration drift

## Data Access

### For Calibration
- Read access to historical data
- Write access to calibration parameters
- Version control for calibration parameters

### For Production
- Real-time access to spot prices
- Real-time access to order book data
- Real-time access to CFB RTI data
- Read access to calibration parameters

## Security Considerations

- API keys for CF Benchmarks (if required)
- API keys for exchange data (if required)
- Encrypted storage of sensitive data
- Access control for calibration parameters
- Audit logging for data access

## Compliance

- CF Benchmarks terms of service
- Exchange API terms of service
- Kalshi API terms of service
- Data retention policies
- Data privacy policies

## Next Steps

1. Set up data collection pipelines
2. Collect initial 7 days of data
3. Validate data quality
4. Fit initial calibration parameters
5. Validate on hold-out set
6. Export calibration parameters
7. Set MERID_CALIBRATION_VERSION=v1
8. Enable unified edge in shadow mode
9. Test for 2-4 hours
10. Gradual rollout to production
