# Sentiment/Mood Hooks Audit — 15m Kalshi Crypto Path

## Classification Key
- **SAFE TELEMETRY**: Logging, metrics, metadata fields that don't block execution
- **EXECUTION-PATH DEPENDENCY**: Awaited calls in hot path, startup dependencies, gates that block trading
- **ZOMBIE CODE**: Unused imports, dead services, commented code

---

## P0 CRITICAL: Execution-Path Dependencies (Must Remove)

### 1. agent_grid.py — Startup/Shutdown Blocking Sentiment
**File**: `merid/prediction/agent_grid.py`
**Lines**: 647, 653, 1085, 1088

**Issue**: Agent grid startup and shutdown await sentiment services
```python
# Line 647 - STARTUP BLOCKER
await self._sentiment.start()

# Line 653 - STARTUP BLOCKER  
await self._mood_bus.start()

# Line 1085 - SHUTDOWN BLOCKER
await self._sentiment.stop()

# Line 1088 - SHUTDOWN BLOCKER
await self._mood_bus.stop()
```

**Impact**: Blocks agent grid from starting/stopping if sentiment services fail or hang
**Fix Required**: Remove these awaits or make them non-blocking background tasks with try/except

---

### 2. crypto15m_lane.py — Sentiment Aggregation in Hot Path
**File**: `merid/lanes/crypto15m_lane.py`
**Lines**: 828, 831, 834, 928, 948

**Issue**: Despite docstring saying "DISABLED for lean 15m", the hot path still awaits sentiment
```python
# Line 828 - HOT PATH BLOCKER
sentiment_bundle = await self._aggregate_sentiment()

# Line 831 - HOT PATH (uses sentiment_bundle)
consensus = await self._get_consensus(markets, sentiment_bundle)

# Line 834 - HOT PATH (uses sentiment_bundle)
risk_decision = await self._evaluate_risk(consensus, sentiment_bundle)

# Line 928 - Called inside _aggregate_sentiment when ENABLE_SENTIMENT_TRUTH=true
asset_sentiment = await self._get_asset_sentiment_15m()

# Line 948 - Duplicate call inside _aggregate_sentiment
asset_sentiment = await self._get_asset_sentiment_15m()
```

**Feature Flag Check** (lines 907-924):
```python
enable_sentiment = os.getenv("ENABLE_SENTIMENT_TRUTH", "false").lower() == "true"
if not enable_sentiment:
    return {neutral_baseline}  # Early return, but...
```

**Problem**: Even with the feature flag, the function is still called and awaited in the hot path. The early return helps, but:
1. The await still happens every cycle
2. If someone sets ENABLE_SENTIMENT_TRUTH=true, it immediately re-enables blocking sentiment calls
3. No guarantee that sentiment failures won't bubble up

**Impact**: Every 15m trading cycle blocks on sentiment aggregation
**Fix Required**: 
- Remove sentiment_bundle from consensus and risk evaluation entirely
- Remove the await from the hot path
- Make sentiment purely optional telemetry if it exists

---

### 3. crypto15m_lane.py — Consensus Uses Sentiment Bundle
**File**: `merid/lanes/crypto15m_lane.py`
**Lines**: 1019-1093 (_get_consensus method)

**Issue**: Consensus logic explicitly uses sentiment_bundle for edge adjustments
```python
# Lines 1030-1040
if sentiment_bundle and "fear_greed" in sentiment_bundle:
    fg = sentiment_bundle["fear_greed"]
    edge_adjustment = fg["contrarian_signal"] * sentiment_bundle.get("weight", 0.5)

if sentiment_bundle and "asset_sentiment_15m" in sentiment_bundle:
    asset = sentiment_bundle["asset_sentiment_15m"]
    asset_score = asset.get("sentiment_score_15m", 0.5)
    asset_adj = (asset_score - 0.5) * 0.3  # Scale down asset sentiment impact
```

**Impact**: Edge computation depends on sentiment data, violating the target contract
**Fix Required**: Remove all sentiment-based edge adjustments from consensus

---

### 4. crypto15m_lane.py — Risk Evaluation Uses Sentiment Bundle
**File**: `merid/lanes/crypto15m_lane.py`
**Lines**: 1129-1281 (_evaluate_risk method)

**Issue**: Risk logic uses sentiment_bundle for fear/greed adjustments
```python
# Lines 1219-1220
if sentiment_bundle and "fear_greed" in sentiment_bundle:
    fg = sentiment_bundle["fear_greed"]

# Lines 1242, 1281
"fear_greed_applied": sentiment_bundle is not None,
"sentiment_weight": consensus.get("sentiment_weight", 0.0),
```

**Impact**: Risk decisions depend on sentiment, violating the target contract
**Fix Required**: Remove sentiment from risk evaluation logic

---

## P1 HIGH: Trading Agent Sentiment Enrichment

