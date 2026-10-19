# Frontend Contributing Guide

> Patterns and anti-patterns established during the March 2026 UI audit.
> These rules are enforced by custom ESLint rules in `.eslintrc.custom.js`.

---

## 1. Null-Safe Numeric Formatting

**Rule**: Always guard `.toFixed()` with `?? 0` when the value comes from API data or hook state.

```tsx
// BAD — NaN if price is null/undefined
<span>{(o.price * 100).toFixed(0)}¢</span>

// GOOD
<span>{((o.price ?? 0) * 100).toFixed(0)}¢</span>
```

**Why**: API responses from `useApiData` can return `null` fields. Destructuring defaults (`= 0`) only cover `undefined`, not `null`.

---

## 2. Stable Hook Dependencies

**Rule**: Never pass a full `useApiData` result object as a `useEffect` / `useCallback` / `useMemo` dependency. Extract the specific property you need first.

```tsx
// BAD — posResult is a new object every render → infinite loop
useEffect(() => { posResult.refetch(); }, [posResult]);

// GOOD — refetch is stable (memoized inside useApiData)
const posRefetch = posResult.refetch;
useEffect(() => { posRefetch(); }, [posRefetch]);
```

**ESLint**: `no-unstable-hook-deps` flags any dep ending in `Result`.

---

## 3. No `window.location.reload()` After Success

**Rule**: After a successful mutation (cancel order, mode switch, etc.), call targeted `refetch()` functions instead of reloading the page.

```tsx
// BAD — kills WS connections, resets all UI state
onSuccess={() => { setTimeout(() => window.location.reload(), 1000); }}

// GOOD
onSuccess={() => { ordRefetch(); fillRefetch(); posRefetch(); }}
```

**ESLint**: `no-window-reload` flags `window.location.reload()` outside `ErrorBoundary` files.

**Exception**: Error boundaries and feature-flag recovery actions may use reload as a last resort.

---

## 4. Click Target Isolation

**Rule**: Never nest informational panels inside a clickable element that triggers a destructive action (kill switch, emergency stop, etc.).

```tsx
// BAD — clicking sizing metrics triggers kill switch confirm
<div onClick={handleKillSwitch}>
  <span>LIVE</span>
  <div className="sizing-panel">...</div>  {/* clicks bubble up */}
</div>

// GOOD — sizing panel is a sibling
<div onClick={handleKillSwitch}>
  <span>LIVE</span>
</div>
<div className="sizing-panel">...</div>
```

---

## 5. WebSocket Hooks: Use Refs for Options

**Rule**: If a WebSocket hook uses `useEffect(fn, [])` (mount-only), store caller-provided options in a ref so reconnect logic always reads the latest values.

```tsx
const optionsRef = useRef(options);
optionsRef.current = options;

useEffect(() => {
  // Inside connect(): use optionsRef.current.authToken, not options.authToken
}, []);
```

**Why**: Empty dep arrays capture stale closures. After token rotation, the WS would reconnect with the old token.

---

## 6. Memoize Context Helpers

**Rule**: If a context hook exposes helper functions derived from state, wrap them in `useCallback` with the relevant state as a dependency.

```tsx
// BAD — new function identity every render
const hasCriticalAlerts = () => (ctx?.alerts?.critical || 0) > 0;

// GOOD
const hasCriticalAlerts = useCallback(
  () => (ctx?.alerts?.critical || 0) > 0,
  [ctx]
);
```

---

## 7. Collection Transforms on Nested Records

**Rule**: `Object.values(record).flat()` is a no-op if the record's values are objects (not arrays). Use `flatMap` for nested `Record<string, Record<string, T>>`.

```tsx
// BAD — flat() on array of objects does nothing
Object.values(matrix).flat().find(cell => cell.agent === id);

// GOOD
Object.values(matrix).flatMap(row => Object.values(row)).find(cell => cell.agent === id);
```

---

## Quick CI Grep Checks

These one-liners can be added to CI as a lint gate:

```bash
# No window.location.reload in views
! grep -rn 'window\.location\.reload' src/views/ --include='*.tsx'

# No full Result objects in hook dep arrays
! grep -Pn '\b\w+Result\b' src/views/ --include='*.tsx' | grep -P '\], \[.*Result'

# No .flat() on Object.values (likely nested Record bug)
! grep -rn 'Object\.values.*\.flat()' src/ --include='*.tsx'
```

---

## Files Modified in the Audit

| File | Fixes |
|---|---|
| `views/KalshiTerminalView.tsx` | UI-001, UI-007, UI-009 |
| `views/KalshiPortfolioView.tsx` | UI-002, UI-004, UI-009 |
| `views/KalshiGridView.tsx` | UI-003, UI-004 |
| `views/KalshiDashboardView.tsx` | UI-006, UI-008, UI-010 |
| `hooks/useKalshiRiskStream.ts` | UI-005 |
| `hooks/useDebateContext.ts` | Memoization |
| `components/HeaderStats.tsx` | Null-safety |
| `components/KalshiCryptoSignalsPanel.tsx` | Null-safety |
| `components/KalshiPaperVsShadowPanel.tsx` | Null-safety |
| `components/PerformanceDashboard.tsx` | Null-safety |
