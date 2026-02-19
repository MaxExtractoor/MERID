# MERID Frontend Contribution Guide

A concise guide for contributing to the MERID React frontend while maintaining architectural consistency.

## Prerequisites

- Node.js 20.x
- TypeScript strict mode familiarity
- React 18+ and hooks patterns
- Read `ARCHITECTURE.md` before starting

## Quick Start

```bash
cd web/react
npm ci
npm run type-check:ci  # Must pass before committing (baseline-aware)
npm test            # Check for regressions
```

---

## Adding a New View

### 1. Define Your Data Types

```typescript
// src/views/MyFeature.tsx

// Domain type from API
interface MyFeatureData {
  id: string;
  name: string;
  status: 'active' | 'inactive' | 'error';  // Domain status
  value: number;
  timestamp: string;
}

// Convert domain status to UI status
type MyFeatureStatus = 'active' | 'inactive' | 'error';

function convertMyFeatureStatus(status: MyFeatureStatus): keyof typeof STATUS_TYPES {
  switch (status) {
    case 'active': return 'ONLINE';
    case 'inactive': return 'OFFLINE';
    case 'error': return 'BAD';
    default: return 'OFFLINE';
  }
}
```

### 2. Define Table Columns (if needed)

```typescript
import { DataTableColumn } from '../components/DataTableEnhanced';

const columns: DataTableColumn<MyFeatureData>[] = [
  { key: 'name', header: 'Name', sortable: true },
  { 
    key: 'status', 
    header: 'Status',
    render: (value, row) => (
      <StatusIndicator status={convertMyFeatureStatus(value)} size="md" />
    )
  },
  { 
    key: 'value', 
    header: 'Value', 
    align: 'right',
    format: (v) => formatCurrency(v)
  },
  { 
    key: 'timestamp', 
    header: 'Last Updated',
    format: (v) => formatDate(v, 'readable')
  },
];
```

### 3. Use Standard Hooks

```typescript
import { useApiData } from '../hooks/useApiData';
import { useMeridSocket } from '../hooks/useMeridSocket';

export default function MyFeature() {
  // Data fetching
  const { data, loading, error } = useApiData<MyFeatureData[]>(
    API_ENDPOINTS.MY_FEATURE,
    { pollingInterval: DEFAULTS.POLLING_INTERVALS.MY_FEATURE }
  );
  
  // Real-time updates (optional)
  const { socket } = useMeridSocket();
  
  useEffect(() => {
    if (!socket) return;
    socket.on('my_feature_update', handleUpdate);
    return () => socket.off('my_feature_update', handleUpdate);
  }, [socket]);
  
  // Safe data access
  const safeData = data ?? [];
  
  // Render with null guards
  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error.message} />;
  
  return (
    <div className="space-y-4">
      {safeData.length > 0 ? (
        <DataTableEnhanced 
          data={safeData} 
          columns={columns}
          pageSize={10}
        />
      ) : (
        <EmptyState message="No data available" />
      )}
    </div>
  );
}
```

---

## Adding a New Component

### 1. Define Props with Strict Types

```typescript
// src/components/MyComponent.tsx

interface MyComponentProps {
  value: number;
  label: string;
  status: 'good' | 'warning' | 'bad';
  onUpdate?: (value: number) => void;
  className?: string;
}

export default function MyComponent({
  value,
  label,
  status,
  onUpdate,
  className = ''
}: MyComponentProps) {
  // ...
}
```

### 2. Use Established Utilities

```typescript
import { formatCurrency, formatPercent, formatDelta } from '../utils/formatters';
import { validateNumberRange } from '../utils/validators';
import { STATUS_TYPES } from '../config/constants';

// Formatting
const formattedValue = formatCurrency(value);
const delta = formatDelta(current, baseline);

// Validation
const validation = validateNumberRange(input, 0, 100);
if (!validation.valid) {
  showError(validation.error);
}

// Status conversion
const uiStatus = status === 'good' ? STATUS_TYPES.GOOD 
  : status === 'warning' ? STATUS_TYPES.WARNING 
  : STATUS_TYPES.BAD;
```

### 3. Add Test IDs for Testing

```typescript
return (
  <div data-testid="my-component" className={className}>
    <span data-testid="my-component-value">{formattedValue}</span>
    <StatusIndicator 
      data-testid="my-component-status"
      status={uiStatus} 
    />
  </div>
);
```

---

## Adding a New Hook

### 1. Follow Hook Naming and Contracts

