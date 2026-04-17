# MERID React Hooks & Utilities Documentation

## 📚 Table of Contents

1. [Authentication](#authentication)
2. [API Services](#api-services)
3. [Hooks](#hooks)
4. [Validation](#validation)
5. [Error Handling](#error-handling)
6. [Performance Monitoring](#performance-monitoring)

---

## Authentication

### `services/auth.ts`

Centralized authentication utilities for consistent auth header management.

#### Functions

##### `getAuthHeaders(additionalHeaders?: HeadersInit): HeadersInit`

Returns authentication headers with Bearer token and X-Session-ID if token exists.

```typescript
import { getAuthHeaders } from './services/auth';

const headers = getAuthHeaders({ 'X-Custom': 'value' });
// { 'Content-Type': 'application/json', 'Authorization': 'Bearer xxx', 'X-Session-ID': 'xxx', 'X-Custom': 'value' }
```

##### `useAuthHeaders(additionalHeaders?: HeadersInit): () => HeadersInit`

Hook-compatible version for React components.

```typescript
const getHeaders = useAuthHeaders();
const headers = getHeaders();
```

##### `isAuthenticated(): boolean`

Check if user has a valid auth token.

##### `getAuthToken(): string | null`

Get the raw auth token from localStorage.

##### `clearAuth(): void`

Remove auth token (logout).

---

## API Services

### `services/api.ts`

Centralized API service with typed methods for all backend endpoints.

#### Class: `APIService`

```typescript
import { api } from './services/api';

// System
const health = await api.getSystemHealth();
const pnl = await api.getPnLSummary();

// Kalshi Trading
const positions = await api.getKalshiPositions();
const orders = await api.getKalshiOrders();
await api.cancelOrder('order-id');
await api.cancelAllOrders();

// Grid & Mode
const mode = await api.getGridMode();
await api.setGridMode('live', true); // force=true

// Operator Actions
await api.emergencyStop('Circuit breaker triggered');
await api.resetKillSwitch();

// Risk
const protections = await api.getRiskProtections();
await api.downsizePositions();
```

---

## Hooks

### `useConfirmModal()`

Modern replacement for `window.confirm()` with promise-based API.

```typescript
import { useConfirmModal } from './hooks/useConfirmModal';

function MyComponent() {
  const { confirm, ConfirmModal } = useConfirmModal();

  const handleDelete = async () => {
    const confirmed = await confirm({
      title: 'Delete Order?',
      message: 'This action cannot be undone.',
      variant: 'danger',
      confirmText: 'Delete',
      cancelText: 'Cancel',
    });

    if (confirmed) {
      // Proceed with deletion
    }
  };

  return (
    <>
      <button onClick={handleDelete}>Delete</button>
      <ConfirmModal />
    </>
  );
}
```

### `useRequestDedup()`

Prevents duplicate API calls across components.

```typescript
import { useRequestDedup } from './hooks/useRequestDedup';

function MyComponent() {
  const dedup = useRequestDedup();

  const fetchData = async () => {
    const data = await dedup.fetch('/api/data', () => 
      fetch('/api/data').then(r => r.json())
    );
    return data;
  };
}
```

### `useSharedPoll()`

Coordinated polling - multiple components subscribe to same endpoint, only one request made.

```typescript
import { useSharedPoll } from './hooks/useRequestDedup';

function MarketData() {
  const { subscribe, getLastData } = useSharedPoll();

  useEffect(() => {
    return subscribe('/api/market-data', (data) => {
      setMarketData(data);
    }, {
      interval: 5000,
      fetchFn: () => api.getMarketData(),
    });
  }, []);
}
```

### `useSWR()`

Lightweight SWR implementation for server state.

```typescript
import { useSWR } from './hooks/useSWR';

function MarketData() {
  const { data, error, isLoading, mutate } = useSWR({
    endpoint: '/api/market-data',
    fetcher: () => api.getMarketData(),
    refreshInterval: 5000,
    dedupingInterval: 2000,
  });

  if (isLoading) return <Loading />;
  if (error) return <Error message={error.message} />;

  return <MarketTable data={data} onRefresh={mutate} />;
}
```

### `useResilientWebSocket()`

WebSocket with automatic HTTP fallback.

```typescript
import { useResilientWebSocket } from './hooks/useResilientWebSocket';

function LiveData() {
  const { 
    connected, 
    lastMessage, 
    isFallback, 
    reconnectAttempts,
    reconnect 
  } = useResilientWebSocket({
    url: 'wss://api.example.com/ws',
    fallbackHttpEndpoint: '/api/poll',
    fallbackAfterFailures: 3,
    fallbackPollInterval: 5000,
    onMessage: (data) => console.log(data),
  });

  if (isFallback) {
    return <Badge>HTTP Fallback Mode</Badge>;
  }
}
```

### `usePerformanceMonitor()`

Track component render performance.

```typescript
import { usePerformanceMonitor } from './hooks/usePerformanceMonitor';

function MyComponent() {
  const { trackApiLatency, trackError, getMetrics } = usePerformanceMonitor('MyComponent', {
    renderThresholdMs: 16,
    maxRendersPerSecond: 30,
  });

  const fetchData = async () => {
    const start = performance.now();
    try {
      const data = await api.getData();
      trackApiLatency(performance.now() - start);
      return data;
    } catch (err) {
      trackError();
      throw err;
    }
  };
}
```

---

## Validation

### `validators/trading.ts`

Zod schemas for trading input validation.

```typescript
import { validators, OrderInput } from './validators/trading';

const order: OrderInput = {
  ticker: 'BTC-2024-01-01',
  side: 'yes',
  action: 'buy',
  count: 100,
  price_cents: 55,
  order_type: 'limit',
  mode: 'paper',
};

const result = validators.order(order);

if (!result.success) {
  console.error(result.errors); // ['Count must be positive', ...]
}
```

### `validators/apiContracts.ts`

Runtime API response validation with Zod.

```typescript
import { validateApiResponse, RiskProtectionsSchema } from './validators/apiContracts';

const response = await api.getRiskProtections();
const result = validateApiResponse(RiskProtectionsSchema, response);

if (result.success) {
  // Type-safe data
  const protections: RiskProtections = result.data;
} else {
  console.error('API contract violation:', result.errors);
}
```

---

## Error Handling

### `utils/errorHandler.ts`

Unified error handling with classification and retry logic.

```typescript
import { processApiError, retryWithBackoff, fetchWithErrorHandling } from './utils/errorHandler';

// Process any error
try {
  await api.getData();
} catch (err) {
  const apiError = processApiError(err, {
    endpoint: '/api/data',
    context: 'DataFetcher',
    onError: (error) => analytics.track(error),
  });
  
  // apiError.type: 'network' | 'auth' | 'validation' | 'server' | 'timeout' | 'unknown'
  // apiError.retryable: boolean
  // apiError.message: user-friendly message
}

// Auto-retry with backoff
const data = await retryWithBackoff(
  () => api.getData(),
  {
    maxRetries: 3,
    baseDelay: 1000,
    shouldRetry: (error) => error.type === 'network',
    onRetry: (attempt, error) => console.log(`Retry ${attempt}: ${error.message}`),
  }
);

// Fetch with error handling
const response = await fetchWithErrorHandling(
  '/api/data',
  { method: 'POST', body: JSON.stringify(data) },
  { context: 'DataSubmission' }
);
```

---

## Performance Monitoring

### `useApiPerformance()`

Measure API call performance with automatic logging.

```typescript
import { useApiPerformance } from './hooks/usePerformanceMonitor';

function DataComponent() {
  const { measure, getStats } = useApiPerformance('/api/data');

  const fetchData = async () => {
    return await measure(() => api.getData());
  };

  // Get performance stats
  const stats = getStats();
  // { count: 50, average: 150, min: 80, max: 2000, p50: 120, p95: 400, p99: 1800 }
}
```

### `useInteractionTiming()`

Track time to first interaction.

```typescript
import { useInteractionTiming } from './hooks/usePerformanceMonitor';

function FormComponent() {
  const { markInteraction } = useInteractionTiming('ContactForm');

  return (
    <form onFocus={markInteraction}>
      {/* Form fields */}
    </form>
  );
}
```

### `withPerformanceTracking()`

HOC for automatic render performance tracking.

```typescript
import { withPerformanceTracking } from './hooks/usePerformanceMonitor';

function SlowComponent(props: Props) {
  // Component logic
}

export default withPerformanceTracking(SlowComponent, 'SlowComponent');
// Logs when renders take >16ms
```

---

## Testing Utilities

### `tests/__utils__/mockFactories.ts`

Centralized test mocks.

```typescript
import {
  getMockConstants,
  createMockApiResponse,
  createMockSystemHealth,
  createMockRiskProtections,
  setupStandardMocks,
} from './tests/__utils__/mockFactories';

// Use in test setup
jest.mock('./config/constants', () => getMockConstants());

// Create mock data
const health = createMockSystemHealth({ status: 'degraded' });
const risk = createMockRiskProtections({ circuit_breaker: { state: 'OPEN' } });
```

---

## Migration Guide

### From `window.confirm()` to `useConfirmModal()`

**Before:**
```typescript
if (window.confirm('Are you sure?')) {
  await deleteItem();
}
```

**After:**
```typescript
const { confirm, ConfirmModal } = useConfirmModal();

const handleDelete = async () => {
  if (await confirm({ title: 'Are you sure?', message: 'This cannot be undone.' })) {
    await deleteItem();
  }
};

// In JSX:
<ConfirmModal />
```

### From inline `fetch()` to `api` service

**Before:**
```typescript
const response = await fetch(`${API_BASE_URL}/api/kalshi/orders`, {
  headers: { Authorization: `Bearer ${token}` },
});
```

**After:**
```typescript
const orders = await api.getKalshiOrders();
```

### From duplicate auth headers to centralized

**Before:**
```typescript
const authHeaders = () => ({
  Authorization: `Bearer ${localStorage.getItem('merid-access')}`,
});
```

**After:**
```typescript
import { getAuthHeaders } from './services/auth';
const headers = getAuthHeaders();
```

---

## Best Practices

1. **Always use `api` service** for backend calls instead of raw `fetch()`
2. **Use `useConfirmModal()`** instead of native `confirm()` / `alert()`
3. **Validate inputs** with `validators/trading.ts` before sending
4. **Handle errors** with `processApiError()` for consistent error UX
5. **Use `useRequestDedup()`** for expensive API calls
6. **Monitor performance** with `usePerformanceMonitor()` for complex components
7. **Use `useResilientWebSocket()`** instead of raw WebSocket for live data
