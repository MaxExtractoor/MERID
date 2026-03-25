# Integration Guide: Kalshi Filter Pipeline with Existing System

## Overview

This guide explains how to integrate the new filter pipeline (`merid/trading/kalshi_continuous_trader.py`) with the existing Kalshi trading infrastructure.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                   KalshiTradingAgent                         │
│         (merid/prediction/trading_agent.py)                  │
│                                                              │
│  ┌─────────────────────────────────────────────────┐       │
│  │     Market Resolution (kalshi_list_markets)      │       │
│  └──────────────┬───────────────────────────────────┘       │
│                 │                                            │
│                 ▼                                            │
│  ┌─────────────────────────────────────────────────┐       │
│  │   NEW: FilterPipeline                            │       │
│  │   - Distance filtering (volatility-aware)        │       │
│  │   - Per-asset + global capping                   │       │
│  │   - Composite scoring                            │       │
│  │   - Detailed metrics & timing                    │       │
│  └──────────────┬───────────────────────────────────┘       │
│                 │                                            │
│                 ▼                                            │
│  ┌─────────────────────────────────────────────────┐       │
│  │     Strategy Evaluation & Order Execution        │       │
│  └─────────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────────┘
```

## Integration Points

### 1. Integrate with Market Resolution

In `merid/prediction/trading_agent.py`, the `_resolve_markets()` method currently fetches markets using `_kalshi_list_markets`. We can enhance this to use the new filter pipeline:

```python
async def _resolve_markets(self) -> None:
    """Resolve config filters into live Kalshi market tickers."""
    from merid.prediction.kalshi_tools import _kalshi_list_markets
    from merid.trading.kalshi_continuous_trader import (
        FilterPipeline,
        FilterPipelineConfig,
        AssetVolatilityConfig,
    )

    # Fetch raw markets for each asset
    raw_markets = {}
    for asset in self.config.assets:
        result = await _kalshi_list_markets(
            category=self.config.category,
            asset=asset,
            timeframe=self.config.timeframes[0] if self.config.timeframes else "",
            limit=100,  # Fetch more, filter later
        )

        if result.success:
            raw_markets[asset] = result.payload.get("markets", [])

    # Configure filter pipeline
    pipeline_config = FilterPipelineConfig(
        assets=self.config.assets,
        max_candidates_per_asset=self.config.risk_limits.max_orders_per_window,
        max_candidates_global=10,
        asset_vol_configs=self._build_vol_configs(),
    )

    pipeline = FilterPipeline(pipeline_config)

    # Set spot prices from price feed
    for asset in self.config.assets:
        spot = await self._get_spot_price(asset)
        if spot:
            pipeline.set_spot_price(asset, spot)

    # Run filter pipeline
    result = await pipeline.filter_markets(raw_markets)

    # Convert final candidates back to EventMarket objects
    self._resolved_markets = self._candidates_to_event_markets(
        result.final_candidates
    )
```

### 2. Integrate with KalshiWebSocket Lag Monitoring

The existing `KalshiWebSocket` class (merid/event_venues/kalshi/ws.py) already has production-grade lag monitoring. We can extend it to track filter pipeline lag:

```python
# In KalshiWebSocket._measure_lag()
def _measure_lag(self, loop: asyncio.AbstractEventLoop) -> None:
    """Measure event-loop lag."""
    now = time.monotonic()
    lag = now - self._expected_lag_ts
    self._loop_lag_samples.append(lag)

    # Keep last 60 samples
    if len(self._loop_lag_samples) > 60:
        self._loop_lag_samples = self._loop_lag_samples[-60:]

    # Warn if lag exceeds threshold
    lag_ms = lag * 1000
    if lag_ms > 100:  # >100ms lag is concerning
        # NEW: Include current task type if available
        task_context = getattr(self, '_current_task', 'unknown')
        logger.warning(
            f"Event-loop lag: {lag_ms:.0f}ms | context={task_context}"
        )

    # Reschedule
    self._schedule_lag_check(loop)
