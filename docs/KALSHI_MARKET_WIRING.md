# Kalshi Market Wiring Layer - Complete Implementation

## Overview

The Kalshi Market Wiring Layer provides complete coverage, explicit mapping, and strong safety constraints for Kalshi prediction markets integration with MERID's unified signal system. This implementation ensures that **no Kalshi market can fall through the cracks** - every open market is either fully mapped with proper context or explicitly disabled with clear reasons.

## Architecture

### Core Components

1. **Models** (`models.py`) - Data structures for markets, mappings, and safety checks
2. **Store** (`store.py`) - Database persistence and querying layer
3. **Sync** (`sync.py`) - Universe synchronization with Kalshi API
4. **Mapping** (`mapping.py`) - Automatic and manual market mapping rules
5. **Safety** (`safety.py`) - Data freshness and risk limit enforcement
6. **Coverage** (`coverage.py`) - Completeness checking and gap detection
7. **Orchestrator** (`orchestrator.py`) - Main coordination and integration layer
8. **API** (`kalshi_wiring_api.py`) - REST endpoints for management and monitoring

### Integration Points

- **Enhanced Kalshi Generator** - Updated to use wiring layer instead of ad-hoc symbol logic
- **Unified Signal System** - Integrates with existing signal generation and CQI gating
- **Execution Bridge** - Respects per-market risk caps and safety checks
- **CQI System** - Extended with segment-based quality tracking

## Key Features

### 1. Complete Market Coverage

```python
# Every open Kalshi market is tracked
kalshi_markets = [
    {
        "market_ticker": "KXBTCD-25JUN-T100000",
        "event_ticker": "E-BTC-DAILY-...",
        "series_ticker": "S-BTC-DAILY-...",
        "category": "crypto",
        "risk_profile": "crypto_linked",
        "enabled_for_merid": True,
        "max_notional_per_trade": 100.0,
        "max_daily_notional": 1000.0,
        "max_open_risk": 500.0,
    }
]
```

### 2. Explicit Symbol Mapping

```python
market_mappings = [
    {
        "market_ticker": "KXBTCD-25JUN-T100000",
        "underlying_symbol": "BTC",
        "merid_symbol": "BTC",
        "sentiment_symbols": ["BTC", "BTC-USD"],
        "debate_symbol": "BTC",
        "requires_crypto_context": True,
        "requires_sentiment_context": True,
        "requires_debate_context": True,
        "enabled": True,
    }
]
```

### 3. Strong Safety Constraints

#### Data Freshness Enforcement
- **Crypto context**: Maximum 5 minutes staleness
- **Sentiment context**: Maximum 10 minutes staleness  
- **Debate context**: Maximum 15 minutes staleness
- **Automatic suppression** when data is stale

#### Per-Market Risk Caps
- **Per-trade notional limits** per market
- **Daily notional limits** per market
- **Open risk limits** per market
- **CQI-based multiplier** reduces limits during poor quality

#### Segment-Based CQI
- `prediction_crypto_linked` - Crypto-linked markets
- `prediction_macro_election` - Election markets
- `prediction_equity_linked` - Equity markets
- `prediction_other` - Idiosyncratic markets

### 4. Risk Profile Classification

#### Crypto-Linked Markets
- **Requirements**: Crypto features + sentiment + debate
- **Risk caps**: Higher limits due to rich context
- **CQI threshold**: More lenient (0.3 minimum)

#### Macro/Election Markets  
- **Requirements**: Debate + sentiment (no crypto)
- **Risk caps**: Conservative limits
- **CQI threshold**: Stricter (0.5 minimum)

#### Equity-Linked Markets
- **Requirements**: Debate + sentiment (optional crypto)
- **Risk caps**: Moderate limits
- **CQI threshold**: Standard (0.4 minimum)

#### Idiosyncratic Markets
- **Requirements**: Manual enablement only
- **Risk caps**: Very conservative
- **CQI threshold**: Strictest (0.6 minimum)

## Database Schema

