# Kalshi Order Group Toolkit

Complete order group management system for Kalshi prediction market trading.

## Overview

Order groups provide a mechanism to batch and limit trading activity by defining:
- **Contracts Limit**: Maximum number of contracts that can be placed through the group
- **Status Tracking**: Active, triggered, canceled, or pending states
- **Auto-Cancel**: Automatic cancellation of open orders when triggered
- **Risk Management**: Pre-trade checks ensure group limits are respected

## Architecture

### Backend Components

```
merid/event_venues/kalshi/
├── order_group_manager.py      # Core order group operations
├── order_group_lifecycle.py    # Lifecycle hooks for trading loop
├── order_group_recovery.py     # Error classification & recovery
├── order_router.py             # Order routing with group assignment
└── ws.py                       # WebSocket message handling

web/api/kalshi_api.py           # REST API endpoints
```

### Frontend Components

```
web/react/src/
├── components/
│   ├── OrderGroupPanel.tsx     # Real-time group management UI
│   ├── BatchOrderPanel.tsx     # Batch order placement with group assignment
│   └── KalshiTradeTicket.tsx   # Single order with optional group
├── hooks/
│   └── useOrderGroupStream.ts  # SSE streaming hook
└── views/
    ├── KalshiDashboardView.tsx # Integrated panel
    ├── KalshiPortfolioView.tsx # Risk tab integration
    └── KalshiGridView.tsx      # Grid view integration
```

## API Endpoints

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/kalshi/order-groups` | Create new order group |
| GET | `/api/v1/kalshi/order-groups` | List all order groups |
| GET | `/api/v1/kalshi/order-groups/{id}` | Get group details |
| PUT | `/api/v1/kalshi/order-groups/{id}/limit` | Update contracts limit |
| POST | `/api/v1/kalshi/order-groups/{id}/trigger` | Manually trigger group |
| PUT | `/api/v1/kalshi/order-groups/{id}/reset` | Reset triggered group |
| DELETE | `/api/v1/kalshi/order-groups/{id}` | Delete order group |
| GET | `/api/v1/kalshi/order-groups/dashboard` | Aggregated status |
| POST | `/api/v1/kalshi/orders/batch` | Batch place with group assignment |

### WebSocket SSE Stream

| Endpoint | Description |
|----------|-------------|
| `/api/v1/kalshi/order-groups/stream` | Real-time order group updates |

**Event Types:**
- `snapshot`: Full state update
- `delta`: Partial update (single group)
- `triggered`: Group reached limit
- `heartbeat`: Keep-alive

## Usage Examples

### Creating an Order Group

```python
import requests

response = requests.post(
    "/api/v1/kalshi/order-groups",
    json={
        "order_group_id": "og-btc-strategy",
        "contracts_limit": 1000,
        "initial_contracts": 0,
        "market_id": "optional-specific-market"
    }
)
```

### Placing Orders with Group Assignment

**Single Order:**
```python
order = OrderIntent(
    ticker="KXBTC-24JUN",
    side="yes",
    action="buy",
    price_cents=55,
    count=10,
    order_group_id="og-btc-strategy",  # Assign to group
    post_only=True
)
```

**Batch Orders:**
```python
batch = BatchOrderIntent(
    orders=[order1, order2, order3],
    order_group_id="og-btc-strategy",  # Default for all
    self_trade_prevention_type="taker_at_cross"
)
```

### React Component Usage

```tsx
// Real-time group monitoring
<OrderGroupPanel
  compact={false}
  onGroupTriggered={(groupId) => {
    console.log('Group triggered:', groupId);
    // e.g., show alert, refresh positions
  }}
/>

// Batch order placement
<BatchOrderPanel
  onOrdersPlaced={() => refetchPositions()}
  availableGroups={groups}
  defaultOrderGroupId="og-btc-strategy"
/>

// Single order with group
<KalshiTradeTicket
  ticker="KXBTC-24JUN"
  outcomes={market.outcomes}
  orderGroupId="og-btc-strategy"