### 5. trading_agent.py — Snapshot Sentiment Injection
**File**: `merid/prediction/trading_agent.py`
**Lines**: 5753-5809

**Issue**: Snapshot enrichment injects sentiment data with age gating
```python
from merid.event_venues.kalshi.sentiment import get_sentiment_service
svc = get_sentiment_service()
local_s = svc.get_local_sentiment(market.market_id)
cat_s = svc.get_category_sentiment(market.category)
glob_s = svc.get_global_sentiment()

# Age gating check
if _age_s > _MAX_SENTIMENT_AGE_S:
    # Skip injection
else:
    snapshot.sentiment_local = local_s.score
    snapshot.sentiment_category = cat_s.score
    snapshot.sentiment_global = glob_s.score
    snapshot.sentiment_regime = local_s.regime if local_s else glob_s.regime
    snapshot.sentiment_age_seconds = _age_s
    snapshot.sentiment_adjusted = True
```

**Impact**: Every snapshot tries to fetch sentiment, potentially blocking
**Fix Required**: Remove sentiment enrichment from snapshot creation

---

### 6. trading_agent.py — Strategy Uses Sentiment
**File**: `merid/prediction/trading_agent.py`
**Lines**: 8384-8418

**Issue**: Strategy uses sentiment_score from snapshot at capped weight
```python
sent_score = getattr(snapshot, "sentiment_global", None)
if sent_score is not None:
    ctx["sentiment_score"] = float(sent_score) / 50.0 - 1.0
```

**Impact**: Strategy decisions use sentiment as a feature
**Fix Required**: Remove sentiment from strategy context

---

## P2 MEDIUM: Config Fields and Telemetry (Documented as Legacy)

### 7. trading_agent.py — Sentiment Config Fields
**File**: `merid/prediction/trading_agent.py`
**Lines**: 134, 138, 2129-2135

**Status**: LEGACY - Documented, not used in 15m crypto path

**Config fields**:
```python
("MERID_PM_CONTRARIAN_SENTIMENT_MIN", "contrarian_sentiment_min"),
("MERID_SENTIMENT_MODE", "sentiment_mode"),
```

**Resolution**: These config fields are read and logged for audit trail but are NOT used for execution gating in the 15m crypto path. They remain for backward compatibility with other profiles that may use sentiment. Per SENTIMENT_ISOLATION_15M.md, 15m crypto execution is sentiment-free.

---

### 8. trading_agent.py — Sentiment Metadata Fields
**File**: `merid/prediction/trading_agent.py`
**Lines**: 2530-2532, 4753, 4869, 6826-6831, 7217, 7517

**Status**: LEGACY TELEMETRY - Documented, not used for execution decisions

**Metadata fields**:
```python
sentiment_driven=signal.metadata.get('sentiment_driven', False),
sentiment_asset=signal.metadata.get('sentiment_asset'),
sentiment_timeframe=signal.metadata.get('sentiment_timeframe'),
```

**Resolution**: These are telemetry fields for historical analysis and debugging. They do NOT affect execution decisions (enter/size/side/exit) in the 15m crypto path. Per SENTIMENT_ISOLATION_15M.md, sentiment may be logged as telemetry but must not control execution.

---

## Files with Sentiment References (Non-Blocking)

### merid/prediction/forecasters/sentiment.py
- Entire module is sentiment forecaster
- Status: SAFE TELEMETRY (if not used in hot path)

### merid/event_venues/kalshi/sentiment.py
- Kalshi-specific sentiment service
- Status: ZOMBIE if not called by 15m path

### merid/sentiment/* (entire directory)
- Sentiment bus, scoring, risk engine
- Status: ZOMBIE for 15m path (should be isolated)

### merid/swarm/market_mood_bus.py
- Market mood aggregation
- Status: ZOMBIE for 15m path

---

## Summary of Required Fixes

### P0 (Critical - Blocking)
1. Remove `await self._sentiment.start()` from agent_grid.py startup
2. Remove `await self._mood_bus.start()` from agent_grid.py startup
3. Remove `await self._sentiment.stop()` from agent_grid.py shutdown
4. Remove `await self._mood_bus.stop()` from agent_grid.py shutdown
5. Remove `await self._aggregate_sentiment()` from crypto15m_lane.py hot path
6. Remove sentiment_bundle parameter from `_get_consensus()`
7. Remove sentiment_bundle parameter from `_evaluate_risk()`
8. Remove sentiment-based edge adjustments from consensus logic
9. Remove sentiment-based adjustments from risk evaluation logic

### P1 (High - Data Flow)
10. Remove sentiment enrichment from trading_agent.py snapshot creation
11. Remove sentiment_score from strategy context

### P2 (Medium - Config/Telemetry)
12. Remove or document sentiment config fields as legacy
13. Remove or document sentiment metadata fields as legacy telemetry
