# MERID–Kalshi Integration: Current State & TODOs

**Document Version:** 1.0
**Last Updated:** 2026-04-05
**Status:** Active Development
**Repository:** MaxExtractoor/MERID

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Loop-Lag Policy: Telemetry Only, No Halt Coupling](#loop-lag-policy-telemetry-only-no-halt-coupling)
3. [Architecture Overview](#architecture-overview)
4. [Current State by Component](#current-state-by-component)
5. [High-Priority Issues (No Halt Coupling)](#high-priority-issues-no-halt-coupling)
6. [End-to-End Audit Checklist](#end-to-end-audit-checklist)
7. [Mode Semantics](#mode-semantics)
8. [Health & Monitoring](#health--monitoring)
9. [Testing & Validation](#testing--validation)
10. [References](#references)

---

## Executive Summary

This document captures the **current state** of the MERID–Kalshi integration and outlines the **immediate work items** required to reach production readiness. It explicitly codifies the **non-halting loop-lag policy**: event loop lag monitoring serves as **operator-facing telemetry only** and does **not** trigger automatic trading halts, throttling, or kill-switch activation.

### Current Integration Status

✅ **Complete** — Core trading pipeline operational
✅ **Complete** — Crypto market coverage (BTC, ETH, SOL, XRP, DOGE × 5 timeframes)
✅ **Complete** — Settlement polling with cursor-based deduplication
✅ **Complete** — Bankroll invariant tracking (warning-only)
✅ **Complete** — Event loop lag monitoring (telemetry-only, non-blocking)
🔶 **In Progress** — CT status API (`_profile` bug fix)
🔶 **In Progress** — Kalshi async reliability (event loop binding, timeout hardening)
🔶 **In Progress** — Settlement pagination duplicate-key bug
🔶 **In Progress** — SOL crypto coverage wiring
🔶 **In Progress** — Reconciliation & position cache alignment

### Production Readiness

**Risk Rating:** MEDIUM (reduced from MEDIUM-HIGH after recent fixes)
**Blockers:** 5 high-priority issues detailed below
**Target:** Production-ready after addressing CT status API, settlement dedup, SOL wiring, and reconciliation semantics

---

## Loop-Lag Policy: Telemetry Only, No Halt Coupling

### Design Philosophy

Event loop lag monitoring is **observability infrastructure**, not a trading control signal. Lag can spike due to legitimate operational patterns (batch operations, database queries, API retries) that do not represent risk to trading quality or correctness.

### Explicit Non-Halt Policy

| Component | Behavior | Rationale |
|-----------|----------|-----------|
| **Loop-Lag Monitor** | Logs WARN/ERROR/CRITICAL at 200ms/500ms/1000ms thresholds | Operator visibility for performance tuning |
| **Trading Execution** | "WARN only, trading continues" — no automatic halts | Lag ≠ trading risk; venue health is a separate signal |
| **Kill Switch** | No wiring from loop-lag monitor | Execution gate uses explicit risk signals (PnL, position limits, venue health) |
| **Throttling** | No auto-throttling based on lag alone | Prevents false-positive starvation; operator decides on load reduction |
| **Health Endpoints** | Loop-lag stats surfaced via `/api/health/event_loop` | UI can show "loop lag high, check machine load" without blocking trading |

### Implementation Details

**File:** `observability/event_loop_monitor.py`

```python
# EventLoopMonitor configuration
sample_interval_ms: float = 100.0
warn_threshold_ms: float = 200.0   # WARN log, no action
crit_threshold_ms: float = 500.0   # ERROR log, no action
profile_threshold_ms: float = 500.0  # Capture stack trace for analysis
```

**Logging Pattern:**

```
[WARN] Event loop lag: 237ms (threshold: 200ms) — WARN only, trading continues
[ERROR] Event loop lag: 523ms (threshold: 500ms) — WARN only, trading continues
[CRITICAL] Event loop lag: 1042ms (threshold: 1000ms) — WARN only, trading continues
```

### Recommended Operator Use

1. **Performance Dashboard:** Display P95/P99 lag in UI alongside tick processing latency
2. **Alerting:** Alert ops team if P95 > 500ms for sustained 5-minute window (investigate machine load, not halt trading)
3. **Profiling:** Use high-lag profiles (`HighLagProfile` captured at >500ms) to identify blocking coroutines for optimization
4. **Correlation Analysis:** Cross-reference lag spikes with venue WS disconnects, API timeouts, settlement ingestion batches

### What Should Trigger Halts Instead

The execution gate (`core/execution_gate.py`) uses **explicit, domain-specific risk signals**:

- **PnL drawdown** beyond configured thresholds
- **Position limit breaches** (per-market, per-group, portfolio-wide)
- **Venue health failures** (WS disconnected, API 5xx errors, order reject rate)
- **Reconciliation criticals** (balance/position mismatch with Kalshi REST API)
- **Manual kill-switch** activation by operator

Loop-lag is **correlated** with some of these (e.g., tight retry loops on API timeouts may spike lag), but treating lag as a root cause would conflate **symptoms** (slow event loop) with **causes** (venue degradation, code bugs).

---

## Architecture Overview

### Trading Pipeline (8 Phases)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ 1. DISCOVER   → KalshiMarketCatalog + MarketFilter                       │
│                 Identifies tradable markets, enriches with metadata       │
├──────────────────────────────────────────────────────────────────────────┤
│ 2. ANALYZE    → OpinionStrategy (model_prob generation)                  │
│                 Computes edge = model_prob - implied_prob                 │
├──────────────────────────────────────────────────────────────────────────┤
│ 3. CONSENSUS  → SwarmConsensusAggregator (optional multi-agent blend)    │
│                 Aggregates opinions across archetypes, adaptive quorum    │
├──────────────────────────────────────────────────────────────────────────┤
│ 4. SIZE       → Kelly sizing with group notional caps                    │
│                 Vetos: edge_too_low, negative_kelly, bankroll_says_0     │
├──────────────────────────────────────────────────────────────────────────┤
│ 5. EXECUTE    → KalshiVenueClient order submission                       │
│                 Resilient API calls, circuit breaker, RSA signing         │
├──────────────────────────────────────────────────────────────────────────┤
│ 6. MONITOR    → Fill ingestion, position updates, PnL tracking           │
│                 KalshiFillsLedger, reconciliation, bankroll invariant     │
├──────────────────────────────────────────────────────────────────────────┤
│ 7. PROMOTE    → Canary → staging → production deployment                 │
│                 Edge profile graduation (initial_live → production)       │
├──────────────────────────────────────────────────────────────────────────┤
│ 8. PROTECT    → Kill switch, execution gate, risk limits                 │
│                 Explicit halt signals (PnL, positions, venue health)      │
└──────────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | File | Purpose |
|-----------|------|---------|
| **Continuous Trader** | `merid/trading/kalshi_continuous_trader.py` | Core trading loop, candidate evaluation, sizing |
| **Market Catalog** | `merid/event_venues/kalshi/market_catalog.py` | Market discovery via Kalshi API |
| **Market Filter** | `merid/event_venues/kalshi/market_filter.py` | Quality filtering, metadata enrichment |
| **Venue Client** | `merid/event_venues/kalshi/client.py` | Kalshi REST API wrapper with resilience |
| **Settlement Poller** | `merid/event_venues/kalshi/settlement_poller.py` | Cursor-driven settlement ingestion |
| **Fills Ledger** | `merid/event_venues/kalshi/fills_ledger.py` | Fill tracking, deduplication |
| **Reconciliation** | `merid/reconciliation.py` | Position/balance cross-check vs Kalshi |
| **Execution Gate** | `core/execution_gate.py` | Pre-trade risk checks, kill-switch integration |
| **Event Loop Monitor** | `observability/event_loop_monitor.py` | Lag tracking (telemetry-only, non-blocking) |

---

## Current State by Component

### 1. Continuous Trader (CT)

**Status:** ✅ Operational with 5 known issues

**Features:**
- ✅ Trade cycle refreshes candidates every iteration
- ✅ Per-asset/timeframe edge thresholds (crypto_kalshi_risk.py)
- ✅ Kelly sizing with group notional caps
- ✅ Bankroll invariant tracking (warning-only)
- ✅ Last-cycle diagnostics exposed via `/api/v1/ct/status`

**Known Issues:**
- 🔴 **CT-001:** `_status_snapshot_inner` throws `NameError: _profile not defined` (blocks UI status endpoint)

**Files:**
- `merid/trading/kalshi_continuous_trader.py` (primary implementation)
- `merid/event_venues/kalshi/crypto_kalshi_risk.py` (risk parameters)
- `tests/trading/test_kalshi_continuous_trader.py` (unit tests)

### 2. Market Discovery

**Status:** ✅ Operational, SOL wiring issue

**Coverage:**
- ✅ BTC, ETH, SOL, XRP, DOGE detection via regex patterns
- ✅ Timeframes: 15m, 1h, daily, weekly, monthly
- ✅ Quality filters: volume, OI, spread, price_band

**Known Issues:**
- 🔴 **CRYPTO-002:** SOL markets discovered but filtered out: `raw=1 ... expiry_out=1` → 0 tradeable markets

**Files:**
- `merid/event_venues/kalshi/market_catalog.py`
- `merid/event_venues/kalshi/market_filter.py`

### 3. Settlement Poller

**Status:** 🔶 Operational with duplicate-key bug

**Features:**
- ✅ Cursor-based pagination with Redis persistence
- ✅ Idempotent settlement ingestion via `_seen_ids` set
- ✅ Auto-start wired into `web/main.py` startup/shutdown
- ✅ Settlement hooks update CT bankroll via `record_trade_result(pnl_cents)`

**Known Issues:**
- 🔴 **SETTLE-001:** `[SETTLEMENT-DUPE] Duplicate key: @` error in pagination logic

**Files:**
- `merid/event_venues/kalshi/settlement_poller.py`
- `merid/reconciliation.py` (settlement hooks)
- `tests/event_venues/kalshi/test_settlement_poller.py`

### 4. Kalshi Async Client

**Status:** 🔶 Operational with event-loop reliability issues

**Features:**
- ✅ Resilient API calls with retries, circuit breaker, rate limiting
- ✅ RSA signing for POST/PUT/DELETE requests
- ✅ WebSocket market data subscriptions

**Known Issues:**
- 🔴 **ASYNC-001:** "Event attached to a different loop" errors under load
- 🔴 **ASYNC-002:** `get_positions()`, `get_fills()`, `get_market()` timeout failures

**Files:**
- `merid/event_venues/kalshi/client.py`
- `merid/event_venues/kalshi/ws_client.py`

### 5. Reconciliation

**Status:** 🔶 Operational with truth-source ambiguity

**Features:**
- ✅ Position cache vs Kalshi REST comparison
- ✅ Balance tracking vs venue API
- ✅ PnL cross-check with fills ledger

**Known Issues:**
- 🔴 **RECON-001:** Position cache shows `0 REST positions` vs non-zero internal positions
- 🔴 **RECON-002:** Discover-health reports "green" with incomplete/size-0 fills

**Files:**
- `merid/reconciliation.py`
- `tests/test_reconciliation.py`

### 6. Event Loop Monitoring

**Status:** ✅ Fully operational (telemetry-only)

**Features:**
- ✅ P50/P95/P99 lag statistics
- ✅ High-lag profiling (captures stack traces at >500ms)
- ✅ Ring buffer for UI display
- ✅ Health endpoint: `/api/health/event_loop`

**Policy:** **Non-blocking.** Lag does not halt trading. See [Loop-Lag Policy](#loop-lag-policy-telemetry-only-no-halt-coupling).

**Files:**
- `observability/event_loop_monitor.py`
- `web/api/health.py` (health endpoint integration)

---

## High-Priority Issues (No Halt Coupling)

### CT-001: CT Status Snapshot Bug

**Severity:** 🔴 HIGH
**Impact:** UI cannot display CT status; `/api/v1/kalshi/continuous-trader/status` returns 500 error

**Description:**
`NameError` in `_status_snapshot_inner()` due to undefined `_profile` variable.

**Fix Requirements:**
1. Define `_profile` in `KalshiContinuousTrader.__init__()` (e.g., `self._profile = {}`)
2. Add unit test: `test_status_snapshot_returns_valid_json()`
3. Verify `/api/v1/kalshi/continuous-trader/status` returns complete JSON for UI

**Halt Behavior:** None (informational API only)

**Files:** `merid/trading/kalshi_continuous_trader.py`, `web/api/ct_api.py`

---

### ASYNC-001/002: Kalshi Async Reliability

**Severity:** 🔴 HIGH
**Impact:** Intermittent failures under load; positions/fills not synced reliably

**Description:**
Event loop binding issues ("attached to different loop") and timeouts on `get_positions()`, `get_fills()`, `get_market()`.

**Fix Requirements:**
1. Tighten concurrency model: **one event loop per client instance**
2. Harden timeout/retry logic with exponential backoff
3. Add load tests: `test_get_positions_under_concurrent_load()`
4. Ensure all async calls use `await` (no detached tasks)

**Halt Behavior:** None; failures visible via health endpoints, but **no automatic halt**. Operators use `/api/health/kalshi/client` to assess venue health and decide on manual intervention.

**Files:** `merid/event_venues/kalshi/client.py`, `tests/event_venues/kalshi/test_client.py`

---

### SETTLE-001: Settlement Pagination Duplicate-Key Bug

**Severity:** 🔴 HIGH
**Impact:** Settlement ingestion may fail or skip records; PnL tracking incomplete

**Description:**
`[SETTLEMENT-DUPE] Duplicate key: @` error suggests pagination logic reprocesses same cursor or merges duplicates incorrectly.

**Fix Requirements:**
1. Fix pagination in `_fetch_settlements()` to avoid reprocessing same page
2. Strengthen deduplication: `if settlement_id in self._seen_ids: continue`
3. Add idempotent reconciliation test: `test_duplicate_settlement_ingestion_is_idempotent()`
4. Expose reconciliation status via `/api/health/settlement_poller`

**Halt Behavior:** None; only explicit kill-switch can halt trading. Settlement errors are **logged and reported** but do not auto-halt.

**Files:** `merid/event_venues/kalshi/settlement_poller.py`

---

### CRYPTO-002: SOL Crypto Coverage Wiring

**Severity:** 🔴 HIGH
**Impact:** SOL markets discovered but not tradeable; 0 candidates post-filtering

**Description:**
`[CRYPTO-WIRING-BUG] asset=SOL ... raw=1 ... expiry_out=1` → all SOL markets filtered out despite discovery.

**Root Cause Hypothesis:**
- Expiry window too narrow (e.g., 2h–48h for 15m markets, excludes SOL markets with different expiry patterns)
- Near-spot filter too tight (e.g., requires strike within 5% of spot, but SOL markets have wider strikes)

**Fix Requirements:**
1. Adjust `get_spot_band()` for SOL to allow wider strike ranges
2. Relax expiry filters in `MarketFilter` for SOL (e.g., 1h–72h for 15m)
3. Add asset coverage tests: `test_sol_markets_not_filtered_out()`, `test_all_crypto_assets_have_tradeables()`
4. Verify end-to-end: `[CRYPTO-WIRING-BUG]` log should not appear for SOL after fix

**Halt Behavior:** None (coverage issue, not execution risk)

**Files:** `merid/event_venues/kalshi/market_filter.py`, `merid/event_venues/kalshi/crypto_kalshi_risk.py`

---

### RECON-001/002: Reconciliation & Position Cache Semantics

**Severity:** 🔶 MEDIUM
**Impact:** Operators cannot trust position cache vs REST; "green" health is misleading

**Description:**
- Position cache shows `0 REST positions` despite non-zero internal positions
- Discover-health reports "green" with incomplete fills (e.g., `size=0`)

**Fix Requirements:**
1. **Clarify truth source:** Kalshi REST API is ground truth; internal cache is derivative
2. Align position cache update logic with venue data: `cache[ticker] = rest_positions[ticker]` (not vice versa)
3. Tighten "green" criteria in `/api/health/discover`:
   - ❌ Green if `fill.size == 0`
   - ❌ Green if `|cache_position - rest_position| > 1 contract`
   - ✅ Green only if: REST positions match internal, no incomplete fills, balance delta < $5
4. Add cross-check endpoint: `/api/reconciliation/status` (REST vs ledger vs CT bankroll)

**Halt Behavior:** None; reconciliation warnings are informational. Only **critical discrepancies** (defined as balance drift >$100 or position mismatch >10 contracts) are escalated to execution gate.

**Files:** `merid/reconciliation.py`, `web/api/health.py`

---

## End-to-End Audit Checklist

| Area | Concrete Tasks | Status | Halt Behavior |
|------|---------------|--------|---------------|
| **CT Status API** | Fix `_profile` bug, add `test_status_snapshot()`, verify UI endpoint | 🔶 In Progress | None (informational only) |
| **Event Loop Diagnostics** | Keep WARN/ERROR/CRITICAL logging, surface in UI, tag runs with max lag | ✅ Complete | **None; "WARN only, trading continues" retained** |
| **Kalshi Positions/Fills Client** | Fix event-loop binding bug, harden timeouts/retries, add load tests | 🔶 In Progress | None; failures visible via health endpoints |
| **Settlement Ingestion** | Fix dupe-key pagination, add idempotent reconciliation checks | 🔶 In Progress | None; only explicit kill-switch can halt |
| **Crypto Coverage** | Resolve SOL wiring, assert coverage across all configured assets | 🔶 In Progress | None |
| **Mode Semantics** | Document DRY-RUN vs LIVE vs paper ladder, enforce in CT and APIs | 🔴 TODO | None |
| **Reconciliation** | Document algorithm, add cross-check endpoint (REST vs ledger vs CT) | 🔶 In Progress | None (warning-only unless critical) |
| **Health Endpoints** | Refine discover-health logic, ensure "green" reflects real trading state | 🔶 In Progress | None |
| **Monitoring/UI** | Centralize surfacing of loop-lag, WS disconnects, retries, settlement errors | 🔴 TODO | None |

---

## Mode Semantics

### Operational Modes

| Mode | Behavior | Execution | Settlement | Reconciliation | Halt on Error |
|------|----------|-----------|------------|----------------|---------------|
| **DRY-RUN** | Paper trading, no real orders | Simulated (no Kalshi API calls) | Disabled | Position cache only | No |
| **PAPER** | Paper trading with venue data | Simulated (CT intent logged but not executed) | Disabled | Cache vs simulated fills | No |
| **LIVE-CANARY** | Real trading, micro-size (1 contract max) | Real Kalshi orders | Enabled | Full REST reconciliation | Yes (on critical discrepancy) |
| **LIVE-PRODUCTION** | Real trading, full sizing | Real Kalshi orders | Enabled | Full REST reconciliation | Yes (on critical discrepancy) |

### Mode Configuration

**Environment Variables:**
```bash
MERID_MODE=LIVE               # LIVE, PAPER, DRY-RUN
CT_EDGE_PROFILE=production    # initial_live, production
CT_MAX_GROUP_NOTIONAL=50.00   # dollars (per group per session)
```

**Edge Profiles:**

| Profile | Min Edge | Min Confidence | Max YES Price | Group Notional Cap |
|---------|----------|----------------|---------------|---------------------|
| `initial_live` | 0.5-2% | 0.52 | 0.65 | $10 |
| `production` | 2-8% | 0.55 | 0.50 | $50 |

**Files:** `merid/trading/kalshi_continuous_trader.py`, `merid/event_venues/kalshi/crypto_kalshi_risk.py`

---

## Health & Monitoring

### Health Endpoints

| Endpoint | Purpose | Fail Condition | Halt on Fail? |
|----------|---------|----------------|---------------|
| `/api/health` | Global system health | Any subsystem critical | **No** (informational aggregate) |
| `/api/health/event_loop` | Loop-lag stats (P95, P99, profiles) | P95 > 1000ms for 10min | **No** (telemetry-only) |
| `/api/health/settlement_poller` | Settlement cursor, poll count, dupe errors | Cursor stuck for 30min | No (manual intervention) |
| `/api/health/kalshi/client` | Venue API health (circuit breaker, retry rate) | Circuit open for 5min | No (venue degradation doesn't auto-halt) |
| `/api/v1/ct/status` | CT last-cycle diagnostics | N/A | No (informational) |
| `/api/reconciliation/status` | Position/balance cross-check | Critical discrepancy | **Yes** (execution gate blocks if critical) |

### Monitoring Best Practices

1. **Dashboard:** Display loop-lag P95 alongside tick processing latency, WS message rate, API retry rate
2. **Alerting:** Alert ops if:
   - Loop-lag P95 > 500ms for 5min (investigate machine load, not halt)
   - Settlement cursor stuck >30min (check Kalshi API health)
   - WS disconnected >3 reconnects/min (venue issue)
   - Reconciliation critical discrepancy (auto-halted by execution gate)
3. **Profiling:** Use `/api/health/event_loop/profiles/summary` to identify blocking coroutines during lag spikes
4. **Correlation:** Cross-reference loop-lag with venue health, settlement batch size, reconciliation runs

---

## Testing & Validation

### Unit Tests

| Test Suite | Coverage | Command |
|------------|----------|---------|
| CT core logic | `test_kalshi_continuous_trader.py` | `pytest tests/trading/test_kalshi_continuous_trader.py` |
| Settlement poller | `test_settlement_poller.py` | `pytest tests/event_venues/kalshi/test_settlement_poller.py` |
| Reconciliation | `test_reconciliation.py` | `pytest tests/test_reconciliation.py` |
| Event loop monitor | `test_event_loop_monitor.py` | `pytest tests/observability/test_event_loop_monitor.py` |
| Crypto coverage | `test_crypto_kalshi_risk.py` | `pytest tests/event_venues/kalshi/test_crypto_kalshi_risk.py` |

### Integration Tests

**Paper Gate** (`scripts/run_paper_gate.py`):
- 30-minute paper trading session with early-stop on failure rate
- Auto-fetches profiling data on early stop
- Validates: CT cycle stats, settlement ingestion, reconciliation, loop-lag telemetry

**Recommended Test Plan:**
1. Run paper gate in `DRY-RUN` mode (no Kalshi API)
2. Run paper gate in `PAPER` mode (Kalshi API for venue data, simulated execution)
3. Run 1-hour LIVE-CANARY session (real orders, 1 contract max)
4. Verify:
   - No `[CT-001]` errors (status snapshot)
   - No `[SETTLEMENT-DUPE]` errors
   - SOL markets appear in candidates (not filtered out)
   - Loop-lag P95 < 500ms
   - Reconciliation "green" with no critical discrepancies

---

## References

### Related Documentation

- **[CT_E2E_AUDIT.md](./CT_E2E_AUDIT.md):** Complete pipeline trace (signals → CT → orders → fills)
- **[KALSHI_INTEGRATION_AUDIT_REPORT_2026.md](./KALSHI_INTEGRATION_AUDIT_REPORT_2026.md):** 8-phase adversarial audit, 19 HIGH + 27 MEDIUM findings
- **[BANKROLL_INVARIANT_DESIGN.md](./BANKROLL_INVARIANT_DESIGN.md):** Bankroll invariant formula, settlement hooks
- **[SETTLEMENT_POLLER_VERIFICATION.md](./SETTLEMENT_POLLER_VERIFICATION.md):** Settlement poller verification guide
- **[CRYPTO_COVERAGE_COMPLETE.md](./CRYPTO_COVERAGE_COMPLETE.md):** Asset/timeframe coverage matrix
- **[PRE_LIVE_CHECKLIST.md](./PRE_LIVE_CHECKLIST.md):** Production readiness checklist

### Key Files

| Component | Primary File | Tests |
|-----------|-------------|-------|
| Continuous Trader | `merid/trading/kalshi_continuous_trader.py` | `tests/trading/test_kalshi_continuous_trader.py` |
| Market Filter | `merid/event_venues/kalshi/market_filter.py` | `tests/event_venues/kalshi/test_market_filter.py` |
| Settlement Poller | `merid/event_venues/kalshi/settlement_poller.py` | `tests/event_venues/kalshi/test_settlement_poller.py` |
| Reconciliation | `merid/reconciliation.py` | `tests/test_reconciliation.py` |
| Event Loop Monitor | `observability/event_loop_monitor.py` | `tests/observability/test_event_loop_monitor.py` |
| Execution Gate | `core/execution_gate.py` | `tests/core/test_execution_gate.py` |

### Environment Configuration

**Critical Environment Variables:**
```bash
# Mode
MERID_MODE=LIVE                      # LIVE, PAPER, DRY-RUN
CT_EDGE_PROFILE=production           # initial_live, production

# Risk Limits
CT_MAX_GROUP_NOTIONAL=50.00          # dollars per group per session
CT_MIN_CONFIDENCE=0.55               # production: 0.55, initial_live: 0.52
CT_MAX_YES_PRICE=0.50                # production: 0.50, initial_live: 0.65

# Loop-Lag (Telemetry Only)
EVENT_LOOP_SAMPLE_INTERVAL_MS=100    # default: 100
EVENT_LOOP_WARN_THRESHOLD_MS=200     # WARN log (no halt)
EVENT_LOOP_CRIT_THRESHOLD_MS=500     # ERROR log (no halt)

# Settlement
SETTLEMENT_POLL_INTERVAL_S=60        # default: 60
SETTLEMENT_CURSOR_REDIS_KEY=merid:kalshi:settlement_cursor

# Reconciliation
RECONCILIATION_CRITICAL_BALANCE_DELTA=100.00  # dollars (halt if exceeded)
RECONCILIATION_CRITICAL_POSITION_DELTA=10     # contracts (halt if exceeded)
```

---

## Appendix: Loop-Lag vs Trading Halt Decision Matrix

| Scenario | Loop-Lag | Venue Health | Position/PnL | Action |
|----------|----------|--------------|--------------|--------|
| Normal operation | P95: 50ms | WS connected, API latency <500ms | Within limits | ✅ Trade normally, log lag stats |
| Machine overload | P95: 800ms | WS connected, API latency <500ms | Within limits | ⚠️ **Log WARN, trade continues**. Alert ops to investigate machine load. |
| Venue degradation | P95: 50ms | WS disconnected, API latency >2s | Within limits | 🛑 **Halt trading** (venue health critical, not lag) |
| Mixed: high lag + venue issue | P95: 1200ms | WS disconnected, API timeout spikes | Within limits | 🛑 **Halt trading** (venue health critical). Investigate lag spike as secondary issue. |
| Reconciliation critical | P95: 50ms | WS connected, API latency <500ms | Balance drift >$100 | 🛑 **Halt trading** (reconciliation critical, not lag) |
| PnL breach | P95: 50ms | WS connected, API latency <500ms | Daily loss >$500 | 🛑 **Halt trading** (PnL critical, not lag) |

**Key Insight:** Loop-lag is **never** the primary halt signal. It's a **symptom** to investigate, not a **cause** to block trading.

---

**Document Owner:** Quantitative Engineering Team
**Feedback:** Open an issue at [github.com/MaxExtractoor/MERID/issues](https://github.com/MaxExtractoor/MERID/issues)
**Last Audit:** 2026-04-05
