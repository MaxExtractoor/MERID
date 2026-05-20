# Multi-Exchange Spot Price Subsystem Implementation

## Overview

This document describes the production-grade multi-exchange spot price subsystem with CF Benchmarks RTI integration implemented for the MERID Kalshi 15m crypto stack.

## Architecture

### Components

1. **data/spot_models.py** - Pydantic data models
   - `ExchangeTick`: Normalized tick from a single exchange
   - `CompositeSpot`: Aggregated spot price across exchanges (VWAP/median)
   - `CfbRtiObservation`: CF Benchmarks Real-Time Index observation
   - `SpotAlignment`: Alignment snapshot between MERID_SPOT and CF Benchmarks RTI

2. **data/cfb_rti_client.py** - CF Benchmarks RTI client
   - Fetches RTI prices for BTC, ETH, SOL, XRP, DOGE
   - Implements caching with TTL
   - Retry logic and error handling
   - Singleton pattern with async context manager

3. **data/spot_composite.py** - Composite spot calculation
   - Aggregates ticks from multiple exchanges
   - Computes VWAP (volume-weighted) when volume available
   - Falls back to median when volume unreliable
   - Health classification: healthy, degraded, insufficient_data

4. **data/spot_alignment_monitor.py** - Alignment monitoring
   - Background task monitoring MERID_SPOT vs CF Benchmarks RTI
   - Computes basis (absolute and bps)
   - Rolling statistics (mean, std, max, P95)
   - Health classification: aligned, mild_drift, severe_drift

5. **config/spot_composite_config.py** - Configuration
   - Environment variables for all subsystems
   - Enable/disable flags
   - Thresholds and timeouts

### Integration Points

#### Upstream Integration

1. **data/live_price_feed.py**
   - Added composite spot system initialization
   - Feeds ExchangeTick objects into composite on price updates
   - Methods: `_feed_composite()`, `get_composite_spot()`, `get_all_composite_spots()`

2. **merid/alignment/spot_basis_tracker.py**
   - Added composite spot support as optional source
   - Added CF Benchmarks RTI alignment checking
   - New fields: `spot_source`, `cfb_rti_alignment`
   - Configurable via `SPOT_FEED_SOURCE` env var (composite, coinbase, kraken, coingecko)

3. **merid/prediction/model.py**
   - Modified `get_spot_price()` to try composite first
   - Falls back to legacy feed if composite unavailable/unhealthy
   - Logs source used (composite vs legacy)

#### Downstream Integration

1. **Logging**
   - Composite health logging in spot_composite.py
   - Alignment logging in spot_alignment_monitor.py
   - Source tracking in model.py

2. **Metrics**
   - Alignment stats (mean, std, max, P95, health percentages)
   - Composite health per asset
   - Contributing exchanges count

## Configuration

### Environment Variables

```bash
# Enable/disable composite spot system
MERID_SPOT_COMPOSITE_ENABLED=false  # Default: false (use legacy)

# Spot feed source for spot_basis_tracker
MERID_SPOT_FEED_SOURCE=coinbase  # Options: composite, coinbase, kraken, coingecko

# CF Benchmarks RTI
CFB_API_KEY=""  # Optional API key for production access
CFB_BASE_URL="https://api.cfbenchmarks.com"

# Composite calculation
MERID_SPOT_COMPOSITE_VWAP_WINDOW=60.0  # Seconds
MERID_SPOT_COMPOSITE_FRESH_TICK_AGE=10.0  # Seconds
MERID_SPOT_COMPOSITE_MIN_EXCHANGES_HEALTHY=2
MERID_SPOT_COMPOSITE_MIN_EXCHANGES_DEGRADED=1
MERID_SPOT_COMPOSITE_VOLUME_WEIGHT_EXPONENT=0.5

# Alignment monitoring
MERID_SPOT_ALIGNMENT_INTERVAL=30.0  # Seconds
MERID_SPOT_ALIGNMENT_WINDOW=3600.0  # Seconds
MERID_SPOT_ALIGNMENT_THRESHOLD1_BPS=5.0  # ALIGNED -> MILD_DRIFT
MERID_SPOT_ALIGNMENT_THRESHOLD2_BPS=20.0  # MILD_DRIFT -> SEVERE_DRIFT
MERID_SPOT_ALIGNMENT_MONITOR_ENABLED=false
```

### Configuration Files

- `config/spot_composite_config.py` - All configuration with defaults
- `config/spot_basis_config.py` - Existing basis tracker config (extended)

## Usage

### Basic Usage

```python
# Get composite spot price
from data.live_price_feed import get_live_price_feed

feed = get_live_price_feed()
composite = feed.get_composite_spot("BTC")
if composite and composite.is_healthy:
    print(f"BTC composite: ${composite.price:.2f}")
    print(f"Method: {composite.method}")
    print(f"Exchanges: {composite.contributing_exchanges}")
```