```typescript
// src/hooks/useMyHook.ts

import { useState, useEffect, useCallback } from 'react';

interface UseMyHookOptions {
  initialValue?: number;
  enabled?: boolean;
}

interface UseMyHookReturn {
  value: number;
  loading: boolean;
  error: Error | null;
  update: (v: number) => void;
}

export function useMyHook(
  key: string,
  options: UseMyHookOptions = {}
): UseMyHookReturn {
  const { initialValue = 0, enabled = true } = options;
  
  const [value, setValue] = useState(initialValue);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  
  // Wrap async operations properly
  const update = useCallback(async (newValue: number) => {
    setLoading(true);
    try {
      // ... async work
      setValue(newValue);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Unknown error'));
    } finally {
      setLoading(false);
    }
  }, []);
  
  useEffect(() => {
    if (!enabled) return;
    // ... effect logic
  }, [enabled, key]);
  
  return { value, loading, error, update };
}
```

### 2. Add Tests

```typescript
// src/hooks/__tests__/useMyHook.test.tsx

import { renderHook, act, waitFor } from '@testing-library/react';
import { useMyHook } from '../useMyHook';

describe('useMyHook', () => {
  it('initializes with default value', () => {
    const { result } = renderHook(() => useMyHook('test'));
    expect(result.current.value).toBe(0);
    expect(result.current.loading).toBe(false);
    expect(result.current.error).toBeNull();
  });
  
  it('updates value', async () => {
    const { result } = renderHook(() => useMyHook('test'));
    
    await act(async () => {
      await result.current.update(42);
    });
    
    expect(result.current.value).toBe(42);
  });
});
```

---

## CI Checklist

Before creating a PR:

- [ ] `npm run type-check:ci` passes (0 **new** TS errors vs baseline)
- [ ] `npm test` shows no new failing tests
- [ ] If tests fail, add entry to `TEST_DEBT.md`
- [ ] New code follows patterns in `ARCHITECTURE.md`
- [ ] No `any` types without justification
- [ ] No `@ts-ignore` without comment explaining why
- [ ] API response shapes use interfaces from `src/types/api.ts` — no new `Record<string, unknown>`

> **Baseline workflow:** We use [`tsc-baseline`](https://github.com/TimMikeladze/tsc-baseline)
> to gate CI on *new* type errors only. If your PR intentionally fixes legacy
> errors, run `npm run type-check:save` to update the baseline and commit the
> updated `.tsc-baseline.json`.

---

## Common Pitfalls

### ❌ Don't

```typescript
// Don't use any
const data: any = fetchData();

// Don't cast API responses to Record<string, unknown>
const items = (data as Record<string, unknown>).items;  // Use types/api.ts

// Don't ignore null/undefined
const value = data.property;  // data might be null

// Don't use magic strings for status
<span className={status === 'good' ? 'green' : 'red'}>

// Don't create one-off formatters
const formatted = `$${value.toFixed(2)}`;  // Use formatCurrency

// Don't use bare WebSocket
const ws = new WebSocket(url);  // Use useMeridSocket

// Don't use raw console.error in catch blocks
} catch (err) { console.error('fetch failed', err); }  // Use logUiError
```

### ✅ Do

```typescript
// Use specific types (pull shapes into src/types/api.ts)
const data: MyFeatureData | null = await fetchData();

// Guard against null
const value = data?.property ?? defaultValue;

// Use STATUS_TYPES
<StatusIndicator status={STATUS_TYPES.GOOD} />

// Use established formatters
const formatted = formatCurrency(value);

// Use MERID WebSocket adapter
const { socket } = useMeridSocket();

// Use structured logger for errors and warnings
import { logUiError, logUiWarn } from '../utils/logger';
} catch (err) { logUiError('MyComponent', 'Fetch failed', err, { endpoint }); }

// Use toast for user-facing error feedback
import { useToast } from '../components/ToastProvider';
const { toast } = useToast();
toast({ type: 'error', title: 'Connection lost', message: 'Retrying...' });
```

---

## Resources

- `ARCHITECTURE.md` - Full pattern documentation
- `TEST_DEBT.md` - Known test failures
- `src/types/api.ts` - Centralized DTO interfaces for API response shapes
- `src/utils/logger.ts` - Structured UI logger (`logUiError`, `logUiWarn`, `logUiInfo`)
- `src/components/ToastProvider.tsx` - Toast notifications (`useToast` hook)
- `src/utils/formatters.ts` - Formatting utilities
- `src/utils/validators.ts` - Validation utilities
- `src/config/constants.ts` - Status types, endpoints, defaults

---

*Last updated: February 13, 2026*
