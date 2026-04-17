# UI Mock Data Audit - Complete Analysis

**Date:** February 5, 2026  
**Status:** 🔴 **CRITICAL - Extensive Mock Data Usage Found**

---

## Executive Summary

Despite fixing 7 components earlier, **the majority of the UI is still using fallback mock data**. Every major section has hardcoded fallback data that displays when API calls fail or return errors.

---

## Sections Using Mock/Fallback Data

### 1. **Overview/Dashboard** 🔴
**File:** `web/react/src/views/Overview.tsx`

**Mock Data Found:**
- Portfolio summary (equity, P&L, positions)
- Watchlist prices (BTC, ETH, SOL, AAPL, NVDA)
- Recent activity/orders

**Lines:**
```typescript
// Line 129-133: Fallback portfolio data
setSummary({
  equity: 1284732.45,
  dailyPnl: 12847.32,
  // ...
});

// Line 144-148: Fallback watchlist
setWatchlist([
  { symbol: 'BTC-USD', price: 43256.78, change: 2.34, volume: '1.2B' },
  // ...
]);

// Line 159-163: Fallback activity
setRecentActivity([
  { time: '10:23:45', action: 'BUY BTC', size: '0.5', price: '43256.78' },
  // ...
]);
```

---

### 2. **Wallet** 🔴
**File:** `web/react/src/views/Wallet.tsx`

**Mock Data Found:**
- Wallet balances (USD, BTC, ETH, SOL)
- Available/locked/total amounts
- Recent transactions

**Lines:**
```typescript
// Line 51-66: Fallback wallet data
setWalletData({
  balances: [
    { currency: 'USD', available: 125430.50, locked: 5000.00, total: 130430.50 },
    { currency: 'BTC', available: 2.5, locked: 0.1, total: 2.6 },
    // ...
  ],
  recent_transactions: [...]
});
```

**Warning Display:** Line 184 shows "Using fallback data" message

---

### 3. **Treasury** 🔴
**File:** `web/react/src/views/Treasury.tsx`

**Mock Data Found:**
- Total treasury value ($2.45M)
- Asset balances
- Allocation percentages
- Historical performance

**Lines:**
```typescript
// Line 72-95: Fallback treasury data
setTreasuryData({
  total_value_usd: 2450000,
  balances: [
    { asset: 'BTC', amount: 15.5, value_usd: 670000, allocation_pct: 27.3 },
    { asset: 'ETH', amount: 250.0, value_usd: 558500, allocation_pct: 22.8 },
    // ...
  ]
});
```

**Warning Display:** Line 228 shows "Using fallback data" message

---

### 4. **Betting/Markets** 🔴
**File:** `web/react/src/views/Betting.tsx`

**Mock Data Found:**
- Prediction markets
- Odds and probabilities
- Positions and P&L
- Market categories

**Lines:**
```typescript
// Line 73-111: Fallback betting markets
setMarkets([
  {
    id: '1',
    question: 'Will Bitcoin reach $50,000 by end of Q1 2024?',
    category: 'Crypto',
    yes_odds: 1.65,
    no_odds: 2.30,
    // ...
  }
]);
```

**Warning Display:** Line 250 shows "Using fallback data" message

---

### 5. **Mining** 🔴
**File:** `web/react/src/views/Mining.tsx`

**Mock Data Found:**
- Mining rigs status
- Hashrate and power consumption
- Profitability metrics
- Pool connections

**Lines:**
```typescript
// Line 67-92: Fallback mining data
setRigs([
  {
    id: '1',
    name: 'Rig Alpha',
    status: 'active',
    hashrate: '125 MH/s',
    power: 850,
    // ...
  }
]);
```

**Warning Display:** Line 193 shows "Using fallback data" message

---

### 6. **Social Feed** 🔴
**File:** `web/react/src/views/Social.tsx`

**Mock Data Found:**
- Social media posts
- Sentiment analysis
- Trending topics
- User interactions

**Lines:**
```typescript
// Line 64-100: Fallback social posts
setPosts([
  {
    id: '1',
    author: 'CryptoWhale',
    content: 'Major BTC accumulation detected...',
    sentiment: 'bullish',
    // ...
  }
]);
```

**Warning Display:** Line 216 shows "Using fallback data" message

---

### 7. **Plugins** 🔴
**File:** `web/react/src/views/Plugins.tsx`

**Mock Data Found:**
- Installed plugins
- Plugin status and versions
- Configuration settings
- Marketplace plugins

**Lines:**
```typescript
// Line 54-85: Fallback plugins data
setPlugins([
  {
    id: '1',
    name: 'Advanced Charting',
    version: '2.1.0',
    status: 'active',
    // ...
  }
]);
```

**Warning Display:** Line 233 shows "Using fallback data" message

---

### 8. **Institutional** 🔴
**File:** `web/react/src/views/Institutional.tsx`