### CF Benchmarks RTI

```python
from data.cfb_rti_client import get_cfb_rti_client
from data.spot_models import Asset

async with get_cfb_rti_client() as client:
    rti = await client.get_latest_rti(Asset.BTC)
    if rti:
        print(f"BTC RTI: ${rti.price:.2f}")
```

### Alignment Monitoring

```python
from data.spot_alignment_monitor import get_spot_alignment_monitor
from data.spot_models import Asset

monitor = await get_spot_alignment_monitor()
await monitor.start()

alignment = monitor.get_latest_alignment(Asset.BTC)
print(f"Alignment: {alignment.health.value}")
print(f"Basis: {alignment.basis_bps:.1f} bps")

stats = monitor.get_stats(Asset.BTC)
print(f"Mean basis: {stats.basis_abs_mean:.2f} USD")
print(f"Aligned %: {stats.aligned_pct:.1f}%")
```

### Spot Basis Tracker with Composite

```python
# Set environment variable
export MERID_SPOT_FEED_SOURCE=composite

# The spot_basis_tracker will now use composite spot
# and check CF Benchmarks RTI alignment
```

## Testing

### Unit Tests

```bash
# Run spot models tests
pytest tests/data/test_spot_models.py -v

# Run spot composite tests
pytest tests/data/test_spot_composite.py -v
```

### Test Coverage

- **test_spot_models.py**: Tests for all Pydantic models
  - ExchangeTick mid price calculation
  - CompositeSpot health classification
  - CfbRtiObservation freshness
  - SpotAlignment basis calculation and health states

- **test_spot_composite.py**: Tests for composite calculation
  - ExchangeTickBuffer operations
  - VWAP calculation with volume weighting
  - Median calculation fallback
  - Multi-exchange aggregation
  - Health state transitions

## Health States

### Composite Health

- **HEALTHY**: 2+ exchanges with fresh ticks
- **DEGRADED**: 1 exchange with fresh tick
- **INSUFFICIENT_DATA**: No fresh ticks available

### Alignment Health

- **ALIGNED**: Basis ≤ 5 bps (configurable)
- **MILD_DRIFT**: 5 bps < Basis ≤ 20 bps (configurable)
- **SEVERE_DRIFT**: Basis > 20 bps (configurable)
- **NO_RTI**: CF Benchmarks RTI unavailable
- **NO_SPOT**: Composite spot unavailable

## Exchanges Supported

### CF Benchmarks Constituent Exchanges

- Coinbase
- Kraken
- Bitstamp
- itBit
- Gemini
- Bullish
- Binance
- Bybit
- OKX

### MERID Assets

- BTC
- ETH
- SOL
- XRP
- DOGE

## Migration Path

### Phase 1: Legacy Mode (Current Default)
- `MERID_SPOT_COMPOSITE_ENABLED=false`
- Uses single-exchange feed (Coinbase/Kraken)
- No changes to existing behavior

### Phase 2: Composite Mode
- `MERID_SPOT_COMPOSITE_ENABLED=true`
- `MERID_SPOT_FEED_SOURCE=composite`
- Uses multi-exchange VWAP/median
- Falls back to legacy if composite unhealthy

### Phase 3: Full Alignment Monitoring
- `MERID_SPOT_ALIGNMENT_MONITOR_ENABLED=true`
- Background alignment monitoring task
- CF Benchmarks RTI integration
- Alerting on severe drift

## Troubleshooting

### Composite Not Updating

1. Check if composite is enabled: `MERID_SPOT_COMPOSITE_ENABLED`
2. Check if LivePriceFeed is feeding ticks
3. Check logs for composite feed errors
4. Verify exchange connectivity

### CF Benchmarks RTI Failures

1. Check API key: `CFB_API_KEY`
2. Check base URL: `CFB_BASE_URL`
3. Verify network connectivity to CF Benchmarks
4. Check logs for API errors (401, 404, timeout)

### Alignment Always NO_SPOT

1. Verify composite is healthy
2. Check if composite has price data
3. Check logs for composite calculation errors
4. Verify exchange tick freshness

## Performance Considerations

- Composite calculation is lightweight (O(n) where n = number of exchanges)
- CF Benchmarks RTI client uses caching (5s TTL)
- Alignment monitor runs on configurable interval (default 30s)
- All operations are async and non-blocking

## Future Enhancements

1. Add more CF Benchmarks indices (hourly, daily)
2. Implement historical RTI data storage
3. Add Prometheus metrics export
4. Implement circuit breaker for CF Benchmarks API
5. Add exchange-specific weight configuration
6. Implement adaptive volume weighting based on liquidity
