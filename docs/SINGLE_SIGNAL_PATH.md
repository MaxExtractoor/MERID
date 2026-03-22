# Single Signal Path Architecture

**Status:** Implemented ✅
**Version:** 1.0
**Date:** 2026-03-22

## Overview

The single signal path architecture consolidates all Kalshi crypto trading through a unified pipeline with no parallel bots and no direct REST calls. Every BTC/ETH/SOL/XRP/DOGE order flows through the same execution path with comprehensive risk management.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Data Sources                                                 │
│ • Kalshi market data (price, volume, OI, spread)           │
│ • Spot feeds (CoinGecko)                                   │
│ • Sentiment (X/Twitter, News, Finnhub)                     │
│ • Fear/Greed indices (CFGI, custom)                        │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ TradingAgent Grid (20 agents: 5 assets × 4 tenors)         │
│                                                              │
│ Per (asset, tenor) agent:                                   │
│   1. Generate edge signal (model_prob vs market_prob)       │
│   2. Pre-execution pipeline:                                │
│      ├─ ExecutionGuard (6 layers)                           │
│      ├─ SwarmConsensusGate (direction check)                │
│      ├─ BTC15m risk layer (for BTC 15m only)               │
│      └─ PreTradeCheck (position limits, notional caps)      │
│   3. Publish ApprovedSignal to event_bus                    │
│      Channel: signals.crypto.{asset}.{tenor}                │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ↓
          ┌──────────────────┐
          │   Event Bus      │
          │ (in-memory pub/sub)
          └──────────┬────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ KalshiContinuousTrader (singleton subscriber)               │
│                                                              │
│ Subscribes to: signals.crypto.*                             │
│                                                              │
│ Processing pipeline:                                        │
│   1. Check per-asset mode (MERID_ASSET_{ASSET}_MODE)       │
│   2. Check correlation cap (40% crypto max)                 │
│   3. Check liquidity gate (spread > 8¢ → edge > 8%)        │
│   4. Calculate Kelly size:                                  │
│      f = (p*b - q)/b × confidence × kelly_fraction          │
│   5. Apply size band multiplier (swarm recommendation)      │
│   6. Execute via route_order_async                          │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ Execution Layer                                             │
│   route_order_async → VenueGate → Kalshi Exchange           │
│   Mode routing: PAPER | LIVE | MOCK                        │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ Post-Execution                                              │
│   • Fill event published to event_bus                       │
│   • Signal + order linkage stored to SQLite                 │
│   • Bankroll update (KalshiRiskManager)                     │
│   • Telegram digest (optional)                              │
└────────────────────┬─────────────────────────────────────────┘
                     │
                     ↓
┌─────────────────────────────────────────────────────────────┐
│ ReflectionAgent (future: 4h cadence)                        │
│   • Read fills vs settlements                               │
│   • Calculate Brier score per (asset, tenor)                │
│   • Adjust agent trust weights in SwarmConsensusAggregator  │
│   • Tune Kelly fractions + min_edge thresholds              │
│   • Write suggestions to data/reflection_suggestions.json   │
└─────────────────────────────────────────────────────────────┘
```

## Key Components

### 1. ApprovedSignal Schema

**Location:** `merid/signals/unified_schema.py`

**Purpose:** Represents a trading signal that has passed all pre-execution checks and is ready for sizing and execution.

**Key Fields:**
```python
@dataclass
class ApprovedSignal:
    # Identity
    signal_id: str
    agent_id: str
    timestamp: datetime

    # Market
    asset: str          # BTC, ETH, SOL, XRP, DOGE
    tenor: str          # 15m, 1h, daily, weekly
    ticker: str         # Kalshi ticker (KXBTC15M-...)
    direction: str      # yes, no

    # Edge model
    model_prob: float   # Model's probability estimate
    market_prob: float  # Current market price
    edge: float         # model_prob - market_prob
    confidence: float   # Signal confidence (0-1)

    # Swarm consensus
    swarm_size_band: str              # small, reduced, base, large
    swarm_consensus_prob: float       # Consensus probability
    agents_voting: int                # Number of agents in consensus

    # Execution parameters
    limit_price_cents: int            # Suggested limit price
    contracts_upper_bound: int        # Max contracts from swarm

    # Risk context
    spread_bps: float
    fear_greed: int                   # 0-100
    volatility_regime: str            # calm, normal, hot

    # Settlement tracking
    settlement_spec_id: str           # "cf_btc_rr", etc.
    settlement_source: str            # "cf_benchmarks", "coinbase"

    # Execution tracking
    executed: bool
    order_id: str
    fill_price_cents: int
    realized_pnl_usd: float