### kalshi_markets Table
```sql
CREATE TABLE kalshi_markets (
    market_ticker TEXT PRIMARY KEY,
    event_ticker TEXT NOT NULL,
    series_ticker TEXT NOT NULL,
    category TEXT NOT NULL,
    tags TEXT,  -- JSON array
    title TEXT NOT NULL,
    subtitle TEXT DEFAULT '',
    close_ts REAL NOT NULL,
    status TEXT NOT NULL,
    enabled_for_merid BOOLEAN DEFAULT FALSE,
    risk_profile TEXT NOT NULL,
    max_notional_per_trade REAL DEFAULT 100.0,
    max_daily_notional REAL DEFAULT 1000.0,
    max_open_risk REAL DEFAULT 500.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
```

### market_mappings Table
```sql
CREATE TABLE market_mappings (
    market_ticker TEXT PRIMARY KEY,
    event_ticker TEXT NOT NULL,
    series_ticker TEXT NOT NULL,
    category TEXT NOT NULL,
    risk_profile TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    merid_symbol TEXT NOT NULL,
    sentiment_symbols TEXT,  -- JSON array
    debate_symbol TEXT,
    enabled BOOLEAN DEFAULT FALSE,
    requires_crypto_context BOOLEAN DEFAULT FALSE,
    requires_debate_context BOOLEAN DEFAULT FALSE,
    requires_sentiment_context BOOLEAN DEFAULT FALSE,
    max_crypto_staleness REAL DEFAULT 300.0,
    max_sentiment_staleness REAL DEFAULT 600.0,
    max_debate_staleness REAL DEFAULT 900.0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    FOREIGN KEY (market_ticker) REFERENCES kalshi_markets(market_ticker)
);
```

## API Endpoints

### Management Endpoints
- `GET /api/v1/kalshi/wiring/status` - Overall system status
- `GET /api/v1/kalshi/wiring/health` - Component health checks
- `POST /api/v1/kalshi/wiring/sync/full` - Trigger full synchronization

### Market Information
- `GET /api/v1/kalshi/wiring/markets` - List markets with filtering
- `GET /api/v1/kalshi/wiring/markets/{ticker}` - Market details
- `GET /api/v1/kalshi/wiring/markets/{ticker}/context` - Market context
- `GET /api/v1/kalshi/wiring/markets/{ticker}/safety` - Safety checks

### Mapping and Coverage
- `GET /api/v1/kalshi/wiring/mappings` - Market mappings
- `GET /api/v1/kalshi/wiring/coverage` - Coverage report
- `POST /api/v1/kalshi/wiring/coverage/check` - Trigger coverage check

### Symbol-Specific
- `GET /api/v1/kalshi/wiring/symbols/{symbol}/markets` - Markets for underlying symbol
- `GET /api/v1/kalshi/wiring/stats` - Comprehensive statistics

## Safety Workflow

### 1. Market Discovery
```python
# Universe sync discovers all open markets
open_markets = await kalshi_client.get_markets(status="open")
for market in open_markets:
    store.upsert_market(parse_market_data(market))
```

### 2. Mapping Creation
```python
# Automatic mapping rules applied
for market in open_markets:
    if matches_crypto_pattern(market):
        mapping = create_crypto_mapping(market)
    elif matches_election_pattern(market):
        mapping = create_election_mapping(market)
    # ... other patterns
    store.upsert_mapping(mapping)
```

### 3. Safety Validation
```python
# Before signal generation
safety_check = safety_layer.perform_safety_check(market_ticker)
if not safety_check.safe_to_trade:
    # Skip or suppress signal
    return None
```

### 4. Signal Generation
```python
# Only for safe markets
if safety_check.safe_to_trade:
    context = get_market_context(market_ticker)
    signal = generate_enhanced_signal(context, safety_check)
    return signal
```

### 5. Execution Validation
```python
# Before order execution
execution_check = safety_layer.check_risk_limits(market, proposed_notional)
if not execution_check.passes_risk_limits:
    # Reject or resize order
    return None
```

## Coverage Enforcement

### Automatic Coverage Check
```python
# Runs hourly
coverage_report = coverage_checker.check_coverage()

# Alerts on gaps
if coverage_report.coverage_percentage < 95.0:
    alert("Low market coverage")

# Auto-disables unmapped markets
if config.auto_disable_unmapped:
    for ticker in coverage_report.unmapped_market_tickers:
        store.update_market_status(ticker, MarketStatus.CLOSED)
```

