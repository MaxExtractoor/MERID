# MERID React Dashboard API Reference

## Overview

This document provides a comprehensive reference for all APIs, hooks, components, and utilities used in the MERID React dashboard.

## Table of Contents

- [Hooks](#hooks)
- [Components](#components)
- [Utilities](#utilities)
- [Configuration](#configuration)
- [Examples](#examples)

---

## Hooks

### useApiData

Generic data fetching hook with polling, caching, and error handling.

```typescript
interface UseApiDataOptions<T> {
  initialData?: T;
  enabled?: boolean;
  pollInterval?: number;
  transform?: (data: any) => T;
  headers?: Record<string, string>;
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: any;
}

interface UseApiDataResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

function useApiData<T>(
  url: string,
  options?: UseApiDataOptions<T>
): UseApiDataResult<T>
```

**Parameters:**
- `url`: API endpoint URL
- `options`: Configuration options

**Returns:**
- `data`: Fetched data or null
- `loading`: Loading state
- `error`: Error message or null
- `refetch`: Function to manually refetch data

**Example:**
```typescript
const { data, loading, error } = useApiData('/api/v1/trading/positions', {
  pollInterval: 5000,
  transform: (data) => data.positions,
});
```

### useWebSocket

WebSocket connection manager with automatic reconnection and JWT refresh.

```typescript
interface UseWebSocketOptions {
  autoReconnect?: boolean;
  reconnectAttempts?: number;
  reconnectDelay?: number;
  timeout?: number;
  onConnect?: () => void;
  onDisconnect?: () => void;
  onError?: (error: Error) => void;
  onMessage?: (event: string, data: any) => void;
  messageHistory?: boolean;
  maxHistorySize?: number;
}

interface UseWebSocketResult {
  connected: boolean;
  connecting: boolean;
  error: Error | null;
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  lastMessage: { event: string; data: any } | null;
  messageHistory: Array<{ event: string; data: any }>;
  send: (event: string, data?: any) => void;
}

function useWebSocket(url: string, options?: UseWebSocketOptions): UseWebSocketResult
```

**Example:**
```typescript
const { connected, send, lastMessage } = useWebSocket('ws://localhost:3000', {
  autoReconnect: true,
  onMessage: (event, data) => {
    console.log(`Received ${event}:`, data);
  },
});
```

### useLocalStorage

Type-safe localStorage hook with cross-tab synchronization.

```typescript
interface UseLocalStorageOptions<T> {
  serializer?: {
    read: (value: string) => T;
    write: (value: T) => string;
  };
  syncAcrossTabs?: boolean;
}

function useLocalStorage<T>(
  key: string,
  defaultValue: T,
  options?: UseLocalStorageOptions<T>
): [T, (value: T | ((prev: T) => T)) => void]
```

**Example:**
```typescript
const [theme, setTheme] = useLocalStorage('theme', 'dark');
```

---

## Components

### MetricCard

KPI display component with status indicators and trend information.

```typescript
interface MetricCardProps {
  label: string;
  value: string | number;
  delta?: number;
  trend?: 'up' | 'down' | 'neutral';
  status?: 'GOOD' | 'WARNING' | 'BAD' | 'ONLINE' | 'DEGRADED' | 'OFFLINE';
  deltaPrecision?: number;
  className?: string;
}
```

**Example:**
```typescript
<MetricCard
  label="Total P&L"
  value="$12,345.67"
  delta={5.2}
  trend="up"
  status="GOOD"
/>
```

### StatusIndicator

Inline status indicator with colors and icons.

```typescript
interface StatusIndicatorProps {
  status: 'ONLINE' | 'DEGRADED' | 'OFFLINE' | 'GOOD' | 'WARNING' | 'BAD';
  text?: string;
  showText?: boolean;
  tooltip?: string;
  size?: 'small' | 'medium' | 'large';
  variant?: 'dot' | 'pill';
}
```

**Example:**
```typescript
<StatusIndicator status="ONLINE" text="Connected" />
```

### PriceTicker

Real-time price display with change indicators.

```typescript
interface PriceTickerData {
  symbol: string;
  last: number;
  change: number;
  changePercent: number;
  volume?: number;
  timestamp: string;
}

interface PriceTickerProps {
  data: PriceTickerData | null;
  loading?: boolean;
  error?: string;
  showVolume?: boolean;
  showTimestamp?: boolean;
  size?: 'small' | 'medium' | 'large';
}
```

**Example:**
```typescript
<PriceTicker
  data={{
    symbol: 'BTC/USD',
    last: 45000,
    change: 500,
    changePercent: 1.12,
    timestamp: '2024-01-30T15:30:00Z',
  }}
  showVolume={true}
/>
```

### DataTableEnhanced

Enhanced data table with sorting, filtering, and pagination.

```typescript
interface Column<T> {
  key: keyof T;
  label: string;
  sortable?: boolean;
  render?: (value: any, row: T) => React.ReactNode;
}

interface DataTableEnhancedProps<T> {
  data: T[];
  columns: Column<T>[];
  loading?: boolean;
  error?: string;
  filterable?: boolean;
  selectable?: boolean;
  pageSize?: number;
  onRowClick?: (row: T) => void;
  onSelectionChange?: (selectedRows: T[]) => void;
  rowClassName?: (row: T) => string;
}
```

**Example:**
```typescript
<DataTableEnhanced
  data={positions}
  columns={[
    { key: 'symbol', label: 'Symbol', sortable: true },
    { key: 'size', label: 'Size', sortable: true },
    { key: 'pnl', label: 'P&L', sortable: true },
  ]}
  filterable={true}
  selectable={true}
/>
```

---

## Utilities

### Formatters

#### formatCurrency
```typescript
formatCurrency(amount: number, currency?: string, precision?: number): string
```

#### formatPercent
```typescript
formatPercent(value: number, precision?: number): string
```

#### formatNumber
```typescript
formatNumber(value: number, precision?: number): string
```

#### formatDate
```typescript
formatDate(date: Date | string, format?: string): string
```

#### formatTime
```typescript
formatTime(date: Date | string, format?: '12h' | '24h', includeSeconds?: boolean): string
```

#### formatDuration
```typescript
formatDuration(seconds: number, format?: 'short' | 'verbose'): string
```

#### formatFileSize
```typescript
formatFileSize(bytes: number, unit?: 'decimal' | 'binary'): string
```

#### formatDelta
```typescript
formatDelta(current: number, previous: number, type?: 'absolute' | 'percent'): {
  value: string;
  percent: string;
  color: string;
  icon: string;
}
```

### Validators

#### validateSymbol
```typescript
validateSymbol(symbol: string): ValidationResult
```

#### validateSize
```typescript
validateSize(size: number, options?: { minSize?: number; maxSize?: number }): ValidationResult
```

#### validatePrice
```typescript
validatePrice(price: number, options?: { maxPrecision?: number }): ValidationResult
```

#### validateLeverage
```typescript
validateLeverage(leverage: number, options?: { maxLeverage?: number }): ValidationResult
```

#### validateOrderType
```typescript
validateOrderType(type: string): ValidationResult
```

#### validateSide
```typescript
validateSide(side: string): ValidationResult
```

#### validateVenue
```typescript
validateVenue(venue: string, options?: { venues?: string[] }): ValidationResult
```

#### validateOrderTicket
```typescript
validateOrderTicket(order: OrderTicket, options?: ValidationOptions): ValidationResult
```

---

## Configuration

### Constants

All configuration is centralized in `src/config/constants.ts`:

```typescript
// API Endpoints
export const API_ENDPOINTS = {
  TRADING: '/api/v1/trading',
  AGENTS: '/api/v1/agents',
  PREDICTIONS: '/api/v1/predictions',
  RISK: '/api/v1/risk',
  API_DASHBOARD: '/api/v1/api',
  RESEARCH: '/api/v1/research',
  LOGS: '/api/v1/logs',
  SETTINGS: '/api/v1/settings',
};

// WebSocket Events
export const WS_EVENTS = {
  PRICE_UPDATE: 'price_update',
  ORDER_UPDATE: 'order_update',
  POSITION_UPDATE: 'position_update',
  AGENT_UPDATE: 'agent_update',
  RISK_ALERT: 'risk_alert',
};

// Status Types
export const STATUS_TYPES = {
  ONLINE: 'ONLINE',
  DEGRADED: 'DEGRADED',
  OFFLINE: 'OFFLINE',
  GOOD: 'GOOD',
  WARNING: 'WARNING',
  BAD: 'BAD',
};

// Default Values
export const DEFAULTS = {
  POLL_INTERVAL: 5000,
  PAGE_SIZE: 25,
  MAX_HISTORY_SIZE: 100,
  RECONNECT_DELAY: 1000,
  RECONNECT_ATTEMPTS: 5,
};
```

---

## Examples

### Complete Trading View Example

```typescript
import React from 'react';
import { useApiData, useWebSocket } from '../hooks';
import { MetricCard, PriceTicker, DataTableEnhanced } from '../components';
import { formatCurrency, formatPercent } from '../utils';

export default function TradingView() {
  const { data: positions, loading: positionsLoading } = useApiData('/api/v1/trading/positions', {
    pollInterval: 5000,
  });

  const { data: orders, loading: ordersLoading } = useApiData('/api/v1/trading/orders', {
    pollInterval: 3000,
  });

  const { connected, lastMessage } = useWebSocket('ws://localhost:3000', {
    autoReconnect: true,
    onMessage: (event, data) => {
      if (event === 'price_update') {
        // Handle price updates
      }
    },
  });

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-4 gap-4">
        <MetricCard
          label="Total P&L"
          value={formatCurrency(positions?.totalPnl || 0)}
          delta={positions?.pnlPercent}
          trend={positions?.pnlPercent >= 0 ? 'up' : 'down'}
          status={positions?.pnlPercent >= 0 ? 'GOOD' : 'BAD'}
        />
        <MetricCard
          label="Open Positions"
          value={positions?.count || 0}
          status="GOOD"
        />
        <MetricCard
          label="Active Orders"
          value={orders?.count || 0}
          status="GOOD"
        />
        <MetricCard
          label="Connection"
          value={connected ? 'Connected' : 'Disconnected'}
          status={connected ? 'GOOD' : 'BAD'}
        />
      </div>

      <DataTableEnhanced
        data={positions?.positions || []}
        columns={[
          { key: 'symbol', label: 'Symbol', sortable: true },
          { key: 'size', label: 'Size', sortable: true },
          { key: 'entryPrice', label: 'Entry Price', sortable: true },
          { key: 'currentPrice', label: 'Current Price', sortable: true },
          { 
            key: 'pnl', 
            label: 'P&L', 
            sortable: true,
            render: (value) => (
              <span className={value >= 0 ? 'text-green-500' : 'text-red-500'}>
                {formatCurrency(value)}
              </span>
            ),
          },
        ]}
        loading={positionsLoading}
        filterable={true}
        pageSize={10}
      />
    </div>
  );
}
```

### Custom Hook Example

```typescript
import { useApiData } from './useApiData';
import { useState, useCallback } from 'react';

export function useTradingData() {
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTC/USD');

  const { data: positions, refetch: refetchPositions } = useApiData(
    '/api/v1/trading/positions',
    { pollInterval: 5000 }
  );

  const { data: orders, refetch: refetchOrders } = useApiData(
    '/api/v1/trading/orders',
    { pollInterval: 3000 }
  );

  const { data: priceData } = useApiData(
    `/api/v1/trading/price/${selectedSymbol}`,
    { pollInterval: 1000 }
  );

  const executeTrade = useCallback(async (order: TradeOrder) => {
    try {
      const response = await fetch('/api/v1/trading/execute', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('merid-access')}`,
        },
        body: JSON.stringify(order),
      });

      if (!response.ok) {
        throw new Error('Trade execution failed');
      }

      // Refresh data
      refetchPositions();
      refetchOrders();
    } catch (error) {
      console.error('Trade execution error:', error);
      throw error;
    }
  }, [refetchPositions, refetchOrders]);

  return {
    positions,
    orders,
    priceData,
    selectedSymbol,
    setSelectedSymbol,
    executeTrade,
  };
}
```

---

## Error Handling

All hooks and components provide consistent error handling:

### useApiData Errors
```typescript
const { data, loading, error } = useApiData('/api/v1/data');

if (error) {
  return <div className="text-red-500">Error: {error}</div>;
}
```

### WebSocket Errors
```typescript
const { connected, error } = useWebSocket('ws://localhost:3000');

if (error) {
  console.error('WebSocket error:', error);
}
```

### Component Error States
```typescript
<DataTableEnhanced
  data={data}
  error={error ? 'Failed to load data' : undefined}
  loading={loading}
/>
```

---

## Performance Considerations

1. **Polling Intervals**: Use appropriate polling intervals to avoid excessive API calls
2. **Data Transformation**: Use the `transform` option to process data on the hook level
3. **Component Memoization**: Use `React.memo` for expensive components
4. **Pagination**: Use pagination for large datasets
5. **WebSocket Debouncing**: Debounce rapid WebSocket messages if needed

---

## TypeScript Support

All components and hooks are fully typed with TypeScript. Type definitions are included for:

- Hook options and return values
- Component props
- Utility function parameters and return values
- API response types
- WebSocket event types

---

## Testing

The library includes comprehensive test coverage using Jest and React Testing Library. Run tests with:

```bash
npm test
```

For coverage reports:

```bash
npm run test:coverage
```