```

**Event Bus Channel:** `signals.crypto.{asset}.{tenor}`

Examples:
- `signals.crypto.BTC.15m`
- `signals.crypto.ETH.1h`
- `signals.crypto.SOL.daily`

### 2. TradingAgent Modifications

**Location:** `merid/prediction/trading_agent.py:820-976`

**Changes:**

1. **New method:** `_publish_approved_signal()` (lines 820-975)
   - Constructs ApprovedSignal from StrategySignal + PreTradeCheck
   - Captures swarm consensus data
   - Determines trade mode (paper vs live)
   - Publishes to event_bus channel

2. **Modified method:** `_execute_signal()` (lines 977-1020)
   - Branches on signal type:
     - **Directional** (BUY_YES/NO, SELL_YES/NO) → publish to event_bus
     - **Quote/Arb** → direct execution (unchanged)

**Quote/Arb Preservation:**
Market-making and arbitrage signals still execute directly via `_kalshi_place_order` to maintain low latency. Only directional signals go through the continuous trader.

### 3. KalshiContinuousTrader

**Location:** `merid/prediction/kalshi_continuous_trader.py`

**Lifecycle:**
```python
trader = get_kalshi_continuous_trader()
await trader.start()  # Subscribes to event bus
# ... runs continuously ...
await trader.stop()   # Unsubscribes and shuts down
```

**Processing Pipeline:**

1. **Per-Asset Mode Check**
   ```python
   MERID_ASSET_BTC_MODE=live    # Override for BTC
   MERID_ASSET_ETH_MODE=paper   # Override for ETH
   MERID_ASSET_SOL_MODE=blocked # Block SOL trading
   ```

2. **Correlation Cap**
   - Maximum 40% of total equity in crypto positions
   - Configurable via `MERID_CORRELATION_CAP_PCT`
   - Prevents over-concentration in correlated assets

3. **Liquidity Gate**
   - Spread > 8¢ requires edge > 8%
   - Prevents trading in illiquid markets without sufficient edge
   - Configurable thresholds

4. **Kelly Sizing**
   ```python
   # Base Kelly formula for binary options
   p = model_prob
   b = payoff_odds  # (1-price)/price for YES, price/(1-price) for NO
   f = (p*b - (1-p)) / b

   # Adjustments
   f *= confidence           # Scale by signal confidence
   f *= KELLY_FRACTION       # Fractional Kelly (default 0.25)

   size_usd = f * total_equity

   # Apply size band multiplier
   multipliers = {
       "small": 0.25,
       "reduced": 0.5,
       "base": 1.0,
       "large": 1.5,
   }
   size_usd *= multipliers[swarm_size_band]

   # Cap at swarm upper bound and correlation capacity
   size_usd = min(size_usd, upper_bound_usd, available_capacity)
   ```

5. **Execution**
   - Converts size to contracts
   - Routes via `route_order_async`
   - Respects VenueGate mode settings
   - Records fill to signal store

### 4. Signal Store Persistence

**Location:** `merid/signals/store.py`

**New Tables:**

```sql
CREATE TABLE approved_signals (
    signal_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    asset TEXT NOT NULL,
    tenor TEXT NOT NULL,
    ticker TEXT NOT NULL,
    market_id TEXT NOT NULL,
    direction TEXT NOT NULL,
    model_prob REAL NOT NULL,
    market_prob REAL NOT NULL,
    edge REAL NOT NULL,
    confidence REAL NOT NULL,
    swarm_size_band TEXT DEFAULT 'base',
    limit_price_cents INTEGER NOT NULL,
    contracts_upper_bound INTEGER NOT NULL,
    trade_mode TEXT DEFAULT 'paper',
    executed INTEGER DEFAULT 0,
    settlement_spec_id TEXT,
    signal_data_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE signal_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    fill_price_cents INTEGER,
    fill_contracts INTEGER,
    fill_timestamp REAL,
    settlement_price REAL,
    settlement_timestamp REAL,
    realized_pnl_usd REAL,
    created_at REAL NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES approved_signals(signal_id)
);
```

**Key Methods:**
- `store_approved_signal(signal_dict)` - Persist signal
- `link_signal_to_order(signal_id, order_id, fill_data)` - Link fill
- `update_signal_settlement(signal_id, settlement_price, realized_pnl)` - Record settlement
- `get_approved_signals(asset, agent_id, executed, limit)` - Query signals
- `get_signal_orders(signal_id)` - Get orders for signal

## Configuration

### Environment Variables

```bash
# Kelly sizing (fractional Kelly to reduce risk)
MERID_KELLY_FRACTION=0.25

