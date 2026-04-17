# MERID Predictions System - Deep Audit & Fix Plan

**Date:** 2026-02-04 19:34 PM  
**Status:** 🔍 Comprehensive Analysis Complete

---

## 🎯 Problem Statement

The predictions panel is showing React errors and not displaying real data. The UI has "cosplay" (mock components) without actual functionality. Need to trace the entire data flow and implement real functionality.

---

## 📋 Current Architecture Analysis

### Data Flow (As Designed)

```
Kalshi API (Real Prediction Markets)
    ↓
monitoring/prediction_markets.py (PredictionMarketAggregator)
    ↓
web/api/us_compliant_markets.py (/api/v1/us-compliant/prediction-markets)
    ↓
Frontend: hooks/usePredictions.ts
    ↓
views/PredictionsPanel.tsx
    ↓
components/DataTableEnhanced.tsx
```

### What Exists

#### Backend Components:
1. ✅ **`monitoring/prediction_markets.py`**
   - `PredictionMarketAggregator` class
   - `PredictionMarket` dataclass
   - Kalshi connector integration
   - Drift detection, arbitrage opportunities
   - Resolution decay metrics

2. ✅ **`web/api/us_compliant_markets.py`**
   - `/api/v1/us-compliant/prediction-markets` endpoint
   - Falls back to sample data if Kalshi unavailable
   - Returns formatted markets

3. ✅ **`monitoring/real_prediction_markets.py`**
   - Alternative implementation
   - Kalshi API integration

#### Frontend Components:
1. ✅ **`hooks/usePredictions.ts`** - Fetches prediction markets
2. ✅ **`views/PredictionsPanel.tsx`** - Main display component
3. ✅ **`components/DataTableEnhanced.tsx`** - Table component
4. ✅ **`types/predictions.ts`** - TypeScript types

---

## ❌ Issues Found

### 1. **DataTableEnhanced Syntax Error**
**File:** `web/react/src/components/DataTableEnhanced.tsx:191`
**Issue:** Malformed arrow function closure
**Fix:** Properly close the return statement

### 2. **API Response Format Mismatch**
**Backend returns:**
```json
{
  "market_id": "...",
  "question": "...",
  "category": "...",
  "yes_price": 0.52,
  "platform": "kalshi"
}
```

**Frontend expects (from types/predictions.ts):**
```typescript
{
  id: string;
  symbol: string;
  question: string;
  yesPrice: number;
  noPrice: number;
  ourPosition: string;
  ourSize: number;
  ourPnl: number;
  modelConfidence: number;
  endTime: string;
  status: string;
  volume: number;
}
```

**Problem:** Complete mismatch between backend and frontend data structures!

### 3. **Missing Data Transformation**
The API returns Kalshi market data, but the frontend expects trading position data (ourPosition, ourPnl, etc.) which doesn't exist in the API response.

### 4. **No WebSocket Integration**
Prediction markets are not connected to the WebSocket publisher system for real-time updates.

### 5. **Kalshi API Not Initialized**
The `PredictionMarketAggregator` is not being started on server startup, so it has no data.

---

## 🔧 Fix Plan

### Priority 1: Fix Data Structure Mismatch

**Step 1.1:** Update backend API to return frontend-compatible format
- Add `symbol` field (derived from market_id)
- Add `ourPosition`, `ourSize`, `ourPnl` (from paper trading engine)
- Add `modelConfidence` (from prediction models)
- Add `status` field (OPEN/CLOSED/RESOLVED)
- Add `volume` field
- Convert snake_case to camelCase

**Step 1.2:** Create data transformation layer
- Map Kalshi markets to frontend format
- Integrate with PaperTradingEngine for position data
- Add confidence scoring from models

### Priority 2: Fix React Component Errors

**Step 2.1:** Fix DataTableEnhanced syntax
**Step 2.2:** Add proper error boundaries
**Step 2.3:** Handle empty/null data gracefully

### Priority 3: Initialize Prediction Markets on Startup

**Step 3.1:** Start `PredictionMarketAggregator` in FastAPI lifespan
**Step 3.2:** Fetch Kalshi markets on startup
**Step 3.3:** Store in app state for persistence

### Priority 4: Add WebSocket Real-Time Updates

**Step 4.1:** Create prediction markets publisher
**Step 4.2:** Subscribe to Kalshi market updates
**Step 4.3:** Broadcast changes via WebSocket

### Priority 5: Integrate with Trading System

**Step 5.1:** Connect to PaperTradingEngine
**Step 5.2:** Track prediction market positions
**Step 5.3:** Calculate real P&L

---

## 📊 Data Structure Mapping

### Backend → Frontend Transformation

