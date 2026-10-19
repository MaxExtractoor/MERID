# 15m Crypto Health Dashboard Design

## Objective

Design a health dashboard for Kalshi 15m crypto markets (BTC, ETH, SOL, XRP, DOGE) that surfaces:
- Consensus confidence distribution
- Data-quality flags
- Sentiment telemetry (clearly labeled as non-executing context)

## Design Principle: Reuse Existing Infrastructure

Per the sentiment isolation audit, sentiment is telemetry-only and must not influence execution. This dashboard should visualize existing data without adding new surface area.

## Existing Data Sources

### 1. Consensus Data (Already Exposed)

**Endpoint**: `GET /api/v1/kalshi-grid/crypto/consensus`

**Response Fields**:
- `ticker`: Kalshi ticker (e.g., KXBTC-15M)
- `direction`: bullish/bearish/neutral
- `confidence`: consensus confidence (0-1)
- `vote_count`: number of agent votes
- `bull_weight`: weight of bullish votes
- `bear_weight`: weight of bearish votes
- `agents`: list of contributing agent IDs

**Source**: `kalshi_crypto_signals_api.py:108-148`

### 2. Data Quality Flags (Available in ConsensusForensicLog)

**Location**: `merid/swarm/consensus_forensics.py`

**Fields**:
- `data_quality_flags`: Dict[str, bool] with keys:
  - `orderbook_valid`: True if orderbook data is valid
  - `candle_valid`: True if candle data is valid
  - `price_boundaries_ok`: True if price boundaries are within limits

**Current Status**: Logged to JSONL files in `data/forensics/` but not exposed via API

### 3. Sentiment Telemetry (Available in ConsensusForensicLog)

**Location**: `merid/swarm/consensus_forensics.py`

**Fields**:
- `telemetry_sentiment_score`: Sentiment score (-1 to +1)
- `telemetry_sentiment_source`: Source (news, twitter, etc.)
- `telemetry_sentiment_confidence`: Confidence in sentiment signal
- `telemetry_sentiment_version`: Model/feed version

**Current Status**: Logged to JSONL files in `data/forensics/` but not exposed via API

### 4. Other Relevant Metrics (Already Exposed)

**Endpoint**: `GET /api/v1/kalshi/metrics/hedge`
- Hedge engine metrics and exposure snapshot

**Endpoint**: `GET /api/v1/kalshi/metrics/signal-state`
- TA signal state, regimes, recent decisions

**Endpoint**: `GET /api/v1/kalshi/metrics/cycle-drawdown`
- 15-minute cycle drawdown metrics

## Recommended Implementation: Minimal Surface Area

### Option 1: Extend Existing Consensus Endpoint (Recommended)

Add optional query parameters to `/api/v1/kalshi-grid/crypto/consensus`:

**Query Parameters**:
- `include_data_quality=true` - Include aggregated data quality flags
- `include_sentiment=true` - Include aggregated sentiment telemetry

**Response Extension**:
```json
{
  "signals": [
    {
      "ticker": "KXBTC-15M",
      "direction": "bullish",
      "confidence": 0.65,
      "vote_count": 5,
      "bull_weight": 0.7,
      "bear_weight": 0.3,
      "agents": ["momentum_btc", "mean_reversion_btc"],
      // NEW FIELDS (optional)
      "data_quality": {
        "orderbook_valid": true,
        "candle_valid": true,
        "price_boundaries_ok": true
      },
      "sentiment_telemetry": {
        "score": 0.3,
        "source": "news",
        "confidence": 0.7,
        "version": "v1.0"
      }
    }
  ],
  "count": 5,
  "pending_votes": 2,
  "consensus_rate": 0.8,
  "engine_running": true
}
```

**Implementation**:
- Modify `kalshi_crypto_signals_api.py:get_crypto_consensus_signals()`
- Add query parameter handling
- Aggregate data quality flags from recent forensic logs (last N proposals per ticker)
- Aggregate sentiment telemetry from recent forensic logs (last N proposals per ticker)
- Use `ConsensusForensicsAnalyzer` from `consensus_forensics.py` for aggregation

### Option 2: Separate Forensics Query Endpoint

**Endpoint**: `GET /api/v1/kalshi/forensics/recent`

**Query Parameters**:
- `tickers=KXBTC-15M,KXETH-15M` - Filter by tickers (optional)
- `limit=100` - Number of recent log entries
- `event_type=proposal_submitted` - Filter by event type

