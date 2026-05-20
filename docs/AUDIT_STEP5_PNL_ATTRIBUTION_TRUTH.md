# Audit Step 5: PnL, Attribution, and Truth

**Date:** 2026-05-12  
**Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute contracts  
**Purpose:** Verify venue reconciliation, per-trade attribution, and strategy performance tracking

---

## Venue Reconciliation

### Portfolio Reconciler
**File:** `merid/event_venues/kalshi/portfolio_reconciliation.py`  
**Purpose:** Continuous reconciliation loop against Kalshi API  
**Interval:** 5 minutes (configurable via `MERID_PORTFOLIO_RECONCILIATION_INTERVAL_SECONDS`)

**Reconciliation Components:**
- Cash tolerance: 1 cent (configurable)
- PnL tolerance: 10 cents (configurable)
- Position tolerance: 0 contracts (exact match required)
- Discrepancy persistence: 2 cycles before alert (configurable)

**Design Principles:**
- Kalshi API is control/sanity-check, not primary state
- Reconcile every N minutes (configurable)
- Alert only when discrepancies exceed thresholds and persist
- Store reconciliation results for investigation

**Status:** ✅ Portfolio reconciliation exists with configurable tolerances

---

### Venue Reconciler
**File:** `merid/reconciliation/venue_reconciler.py`  
**Purpose:** Generic venue reconciliation interface

**Status:** ✅ Generic venue reconciler exists

---

### Kalshi Reconciler
**File:** `merid/reconciliation/kalshi_reconciler.py`  
**Purpose:** Kalshi-specific reconciliation implementation

**Status:** ✅ Kalshi-specific reconciler exists

---

## Per-Trade Attribution

### PnL Attribution
**File:** `merid/prediction/pnl_attribution.py`  
**Purpose:** Track per-trade PnL attribution

**Status:** ✅ Per-trade PnL attribution exists

---

### PnL Attribution Database
**File:** `merid/prediction/pnl_attribution_db.py`  
**Purpose:** Database persistence for PnL attribution

**Status:** ✅ PnL attribution database exists

---

### Fills Ledger
**File:** `merid/event_venues/kalshi/fills_ledger.py`  
**Purpose:** Track all fills for attribution

**Status:** ✅ Fills ledger exists

---

### Sentiment PnL Attribution
**File:** `merid/sentiment/sentiment_pnl_attribution.py`  
**Purpose:** Sentiment-specific PnL attribution

**Status:** ✅ Sentiment PnL attribution exists

---

### Hedge PnL Tracker
**File:** `merid/hedging/pnl_tracker.py`  
**Purpose:** Track hedge PnL for attribution

**Status:** ✅ Hedge PnL tracker exists

---

## Strategy Performance

### Agent Performance Tracker
**File:** `merid/prediction/agent_performance_tracker.py`  
**Purpose:** Track agent performance metrics

**Metrics Tracked:**
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Profit factor
- Win rate
- Average win/loss
- Drawdown

**Status:** ✅ Agent performance tracker exists

---

### Portfolio PnL Computer
**File:** `merid/event_venues/kalshi/portfolio_pnl_computer.py`  
**Purpose:** Compute portfolio PnL from fills

**Status:** ✅ Portfolio PnL computer exists

---

### Portfolio Engine
**File:** `merid/event_venues/kalshi/portfolio_engine.py`  
**Purpose:** Manage portfolio state and PnL

**Status:** ✅ Portfolio engine exists

---

## Critical Findings

### 🟢 INFO: Comprehensive Reconciliation Infrastructure

**Positive:** Multiple layers of reconciliation exist

**Implementation:**
- Portfolio reconciler (continuous against Kalshi API)
- Generic venue reconciler
- Kalshi-specific reconciler
- Configurable tolerances (cash, PnL, positions)
- Discrepancy persistence before alerting

---

### 🟢 INFO: Per-Trade Attribution Infrastructure

**Positive:** Multiple attribution tracking mechanisms

**Implementation:**
- PnL attribution (general)
- PnL attribution database
- Fills ledger
- Sentiment PnL attribution
- Hedge PnL tracker

---

### 🟢 INFO: Strategy Performance Tracking

**Positive:** Comprehensive performance metrics

**Metrics:**
- Sharpe ratio
- Sortino ratio
- Calmar ratio
- Profit factor
- Win rate
- Average win/loss
- Drawdown

---

### 🟡 WARNING: Reconciliation Interval is 5 Minutes

**Issue:** Portfolio reconciliation runs every 5 minutes by default

**Impact:** Discrepancies may not be detected for up to 5 minutes

**Risk:** Low-Medium - Could miss short-lived discrepancies

**Recommendation:** Consider reducing to 1-2 minutes for faster detection

---

## Missing Capabilities

### 1. Cross-Venue Reconciliation
**Current:** Kalshi-specific reconciliation only  
**Needed:** Cross-venue reconciliation if multiple venues are used

---

### 2. Real-Time PnL Attribution
**Current:** PnL attribution computed periodically  
**Needed:** Real-time PnL attribution per trade

---

### 3. Strategy-Level Attribution
**Current:** Agent-level attribution  
**Needed:** Strategy-level attribution (e.g., band strategy vs momentum)

---

## Next Steps for Step 5

1. ✅ Identify reconciliation infrastructure - DONE
2. ✅ Identify attribution infrastructure - DONE
3. ✅ Identify performance tracking - DONE
4. ⏳ Sample real reconciliation results - NEED PRODUCTION DATA
5. ⏳ Verify per-trade attribution accuracy - NEED PRODUCTION DATA

---

## Summary

**Obviously Broken:**
- None found in this step

**Probably Fine:**
- Portfolio reconciliation exists with configurable tolerances
- Generic venue reconciler exists
- Kalshi-specific reconciler exists
- Per-trade PnL attribution exists
- PnL attribution database exists
- Fills ledger exists
- Sentiment PnL attribution exists
- Hedge PnL tracker exists
- Agent performance tracker exists
- Portfolio PnL computer exists
- Portfolio engine exists

**Weird/Unclear:**
- Reconciliation interval is 5 minutes (could be faster)
- No cross-venue reconciliation (Kalshi-specific only)
- No real-time PnL attribution (periodic only)
- No strategy-level attribution (agent-level only)