```

### 3. Wire Spot Price Feed

The filter pipeline needs real-time spot prices for distance calculations. We can source these from the existing price feed infrastructure:

```python
async def _get_spot_price(self, asset: str) -> Optional[Decimal]:
    """Get current spot price for an asset.

    This should integrate with your existing price feed infrastructure.
    For example, from the crypto price feed or market catalog.
    """
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()

        # Get reference price from catalog
        # This is a placeholder - adjust based on your actual price feed
        ref_price = catalog.get_reference_price(asset)

        if ref_price:
            return Decimal(str(ref_price))

        logger.warning(f"No spot price available for {asset}")
        return None
    except Exception as exc:
        logger.warning(f"Error fetching spot price for {asset}: {exc}")
        return None
```

### 4. Configure Volatility Estimates

Volatility estimates can be sourced from historical data or implied volatility:

```python
def _build_vol_configs(self) -> Dict[str, AssetVolatilityConfig]:
    """Build per-asset volatility configurations.

    This should integrate with your volatility estimation system.
    """
    # Default configurations (can be loaded from config file)
    configs = {
        "BTC": AssetVolatilityConfig(
            asset="BTC",
            max_vols_from_spot=3.0,
            max_pct_from_spot=0.25,
            daily_volatility=0.03,  # 3% daily vol
        ),
        "ETH": AssetVolatilityConfig(
            asset="ETH",
            max_vols_from_spot=3.0,
            max_pct_from_spot=0.25,
            daily_volatility=0.04,  # 4% daily vol
        ),
        "SOL": AssetVolatilityConfig(
            asset="SOL",
            max_vols_from_spot=2.5,
            max_pct_from_spot=0.30,
            daily_volatility=0.05,  # 5% daily vol
        ),
        "XRP": AssetVolatilityConfig(
            asset="XRP",
            max_vols_from_spot=2.5,
            max_pct_from_spot=0.30,
            daily_volatility=0.04,
        ),
        "DOGE": AssetVolatilityConfig(
            asset="DOGE",
            max_vols_from_spot=2.5,
            max_pct_from_spot=0.30,
            daily_volatility=0.06,
        ),
    }

    # TODO: Enhance with dynamic vol estimation from historical prices
    # from merid.volatility.estimator import get_volatility_estimator
    # estimator = get_volatility_estimator()
    # for asset in self.config.assets:
    #     realized_vol = estimator.get_daily_vol(asset, lookback_days=30)
    #     if realized_vol:
    #         configs[asset].daily_volatility = realized_vol

    return configs
```

## Configuration

### Option 1: Environment Variables

Add to your `.env` file:

```bash
# Filter pipeline configuration
FILTER_MAX_CANDIDATES_PER_ASSET=5
FILTER_MAX_CANDIDATES_GLOBAL=10
FILTER_MIN_VOLUME=50
FILTER_MIN_OPEN_INTEREST=10
FILTER_MAX_SPREAD_CENTS=12

# Per-asset volatility settings
FILTER_BTC_MAX_VOLS=3.0
FILTER_BTC_MAX_PCT=0.25
FILTER_BTC_DAILY_VOL=0.03

FILTER_ETH_MAX_VOLS=3.0
FILTER_ETH_MAX_PCT=0.25
FILTER_ETH_DAILY_VOL=0.04

# Event-loop monitoring
FILTER_LAG_WARNING_MS=200
```

### Option 2: Configuration File

Add to `config/kalshi_agent_grid.yaml`:

```yaml
filter_pipeline:
  max_candidates_per_asset: 5
  max_candidates_global: 10

  liquidity:
    min_volume: 50
    min_open_interest: 10
    max_spread_cents: 12

  expiry:
    min_minutes_to_expiry: 5
    max_minutes_to_expiry: 180

  event_loop:
    lag_warning_ms: 200

  assets:
    BTC:
      max_vols_from_spot: 3.0
      max_pct_from_spot: 0.25
      daily_volatility: 0.03

    ETH:
      max_vols_from_spot: 3.0
      max_pct_from_spot: 0.25
      daily_volatility: 0.04

    SOL:
      max_vols_from_spot: 2.5
      max_pct_from_spot: 0.30
      daily_volatility: 0.05

    XRP:
      max_vols_from_spot: 2.5
      max_pct_from_spot: 0.30
      daily_volatility: 0.04

    DOGE:
      max_vols_from_spot: 2.5
      max_pct_from_spot: 0.30
      daily_volatility: 0.06
