# MERID React Frontend Architecture

This document codifies the patterns and contracts established during the TypeScript strict-mode refactor. All future work should align with these conventions.

## Table of Contents

1. [Status Pattern](#status-pattern)
2. [Column/Table Pattern](#columntable-pattern)
3. [WebSocket Pattern](#websocket-pattern)
4. [Null Safety](#null-safety)
5. [Utils Contracts](#utils-contracts)
6. [Testing Patterns](#testing-patterns)

---

## Status Pattern

Domain-level status enums are converted to UI-level `STATUS_TYPES` for component consumption.

### Domain Status Types

```typescript
// src/types/status.ts
type RiskStatus = 'low' | 'medium' | 'high' | 'critical';
type HealthStatus = 'healthy' | 'degraded' | 'unhealthy';
type SystemStatus = 'online' | 'degraded' | 'offline';
```

### UI Status Contract

```typescript
// src/config/constants.ts
export const STATUS_TYPES = {
  ONLINE: "online",
  DEGRADED: "degraded", 
  OFFLINE: "offline",
  GOOD: "good",
  WARNING: "warning",
  BAD: "bad",
} as const;
```

### Conversion Functions

```typescript
// Convert domain status to UI status
function convertRiskStatus(risk: RiskStatus): keyof typeof STATUS_TYPES {
  switch (risk) {
    case 'low': return 'GOOD';
    case 'medium': return 'WARNING';
    case 'high': case 'critical': return 'BAD';
    default: return 'OFFLINE';
  }
}
```

### Component Usage

```typescript
import StatusIndicator from '../components/StatusIndicator';
import { STATUS_TYPES } from '../config/constants';

// StatusIndicator expects keyof typeof STATUS_TYPES
<StatusIndicator status={STATUS_TYPES.GOOD} size="md" />
```

---

## Column/Table Pattern

All tables use typed columns with `Row` interface and `keyof Row` for type-safe column definitions.

### Row Interface

```typescript
interface Agent {
  id: string;
  name: string;
  status: string;
  pnl: number;
  lastActive: string;
}

type ColumnKey = keyof Agent; // 'id' | 'name' | 'status' | 'pnl' | 'lastActive'
```

### Column Definition

```typescript
import { DataTableColumn } from '../components/DataTableEnhanced';

const columns: DataTableColumn<Agent>[] = [
  { key: 'name', header: 'Name', sortable: true },
  { key: 'status', header: 'Status', render: (value) => <StatusIndicator status={value} /> },
  { key: 'pnl', header: 'PnL', align: 'right', format: (v) => formatCurrency(v) },
  { key: 'lastActive', header: 'Last Active', sortable: true },
];
```

### DataTableEnhanced Props

```typescript
interface DataTableColumn<Row> {
  key: keyof Row;
  header: string;
  sortable?: boolean;
  align?: 'left' | 'right' | 'center';
  render?: (value: Row[keyof Row], row: Row) => React.ReactNode;
  format?: (value: Row[keyof Row]) => string;
}

interface DataTableEnhancedProps<Row> {
  data: Row[];
  columns: DataTableColumn<Row>[];
  pageSize?: number;
  showPagination?: boolean;
  showFilter?: boolean;
  showSelection?: boolean;
  onRowSelect?: (row: Row) => void;
  className?: string;
}
```

---

## WebSocket Pattern

Native WebSocket with layered hooks. No direct socket.io usage in components.

### Layer Architecture

```
Components
    ↓
useMeridSocket() - Socket.io-like API (emit/on/off)
    ↓
useWebSocket() - Native WebSocket management
    ↓
WebSocket (Browser API)
```

### useWebSocket (Base Layer)

```typescript
// Returns stable socket reference and connection state
const { socket, connected, lastMessage, error, send } = useWebSocket({
  url: WS_URL,
  autoConnect: true,
});
```

### useMeridSocket (Adapter Layer)

```typescript
// Provides Socket.io-like API
const { socket, connected } = useMeridSocket();

socket?.emit('subscribe_prices', ['BTC-USD']);
socket?.on('price_tick', handlePriceTick);
socket?.off('price_tick', handlePriceTick);
```

### Component Usage

```typescript
function PriceFeed() {
  const { socket, connected } = useMeridSocket();
  const [prices, setPrices] = useState<PriceData[]>([]);

  useEffect(() => {
    if (!socket) return;
    
    const handleUpdate = (data: PriceData) => {
      setPrices(prev => [...prev, data]);
    };
    
    socket.on('price_update', handleUpdate);
    return () => socket.off('price_update', handleUpdate);
  }, [socket]);

  return (
    <div>
      <StatusIndicator status={connected ? 'ONLINE' : 'OFFLINE'} />
      {/* Render prices */}
    </div>
  );
}
```

---

## Null Safety

Explicit guards and defaults. Minimal use of non-null assertions (`!`).

### API Data Guards

```typescript
const { data, loading, error } = useApiData<Agent[]>(API_ENDPOINTS.AGENTS);

// Always provide default
const safeAgents: Agent[] = data ?? [];

// Guard in JSX
{safeAgents.length > 0 ? (
  <DataTableEnhanced data={safeAgents} columns={columns} />
) : (
  <EmptyState message="No agents found" />
)}
```

### WebSocket Guards

```typescript
const { socket, connected } = useMeridSocket();

// Check socket exists before use
useEffect(() => {
  if (!socket) return;  // Guard clause
  
  socket.emit('subscribe', { channel: 'prices' });
  
  return () => {
    socket.emit('unsubscribe', { channel: 'prices' });
  };
}, [socket]);
```

### Chart/Canvas Guards

```typescript
const canvas = document.getElementById("equityChart") as HTMLCanvasElement | null;
if (!canvas) return;

const ctx = canvas.getContext("2d");
if (!ctx) return;

// Now safe to use ctx
const chart = new Chart(ctx, config);
```

### Optional Chaining + Defaults

```typescript
// For nested optional properties
const tickColor = chart.options?.scales?.x?.ticks?.color ?? '#9ca3af';

// For conditional rendering
{agentDetail?.metrics?.map(m => (
  <MetricCard key={m.label} {...m} />
)) ?? <LoadingState />}
```

---

## Utils Contracts

### Formatters

```typescript
// formatDelta returns structured object
export interface DeltaFormatted {
  value: string;    // Formatted absolute change (+$23.45)
  percent: string;  // Formatted percent change (+23.45%)
  color: string;    // Tailwind class (text-green-500)
  icon: string;     // Unicode arrow (↑↓→)
}

export function formatDelta(
  value: number, 
  baseline?: number, 
  mode?: 'percent' | 'value'
): DeltaFormatted;

// Other formatters
formatCurrency(value: number, currency?: string, digits?: number): string;
formatPercent(value: number, digits?: number): string;  // Multiplies by 100
formatDate(iso: string | Date, format?: 'readable' | 'relative' | 'MM/DD/YYYY'): string;
formatFileSize(bytes: number, unitType?: 'binary'): string;  // binary = KiB, MiB
```

### Validators

```typescript
export interface ValidationResult {
  valid: boolean;
  error?: string;      // Single error message
  errors?: string[];   // Multiple errors (for aggregates)
  message?: string;    // Legacy/alias for error
}

// Basic validators
validateSymbol(symbol: string | null | undefined): ValidationResult;
validateSize(size: string | number, options?: SizeOptions | number): ValidationResult;
validatePrice(price: string | number, options?: PriceOptions): ValidationResult;
validateLeverage(leverage: string | number, options?: LeverageOptions | number): ValidationResult;

// Options interfaces
interface SizeOptions { minSize?: number; maxSize?: number; }
interface PriceOptions { maxPrecision?: number; }
interface LeverageOptions { maxLeverage?: number; }

// Composite validator
validateOrderTicket(order: OrderInput, options?: { maxSize?: number }): ValidationResult;
// Returns aggregated errors[] for multiple failures
```

### Order Input Contract

```typescript
interface OrderInput {
  symbol: string;
  side: string;
  orderType: string;  // Not 'type' - must be orderType
  size: string | number;
  price?: string | number;
  venue: string;
}
```

---

## Testing Patterns

### Component Tests

```typescript
// No React import needed (JSX transform)
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import StatusIndicator from '../StatusIndicator';

describe('StatusIndicator', () => {
  it('renders with correct status', () => {
    render(<StatusIndicator status="ONLINE" />);
    expect(screen.getByText('Online')).toBeInTheDocument();
  });
});
```

### Hook Tests

```typescript
// Use RTL's renderHook, not react-hooks
import { renderHook, act } from '@testing-library/react';
import { useLocalStorage } from '../useLocalStorage';

describe('useLocalStorage', () => {
  it('reads initial value', () => {
    const { result } = renderHook(() => 
      useLocalStorage('key', 'default')
    );
    expect(result.current[0]).toBe('default');
  });
});
```

### Mock Patterns

```typescript
// WebSocket mock in setupTests.ts
class MockWebSocket {
  constructor(_url: string) {  // Prefix unused params with _
    setTimeout(() => {
      if (this.onopen) this.onopen(new Event('open'));
    }, 0);
  }
  send = jest.fn();
  close = jest.fn();
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
}
```

---

## Enforcement

### Pre-Commit Checks

```bash
# package.json scripts
"typecheck": "tsc --noEmit",
"lint": "eslint src --ext .ts,.tsx",
"test": "jest"
```

### CI Requirements

All PRs must pass:
- `npm run typecheck` (0 errors)
- `npm run lint` (no warnings)
- `npm test` (all tests pass)

### Adding New Patterns

When introducing new patterns:
1. Type them strictly
2. Add to this document
3. Update existing code to match
4. Never weaken types to "fix" errors

---

*Last updated: January 30, 2026*
