# MERID State Model - Flow

**Version:** 1.0  
**Date:** January 12, 2026  
**Status:** Data Flow Specification

---

## 🔒 CONSTITUTIONAL CONSTRAINT

> **All flows must operate on state defined in `state-model-core.md` using events defined in `state-model-events.md`**

No flow may bypass the event bus or mutate state directly.

---

## 🌊 SYSTEM BREATHING PATTERN

```
Backend Reality → WebSocket → Event Bus → State Reducer → State Tree → View Subscribers → UI
                                    ↑                                           ↓
                                    └─────────── User Actions ─────────────────┘
```

---

## 📡 WEBSOCKET → EVENT BUS FLOW

### **Connection Architecture**

```javascript
// Two WebSocket connections at top-level scope
const priceWebSocket = new WebSocket('ws://localhost:8000/ws/prices');
const agentWebSocket = new WebSocket('ws://localhost:8000/ws/agents');
```

### **Message Flow**

```
1. WebSocket receives message
2. Parse JSON payload
3. Validate message structure
4. Emit typed event to Event Bus
5. Event Bus validates against schema
6. Reducer applies state mutation
7. Subscribers notified of change
```

### **Price WebSocket Handler**

```javascript
priceWebSocket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    switch (message.type) {
        case 'price_update':
            EventBus.emit('MARKET_PRICE_UPDATE', message.payload);
            break;
        case 'orderbook_update':
            EventBus.emit('MARKET_ORDERBOOK_UPDATE', message.payload);
            break;
        case 'trade':
            EventBus.emit('MARKET_TRADE', message.payload);
            break;
    }
};
```

### **Agent WebSocket Handler**

```javascript
agentWebSocket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    switch (message.type) {
        case 'agent_status':
            EventBus.emit('AGENT_STATUS_CHANGE', message.payload);
            break;
        case 'agent_task':
            EventBus.emit('AGENT_TASK_UPDATE', message.payload);
            break;
        case 'consensus':
            EventBus.emit('CONSENSUS_UPDATE', message.payload);
            break;
        case 'agent_message':
            EventBus.emit('AGENT_MESSAGE', message.payload);
            break;
    }
};
```

### **Reconnection Flow**

```javascript
let reconnectAttempts = 0;
const MAX_RECONNECT = 5;

priceWebSocket.onclose = () => {
    if (reconnectAttempts < MAX_RECONNECT) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
        setTimeout(() => {
            reconnectAttempts++;
            initPriceWebSocket();
        }, delay);
    } else {
        EventBus.emit('SYSTEM_HEALTH_CHANGE', {
            health: 'CRITICAL',
            timestamp: Date.now()
        });
    }
};
```

---

## 🔄 EVENT BUS → STATE FLOW

### **Event Bus Implementation**

```javascript
const EventBus = {
    subscribers: new Map(),
    
    emit(eventType, payload) {
        // 1. Validate payload against schema
        if (!this.validate(eventType, payload)) {
            console.error(`Invalid payload for ${eventType}`, payload);
            return;
        }
        
        // 2. Apply state mutation via reducer
        const newState = StateReducer.reduce(eventType, payload);
        
        // 3. Validate state invariants
        if (!StateValidator.check(newState)) {
            console.error('State invariants violated', newState);
            return;
        }
        
        // 4. Update global state
        MERIDState = newState;
        
        // 5. Notify subscribers
        this.notify(eventType, payload);
    },
    
    subscribe(eventType, callback) {
        if (!this.subscribers.has(eventType)) {
            this.subscribers.set(eventType, []);
        }
        this.subscribers.get(eventType).push(callback);
    },
    
    notify(eventType, payload) {
        const callbacks = this.subscribers.get(eventType) || [];
        callbacks.forEach(cb => cb(payload));
    }
};
```

### **State Reducer Pattern**

```javascript
const StateReducer = {
    reduce(eventType, payload) {
        // Create new state object (immutable)
        const newState = { ...MERIDState };
        
        switch (eventType) {
            case 'MARKET_PRICE_UPDATE':
                return this.reducePriceUpdate(newState, payload);
            case 'AGENT_STATUS_CHANGE':
                return this.reduceAgentStatus(newState, payload);
            // ... other reducers
        }
        
        return newState;
    },
    
    reducePriceUpdate(state, payload) {
        state.markets.prices.set(payload.symbol, {
            symbol: payload.symbol,
            price: payload.price,
            bid: payload.bid,
            ask: payload.ask,
            volume_24h: payload.volume_24h,
            change_24h: payload.change_24h,
            timestamp: payload.timestamp
        });
        state.markets.lastUpdate = payload.timestamp;
        return state;
    }
};
```