```

## Monitoring and Observability

### 1. Filter Pipeline Metrics

Add to your metrics/monitoring system:

```python
# In merid/monitoring/metrics.py or similar
from merid.trading.kalshi_continuous_trader import FilterPipeline

class FilterPipelineMetrics:
    """Prometheus-style metrics for filter pipeline."""

    def __init__(self):
        self.pipeline_duration_seconds = Histogram(
            'kalshi_filter_pipeline_duration_seconds',
            'Time spent in filter pipeline',
            ['asset']
        )

        self.markets_filtered_total = Counter(
            'kalshi_markets_filtered_total',
            'Total markets filtered',
            ['asset', 'reason']
        )

        self.candidates_selected = Gauge(
            'kalshi_candidates_selected',
            'Number of candidates selected',
            ['asset']
        )

    def record_filter_result(self, asset: str, result: AssetFilterResult):
        """Record filter result metrics."""
        self.pipeline_duration_seconds.labels(asset=asset).observe(
            result.timings.total_ms / 1000
        )

        # Record rejections by reason
        if result.strike_too_far > 0:
            self.markets_filtered_total.labels(
                asset=asset, reason='strike_too_far'
            ).inc(result.strike_too_far)

        if result.illiquid > 0:
            self.markets_filtered_total.labels(
                asset=asset, reason='illiquid'
            ).inc(result.illiquid)

        # ... other rejection reasons

        self.candidates_selected.labels(asset=asset).set(result.candidates)
```

### 2. Dashboard Queries

Example Grafana queries:

```promql
# Filter pipeline latency by asset
histogram_quantile(0.95,
  rate(kalshi_filter_pipeline_duration_seconds_bucket[5m])
) by (asset)

# Markets filtered by reason
sum by (reason) (
  rate(kalshi_markets_filtered_total[5m])
)

# Candidate selection rate
rate(kalshi_candidates_selected[5m])

# Event-loop lag correlation
kalshi_event_loop_lag_ms > 200
```

### 3. Alerting

Set up alerts for:

```yaml
# Prometheus alert rules
groups:
  - name: kalshi_filter_pipeline
    rules:
      - alert: HighFilterPipelineLag
        expr: kalshi_filter_pipeline_duration_seconds > 0.1
        for: 5m
        annotations:
          summary: "Filter pipeline latency too high"

      - alert: NoMarketCandidates
        expr: kalshi_candidates_selected == 0
        for: 10m
        annotations:
          summary: "No market candidates found for {{ $labels.asset }}"

      - alert: HighEventLoopLag
        expr: kalshi_event_loop_lag_ms > 500
        for: 2m
        annotations:
          summary: "Event loop lag exceeds 500ms"
```

## Testing Integration

### Unit Tests

Test the integration points:

```python
# tests/integration/test_kalshi_filter_integration.py

@pytest.mark.asyncio
async def test_trading_agent_with_filter_pipeline():
    """Test KalshiTradingAgent with integrated filter pipeline."""
    # Create agent with filter-enabled config
    config = AgentConfig(
        name="test_btc_agent",
        assets=["BTC"],
        timeframes=["15m"],
        use_filter_pipeline=True,  # New flag
    )

    agent = KalshiTradingAgent(config)

    # Mock market data
    with patch('merid.prediction.kalshi_tools._kalshi_list_markets') as mock_list:
        mock_list.return_value = ToolResult(
            success=True,
            payload={
                "markets": [
                    {
                        "ticker": "KXBTC-15M-26MAR25-T95000",
                        "volume": 100,
                        "open_interest": 50,
                        # ... other fields
                    },
                    # ... more markets
                ]
            }
        )

        # Run market resolution
        await agent._resolve_markets()

        # Verify filtered markets
        assert len(agent._resolved_markets) > 0
        assert all(m.market_id.startswith("KXBTC") for m in agent._resolved_markets)
```

### Integration Tests

Test end-to-end flow:

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_end_to_end_filter_to_order():
    """Test full flow from filter pipeline to order placement."""
    # Setup
    config = FilterPipelineConfig(
        assets=["BTC"],
        max_candidates_per_asset=3,
        max_candidates_global=3,
    )

    # Create components
    trader = KalshiContinuousTrader(config)
    await trader.start()

    # Wait for one cycle
    await asyncio.sleep(10)

    # Verify filter pipeline ran
    stats = trader.get_stats()
    assert stats['running']
    assert stats['avg_loop_lag_ms'] < 500

    # Cleanup
    await trader.stop()
```

