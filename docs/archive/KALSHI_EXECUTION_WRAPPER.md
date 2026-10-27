# MERID Kalshi Fills Integration — Execution + Verification Wrapper
## Ship-to-Prod Checklist

---

## 1) Implementation Tasks (Flat Checklist)

### Ledger Locking & Core Instrumentation
- [ ] LEDGER_LOCK_01 — fills_ledger.py — Replace `threading.Lock()` with `threading.RLock()` in `__init__`
- [ ] LEDGER_LOCK_02 — fills_ledger.py — Wrap `add_fill()` body with `with self._lock:`
- [ ] LEDGER_LOCK_03 — fills_ledger.py — Wrap `_update_cached_position()` with `with self._lock:`
- [ ] LEDGER_LOG_01 — fills_ledger.py — Add structured logging for NEW fill (result, fill_id, ticker, side, size, price, source)
- [ ] LEDGER_LOG_02 — fills_ledger.py — Add structured logging for DUPLICATE fill (result, fill_id, existing_seq, source)
- [ ] LEDGER_LOG_03 — fills_ledger.py — Add structured logging for REJECTED fill (result, fill_id, reason, source)
- [ ] LEDGER_METRIC_01 — fills_ledger.py — Add `fills_new_total` Counter with labels [source]
- [ ] LEDGER_METRIC_02 — fills_ledger.py — Add `fills_duplicate_total` Counter with labels [source]
- [ ] LEDGER_METRIC_03 — fills_ledger.py — Add `fills_invalid_total` Counter with labels [reason]
- [ ] LEDGER_UNIT_01 — tests/ — Unit test: concurrent `add_fill()` with same fill_id → exactly 1 NEW, rest DUPLICATE

### Pagination & Cursor Continuity
- [ ] POLLER_STATE_01 — fills_poller.py — Add SQLite `poller_state` table schema (last_cursor, last_poll_time, last_fill_id, continuity_verified)
- [ ] POLLER_GAP_01 — fills_poller.py — Store `_last_seen_fill_id` and `_last_seen_ts` in `_poll_once()`
- [ ] POLLER_GAP_02 — fills_poller.py — Detect gap: if `page[0].fill_id != _last_seen_fill_id` → log warning + increment metric
- [ ] POLLER_GAP_03 — fills_poller.py — Detect out-of-order: if page timestamps not sorted → log warning + increment metric
- [ ] POLLER_GAP_04 — fills_poller.py — Log `fills_poller.hit_page_limit` when `len(page) == 100`
- [ ] POLLER_METRIC_01 — fills_poller.py — Add `fills_pagination_gaps_total` Counter
- [ ] POLLER_METRIC_02 — fills_poller.py — Add `fills_pagination_out_of_order_total` Counter
- [ ] POLLER_METRIC_03 — fills_poller.py — Add `fills_pagination_hit_limit_total` Counter
- [ ] POLLER_STARTUP_01 — fills_poller.py — On `start()`, load persisted state; decide trust/cursor_reset based on age
- [ ] POLLER_STARTUP_02 — fills_poller.py — Add `fills_cursor_continuous` Gauge (1 if verified, 0 otherwise)

### TOCTOU Observability
- [ ] TOCTOU_01 — fills_ledger.py — Add `_batch_write_in_progress` flag in `add_fill_batch()`
- [ ] TOCTOU_02 — fills_ledger.py — Add `_reads_during_batch` counter in `get_position()`
- [ ] TOCTOU_03 — fills_ledger.py — Log every 10th read during batch: `ledger.toctou_detected` with `READ_DURING_BATCH_WRITE`
- [ ] TOCTOU_METRIC_01 — fills_ledger.py — Add `fills_toctou_reads_total` Counter

### Position Reconciliation Job
- [ ] RECON_01 — prediction/ — Create `PositionReconciliationJob` class with `RUN_INTERVAL = 300`
- [ ] RECON_02 — prediction/ — Implement `_reconstruct_positions()` from fills (last 24h)
- [ ] RECON_03 — prediction/ — Compare vs live positions endpoint; log discrepancy with expected/actual/delta
- [ ] RECON_04 — prediction/ — Add `fills_recon_discrepancies_total` Counter with labels [type]
- [ ] RECON_05 — prediction/ — Wire job into background task lifecycle (start/stop with app)
- [ ] RECON_UNIT_01 — tests/ — Unit test: injected fill sequence → reconstructed position matches expected

---

## 2) Minimal Verification Runs

### Group A: Ledger Locking & add_fill Instrumentation
**Scenario:** Audit Narrative #2 (Single Leg, Single Fill) with rapid WS+HTTP overlap  
**Parameters:** Inject same fill_id via HTTP poller and WebSocket within 100ms window  

