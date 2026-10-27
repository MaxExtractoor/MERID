# FVG (Fair Value Gap) Integration Summary

## Overview
Complete integration of the Fair Value Gap (FVG) system into the MERID Kalshi production setup. FVG analysis detects price imbalances (gaps) from candle data and generates trading signals based on price proximity to unfilled gaps.

## Architecture

### Core Components

1. **FVG Forecaster** (`merid/prediction/forecasters/fvg.py`)
   - `FVG` dataclass: Represents a Fair Value Gap (direction, top/bottom prices, size, creation time)
   - `FVGStore`: Thread-safe singleton for storing and retrieving active FVGs
   - `FVGForecaster`: Implements the Forecaster protocol, produces calibrated probability adjustments
   - Rolling window candle gap detection (default 20 candles)
   - Bullish/bearish FVG detection from 3-candle patterns
   - FVG fill detection with configurable threshold (default 5 cents)
   - Multi-timeframe confluence scoring

2. **FVG Integration Module** (`merid/prediction/fvg_integration.py`)
   - `FVGIntegrator`: Connects Kalshi market data to FVG detection
   - `SyntheticCandle`: Builds candles from orderbook mid-price ticks
   - `update_price_from_orderbook()`: Feeds price updates to FVG store
   - `get_fvg_signal_for_market()`: Provides signal interface for trading
   - `is_fvg_enabled()`: Environment-based feature toggle

3. **Market State Store Integration** (`merid/event_venues/kalshi/market_state.py`)
   - Wire FVG integration to live orderbook updates
   - Feed bid/ask/mid prices to FVG store on every orderbook update
   - Best-effort approach: FVG failures don't block market state updates

4. **FVG API** (`web/api/fvg_api.py`)
   - `GET /api/v1/fvg/signals/{ticker}`: FVG signal for specific market
   - `GET /api/v1/fvg/stats`: Aggregate FVG statistics across assets
   - `GET /api/v1/fvg/config`: FVG configuration parameters
   - `GET /api/v1/fvg/fvgs/{asset}/{timeframe}`: Active FVGs for asset/timeframe

5. **Frontend Constants** (`web/react/src/config/constants.ts`)
   - `FVG_SIGNALS`: FVG signal endpoint
   - `FVG_STATS`: FVG statistics endpoint
   - `FVG_CONFIG`: FVG configuration endpoint
   - `FVG_ACTIVE_GAPS`: Active FVGs endpoint

6. **Forecaster Registry** (`merid/prediction/forecasters/registry.py`)
   - Registered FVG forecaster in default forecasters list
   - Includes in `ForecasterRegistry` for ensemble predictions

7. **Module Exports** (`merid/prediction/forecasters/__init__.py`)
   - Added FVG forecaster to package exports

## Configuration

Environment variables:
- `MERID_FVG_ENABLED`: Enable/disable FVG analysis (default: true)
- `MERID_FVG_WINDOW_SIZE`: FVG detection window (default: 20 candles)
- `MERID_FVG_MIN_GAP_CENTS`: Minimum gap size (default: 2.0 cents)
- `MERID_FVG_FILL_THRESHOLD`: Fill detection threshold (default: 5.0 cents)
- `MERID_FVG_ATR_PERIOD`: ATR calculation period (default: 14)
- `MERID_FVG_MIN_PRICE_CHANGE`: Candle update threshold (default: 0.5 cents)

## File Locations

```
merid/prediction/forecasters/fvg.py          - FVG detection and forecaster
merid/prediction/fvg_integration.py          - Kalshi market data integration
merid/event_venues/kalshi/market_state.py      - Live price feed wiring
merid/prediction/forecasters/registry.py       - Ensemble registration
merid/prediction/forecasters/__init__.py     - Package exports
web/api/fvg_api.py                           - REST API endpoints
web/main.py                                  - Router registration
web/react/src/config/constants.ts            - Frontend API constants
tests/prediction/forecasters/test_fvg.py     - Unit tests
```

## Testing

Tests cover:
- Bullish/bearish FVG detection
- FVG fill detection and invalidation
- Signal generation near FVGs
- Singleton store and forecaster
- Asset/timeframe extraction from tickers
- Multi-timeframe confluence scoring