**Mock Data Found:**
- Institutional accounts
- AUM (Assets Under Management)
- Performance metrics
- Client information

**Lines:**
```typescript
// Line 74-106: Fallback institutional data
setAccounts([
  {
    id: '1',
    name: 'Hedge Fund Alpha',
    type: 'hedge_fund',
    aum: 125000000,
    // ...
  }
]);
```

**Warning Display:** Line 257 shows "Using fallback data" message

---

## Components Already Fixed ✅

1. ReflectionPanel
2. ConsensusPanel
3. DriftDetectionPanel
4. PaperTradingPanel
5. SimulationControlPanel
6. AgentReasoningPanel
7. PerformanceAnalyticsDashboard
8. Agents view (Bots & Agents section)

---

## Root Cause Analysis

### Why Mock Data is Displaying

1. **API endpoints don't exist** - Many endpoints called by views return 404 or 500
2. **Catch blocks have fallback data** - Every try/catch has hardcoded mock data
3. **No error propagation** - Errors are caught and hidden with fake data
4. **Missing backend implementations** - Many features not implemented in backend

### Pattern Found

```typescript
try {
  const response = await fetch('/api/v1/some/endpoint');
  if (response.ok) {
    const data = await response.json();
    setData(data);
  }
} catch (err) {
  setError(err.message);
  // 🔴 PROBLEM: Fallback mock data
  setData({
    // Hardcoded fake data here
  });
}
```

---

## Fix Strategy

### Phase 1: Remove All Mock Data Fallbacks ⚠️

**For each view file:**
1. Remove fallback mock data from catch blocks
2. Keep error state only
3. Display proper error messages instead of fake data

### Phase 2: Implement Missing Backend Endpoints 🔧

**Need to create:**
- `/api/v1/wallet/balances` - Wallet data
- `/api/v1/treasury/overview` - Treasury data
- `/api/v1/betting/overview` - Betting markets (already exists but may need fixes)
- `/api/v1/mining/overview` - Mining rigs data
- `/api/v1/social/feed` - Social feed data
- `/api/v1/plugins/list` - Plugins data
- `/api/v1/institutional/overview` - Institutional accounts

### Phase 3: Update Views to Use api.ts Service 🔄

**For each view:**
1. Import `api` from `../services/api`
2. Add methods to `api.ts` for missing endpoints
3. Replace raw `fetch()` with `api.method()` calls
4. Remove try/catch fallback data

---

## Immediate Actions Required

### Critical Files to Fix (Priority Order)

1. **Overview.tsx** - Main dashboard, most visible
2. **Wallet.tsx** - Core functionality
3. **Treasury.tsx** - Financial data
4. **Betting.tsx** - Prediction markets (key feature)
5. **Social.tsx** - Social feed
6. **Mining.tsx** - Mining operations
7. **Plugins.tsx** - Plugin system
8. **Institutional.tsx** - Institutional features

---

## Backend Endpoints Status

### Existing (Working) ✅
- `/api/agents/summary`
- `/api/system/health`
- `/api/v1/reflection/*`
- `/api/v1/consensus/*`
- `/api/v1/simulation/*`
- `/api/v1/paper/*`

### Missing (Need Implementation) 🔴
- `/api/v1/wallet/balances`
- `/api/v1/treasury/overview`
- `/api/v1/mining/overview`
- `/api/v1/social/feed`
- `/api/v1/plugins/list`
- `/api/v1/institutional/overview`

### Partially Working (Need Fixes) ⚠️
- `/api/v1/betting/overview` - Exists but may return errors
- `/api/portfolio/summary` - Exists but may have issues
- `/api/prices/live` - Exists but may have issues
- `/api/orders/recent` - Exists but may have issues

---

## Estimated Work

**To remove all mock data and implement real endpoints:**

- **Frontend fixes:** 8 view files × 30 min = 4 hours
- **Backend endpoints:** 6 new endpoints × 1 hour = 6 hours
- **Testing:** 2 hours
- **Total:** ~12 hours of work

---

## Recommendation

**Option 1: Quick Fix (Remove Mock Data)**
- Remove all fallback mock data immediately
- Show proper error states
- Users see "No data available" instead of fake data
- **Time:** 2 hours

**Option 2: Full Fix (Implement Real Endpoints)**
- Implement all missing backend endpoints
- Update frontend to use real data
- Remove all mock data
- **Time:** 12 hours

**Option 3: Hybrid Approach**
- Fix high-priority sections first (Overview, Wallet, Treasury)
- Leave low-priority sections with "Coming Soon" placeholders
- **Time:** 4-6 hours

---

## Summary

**Current State:** 🔴 **8 major sections using mock data**  
**Fixed Sections:** ✅ **8 components using real data**  
**Mock Data Lines:** ~500+ lines of hardcoded fake data  
**User Impact:** High - Users cannot trust any data they see  

**Next Step:** Choose fix strategy and begin implementation.