**Response**:
```json
{
  "entries": [
    {
      "timestamp": "2026-05-12T21:00:00Z",
      "event_type": "proposal_submitted",
      "asset": "BTC",
      "timeframe": "15m",
      "agent_id": "momentum_btc",
      "data_quality_flags": {
        "orderbook_valid": true,
        "candle_valid": true,
        "price_boundaries_ok": true
      },
      "sentiment_telemetry": {
        "score": 0.3,
        "source": "news",
        "confidence": 0.7,
        "version": "v1.0"
      }
    }
  ],
  "count": 100
}
```

**Implementation**:
- Create new endpoint in `kalshi_metrics_api.py` (aligned with existing metrics endpoints)
- Use `ConsensusForensicsAnalyzer` from `consensus_forensics.py`
- Read from JSONL files in `data/forensics/`

## Dashboard Layout

### Panel 1: Consensus Confidence Distribution

**Data Source**: `/api/v1/kalshi-grid/crypto/consensus`

**Visualization**:
- Bar chart showing confidence per ticker (BTC, ETH, SOL, XRP, DOGE)
- Color-coded by direction (green=bullish, red=bearish, gray=neutral)
- Hover shows vote count, bull/bear weights

### Panel 2: Data Quality Flags

**Data Source**: Extended consensus endpoint or forensics endpoint

**Visualization**:
- Per-ticker status indicators:
  - Orderbook valid (green/red)
  - Candle valid (green/red)
  - Price boundaries ok (green/red)
- Overall health score (percentage of valid flags across all assets)

### Panel 3: Sentiment Telemetry (Research-Only)

**Data Source**: Extended consensus endpoint or forensics endpoint

**Visualization**:
- Sentiment score gauge (-1 to +1) per asset
- Sentiment source breakdown (news vs twitter vs other)
- Sentiment confidence indicator
- **Clear label**: "TELEMETRY ONLY - NOT USED FOR EXECUTION"

### Panel 4: Additional Metrics (Optional)

**Data Sources**: `/api/v1/kalshi/metrics/hedge`, `/api/v1/kalshi/metrics/signal-state`, `/api/v1/kalshi/metrics/cycle-drawdown`

**Visualization**:
- Hedge exposure snapshot
- Market regime status
- Cycle drawdown status

## Implementation Priority

### Phase 1: Minimal Extension (Recommended)
1. Extend `/api/v1/kalshi-grid/crypto/consensus` with `include_data_quality` and `include_sentiment` query parameters
2. Add aggregation logic using `ConsensusForensicsAnalyzer`
3. Update frontend to consume extended response

### Phase 2: Dedicated Forensics Endpoint (Optional)
1. Create `/api/v1/kalshi/forensics/recent` endpoint
2. Add query parameters for filtering
3. Update frontend to query forensics directly

### Phase 3: Dashboard UI (Optional)
1. Create new React component: `Kalshi15mHealthDashboard.tsx`
2. Add to navigation menu
3. Wire to extended consensus endpoint or forensics endpoint

## Security & Isolation

**Critical**: Sentiment telemetry must be clearly labeled as non-executing context in the UI:
- Use a distinct visual style (e.g., gray background, dashed border)
- Add explicit label: "TELEMETRY ONLY - NOT USED FOR EXECUTION DECISIONS"
- Do not place sentiment in the same visual hierarchy as execution-critical data

## Testing

### Unit Tests
- Test extended consensus endpoint with and without query parameters
- Test data quality aggregation logic
- Test sentiment telemetry aggregation logic

### Integration Tests
- Test that extended endpoint returns expected data structure
- Test that forensics endpoint reads from JSONL files correctly
- Test that sentiment telemetry is never used in execution decisions (existing quarantine tests)

### UI Tests
- Test dashboard renders correctly with extended data
- Test that sentiment telemetry is visually distinct
- Test that data quality flags display correctly

## File Changes Required

### Option 1 (Minimal Extension)
- `web/api/kalshi_crypto_signals_api.py` - Extend `get_crypto_consensus_signals()` function
- `merid/swarm/consensus_forensics.py` - Add aggregation methods if needed

### Option 2 (Dedicated Endpoint)
- `web/api/kalshi_metrics_api.py` - Add `/forensics/recent` endpoint

### Option 3 (Dashboard UI)
- `web/react/src/components/Kalshi15mHealthDashboard.tsx` - New component
- `web/react/src/config/constants.ts` - Add endpoint constant
- `web/react/src/types/views.ts` - Add view type

## Recommendation

Start with **Option 1 (Minimal Extension)** to avoid adding new surface area. Extend the existing consensus endpoint with optional query parameters for data quality flags and sentiment telemetry. This reuses existing infrastructure and follows the principle of minimal surface area.