## Performance Optimization

### 1. Caching

Add caching for parsed tickers and distance calculations:

```python
from functools import lru_cache

class FilterPipeline:
    def __init__(self, config: FilterPipelineConfig):
        self.config = config
        self._spot_prices: Dict[str, Decimal] = {}
        self._ticker_cache: Dict[str, Tuple] = {}  # NEW: Cache parsed tickers

    def _parse_strikes(self, asset: str, markets: List[Dict], result: AssetFilterResult):
        """Parse strikes with caching."""
        candidates = []

        for mkt in markets:
            ticker = mkt.get("ticker", "")

            # Check cache first
            if ticker in self._ticker_cache:
                parsed_asset, series, strike = self._ticker_cache[ticker]
            else:
                parsed_asset, series, strike = TickerParser.parse(ticker)
                self._ticker_cache[ticker] = (parsed_asset, series, strike)

            # ... rest of logic
```

### 2. Parallelization

Process each asset's pipeline concurrently:

```python
async def filter_markets(self, raw_markets: Dict[str, List[Dict]]):
    """Run filter pipeline concurrently per asset."""
    tasks = []
    for asset, markets in raw_markets.items():
        task = asyncio.create_task(self._filter_asset(asset, markets))
        tasks.append((asset, task))

    # Wait for all assets to complete
    results = await asyncio.gather(*[task for _, task in tasks])

    # ... aggregate results
```

## Rollout Strategy

### Phase 1: Shadow Mode (Week 1-2)

- Deploy with `use_filter_pipeline=False` (disabled)
- Run filter pipeline in shadow mode (log only, don't use results)
- Monitor metrics and logs
- Tune configuration parameters

### Phase 2: Canary (Week 3)

- Enable for single asset (e.g., BTC)
- Monitor order quality and PnL
- Compare against baseline (non-filtered)

### Phase 3: Gradual Rollout (Week 4-6)

- Enable for all assets, one at a time
- Monitor each asset's performance
- Adjust per-asset configurations as needed

### Phase 4: Full Production (Week 7+)

- Enable globally
- Continuous monitoring and tuning
- Iterate on composite scoring and vol estimates

## Troubleshooting

### Issue: No candidates found

**Symptoms**: `total_candidates_post_cap=0`

**Possible causes**:
1. Spot prices not available
2. Volatility thresholds too tight
3. Liquidity filters too strict

**Solution**:
```python
# Check logs for specific rejection reasons
# Adjust config based on dominant rejection category
config.max_pct_from_spot = 0.30  # Widen percent threshold
config.min_volume = 30  # Lower volume threshold
```

### Issue: High event-loop lag

**Symptoms**: `Event-loop lag: 703ms | task=filter_pipeline_batch`

**Possible causes**:
1. Too many markets being processed
2. Synchronous operations in pipeline

**Solution**:
```python
# Reduce batch size
result = await _kalshi_list_markets(limit=50)  # Lower from 100

# Or parallelize per asset (see Performance Optimization above)
```

### Issue: Incorrect distance calculations

**Symptoms**: Markets incorrectly filtered as `strike_too_far`

**Possible causes**:
1. Wrong spot price
2. Ticker parsing error

**Solution**:
```python
# Verify spot prices
for asset in config.assets:
    spot = pipeline.get_spot_price(asset)
    logger.info(f"{asset} spot: {spot}")

# Test ticker parsing
asset, series, strike = TickerParser.parse("KXBTC-26MAR25-T95000")
logger.info(f"Parsed: {asset=}, {series=}, {strike=}")
```

## Next Steps

1. **Implement volatility estimator**: Dynamic vol calculation from historical prices
2. **Machine learning scoring**: Train model for composite scoring
3. **Real-time vol surface**: Build implied vol surface from market prices
4. **Portfolio optimization**: Factor in current positions for candidate selection
5. **Backtesting framework**: Test filter pipeline on historical data

## Questions?

See `docs/KALSHI_FILTER_PIPELINE_IMPLEMENTATION.md` for detailed implementation documentation.

For issues or enhancements, file a ticket in the project tracker.