# Correlation cap (max % of equity in crypto)
MERID_CORRELATION_CAP_PCT=40

# Liquidity gate thresholds
MERID_LIQUIDITY_GATE_SPREAD_CENTS=8.0  # Spread threshold in cents
MERID_LIQUIDITY_GATE_MIN_EDGE=0.08     # Min edge % for wide spreads

# Per-asset mode overrides (paper | live | blocked)
MERID_ASSET_BTC_MODE=live
MERID_ASSET_ETH_MODE=paper
MERID_ASSET_SOL_MODE=paper
MERID_ASSET_XRP_MODE=blocked
MERID_ASSET_DOGE_MODE=blocked

# Global venue gate mode (fallback if no asset override)
MERID_PM_TRADING_MODE=paper  # mock | paper | live
MERID_PM_LIVE_ENABLED=false
```

### Agent Grid Configuration

**File:** `merid/prediction/agent_grid_config.py` (example)

```python
# 20 agents: 5 assets × 4 tenors
AGENT_GRID = [
    # BTC agents
    {"asset": "BTC", "tenor": "15m", "archetype": "momentum"},
    {"asset": "BTC", "tenor": "1h", "archetype": "trend"},
    {"asset": "BTC", "tenor": "daily", "archetype": "mean_reversion"},
    {"asset": "BTC", "tenor": "weekly", "archetype": "value"},

    # ETH agents
    {"asset": "ETH", "tenor": "15m", "archetype": "momentum"},
    # ... etc
]
```

## Risk Management Layers

The single signal path includes **6 risk layers** before execution:

1. **ExecutionGuard** - Pre-execution checks
   - Position limits
   - Notional caps
   - Rate limits
   - Session limits

2. **SwarmConsensusGate** - Direction validation
   - Minimum 2 agents for consensus
   - 60% agreement threshold
   - Blocks conflicting signals

3. **BTC15m Risk Layer** - Asset-specific rules (BTC 15m only)
   - Per-trade caps ($0.25 base, $0.30 hard cap)
   - Daily loss limits (-$0.50 soft, -$1.00 hard)
   - Max open exposure ($0.50)
   - Fear/greed multipliers
   - Spread/expiry filters

4. **PreTradeCheck** - Individual order validation
   - Market-specific limits
   - Event-level exposure caps
   - Edge requirements
   - Fee estimates

5. **Correlation Cap** - Portfolio-level risk
   - 40% max crypto allocation
   - Prevents over-concentration

6. **Liquidity Gate** - Market quality filter
   - Spread > 8¢ requires edge > 8%
   - Protects against illiquid markets

## Integration Points

### Starting KalshiContinuousTrader

**Recommended:** Wire into application lifespan

```python
# In your FastAPI/async app startup
from merid.prediction.kalshi_continuous_trader import get_kalshi_continuous_trader

@app.on_event("startup")
async def startup():
    trader = get_kalshi_continuous_trader()
    await trader.start()
    logger.info("KalshiContinuousTrader started")

@app.on_event("shutdown")
async def shutdown():
    trader = get_kalshi_continuous_trader()
    await trader.stop()
    logger.info("KalshiContinuousTrader stopped")
```

### ReflectionAgent Integration (Future)

**Not yet implemented** - Planned for reflection loop:

```python
# 4-hour cadence reflection
@app.on_event("startup")
async def startup():
    async def reflection_loop():
        while True:
            await asyncio.sleep(4 * 3600)  # 4 hours
            await run_reflection_cycle()

    asyncio.create_task(reflection_loop())
```

Reflection cycle should:
1. Query `signal_orders` for settled positions
2. Calculate Brier scores per (asset, tenor, agent)
3. Update trust weights in SwarmConsensusAggregator
4. Adjust Kelly fractions based on performance
5. Write suggestions to `data/reflection_suggestions.json`

## Testing

### Unit Tests

Test individual components:

```python
# Test ApprovedSignal serialization
def test_approved_signal_roundtrip():
    signal = ApprovedSignal(...)
    data = signal.to_dict()
    reconstructed = ApprovedSignal.from_dict(data)
    assert reconstructed.signal_id == signal.signal_id

