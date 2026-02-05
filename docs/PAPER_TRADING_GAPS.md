# Paper Trading System - Gap Analysis & Enhancement Plan

## Current State Assessment

### ✅ Existing Features
- Basic order execution (market, limit, stop-loss)
- Position tracking with P&L calculation
- Portfolio management with balance tracking
- Trade history recording
- Real-time price updates via live feed
- Risk controller integration
- Telemetry/event system

### ❌ Identified Gaps

#### 1. **No UI for Paper Trading Positions**
**Impact:** High  
**Description:** Users cannot view their paper trading positions, orders, or P&L in the UI.

**Required:**
- PaperTradingPanel.tsx component
- Real-time position updates
- Order book visualization
- P&L charts

---

#### 2. **Missing Prediction Market Paper Trading**
**Impact:** High  
**Description:** Prediction market orders don't properly integrate with SimulationPredictionAggregator.

**Current Issue:**
```python
# Line 437-438: Simplified prediction market pricing
current_price = order.price or 0.5
```

**Required:**
- Integration with SimulationPredictionAggregator
- Real probability-based pricing from Polymarket/Augur
- Outcome resolution tracking
- Brier score integration for prediction accuracy

---

#### 3. **No Order Management UI**
**Impact:** Medium  
**Description:** Cannot cancel pending orders, modify orders, or view order status.

**Required:**
- Order list with status
- Cancel order functionality
- Modify order functionality
- Order history with filters

---

#### 4. **Limited Performance Analytics**
**Impact:** Medium  
**Description:** Basic stats exist but no detailed analytics dashboard.

**Current Stats:**
- Total P&L
- Win/loss count
- Trade count

**Missing:**
- Sharpe ratio
- Max drawdown
- Win rate percentage
- Average win/loss size
- Risk-adjusted returns
- Trade duration analysis
- Asset-wise performance breakdown

---

#### 5. **No Backtesting Integration**
**Impact:** Medium  
**Description:** Paper trading doesn't connect to historical data for strategy testing.

**Required:**
- Historical price replay
- Fast-forward simulation
- Strategy comparison
- Performance attribution

---

#### 6. **Missing Multi-User Support**
**Impact:** Low  
**Description:** System supports multiple users but no UI for user selection/management.

**Required:**
- User portfolio selector
- Leaderboard
- Competition mode
- Portfolio comparison

---

#### 7. **No Stop-Loss/Take-Profit Automation**
**Impact:** Medium  
**Description:** Stop-loss orders exist but aren't automatically triggered.

**Current Issue:**
```python
# Line 426: Pending orders not checked against price movements
portfolio.orders[order_id] = order
```

**Required:**
- Price monitoring loop
- Automatic order triggering
- Trailing stop-loss
- OCO (One-Cancels-Other) orders

---

#### 8. **Missing Risk Metrics Integration**
**Impact:** Medium  
**Description:** Paper trading doesn't show risk metrics like position sizing, exposure, etc.

**Required:**
- Real-time exposure calculation
- Position size recommendations
- Risk/reward ratio display
- Kelly Criterion calculator

---

#### 9. **No Trade Simulation Controls**
**Impact:** High  
**Description:** Cannot control simulation speed, pause/resume, or reset.

**Required:**
- Simulation control panel
- Speed controls (1x, 10x, 100x)
- Pause/resume functionality
- Reset portfolio
- Save/load simulation state

---

#### 10. **Missing WebSocket Real-Time Updates**
**Impact:** Medium  
**Description:** UI would need to poll for updates instead of receiving real-time pushes.

**Required:**
- WebSocket endpoint for paper trading events
- Real-time position updates
- Live order status changes
- P&L streaming

---

## Implementation Priority

### Phase 1: Critical UI Components (High Priority)
1. **PaperTradingPanel.tsx** - Main dashboard
2. **Simulation Control Panel** - Start/stop/reset controls
3. **WebSocket Integration** - Real-time updates

### Phase 2: Core Functionality (High Priority)
4. **Prediction Market Integration** - SimulationPredictionAggregator
5. **Stop-Loss Automation** - Auto-trigger pending orders
6. **Order Management UI** - Cancel/modify orders

### Phase 3: Analytics & Enhancement (Medium Priority)
7. **Performance Analytics Dashboard** - Detailed metrics
8. **Risk Metrics Display** - Exposure, position sizing
9. **Trade History Visualization** - Charts and filters

### Phase 4: Advanced Features (Low Priority)
10. **Backtesting Integration** - Historical replay
11. **Multi-User Features** - Leaderboard, competitions
12. **Advanced Order Types** - Trailing stops, OCO

---

## Technical Specifications

### API Endpoints Needed

```python
# Paper Trading Control
POST /api/v1/paper-trading/start
POST /api/v1/paper-trading/stop
POST /api/v1/paper-trading/reset
POST /api/v1/paper-trading/speed/{multiplier}

# Order Management
GET /api/v1/paper-trading/orders
POST /api/v1/paper-trading/orders/{order_id}/cancel
PUT /api/v1/paper-trading/orders/{order_id}/modify

# Analytics
GET /api/v1/paper-trading/analytics/performance
GET /api/v1/paper-trading/analytics/risk-metrics
GET /api/v1/paper-trading/analytics/trade-history

# WebSocket
WS /ws/paper-trading
```