**Observables:**
| What | Logger/Metric | Key Fields |
|------|--------------|------------|
| NEW fill | `ledger.add_fill` | `result=NEW`, `fill_id`, `source=HTTP\|WS` |
| DUPLICATE fill | `ledger.add_fill` | `result=DUPLICATE`, `fill_id`, `source` |
| Counter | `fills_new_total` | Should increment by 1 |
| Counter | `fills_duplicate_total` | Should increment by 1 |

**PASS/FAIL:** PASS if exactly 1 NEW and 1 DUPLICATE logged for same fill_id, and `fills_new_total` + `fills_duplicate_total` sum to 2.

---

### Group B: Pagination Gap & Cursor Continuity
**Scenario:** Audit Narrative #4 (TOCTOU / Rapid Trade Burst) — simulate 250 fills in 30 seconds  
**Parameters:** Page size 100, poll interval 20s  

**Observables:**
| What | Logger/Metric | Key Fields |
|------|--------------|------------|
| Page limit hit | `fills_poller.hit_page_limit` | `cursor`, `count=100`, `pagination_depth` |
| Gap detected | `fills_poller.gap_detected` | `expected_first_id`, `actual_first_id` |
| Metric | `fills_pagination_hit_limit_total` | Should be ≥2 (250 fills = 3 pages) |
| Cursor health | `fills_cursor_continuous` | Should be 1 after successful poll |

**PASS/FAIL:** PASS if `hit_page_limit` logged at least twice, `fills_cursor_continuous=1` within 60s of startup, and no `gap_detected` when pages are contiguous.

---

### Group C: Hit Page Limit & TOCTOU Tripwires
**Scenario:** Audit Narrative #5 (Stuck Cursor Simulation) with concurrent position queries  
**Parameters:** 50 parallel `get_position()` calls during `add_fill_batch()` of 100 fills  

**Observables:**
| What | Logger/Metric | Key Fields |
|------|--------------|------------|
| TOCTOU detected | `ledger.toctou_detected` | `event=READ_DURING_BATCH_WRITE`, `ticker`, `batch_reads_total` |
| Metric | `fills_toctou_reads_total` | Should be ≥5 (every 10th read) |
| Page limit | `fills_poller.hit_page_limit` | Must include `from_ts`, `to_ts`, `total_collected` |

**PASS/FAIL:** PASS if TOCTOU logs appear with `batch_reads_total` incrementing, and `fills_toctou_reads_total` non-zero.

---

### Group D: Position Reconciliation Job
**Scenario:** Audit Narrative #3 (Multiple Legs Across Markets) — 3 markets, 10 fills each, mixed sides  
**Parameters:** Run reconciliation job manually or wait for 5-min interval  

**Observables:**
| What | Logger/Metric | Key Fields |
|------|--------------|------------|
| Recon OK | `recon.ok` | `ticker`, `size` |
| Discrepancy | `recon.discrepancy` | `ticker`, `expected_size`, `actual_size`, `delta`, `last_fill_id` |
| Metric | `fills_recon_discrepancies_total` | Must be 0 for all labels |

**PASS/FAIL:** PASS if `fills_recon_discrepancies_total=0` and `recon.ok` logs for all 3 markets with correct reconstructed sizes.

---

## 3) Observability Stack Wiring

### Loggers
| Logger Name | File | Purpose | Must-Have? |
|-------------|------|---------|------------|
| `merid.kalshi.fills.ledger` | fills_ledger.py | All fill ingestion events | **MUST** — incident response |
| `merid.kalshi.fills.poller` | fills_poller.py | Pagination, gaps, cursor | **MUST** — incident response |
| `merid.kalshi.fills.recon` | prediction/recon_job.py | Position reconciliation | **MUST** — data integrity |

### Log Format (Structured JSON)
```json
{
  "timestamp": "2026-03-30T12:00:00Z",
  "level": "INFO|WARNING|ERROR",
  "logger": "merid.kalshi.fills.ledger",
  "event": "add_fill|gap_detected|discrepancy",
  "fields": {
    "fill_id": "uuid",
    "market_id": "KXBTCD-2026-03-30",
    "ticker": "BTCUSD",
    "side": "yes|no",
    "size": 10,
    "price": 45.5,
    "source": "HTTP|WS",
    "result": "NEW|DUPLICATE|REJECTED",
    "cursor": "abc123",
    "scenario_tag": "NARRATIVE_2"
  }
}
```