---

## 🎨 STATE → UI FLOW

### **View Subscription Pattern**

```javascript
// Each UI component subscribes to relevant state changes
class PriceTickerView {
    constructor(symbol) {
        this.symbol = symbol;
        this.element = document.getElementById(`price-${symbol.toLowerCase()}`);
        
        // Subscribe to price updates
        EventBus.subscribe('MARKET_PRICE_UPDATE', (payload) => {
            if (payload.symbol === this.symbol) {
                this.render(payload);
            }
        });
    }
    
    render(priceData) {
        this.element.textContent = `$${priceData.price.toFixed(2)}`;
        this.element.className = priceData.change_24h >= 0 ? 'price up' : 'price down';
    }
}
```

### **Selective Rendering**

```javascript
// Only re-render when relevant state changes
EventBus.subscribe('PORTFOLIO_POSITION_UPDATE', (payload) => {
    // Only update if position is in current view
    if (state.ui.activeSection === 'portfolio') {
        PortfolioView.renderPosition(payload.symbol);
    }
});
```

### **Batch Updates**

```javascript
// Batch multiple updates to avoid excessive re-renders
let updateQueue = [];
let updateScheduled = false;

EventBus.subscribe('MARKET_PRICE_UPDATE', (payload) => {
    updateQueue.push(payload);
    
    if (!updateScheduled) {
        updateScheduled = true;
        requestAnimationFrame(() => {
            PriceView.batchRender(updateQueue);
            updateQueue = [];
            updateScheduled = false;
        });
    }
});
```

---

## 🔍 FILTER FLOW (No Refetch)

### **Filter Architecture**

**Rule:** Filters operate on existing state, never trigger new fetches

```javascript
// WRONG: Filter triggers API call
function filterMarkets(category) {
    fetch(`/api/v1/predictions/markets?category=${category}`)  // ❌ NO
        .then(r => r.json())
        .then(data => renderMarkets(data));
}

// RIGHT: Filter operates on state
function filterMarkets(category) {
    // 1. Update UI filter state
    EventBus.emit('UI_FILTER_CHANGE', {
        domain: 'predictions',
        filters: { category }
    });
    
    // 2. Filter existing state
    const allMarkets = Array.from(state.predictions.markets.values());
    const filtered = category === 'all' 
        ? allMarkets
        : allMarkets.filter(m => m.category === category);
    
    // 3. Render filtered results
    PredictionsView.render(filtered);
}
```

### **Global Filter Propagation**

```javascript
// Global filters affect multiple views
EventBus.subscribe('UI_FILTER_CHANGE', (payload) => {
    if (payload.domain === 'global') {
        const { timeRange, symbols } = payload.filters;
        
        // Update all time-sensitive views
        if (timeRange) {
            ChartsView.updateTimeRange(timeRange);
            HistoryView.updateTimeRange(timeRange);
        }
        
        // Update all symbol-filtered views
        if (symbols) {
            PriceView.filterSymbols(symbols);
            OrderbookView.filterSymbols(symbols);
            TradesView.filterSymbols(symbols);
        }
    }
});
```

### **Filter State Persistence**

```javascript
// Filters persist across section changes
EventBus.subscribe('UI_SECTION_CHANGE', (payload) => {
    const section = payload.section;
    const filters = state.ui.filters[section] || {};
    
    // Apply persisted filters when entering section
    if (section === 'predictions') {
        PredictionsView.applyFilters(filters);
    }
});
```

---

## 🚀 COLD START FLOW

### **Initial Load Sequence**

```javascript
async function initializeDashboard() {
    console.log('[Dashboard] Cold start initiated');
    
    // 1. Fetch initial state from API
    const [prices, agents, portfolio, risk, execution, predictions] = await Promise.all([
        fetch('/api/v1/live/prices').then(r => r.json()),
        fetch('/api/v1/agents/status').then(r => r.json()),
        fetch('/api/v1/dashboard/portfolio/summary').then(r => r.json()),
        fetch('/api/v1/dashboard/risk/metrics').then(r => r.json()),
        fetch('/api/v1/dashboard/execution/stats').then(r => r.json()),
        fetch('/api/v1/predictions/markets').then(r => r.json())
    ]);
    
    // 2. Populate initial state via events
    prices.prices && Object.entries(prices.prices).forEach(([symbol, data]) => {
        EventBus.emit('MARKET_PRICE_UPDATE', { symbol, ...data });
    });
    
    agents.agents && agents.agents.forEach(agent => {
        EventBus.emit('AGENT_STATUS_CHANGE', agent);
    });
    
    // ... populate other domains
    
    // 3. Initialize WebSockets for live updates
    initPriceWebSocket();
    initAgentWebSocket();
    
    // 4. Start periodic polling for non-WebSocket data
    startPolling();
    
    console.log('[Dashboard] Cold start complete');
}
```

