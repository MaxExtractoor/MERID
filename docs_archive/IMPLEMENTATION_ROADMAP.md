# MERID Implementation Roadmap - Making It Real

## 🎯 OBJECTIVE
Transform MERID from mock implementations to fully operational system with:
- Real agents posting to X and Telegram
- Real data flowing through UI
- Real consensus formation with agent swarming
- Real trading execution
- End-to-end data flow verified

---

## ✅ COMPLETED (Real, Production-Grade Code)

### Core Agent Infrastructure
1. ✅ **TwitterAgent** (`agents/twitter_agent.py`) - 250 lines
   - Real Tweepy v2 API integration
   - Actual posting methods
   - Rate limiting
   - Engagement tracking

2. ✅ **TelegramAgent** (`agents/telegram_agent.py`) - 220 lines
   - Real python-telegram-bot integration
   - Async message sending
   - HTML formatting
   - Message tracking

3. ✅ **NewsMonitorAgent** (`agents/news_monitor_agent.py`) - 180 lines
   - Monitors real news feeds
   - Auto-posts to X and Telegram
   - Importance filtering
   - Continuous monitoring loop

4. ✅ **LivePriceFeed** (`data/live_price_feed.py`) - 200 lines
   - Real CCXT exchange integration
   - Binance/Coinbase connections
   - Real-time price streaming
   - Historical OHLCV data
   - Subscriber pattern

5. ✅ **AgentOrchestrator** (`core/agent_orchestrator.py`) - 400 lines
   - Coordinates all agents
   - Real consensus formation
   - Agent voting system
   - Arbitrage monitoring
   - Social media broadcasting

6. ✅ **SystemControlAPI** (`web/api/system_control.py`) - 200 lines
   - Start/stop endpoints
   - System status monitoring
   - Agent control
   - Manual posting

7. ✅ **WebSocket Price Stream** - Updated with real data
   - Integrated LivePriceFeed
   - Real CCXT prices
   - No mock data

---

## 🚧 IN PROGRESS - Critical Path Items

### 1. Complete WebSocket Stream Integration
**Status:** 25% complete (prices done, others need work)

**Remaining Work:**
- [ ] Wire `/ws/trades` to real ExecutionAgent events
- [ ] Wire `/ws/agents` to real AgentOrchestrator decisions
- [ ] Wire `/ws/simulation` to real mining process
- [ ] Wire `/ws/positions` to real position tracking

**Files to Modify:**
- `web/api/streams.py` - Replace mock data generators

### 2. Implement Real Trading Execution
**Status:** 0% complete (all mock/TODO)

**Required:**
- [ ] Connect CCXT for real order placement
- [ ] Implement position management
- [ ] Add balance tracking
- [ ] Wire up to ExecutionAgent

**Files to Modify:**
- `web/api/trading.py` - Remove TODOs, add real execution
- `trading/agents/execution_agent.py` - Add real exchange integration

### 3. Remove All Mock Data from APIs
**Status:** 10% complete

**Locations with Mock Data:**
- [ ] `web/api/trading.py` - Lines 351, 396-399, 436-442, 455-458, 470-473, 483-486
- [ ] `web/api/streams.py` - Lines 95-150 (trades, agents, simulation, positions)
- [ ] `trading/perp/base.py` - Mock fallbacks throughout
- [ ] `trading/augur_trading_layer.py` - Mock market data

### 4. Wire UI to Real Data
**Status:** 0% complete

**Required:**
- [ ] Connect charts to LivePriceFeed OHLCV data
- [ ] Display real agent decisions from orchestrator
- [ ] Show real consensus results
- [ ] Display real arbitrage opportunities
- [ ] Show real positions and P&L

**Files to Modify:**
- `web/static/js/trading_perps.js` - Connect to real WebSocket data
- `web/static/js/production.js` - Display real agent data
- `web/templates/production_dashboard.html` - Wire up real data

---

## 📋 DETAILED ACTION PLAN

