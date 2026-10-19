# UI Crash Triage Plan

## Overview
This document defines reproducible failure journeys for the MERID frontend to systematically identify and fix UI crashes.

## Progress Summary
- **Step 1 (Failure Journeys):** ✅ Complete - 5 journeys defined
- **Step 2 (Crash Signatures):** ⏸️ Pending - Requires browser access
- **Step 3 (Guardrails):** ✅ Complete - Error boundaries added
- **Step 4 (Debug Buckets):** ⏸️ Pending - Requires browser access
- **Step 5 (Live Data):** ✅ Complete - Defensive coding added
- **Step 6 (Performance):** ⏸️ Pending
- **Step 7 (Regression Tests):** ⏸️ Pending

## Failure Journey Definitions

### Journey 1: App Load with Backend Offline
**Description:** User loads the application when the backend server is completely unreachable.

**Steps:**
1. Start with backend server stopped (or network blocked)
2. Open browser to `http://localhost:5173` (dev) or production URL
3. Observe initial render and error handling
4. Check Console for errors
5. Check Network tab for failed requests
6. Verify ErrorBoundary displays degraded state
7. Verify UI doesn't go completely white

**Expected Crash Points:**
- `useApiData` hooks failing on initial data fetch
- Portfolio client WebSocket connection failing
- Missing data causing null dereferences in views
- Auth token refresh attempts failing

**Current Guardrails:**
- ErrorBoundary wraps each view (App.tsx:196)
- useApiData has error state and backendOffline flag
- Portfolio client has exponential backoff reconnection
- Token refresh logic in useApiData (lines 112-153)

---

### Journey 2: Main Trading Flow (Overview → Execute → Monitor)
**Description:** User navigates through the core trading workflow with live data.

**Steps:**
1. Load Overview view
2. Navigate to Execute view
3. Select a market ticker
4. Submit a trade (paper mode)
5. Navigate to Monitor view
6. Check Portfolio tab for position
7. Check PnL tab for equity curve
8. Return to Overview

**Expected Crash Points:**
- Portfolio WebSocket disconnect during navigation
- Market data API returning malformed JSON
- Position data missing required fields (ticker, side, quantity)
- PnL chart receiving null/undefined data points
- Navigation state updates causing race conditions

**Current Guardrails:**
- Portfolio client handles delta messages and snapshot merging
- useApiData has transform function for data shaping
- Views use optional chaining (`portfolio?.positions`)
- ErrorBoundary per-view isolation

---

### Journey 3: WebSocket Reconnection During Active Session
**Description:** WebSocket connection drops and reconnects while user is actively using the app.

**Steps:**
1. Load app and let it connect to portfolio WebSocket
2. Navigate to Monitor view (Portfolio tab)
3. Kill backend WebSocket server
4. Observe reconnection attempts in Console
5. Restart WebSocket server
6. Verify data resumes correctly
7. Check for duplicate data or stale state

**Expected Crash Points:**
- Portfolio client attempting to merge delta into null snapshot
- Reconnection triggering multiple concurrent fetch requests
- Stale data not being detected after reconnection
- Subscriber callbacks throwing errors during reconnection
- State updates from old messages arriving after reconnection

**Current Guardrails:**
- Portfolio client has generation counter to discard stale responses
- Exponential backoff (1s → 30s max)
- Max 10 reconnection attempts before giving up
- Heartbeat with stale data detection (60s threshold)
- Subscriber error handling with try/catch (portfolioClient.ts:398-403)

---

### Journey 4: Rapid View Navigation with Polling
**Description:** User rapidly switches between views while multiple API hooks are polling.

**Steps:**
1. Load Overview view (triggers multiple useApiData hooks)
2. Quickly click: Execute → Monitor → Positions → Overview
3. Repeat navigation 5-10 times rapidly
4. Observe console for warnings/errors
5. Check for memory leaks (Chrome DevTools Memory profiler)
6. Verify no "Too many re-renders" errors

**Expected Crash Points:**
- Polling intervals not being cleaned up on unmount
- Abort controllers not being cancelled
- Multiple concurrent requests to same endpoint
- State updates from stale requests after component unmount
- React useEffect dependency array issues causing infinite loops

**Current Guardrails:**
- useApiData has abort controller with 10s timeout
- Cleanup function clears timers and aborts requests (useApiData.ts:245-262)
- Generation counter discards stale responses
- Polling interval ref nulled before setting new timer (useApiData.ts:215)

---

### Journey 5: Malformed API Response
**Description:** Backend returns unexpected data structure or malformed JSON.

**Steps:**
1. Mock backend endpoint to return malformed JSON
2. Navigate to view that consumes that endpoint
3. Observe error handling
4. Check if view crashes or displays degraded state
5. Verify ErrorBoundary catches the error
6. Check Console for specific error messages

**Expected Crash Points:**
- JSON.parse() failing silently
- Transform function receiving unexpected structure
- Views assuming fields exist (e.g., `data.positions.map()`)
- Type mismatches between expected and actual data
- Missing null checks before array/object operations