### **Polling for Non-WebSocket Data**

```javascript
function startPolling() {
    // Portfolio updates every 5s
    setInterval(async () => {
        const portfolio = await fetch('/api/v1/dashboard/portfolio/summary').then(r => r.json());
        EventBus.emit('PORTFOLIO_BALANCE_UPDATE', portfolio.balance);
        EventBus.emit('PORTFOLIO_PNL_UPDATE', portfolio.pnl);
    }, 5000);
    
    // Risk updates every 10s
    setInterval(async () => {
        const risk = await fetch('/api/v1/dashboard/risk/metrics').then(r => r.json());
        EventBus.emit('RISK_EXPOSURE_UPDATE', risk.exposure);
    }, 10000);
    
    // Execution stats every 15s
    setInterval(async () => {
        const exec = await fetch('/api/v1/dashboard/execution/stats').then(r => r.json());
        EventBus.emit('EXECUTION_STATS_UPDATE', exec.stats);
    }, 15000);
}
```

---

## 🔄 LIVE SYNC FLOW

### **WebSocket Live Updates**

```javascript
// Prices update in real-time via WebSocket
priceWebSocket.onmessage = (event) => {
    const message = JSON.parse(event.data);
    
    if (message.type === 'price_update') {
        // Event flows through bus → reducer → state → views
        EventBus.emit('MARKET_PRICE_UPDATE', message.payload);
        // Views automatically update via subscriptions
    }
};
```

### **Reconciliation on Reconnect**

```javascript
priceWebSocket.onopen = async () => {
    console.log('[WebSocket] Price feed connected');
    
    // Fetch latest state to reconcile any missed updates
    const prices = await fetch('/api/v1/live/prices').then(r => r.json());
    
    Object.entries(prices.prices).forEach(([symbol, data]) => {
        const existing = state.markets.prices.get(symbol);
        
        // Only update if server data is newer
        if (!existing || data.timestamp > existing.timestamp) {
            EventBus.emit('MARKET_PRICE_UPDATE', { symbol, ...data });
        }
    });
};
```

---

## ⚠️ ERROR FLOW

### **WebSocket Error Handling**

```javascript
priceWebSocket.onerror = (error) => {
    console.error('[WebSocket] Price feed error', error);
    
    // Emit system health degradation
    EventBus.emit('SYSTEM_HEALTH_CHANGE', {
        health: 'DEGRADED',
        timestamp: Date.now()
    });
    
    // Show user notification
    EventBus.emit('UI_NOTIFICATION', {
        id: `ws-error-${Date.now()}`,
        type: 'WARNING',
        message: 'Real-time price feed disconnected. Attempting to reconnect...',
        duration: null,
        timestamp: Date.now()
    });
};
```

### **API Error Handling**

```javascript
async function fetchWithRetry(url, maxRetries = 3) {
    for (let i = 0; i < maxRetries; i++) {
        try {
            const response = await fetch(url);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            return await response.json();
        } catch (error) {
            if (i === maxRetries - 1) {
                // Final retry failed
                EventBus.emit('UI_NOTIFICATION', {
                    id: `api-error-${Date.now()}`,
                    type: 'ERROR',
                    message: `Failed to fetch data from ${url}`,
                    duration: 5000,
                    timestamp: Date.now()
                });
                throw error;
            }
            // Exponential backoff
            await new Promise(resolve => setTimeout(resolve, 1000 * Math.pow(2, i)));
        }
    }
}
```

### **State Validation Failure**

```javascript
const StateValidator = {
    check(state) {
        const violations = [];
        
        // Check temporal consistency
        if (state.markets.lastUpdate > state.system.timestamp) {
            violations.push('markets.lastUpdate > system.timestamp');
        }
        
        // Check referential integrity
        if (state.ui.selectedSymbol && !state.markets.prices.has(state.ui.selectedSymbol)) {
            violations.push('ui.selectedSymbol not in markets.prices');
        }
        
        // Check numeric constraints
        const balance = state.portfolio.balance;
        if (Math.abs(balance.total - (balance.available + balance.locked)) > 0.01) {
            violations.push('portfolio.balance invariant violated');
        }
        
        if (violations.length > 0) {
            console.error('[StateValidator] Invariants violated:', violations);
            EventBus.emit('UI_NOTIFICATION', {
                id: `state-error-${Date.now()}`,
                type: 'ERROR',
                message: 'State inconsistency detected. Dashboard may show incorrect data.',
                duration: null,
                timestamp: Date.now()
            });
            return false;
        }
        
        return true;
    }
};
```