### Database Schema Extensions

```sql
-- Trade history with more metadata
ALTER TABLE paper_trades ADD COLUMN strategy_id TEXT;
ALTER TABLE paper_trades ADD COLUMN tags TEXT[];
ALTER TABLE paper_trades ADD COLUMN notes TEXT;

-- Performance snapshots
CREATE TABLE paper_performance_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    balance REAL NOT NULL,
    total_pnl REAL NOT NULL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    win_rate REAL
);
```

---

## UI Component Specifications

### PaperTradingPanel.tsx

**Sections:**
1. **Portfolio Summary**
   - Current balance
   - Total P&L ($ and %)
   - Open positions count
   - Pending orders count

2. **Open Positions Table**
   - Asset, Side, Size, Entry Price, Current Price
   - Unrealized P&L ($ and %)
   - Leverage, Duration
   - Close button

3. **Pending Orders Table**
   - Asset, Type, Side, Size, Price
   - Status, Created At
   - Cancel/Modify buttons

4. **Trade History**
   - Recent trades with P&L
   - Filters by asset, date, outcome
   - Export functionality

5. **Performance Charts**
   - Balance over time
   - P&L distribution
   - Win/loss ratio pie chart

---

### SimulationControlPanel.tsx

**Controls:**
1. **Playback Controls**
   - Play/Pause button
   - Speed selector (1x, 10x, 100x, 1000x)
   - Reset button

2. **Time Controls**
   - Current simulation time
   - Jump to date
   - Fast-forward to next event

3. **Scenario Selection**
   - Load historical period
   - Select market conditions
   - Custom price data upload

4. **State Management**
   - Save simulation state
   - Load saved state
   - Export results

---

## Integration Points

### 1. SimulationPredictionAggregator Integration

```python
# In paper_trading.py
def _execute_prediction_order(self, order: PaperOrder):
    from monitoring.simulation_prediction_markets import get_simulation_aggregator
    
    aggregator = get_simulation_aggregator()
    markets = aggregator.get_all_markets()
    
    # Find matching market
    market = next((m for m in markets if m['market_id'] == order.market_id), None)
    
    if market:
        # Use real probability as price
        current_price = market['yes_price'] if order.side == 'yes' else market['no_price']
        order.fill_price = current_price
        # ... execute order
```

### 2. WebSocket Event Stream

```python
# In web/main.py
@root_router.websocket("/ws/paper-trading")
async def paper_trading_websocket(websocket: WebSocket):
    await websocket.accept()
    engine = get_paper_trading_engine()
    
    def on_trade(event):
        asyncio.create_task(websocket.send_json(event))
    
    unsubscribe = engine._subscribe("trade", on_trade)
    
    try:
        while True:
            await asyncio.sleep(1)
    finally:
        unsubscribe()
```

### 3. Automatic Stop-Loss Triggering

```python
# In paper_trading.py
def _check_pending_orders(self):
    """Check if any pending orders should be triggered."""
    for portfolio in self.portfolios.values():
        for order_id, order in list(portfolio.orders.items()):
            if order.order_type == PaperOrderType.STOP_LOSS:
                current_price = self.current_prices.get(order.asset, 0)
                
                if order.side == "long" and current_price <= order.stop_price:
                    self._execute_order(order, portfolio)
                    del portfolio.orders[order_id]
                elif order.side == "short" and current_price >= order.stop_price:
                    self._execute_order(order, portfolio)
                    del portfolio.orders[order_id]
```

---

## Success Metrics

### Functionality
- [ ] All 10 gaps addressed
- [ ] UI components render without errors
- [ ] Real-time updates working
- [ ] Order execution < 100ms latency

### User Experience
- [ ] Intuitive navigation
- [ ] Clear P&L visualization
- [ ] Responsive on mobile
- [ ] Accessible (WCAG 2.1 AA)

### Performance
- [ ] Handle 1000+ trades without lag
- [ ] WebSocket < 50ms latency
- [ ] Chart rendering < 200ms
- [ ] API responses < 100ms

---

## Next Steps

1. Create PaperTradingPanel.tsx component
2. Add WebSocket endpoint for paper trading
3. Integrate SimulationPredictionAggregator
4. Implement automatic order triggering
5. Create SimulationControlPanel.tsx
6. Add performance analytics API
7. Build trade history visualization
8. Add risk metrics display
9. Implement backtesting integration
10. Add multi-user features

---

## Dependencies

- `web/react/src/components/PaperTradingPanel.tsx` (new)
- `web/react/src/components/SimulationControlPanel.tsx` (new)
- `web/api/paper_trading.py` (enhance)
- `trading/paper_trading.py` (enhance)
- `monitoring/simulation_prediction_markets.py` (integrate)
- WebSocket infrastructure (existing)