**Current Guardrails:**
- useApiData has try/catch around JSON parsing (line 159)
- Transform function allows custom data shaping
- ErrorBoundary catches render errors
- Some views use optional chaining, but not consistently

---

## High-Risk Components Identified

### 1. Portfolio Client (portfolioClient.ts)
- **Risk:** WebSocket message parsing failure (line 233)
- **Risk:** Delta merge with null snapshot (line 347)
- **Risk:** Subscriber callback errors (line 398)
- **Mitigation:** Has error handling, but subscriber errors are logged but don't trigger ErrorBoundary

### 2. useApiData Hook (useApiData.ts)
- **Risk:** Token refresh failure (line 152)
- **Risk:** AbortError not being handled in all paths (line 172)
- **Risk:** Polling timer cleanup race condition (line 215)
- **Mitigation:** Good error handling overall, generation counter prevents stale updates

### 3. Overview View (Overview.tsx)
- **Risk:** Portfolio data null dereferences
- **Risk:** KalshiHealthCard data assumptions
- **Risk:** RebootControlPanel state updates
- **Mitigation:** Uses portfolio subscription, but some legacy API calls may not be defensive

### 4. ExecuteView (ExecuteView.tsx)
- **Risk:** Order status badge with undefined status
- **Risk:** Market selection with null ticker
- **Risk:** Position mapping with missing fields
- **Mitigation:** Uses optional chaining in some places, but not consistently

### 5. PositionsView (PositionsView.tsx)
- **Risk:** Position filtering with undefined ticker
- **Risk:** Sorting with null/undefined values
- **Risk:** Legacy API calls (risk, gridPortfolio) may fail
- **Mitigation:** Has null checks in useMemo, but could be more defensive

### 6. MonitorView (MonitorView.tsx)
- **Risk:** PnL chart with null data points
- **Risk:** Health status parsing failures
- **Risk:** Portfolio state updates during tab switch
- **Mitigation:** Uses portfolio subscription, but chart components may not handle null data

---

## Next Steps (Step 2: Capture and Classify Crash Signatures)

1. Run each failure journey in Chrome DevTools
2. Record Console errors with full stack traces
3. Record Network tab failures (404, 500, timeouts)
4. Export HAR files for timing analysis
5. Group errors by signature (same error message + similar stack)
6. Document user-visible impact per crash bucket
7. Note frequency (every time vs edge case)
8. Identify which crashes block core trading flows

---

## Step 3: Guardrails Implementation Summary

### Error Boundaries Added
**App.tsx** - Enhanced error boundary coverage:
- Main view ErrorBoundary now uses `enhanced={true}` mode with retry enabled (max 3 retries)
- Added ErrorBoundary around Sidebar component (non-enhanced mode for layout stability)
- Added ErrorBoundary around TopBar component (non-enhanced mode)
- Added ErrorBoundary around StatusBanners (RealtimeDisconnectedBanner, ExecutionBlockedBanner, OfflineIndicator)

### Defensive Coding Added

**portfolioClient.ts** - Subscriber error isolation:
- Enhanced `notifySubscribers()` with explicit error handling
- Subscriber callback errors are logged but don't crash other subscribers
- Added comment explaining error isolation strategy

**PositionsView.tsx** - Position mapping defensive coding:
- Added array type check: `!Array.isArray(portfolio.positions)`
- Added object type check: `p && typeof p === 'object'`
- Added null coalescing for all numeric fields: `p.quantity || 0`, `p.avg_entry_price_cents || 0`, etc.
- Added default values for string fields: `p.side || 'unknown'`

**ExecuteView.tsx** - Position mapping defensive coding:
- Same defensive pattern as PositionsView
- Added null coalescing for instrument_id, ticker, side, contracts, prices
- Ensures position rendering doesn't crash on malformed data

**MonitorView.tsx** - Portfolio subscription error handling:
- Wrapped portfolio update callback in try/catch
- Logs errors without crashing the component
- Prevents malformed updates from taking down the Monitor view

**Overview.tsx** - Cleanup:
- Removed unused portfolio subscription (was causing lint errors)
- Temporarily passed empty array to KalshiPositionsCard (legacy positions fetch is commented out)
- Note: Full portfolio migration to Overview is deferred to avoid breaking changes

### Key Design Principles Applied
1. **Error Isolation:** One component crash doesn't take down the entire app
2. **Defensive Defaults:** All numeric fields use `|| 0`, strings use `|| 'unknown'`
3. **Type Checking:** Verify arrays and objects before accessing properties
4. **Graceful Degradation:** Show empty states or partial data rather than crash
5. **Logging:** All errors are logged to console for debugging

### Remaining Guardrails Gaps
- Chart components (KalshiPnlChart, etc.) may need null data handling
- WebSocket reconnection UI feedback could be improved
- Some legacy API calls don't have shape validation
- Overview view positions card needs proper portfolio data integration