# Test Kelly sizing
def test_kelly_sizing():
    trader = KalshiContinuousTrader()
    signal = ApprovedSignal(
        model_prob=0.6,
        market_prob=0.5,
        confidence=0.8,
        limit_price_cents=50,
        swarm_size_band="base",
    )
    size = trader._calculate_kelly_size(signal)
    assert size > 0
    assert size < trader._portfolio.total_equity_usd
```

### Integration Tests

Test end-to-end flow:

```python
async def test_signal_flow():
    # 1. Start continuous trader
    trader = get_kalshi_continuous_trader()
    await trader.start()

    # 2. Publish test signal
    from core.event_bus import event_stream
    test_signal = ApprovedSignal(...)
    await event_stream.publish(
        test_signal.get_event_channel(),
        test_signal.to_dict()
    )

    # 3. Wait for processing
    await asyncio.sleep(1.0)

    # 4. Verify signal recorded
    from merid.signals.store import get_signal_store
    store = get_signal_store()
    signals = store.get_approved_signals(asset="BTC", limit=1)
    assert len(signals) > 0

    # 5. Cleanup
    await trader.stop()
```

## Migration Guide

### From Direct Execution

**Before:**
```python
# TradingAgent directly calls route_order_async
result = await route_order_async(intent)
```

**After:**
```python
# TradingAgent publishes signal
await event_stream.publish(channel, signal.to_dict())
# KalshiContinuousTrader handles execution
```

### Backwards Compatibility

- Quote/arb signals still execute directly
- Existing risk checks still apply
- VenueGate mode routing unchanged
- Paper session tracking preserved

## Monitoring

### Key Metrics

Track via `trader.summary()`:

```python
{
    "running": true,
    "signals_processed": 1247,
    "orders_placed": 894,
    "orders_blocked": 353,
    "portfolio": {
        "total_equity_usd": 1000.0,
        "crypto_notional_usd": 350.0,
        "crypto_allocation_pct": 35.0,
        "available_capacity_usd": 50.0
    },
    "config": {
        "kelly_fraction": 0.25,
        "correlation_cap_pct": 40.0,
        ...
    }
}
```

### Logs

Watch for:
- `Published ApprovedSignal to signals.crypto.BTC.15m`
- `Processing signal: BTC 15m YES @ 58.0%`
- `Signal blocked by correlation cap: current=42.1%, max=40%`
- `Kelly sizing: base=12.50, band=base (1.0x), final=10.00 USD`
- `Executing order: BTC 15m yes 10x @ 58¢ (live)`
- `Fill recorded to database: BTC 15m YES @ 58%`

## Known Limitations

1. **RTI/Settlement Not Yet Wired**
   - `settlement_spec_id` is placeholder
   - CF Benchmarks integration needed
   - Coinbase settlement feed not connected

2. **ReflectionAgent Not Scheduled**
   - Periodic trigger not wired
   - Trust weight updates not automatic
   - Kelly tuning manual for now

3. **UI Components Not Mounted**
   - SwarmVerdictFeed exists but not displayed
   - ExecutionGateStrip ready but not wired
   - KalshiCryptoSignalsPanel built but unmounted

## Future Enhancements

1. **Settlement Data Integration**
   - Wire CF Benchmarks RTI feed
   - Add Coinbase settlement prices
   - Map Kalshi series codes to settlement specs

2. **Reflection Automation**
   - Schedule 4h cadence reflection
   - Automated trust weight updates
   - Dynamic Kelly fraction tuning

3. **Advanced Sizing**
   - Multi-asset portfolio optimization
   - Volatility-adjusted Kelly
   - Dynamic correlation estimates

4. **Performance Analytics**
   - Per-agent Sharpe ratios
   - Asset-tenor performance breakdowns
   - Edge realization tracking

## Support

For questions or issues:
- GitHub Issues: https://github.com/MaxExtractoor/MERID/issues
- Documentation: This file
- Code: See inline comments in source files

---

**Version History:**
- v1.0 (2026-03-22): Initial implementation
- Core signal path complete
- Persistence layer added
- Kelly sizing + risk gates implemented