Run tests:
```bash
py -m pytest tests/prediction/forecasters/test_fvg.py -v
```

### 8. Production Configuration (`config/fvg_production.env`)

A comprehensive production-ready environment configuration has been created with:

- **Core Enablement**: Feature flags and window management
- **Detection Parameters**: Gap thresholds, fill distance, price change sensitivity
- **Signal Calibration**: Confidence scores, edge calculations
- **Position Sizing Impact**: Multipliers, max boost caps
- **Entry/Exit Timing**: Proximity thresholds, urgency scoring
- **Ensemble Weights**: FVG forecaster weighting in predictions
- **Risk Management**: Trade limits, debounce, opposing gap cancellation
- **Monitoring**: Signal logging, gap alerts
- **Asset-Specific Overrides**: Per-asset calibration

### 9. Complete Pipeline Integration

FVG is now fully integrated across the entire trading pipeline:

**Strategy Layer** (`merid/prediction/strategy.py`):
- FVG entry timing check before signal generation
- FVG-based confidence boost for optimal entry timing
- FVG position sizing multiplier (up to 50% boost)
- FVG context added to signal eval_context and reason

**Exit Management** (`merid/event_venues/kalshi/`):
- **Take Profit**: FVG exit triggers when opposing FVG creates resistance
- **Stop Loss**: FVG-based stop signals for critical opposing pressure

**Ensemble Integration** (`merid/prediction/forecasters/registry.py`):
- FVG calibration weights with environment-based overrides
- FVG-specific ensemble weighting (default 25%)
- Confluence bonus weight for high-confluence signals

**Production Configuration** (`config/fvg_production.env`):
- 31 environment variables for complete calibration
- Asset-specific overrides for BTC, ETH, SOL, XRP, DOGE
- Entry/exit timing thresholds calibrated to production

**Comprehensive Tests** (`tests/prediction/test_fvg_pipeline_integration.py`):
- 16 test classes covering all integration points
- Signal generation, timing, sizing, exits, calibration
- Thread safety and graceful degradation tests

## Production Readiness

- Thread-safe singleton stores
- Environment-configurable parameters
- Graceful degradation (FVG failures don't crash market state updates)
- Configurable via environment variables
- Proper logging for diagnostics
- Type hints throughout
- Unit tests for core logic

## Integration Points

1. **Price Data Flow**:
   ```
   WS Bridge → MarketStateStore._sync_book_fields → update_price_from_orderbook → FVGIntegrator → FVGStore
   ```

2. **Signal Flow**:
   ```
   FVGStore → FVGForecaster.predict → ForecastResult → ForecasterRegistry → Ensemble Prediction
   ```

3. **API Access**:
   ```
   UI/Clients → /api/v1/fvg/* → FVG API → FVGStore/FVGIntegrator
   ```

## Production Readiness Checklist

- ✅ FVG detection from synthetic candles (Kalshi mid-price ticks)
- ✅ Multi-timeframe FVG confluence scoring
- ✅ FVG fill detection and invalidation
- ✅ FVG forecaster registered in ensemble (25% weight)
- ✅ Strategy entry timing with FVG signals
- ✅ Strategy position sizing with FVG multipliers
- ✅ Take profit FVG exit triggers
- ✅ Stop loss FVG-based stops
- ✅ Environment-configurable production parameters
- ✅ API endpoints for FVG signals and stats
- ✅ Frontend constants for FVG API access
- ✅ Comprehensive test coverage
- ✅ Thread-safe FVG store
- ✅ Production calibration documented

## Known Limitations

- FVG detection requires at least 3 candles per timeframe
- Synthetic candle building is simplified (no OHLC from historical data)
- Confluence scoring is based on active FVG counts, not weighted by size
- Weekly timeframe requires 20 weeks of data for full window

## Future Enhancements

- Historical OHLC data from Kalshi candles API
- Weighted confluence scoring by FVG size and age
- Cross-asset FVG correlation
- FVG-based position sizing in strategy
- Real-time FVG alert system