/>
```

### SSE Stream Hook

```tsx
const { groups, alerts, isConnected } = useOrderGroupStream({
  groupIds: ['og-1', 'og-2'], // Optional filter
  autoConnect: true,
  onTriggered: (groupId, data) => {
    toast.warning(`Group ${groupId} triggered!`);
  }
});
```

## Risk Integration

### Execution Guard Checks

The execution guard (`merid/execution_guard.py`) performs pre-trade validation:

1. **Group Existence**: Verify group exists
2. **Active Status**: Block if group is triggered/canceled
3. **Limit Check**: Ensure sufficient remaining contracts
4. **Auto-Clamp**: Reduce order size if partial fill possible

### Risk Check Outcomes

| Scenario | Action |
|----------|--------|
| Group triggered | Block trade |
| Group not found | Allow with warning |
| Insufficient remaining | Block or clamp |
| Check throws exception | Allow (fail-open) |

## Lifecycle Integration

The main trading loop (`merid/loop.py`) includes order group lifecycle sync:

```python
# Step 7b: Order group lifecycle sync (for prediction domain)
if "prediction" in self.config.active_domains:
    await self._sync_order_groups(summary)
```

This ensures:
- Group state is refreshed from API
- Triggered groups are detected
- Metrics are reported in tick summaries

## Error Recovery

The error recovery system (`order_group_recovery.py`) handles:

| Error Code | Recovery Action |
|------------|----------------|
| `INVALID_LIMIT` | Skip and continue |
| `ORDER_GROUP_NOT_FOUND` | Refresh groups, retry |
| `GROUP_TRIGGERED` | Reset group, retry |
| `CONTRACTS_LIMIT_EXCEEDED` | Reduce size, retry |
| `API_ERROR` | Backoff retry |

## Testing

### Backend Tests

```bash
pytest tests/event_venues/test_order_groups.py -v
```

Covers:
- OrderGroupState calculations
- OrderGroupRiskManager tracking
- ErrorClassifier patterns
- RecoveryManager logic

### Frontend Tests

```bash
# Component tests
npm test -- OrderGroupPanel.test.tsx

# Hook tests  
npm test -- useOrderGroupStream.test.tsx
```

## Constants

```typescript
// API Endpoints
KALSHI_ORDER_GROUPS: "/api/v1/kalshi/order-groups"
KALSHI_ORDER_GROUP_DETAIL: (id) => `/api/v1/kalshi/order-groups/${id}`
KALSHI_ORDER_GROUP_CREATE: "/api/v1/kalshi/order-groups"
KALSHI_ORDER_GROUP_LIMIT: (id) => `/api/v1/kalshi/order-groups/${id}/limit`
KALSHI_ORDER_GROUP_TRIGGER: (id) => `/api/v1/kalshi/order-groups/${id}/trigger`
KALSHI_ORDER_GROUP_RESET: (id) => `/api/v1/kalshi/order-groups/${id}/reset`
KALSHI_ORDER_GROUP_DELETE: (id) => `/api/v1/kalshi/order-groups/${id}`
KALSHI_ORDER_GROUP_DASHBOARD: "/api/v1/kalshi/order-groups/dashboard"
KALSHI_ORDER_GROUP_STREAM: "/api/v1/kalshi/order-groups/stream"
KALSHI_BATCH_ORDERS: "/api/v1/kalshi/orders/batch"
```

## Best Practices

1. **Always assign groups for batch orders** — ensures collective limit enforcement
2. **Monitor alerts** — high utilization warnings indicate approaching limits
3. **Reset promptly** — reset triggered groups after reviewing positions
4. **Use post-only** — prevents taking liquidity unintentionally
5. **Check execution verdicts** — review `checks_passed`/`checks_failed` for issues

## Related Documentation

- [Kalshi UI/UX Audit](./docs/KALSHI_UI_AUDIT.md)
- [Execution Guard](./merid/execution_guard.py)
- [Order Router](./merid/event_venues/kalshi/order_router.py)