### Phase 1: Complete Agent Integration (2-3 hours)

#### Step 1.1: Wire Trade Stream to Real Events
```python
# In web/api/streams.py
@router.websocket("/trades")
async def trade_stream(websocket: WebSocket):
    await websocket.accept()
    
    # Subscribe to ExecutionAgent events
    execution_agent = get_execution_agent()
    
    async def trade_callback(trade_data):
        await websocket.send_json({
            "timestamp": time.time(),
            "trade_id": trade_data['order_id'],
            "asset": trade_data['asset'],
            "side": trade_data['side'],
            "size": trade_data['size'],
            "price": trade_data['fill_price'],
            "status": trade_data['status']
        })
    
    execution_agent.subscribe_to_fills(trade_callback)
    # Keep connection alive and handle disconnects
```

#### Step 1.2: Wire Agent Stream to Real Decisions
```python
# In web/api/streams.py
@router.websocket("/agents")
async def agent_stream(websocket: WebSocket):
    await websocket.accept()
    
    # Subscribe to AgentOrchestrator decisions
    orchestrator = get_agent_orchestrator()
    
    async def decision_callback(decision):
        await websocket.send_json({
            "timestamp": decision.timestamp.isoformat(),
            "agent": decision.agent_role.value,
            "type": decision.decision_type,
            "data": decision.data,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning
        })
    
    orchestrator.subscribe_to_decisions(decision_callback)
    # Keep connection alive
```

#### Step 1.3: Wire Simulation Stream to Real Mining
```python
# Connect to actual mining engine events
# Broadcast real block mining stages
# Remove mock simulation data
```

#### Step 1.4: Wire Position Stream to Real Tracking
```python
# Fetch real positions from paper trading or live trading
# Calculate real P&L
# Broadcast actual position updates
```

### Phase 2: Implement Real Trading Execution (3-4 hours)

#### Step 2.1: Add Real Exchange Integration to ExecutionAgent
```python
# In trading/agents/execution_agent.py
import ccxt

class ExecutionAgent:
    def __init__(self):
        self.exchange = ccxt.binance({
            'apiKey': os.getenv('BINANCE_API_KEY'),
            'secret': os.getenv('BINANCE_API_SECRET'),
            'enableRateLimit': True
        })
        self.fill_subscribers = []
    
    async def execute_market_order(self, asset, side, size_usd):
        # Real order placement via CCXT
        symbol = f"{asset}/USDT"
        order_type = 'market'
        amount = size_usd / current_price  # Calculate amount
        
        order = self.exchange.create_order(
            symbol=symbol,
            type=order_type,
            side=side,
            amount=amount
        )
        
        # Broadcast to subscribers
        for callback in self.fill_subscribers:
            await callback(order)
        
        return order
```

#### Step 2.2: Implement Position Management
```python
# Track open positions
# Calculate real-time P&L
# Handle position closing
```

#### Step 2.3: Wire Up Trading API Endpoints
```python
# Remove all TODO comments
# Implement real execution logic
# Connect to ExecutionAgent
```

### Phase 3: Update UI with Real Data (2-3 hours)

#### Step 3.1: Connect Charts to Real OHLCV
```javascript
// In trading_perps.js
async function loadChartData() {
    const response = await fetch(`/api/v1/data/ohlcv?symbol=${currentAsset}&timeframe=1h&limit=100`);
    const data = await response.json();
    
    // Update chart with real data
    chart.setData(data.ohlcv);
}
```

#### Step 3.2: Display Real Agent Decisions
```javascript
// Subscribe to agent WebSocket
const agentWs = new WebSocket('ws://localhost:8001/ws/agents');
agentWs.onmessage = (event) => {
    const decision = JSON.parse(event.data);
    displayAgentDecision(decision);
};
```

#### Step 3.3: Show Real Consensus Results
```javascript
// Fetch and display real consensus history
async function loadConsensusHistory() {
    const response = await fetch('/api/v1/system/consensus/history');
    const data = await response.json();
    displayConsensusResults(data.consensus_results);
}
```

