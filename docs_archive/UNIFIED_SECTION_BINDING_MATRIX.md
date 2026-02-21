# MERID Unified Platform - Section Data Binding Matrix

| Section Key | Template | JS Module | REST APIs | WebSockets | Priority |
| --- | --- | --- | --- | --- | --- |
| dashboard | `partials/dashboard_overview.html` | `sections/dashboard.js` | `/api/v1/institutional/predictions/markets` | `/ws`, `/ws/live` | P0 |
| markets/whales | `partials/markets_whales.html` | `sections/markets_whales.js` | `/api/v1/institutional/predictions/whales` | `/ws/whales` | P0 |
| markets/arbitrage | `partials/markets_arbitrage.html` | `sections/markets_arbitrage.js` | `/api/v1/arbitrage/opportunities`, `/stats` | `/ws/arbitrage` | P1 |
| markets/prediction | `partials/markets_prediction.html` | `sections/markets_prediction.js` | `/api/v1/institutional/predictions/markets` | (TBD: `/ws/prediction` or `/ws`) | P1 |
| trading/perps | `partials/trading_perps.html` | `sections/trading_perps.js` | `/api/v1/trading/perps/*` | `/ws/prices`, `/ws/trades`, `/ws/positions` | P0 |
| trading/arena | `partials/trading_arena.html` | `sections/trading_arena.js` | `/api/v1/trading/arena/status` | `/ws/spectator/stream` | P0 |
| agents/simulation | `partials/simulation.html` | `sections/simulation.js` | `/api/v1/simulation/status`, `/runs` | `/ws/simulation` | P0 |
| live | `partials/live.html` | `sections/live.js` | `/api/v1/trading/portfolio` | `/ws/live` | P0 |
| analytics/metrics | `partials/analytics_metrics.html` | `sections/analytics_metrics.js` | `/api/v1/analytics/metrics` | (optional) `/ws/system` | P1 |
| admin/system | `partials/admin_system.html` | `sections/admin_system.js` | `/api/v1/system/health`, `/subsystems`, `/metrics`, `/events` | `/ws/system` | P0 |

## Implementation Priority

### Phase 2.1 - Core Sections (Already Have Templates)

1. `/unified/dashboard` - Extract from `analytics_dashboard.html`
2. `/unified/markets/whales` - Extract from whale alerts
3. `/unified/trading/perps` - Extract from `trading_perps.html`
4. `/unified/trading/arena` - Extract from `trading_arena.html`
5. `/unified/simulation` - Extract from `simulation.html`
6. `/unified/live` - Extract from `live_monitor.html`

### Phase 2.2 - High Priority Sections

1. `/unified/markets/arbitrage` - Use existing API
2. `/unified/markets/prediction` - Use existing API
3. `/unified/trading/markets` - Use existing template
4. `/unified/agents/cohorts` - Use orchestrator data
5. `/unified/admin/system` - Use health endpoints

### Phase 2.3 - Advanced Sections

1. `/unified/analytics/metrics` - Brier metrics DB
2. `/unified/governance/policies` - Governance system
3. `/unified/analytics/explainability` - Data policies
4. `/unified/news/sentinel` - News agent
5. `/unified/trading/strategies` - Strategy monitoring

## WebSocket Integration Requirements

### Existing WebSocket Endpoints (Ready for Integration)

- `/ws` - General events, market updates
- `/ws/whales` - Whale detection events
- `/ws/live` - Live trading monitor
- `/ws/prices` - Price streaming
- `/ws/trades` - Trade streaming
- `/ws/positions` - Position updates
- `/ws/simulation` - Simulation updates
- `/ws/spectator/stream` - Trading arena events

### Stream Manager Integration Pattern

```javascript
// Example for dashboard section
const unsubscribeGeneral = streamManager.subscribe('/ws', (data) => {
    if (data.type === 'market_update') {
        updateMarketWidgets(data);
    }
});

const unsubscribeWhales = streamManager.subscribe('/ws/whales', (data) => {
    if (data.type === 'whale') {
        updateWhaleAlerts(data);
    }
});

// Cleanup on section unload
return () => {
    unsubscribeGeneral();
    unsubscribeWhales();
};
```

## Data Flow Architecture

### REST API Integration

- All sections will use existing FastAPI endpoints
- Polling fallback for sections without WebSocket support
- Error handling and retry logic for failed requests

### WebSocket Event Types

- Market updates, price changes, trade executions
- Whale alerts, arbitrage opportunities
- Agent status changes, simulation events
- System health, governance updates

### Section Teardown Pattern

```javascript
// In unified-shell.js section cleanup
const cleanup = currentSection.cleanup;
if (cleanup) {
    cleanup(); // Unsubscribe from WebSockets, clear intervals
}
```