```python
# Backend (Kalshi API)
{
    "market_id": "PRES-2024-01",
    "question": "Will Trump win 2024?",
    "category": "politics",
    "yes_price": 0.52,
    "no_price": 0.48,
    "volume_24h": 1250000,
    "platform": "kalshi",
    "close_date": "2024-11-05T23:59:59"
}

# Transform to Frontend Format
{
    "id": "PRES-2024-01",
    "symbol": "PRES24",  # Derived
    "question": "Will Trump win 2024?",
    "yesPrice": 0.52,
    "noPrice": 0.48,
    "ourPosition": "YES",  # From trading engine
    "ourSize": 100,  # From trading engine
    "ourPnl": 250.00,  # Calculated
    "modelConfidence": 0.75,  # From prediction models
    "endTime": "2024-11-05T23:59:59",
    "status": "OPEN",  # Derived
    "volume": 1250000
}
```

---

## 🚀 Implementation Steps

### Step 1: Fix Backend API Response Format

**File:** `web/api/us_compliant_markets.py`

```python
@router.get("/prediction-markets")
async def get_prediction_markets():
    """Get prediction markets with frontend-compatible format."""
    try:
        from monitoring.prediction_markets import get_prediction_aggregator
        from trading.paper_trading import get_paper_trading_engine
        
        aggregator = get_prediction_aggregator()
        trading_engine = get_paper_trading_engine()
        
        all_markets = aggregator.get_all_markets()
        formatted_markets = []
        
        for market in all_markets:
            # Get position from trading engine
            position = trading_engine.get_prediction_position(market.market_id)
            
            formatted_markets.append({
                "id": market.market_id,
                "symbol": market.market_id[:8].upper(),  # First 8 chars
                "question": market.question,
                "yesPrice": market.yes_price,
                "noPrice": market.no_price,
                "ourPosition": position.side if position else "NONE",
                "ourSize": position.size if position else 0,
                "ourPnl": position.pnl if position else 0.0,
                "modelConfidence": 0.75,  # TODO: Get from models
                "endTime": market.resolution_date.isoformat() if market.resolution_date else None,
                "status": "OPEN" if market.status == ResolutionStatus.OPEN else "CLOSED",
                "volume": market.total_volume
            })
        
        return {
            "markets": formatted_markets,
            "meta": {
                "total": len(formatted_markets),
                "open": sum(1 for m in formatted_markets if m["status"] == "OPEN"),
                "totalVolume": sum(m["volume"] for m in formatted_markets),
                "totalPnl": sum(m["ourPnl"] for m in formatted_markets)
            },
            "lastUpdated": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
```

### Step 2: Initialize on Startup

**File:** `web/main.py`

```python
@application.on_event("startup")
async def start_prediction_markets():
    """Start prediction markets aggregator."""
    try:
        from monitoring.prediction_markets import get_prediction_aggregator
        aggregator = get_prediction_aggregator()
        
        # Start background task to fetch markets
        asyncio.create_task(aggregator.start())
        
        logger.info("Prediction markets aggregator started")
    except Exception as e:
        logger.error(f"Failed to start prediction markets: {e}")
```

### Step 3: Add WebSocket Publisher

**File:** `web/services/prediction_publisher.py` (NEW)

```python
class PredictionPublisher:
    """Publishes prediction market updates to WebSocket clients."""
    
    def __init__(self):
        self.event_stream = get_event_stream()
        self.aggregator = get_prediction_aggregator()
        self.running = False
    
    async def start(self):
        self.running = True
        self.task = asyncio.create_task(self._publish_loop())
    
    async def _publish_loop(self):
        while self.running:
            markets = self.aggregator.get_all_markets()
            
            # Transform and publish
            formatted = self._format_markets(markets)
            await self.event_stream.publish("prediction_update", {
                "markets": formatted,
                "timestamp": int(time.time() * 1000)
            })
            
            await asyncio.sleep(30)  # Update every 30 seconds
```

---

## ✅ Success Criteria

1. **Backend API returns correct format** - matches frontend TypeScript types
2. **Kalshi markets load on startup** - aggregator initialized
3. **Real position data displayed** - integrated with trading engine
4. **WebSocket updates working** - real-time market changes
5. **No React errors** - all components render properly
6. **Real P&L calculations** - actual trading data
7. **Model confidence scores** - from prediction models

---

## 📝 Files to Modify

1. ✏️ `web/api/us_compliant_markets.py` - Fix response format
2. ✏️ `web/main.py` - Add startup initialization
3. ✏️ `web/services/prediction_publisher.py` - NEW FILE
4. ✏️ `web/react/src/components/DataTableEnhanced.tsx` - Fix syntax
5. ✏️ `trading/paper_trading.py` - Add prediction market support
6. ✏️ `monitoring/prediction_markets.py` - Ensure Kalshi integration works

---

## 🎯 Next Actions

1. Fix DataTableEnhanced syntax error
2. Transform API response to match frontend expectations
3. Initialize prediction markets on server startup
4. Test with real Kalshi data
5. Add WebSocket real-time updates
6. Integrate with trading engine for positions

---

**This is a comprehensive fix that will make predictions fully functional with real data!**