### Prometheus Metrics
| Metric Name | Type | Labels | Must-Have? |
|-------------|------|--------|------------|
| `fills_new_total` | Counter | `venue="kalshi"`, `source="http\|ws"` | **MUST** |
| `fills_duplicate_total` | Counter | `venue="kalshi"`, `source="http\|ws"` | **MUST** |
| `fills_invalid_total` | Counter | `venue="kalshi"`, `reason="incomplete\|missing_id"` | **MUST** |
| `fills_pagination_gaps_total` | Counter | `venue="kalshi"` | **MUST** |
| `fills_pagination_out_of_order_total` | Counter | `venue="kalshi"` | Nice-to-have |
| `fills_pagination_hit_limit_total` | Counter | `venue="kalshi"` | Nice-to-have |
| `fills_cursor_continuous` | Gauge | `venue="kalshi"` | **MUST** |
| `fills_toctou_reads_total` | Counter | `venue="kalshi"` | **MUST** |
| `fills_recon_discrepancies_total` | Counter | `venue="kalshi"`, `type="missing\|size_mismatch"` | **MUST** |

---

## 4) Go/No-Go Gate for Rollout

| Condition | How Verified | Owner |
|-----------|--------------|-------|
| All 21 implementation items checked | PR checklist reviewed by reviewer | PR Author |
| Group A verification run passed | Run Narrative #2, check logs/metrics match expected counts | QA/Dev |
| Group B verification run passed | Run Narrative #4, confirm `fills_cursor_continuous=1` | QA/Dev |
| Group C verification run passed | Run Narrative #5, confirm TOCTOU metrics non-zero | QA/Dev |
| Group D verification run passed | Run Narrative #3, confirm `fills_recon_discrepancies_total=0` | QA/Dev |
| No `gap_detected` at WARN+ in test window | Log scan: `grep "gap_detected" | grep -v "DEBUG"` should return empty | QA |
| No `cursor_inconsistent` at WARN+ in test window | Log scan for `cursor_inconsistent` or `cursor_reset` at WARNING+ | QA |
| No `recon.discrepancy` in test window | Log scan: `grep "recon.discrepancy"` should return empty | QA |
| All MUST-HAVE metrics emitting | Prometheus query: `{__name__=~"fills_.*"}` returns 9 series | SRE |
| Feature flag `kalshi_fills_enhanced` can disable | Confirm flag gates new poller logic, fallback to legacy works | Dev |

**GO Decision:** All conditions pass → Safe to scale to real money.  
**NO-GO Decision:** Any condition fails → Fix, re-run failed verification group, re-assess.

---

## 5) Final Health Summary Format

### Kalshi Integration Health Summary — YYYY-MM-DD

**Current Status:** GREEN / AMBER / RED  
**Justification:** One-line rationale (e.g., "All 5 audit narratives passed, zero invariant violations, 48h production burn-in clean")

---

### Outstanding Known Risks (Max 5)

| Risk | Severity | Status |
|------|----------|--------|
| Network partition >1h forces cursor reset fallback | MEDIUM | Accepted — 1h window covers 99% of cases |
| Kalshi API behavioral change breaks contract | LOW | Mitigated — contract tests in CI |
| Clock skew on fill timestamps causes out-of-order detection | LOW | Accepted — NTP sync required on hosts |
| SQLite contention under >1000 fills/sec | MEDIUM | Mitigated — WAL mode enabled, single writer |
| (Reserve slot) | — | — |

---

### Key Observability Hooks (Top 5 to Watch in Production)

| Metric/Log | Alert Threshold | What It Tells You |
|------------|-----------------|-------------------|
| `fills_recon_discrepancies_total > 0` | Immediate Paging | Ledger vs live positions diverged — data integrity issue |
| `fills_pagination_gaps_total` increasing | Warn at 1, Page at 5 in 5min | Fill loss likely — poller missed trades |
| `fills_cursor_continuous == 0` for >5min | Warn | Cursor continuity broken — may duplicate or miss fills on restart |
| `fills_toctou_reads_total` > 100/min | Warn | Excessive reads during batch writes — consider locking review |
| `fills_new_total` flat for >poll_interval*2 | Warn | Poller stalled — no new fills ingested |

---

### Release Readiness Statement

> Kalshi fills integration is **GO** for real-money scaling.  
> All 21 implementation items merged. 5/5 audit narratives verified.  
> Zero invariant violations in test window. Top 5 observability hooks confirmed emitting.  
> Residual risks accepted and documented.

---

## PR Boundaries (Optional Next Step)

| PR | Scope | Files | Review Focus |
|----|-------|-------|--------------|
| #1 Observability Only | LEDGER_LOG_*, LEDGER_METRIC_*, POLLER_METRIC_* | fills_ledger.py, fills_poller.py | Log format correctness, metric registration |
| #2 Behavioral Changes | LEDGER_LOCK_*, POLLER_GAP_*, POLLER_STARTUP_* | fills_ledger.py, fills_poller.py | Thread safety, pagination logic, state persistence |
| #3 Reconciliation | RECON_*, TOCTOU_* | prediction/recon_job.py, fills_ledger.py | Data integrity, background job lifecycle |
| #4 Tests & Verification | *_UNIT_* | tests/ | Coverage, assertion correctness |