### Manual Override Support
```json
// manual_overrides.json
{
  "KXBTCD-25JUN-T100000": {
    "underlying_symbol": "BTC",
    "merid_symbol": "BTC",
    "risk_profile": "crypto_linked",
    "enabled": true,
    "max_notional_per_trade": 200.0
  }
}
```

## Integration with Existing Systems

### Enhanced Kalshi Generator
```python
# Old approach (removed)
symbol = extract_symbol_from_kalshi_ticker(ticker)
crypto_features = get_crypto_features(symbol)

# New approach (wiring layer)
context = wiring_integration.get_context_for_market(ticker)
if not context or not context.safe_to_trade:
    return None  # Market disabled or unsafe
```

### CQI System Extension
```python
# Segment-based CQI
cqi_value = get_cqi(domain="prediction", segment="prediction_crypto_linked")
if cqi_value < 0.3:
    # Suppress crypto-linked signals
    return GatingDecision.SUPPRESS
```

### Execution Bridge Integration
```python
# Per-market risk caps
market = store.get_market(signal.market_ticker)
if signal.notional > market.max_notional_per_trade:
    signal.notional = market.max_notional_per_trade
```

## Deployment and Operations

### Environment Configuration
```bash
# Sync intervals
KALSHI_SYNC_INTERVAL_SECONDS=900
COVERAGE_CHECK_INTERVAL_SECONDS=3600

# Auto-enable rules
KALSHI_AUTO_ENABLE_CRYPTO=true
KALSHI_AUTO_ENABLE_MACRO=true
KALSHI_AUTO_ENABLE_ELECTIONS=true
KALSHI_AUTO_ENABLE_EQUITY=false

# Coverage thresholds
KALSHI_ALERT_UNMAPPED_THRESHOLD=0.05
KALSHI_ALERT_DISABLED_THRESHOLD=0.10
```

### Service Startup
```python
# Start wiring services
orchestrator = await get_kalshi_wiring_orchestrator()
await orchestrator.start_wiring_services()

# Perform initial sync
await orchestrator.perform_full_sync()
```

### Monitoring
```python
# Health checks
health = await orchestrator.health_check()
if health["overall"] != "healthy":
    alert("Wiring system unhealthy")

# Coverage monitoring
coverage = orchestrator.get_latest_report()
if coverage.coverage_percentage < 95.0:
    alert("Market coverage below threshold")
```

## Benefits

### 1. Complete Coverage
- **Zero dark markets**: Every open Kalshi market is tracked
- **Explicit policies**: Clear enable/disable reasons
- **Automated discovery**: No manual market list maintenance

### 2. Strong Safety
- **Data freshness**: Stale data automatically suppresses signals
- **Risk limits**: Per-market caps prevent concentration
- **Quality gating**: Segment-based CQI protects against model issues

### 3. Operational Excellence
- **Complete visibility**: Full audit trail and monitoring
- **Manual overrides**: Fine-grained control when needed
- **Automated operations**: Minimal manual intervention required

### 4. Scalability
- **Independent services**: Sync, mapping, and coverage run separately
- **Database optimization**: Efficient queries with proper indexing
- **API integration**: Easy integration with existing systems

## Migration Path

### Phase 1: Deployment
1. Deploy database schema
2. Start wiring services
3. Perform initial universe sync
4. Validate mappings and coverage

### Phase 2: Integration
1. Update Enhanced Kalshi Generator
2. Wire in safety checks to execution
3. Extend CQI with segments
4. Update monitoring dashboards

### Phase 3: Validation
1. Run in shadow mode with existing system
2. Compare signal generation results
3. Validate safety check effectiveness
4. Cut over to wiring layer

### Phase 4: Optimization
1. Tune mapping rules based on performance
2. Adjust risk caps and CQI thresholds
3. Optimize sync intervals and caching
4. Expand to additional market types

This comprehensive market wiring layer ensures that MERID can safely and effectively trade Kalshi prediction markets with complete coverage, explicit mappings, and strong safety constraints.