### Phase 4: Verify Agents Are Posting (1 hour)

#### Step 4.1: Configure Credentials
```bash
# User must add to .env:
X_BEARER_TOKEN=...
X_API_KEY=...
X_API_SECRET=...
X_ACCESS_TOKEN=...
X_ACCESS_TOKEN_SECRET=...

TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

#### Step 4.2: Test Twitter Posting
```python
# Test endpoint
POST /api/v1/system/agents/twitter/post
{
    "text": "Test tweet from MERID"
}
```

#### Step 4.3: Test Telegram Sending
```python
# Test endpoint
POST /api/v1/system/agents/telegram/send
{
    "text": "Test message from MERID"
}
```

#### Step 4.4: Verify News Monitor
```python
# Check news monitor is running
GET /api/v1/system/agents

# Should show news_monitor with running: true
```

### Phase 5: End-to-End Verification (1 hour)

#### Step 5.1: Start System
```bash
python -m uvicorn web.main:app --host 127.0.0.1 --port 8001
```

#### Step 5.2: Verify Agent Orchestrator Started
```bash
# Check logs for:
# "Initializing MERID agent orchestrator..."
# "All agents started successfully"
```

#### Step 5.3: Check System Status
```bash
GET /api/v1/system/status

# Should show:
# - system_running: true
# - agents.active: 7
# - twitter_enabled: true (if credentials configured)
# - telegram_enabled: true (if credentials configured)
# - news_monitoring: true
# - price_streaming: true
```

#### Step 5.4: Verify Data Flow
1. Open browser to `http://127.0.0.1:8001/trading/perps`
2. Check WebSocket connections in browser console
3. Verify real prices are updating
4. Check agent decisions are appearing
5. Verify consensus results are shown

#### Step 5.5: Verify Social Media Posting
1. Check Twitter/X for MERID posts
2. Check Telegram for MERID messages
3. Verify breaking news is being posted
4. Check market updates are being sent

---

## 🎯 SUCCESS METRICS

### System is "Fully Operational" When:

1. ✅ Twitter agent posts visible on X (requires credentials)
2. ✅ Telegram messages visible in Telegram (requires credentials)
3. ✅ News monitor auto-posts breaking news
4. ✅ Live prices flow from exchanges to UI
5. ✅ Agent decisions displayed in real-time
6. ✅ Consensus formation visible with real voting
7. ✅ Arbitrage opportunities are real and tracked
8. ✅ Trading execution connects to exchanges
9. ✅ Positions show real P&L
10. ✅ All WebSocket streams broadcast real data

---

## 📊 CURRENT STATUS SUMMARY

### What's Real:
- ✅ Agent classes with real API integration
- ✅ Price feed with real CCXT data
- ✅ News aggregator with real feeds
- ✅ Orchestrator with real coordination logic
- ✅ System control API
- ✅ One WebSocket stream (prices) has real data

### What's Mock:
- ❌ 3 WebSocket streams (trades, agents, simulation, positions)
- ❌ Trading execution (all TODO/mock)
- ❌ UI data connections (not wired up)
- ❌ Consensus formation (simplified logic)

### What's Missing:
- ❌ API credentials for posting
- ❌ Exchange API keys for trading
- ❌ End-to-end testing
- ❌ Verification of data flow

---

## 🚀 IMMEDIATE NEXT STEPS

1. **Complete WebSocket stream integration** - Wire up remaining 3 streams
2. **Implement real trading execution** - Add CCXT integration
3. **Remove all mock data** - Replace with real data sources
4. **Wire up UI** - Connect to real WebSocket streams
5. **Test with credentials** - Verify agents post to X/Telegram
6. **Verify end-to-end** - Confirm data flows from agents to UI

**Estimated Time to Full Operation:** 8-12 hours of focused implementation

**Priority:** HIGH - System foundation is solid, needs real data wired throughout