---

## 🔄 RETRY FLOW

### **Exponential Backoff**

```javascript
async function retryWithBackoff(fn, maxRetries = 5) {
    for (let i = 0; i < maxRetries; i++) {
        try {
            return await fn();
        } catch (error) {
            if (i === maxRetries - 1) throw error;
            
            const delay = Math.min(1000 * Math.pow(2, i), 30000);
            console.log(`[Retry] Attempt ${i + 1} failed, retrying in ${delay}ms`);
            await new Promise(resolve => setTimeout(resolve, delay));
        }
    }
}
```

### **Circuit Breaker**

```javascript
const CircuitBreaker = {
    failures: new Map(),
    threshold: 5,
    timeout: 60000,
    
    async call(key, fn) {
        const failure = this.failures.get(key);
        
        // Circuit open - reject immediately
        if (failure && failure.count >= this.threshold) {
            if (Date.now() - failure.timestamp < this.timeout) {
                throw new Error(`Circuit breaker open for ${key}`);
            } else {
                // Reset after timeout
                this.failures.delete(key);
            }
        }
        
        try {
            const result = await fn();
            this.failures.delete(key);  // Success - reset
            return result;
        } catch (error) {
            // Record failure
            const current = this.failures.get(key) || { count: 0, timestamp: Date.now() };
            this.failures.set(key, {
                count: current.count + 1,
                timestamp: Date.now()
            });
            throw error;
        }
    }
};
```

---

## 📊 PERFORMANCE OPTIMIZATIONS

### **Debouncing Rapid Updates**

```javascript
function debounce(fn, delay) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn(...args), delay);
    };
}

// Debounce filter changes
const debouncedFilter = debounce((category) => {
    filterMarkets(category);
}, 300);
```

### **Throttling High-Frequency Events**

```javascript
function throttle(fn, limit) {
    let inThrottle;
    return (...args) => {
        if (!inThrottle) {
            fn(...args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Throttle price updates to max 10/sec
const throttledPriceUpdate = throttle((payload) => {
    PriceView.render(payload);
}, 100);
```

### **Virtual Scrolling for Large Lists**

```javascript
// Only render visible items
class VirtualList {
    constructor(container, itemHeight, renderItem) {
        this.container = container;
        this.itemHeight = itemHeight;
        this.renderItem = renderItem;
        
        this.container.addEventListener('scroll', () => {
            this.render();
        });
    }
    
    render() {
        const scrollTop = this.container.scrollTop;
        const viewportHeight = this.container.clientHeight;
        
        const startIndex = Math.floor(scrollTop / this.itemHeight);
        const endIndex = Math.ceil((scrollTop + viewportHeight) / this.itemHeight);
        
        // Only render visible items
        for (let i = startIndex; i < endIndex; i++) {
            if (this.items[i]) {
                this.renderItem(this.items[i], i);
            }
        }
    }
}
```

---

## 🎯 COMPLETE FLOW EXAMPLE

### **Price Update End-to-End**

```
1. Exchange sends price update
   ↓
2. Backend receives via exchange WebSocket
   ↓
3. Backend broadcasts to dashboard WebSocket
   ↓
4. Dashboard priceWebSocket.onmessage receives
   ↓
5. Parse JSON and extract payload
   ↓
6. EventBus.emit('MARKET_PRICE_UPDATE', payload)
   ↓
7. EventBus validates payload schema
   ↓
8. StateReducer.reducePriceUpdate(state, payload)
   ↓
9. New state created (immutable)
   ↓
10. StateValidator.check(newState)
    ↓
11. MERIDState = newState
    ↓
12. EventBus.notify subscribers
    ↓
13. PriceTickerView.render(payload)
    ↓
14. DOM updated with new price
```

**Total latency:** ~5-10ms from WebSocket message to DOM update

---

## 🔐 FLOW INVARIANTS

### **Unidirectional Data Flow**
- Data flows one way: Backend → WebSocket → Event → State → View
- UI never mutates state directly
- UI never fetches data directly (except cold start)

### **Event Bus as Single Entry Point**
- All state changes go through event bus
- No direct state mutation
- No bypassing validation

### **Filters Never Fetch**
- Filters operate on existing state
- Filters update UI state only
- Filters trigger re-render, not re-fetch

### **Immutable State Updates**
- State tree never mutated in place
- New objects created on update
- Structural sharing for performance

---

**All three documents complete. System specification ready for implementation.**
