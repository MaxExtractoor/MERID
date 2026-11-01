# MERID Telemetry/Stall Incident — 2026-10-31

Incident ID: INC-2026-10-31-telemetry-stall-01
Status: OPEN — process stable but failure mode not yet captured end-to-end
Scope: production server (port 8011), telemetry persistence path, event-loop stalls

## Timeline (local time, EDT; UTC = local + 4h)

| time | event | evidence |
|---|---|---|
| ~18:21 | Prior server process (pre-restart) silently died; decision-audit backlog >3000, p95 write-wait ~38min before disappearance | lifecycle log ends; console err log ends at 18:21:42; no exit code, no exception — launcher also died without logging the exit |
| 19:02:43 | Controlled restart, PID 148, run `20261031230318_148_22e3d3d8`, SHA `f16ce816` | console log `server_console_20261031_190243.err.log` |
| 19:03:39 | `LIVE_ENTRIES_ENABLED`; preflight recon clean (0 open orders, 0 positions) | pinned_fav_policy_resolution echo verified |
| 19:03–19:37 | Stall episode: `MERID_GRID_CYCLE_HANG_DUMP_S=80` watchdog fired repeatedly; `faulthandler_dump.log` grew to 347,704,752 bytes (13,359 dump headers ≈ repeated re-fires during sustained stalls) | faulthandler_dump.log LastWrite 19:37:11 |
| 19:48–19:49 | Audit writer backlog 520→679 (~+90/min observed window); log queue 13.7k→17.7k | console err log |
| 19:56–19:58 | Stall released; audit backlog drained 608→206; log queue dropped 18,729→7,756 in one burst | console err log |
| 20:05–20:08 | Log queue re-climbing 7,756→10,014 (~+900/min); oscillating with rising troughs | console err log |
| 20:05 | Fresh exchange reconciliation via live REST: open_orders=0, positions=0, balance $14.2821, locked $0 | direct KalshiVenueClient query, this incident record |

## Failure-class classification

| class | verdict | evidence |
|---|---|---|
| Process exits | NOT currently occurring (PID 148 alive 66+ min). Prior 18:21 event WAS an exit — no exit code, no Python exception, launcher died silently → consistent with external kill or unmanaged fault (python311.dll 0xc0000005 history) — UNPROVEN | process table, lifecycle log |
| Process alive, API unresponsive | NOT observed; port 8011 listening, local endpoints serving balance/positions during incident | port check, log lines during stall window |
| API ok, UI disconnects | not assessed — no frontend session tested | — |
| Venue transport drops only | NOT primary; WS is healthy with normal `BOOK-UNTRUSTED`/state-transition noise; orders/fills subscriptions live | heartbeat lines |
| Supervisor replaces process | NOT occurring; no supervisor; launcher = start_15m.ps1 spawn, no restart-on-exit | process tree |
| **Worker/loop stalls while process lives** | **CONFIRMED — the actual current failure mode.** Repeated ≥80s event-loop stalls; dump watchdog re-fires; main thread captured inside synchronous `sqlite3.connect+write` in `record_settlement_proceeds` (fills_ledger.py:7435) running ON the uvicorn event loop | faulthandler_dump.log final block; 13,359 headers |

## Captured evidence

- Stall mechanism: sync sqlite3 settlement write on the asyncio thread — specifically the `time.sleep(2.0 + attempt)` **retry backoff** inside `record_settlement_proceeds` (`fills_ledger.py`), up to ~50s of sleep per call under contention — plus simultaneous backlog in 4 sqlite writer threads (`decision_audit_ledger._writer_main`, `order_decision_ledger._writer_main`, `rejection_counterfactual._writer_main`) + QueueListener file writes — all on one HDD spindle.
- Amplifier: `faulthandler_dump.log` is **append-mode, created 2026-10-10** — the 13,359 dump headers are ~3 weeks of accumulation, NOT today's incident. Dominant producer: per-cycle `StackDumpTimer(hang_dump_s=80)` — one dump per stalled grid cycle. (Correction vs. earlier reading: the `repeat=True` startup watchdog in `main_15m_lean` is cancelled when the startup coroutine completes — startup window only, ~0-1 dumps per run.) Each stalled ≥80s cycle still appends ~MBs to the same disk → stall→dump→contention→deeper-stall feedback.
- Queue behavior: backlogs built DURING stall, drained AFTER release → service capacity is adequate when the loop is not stalled; overload was symptom, not primary cause.
- Process: 1.12GB private bytes, 1432 handles, ~20+ threads, CPU 7071s/66min.
- Missing: disk queue-length counter (Get-Counter hung in sandbox), memory-commit timeline, exit code for 18:21 death, thread stacks AT the terminal event.

## Hypothesis ranking (user's table applied)

1. Telemetry > persistence capacity — PARTIALLY: only while loop is stalled; drain rates post-release show capacity is adequate otherwise.
2. Logging second overload — CONFIRMED contributor: 18.7k log queue depth, oscillating recovery.
3. Checkpoint/long-reader stalls — PLAUSIBLE, unmeasured: 19GB audit DB, WAL checkpoint cadence 900s, no reader-lifetime data.
4. Writer thread fails/retries — NOT observed: all writers parked normally in `_writer_main`, heartbeats continued.
5. **Sync work blocks async loop — CONFIRMED on one path: `record_settlement_proceeds` sync sqlite3 on event loop.** Other sync-call sites on the loop unmapped.
6. Queue objects exhaust memory — unmeasured; private bytes 1.12GB not alarming.
7. External supervisor/watchdog kill — PLAUSIBLE for 18:21 exit (no exit code/exception/launcher survival); unidentified.

## Unproven — do not close yet

- Terminal event of the 18:21 death (no dump/exit code captured at kill time).
- Whether stalls correlate with WAL checkpoints, the settlement-poll write specifically, or HDD bursts generally.
- Whether the rising log-queue troughs stabilize or re-backlog on the next stall.

## Resolution (commit `c636943f`, deployed 2026-10-31 20:28)

**Off-loop settlement write.** `record_settlement_proceeds` split into `_settlement_proceeds_plan` (pure compute, loop-safe) / `_settlement_proceeds_db_write` (blocking: connect+insert+commit+retries) / `_register_settlement_legs` (in-memory, owning thread only). New `record_settlement_proceeds_async` runs the blocking phase on a dedicated **single-worker executor**, awaited by the caller (ack only after commit — never fire-and-forget). Per-market inflight map coalesces poller re-deliveries onto one op (INSERT OR IGNORE under durable `settlement:{ticker}:{side}` identity — no duplicate writes). Timeout → tracked **unresolved** state: the op continues, reconciles by durable identity, no blind retry. Failures raise `SettlementProceedsWriteError` and increment `_settlement_write_stats`. Sync `record_settlement_proceeds` signature/semantics preserved (tests + any sync callers unchanged).

**Dump volume bounded.** Shared `DumpBudget` (`merid/utils/stack_dump_timer.py`) acquired at fire time by every producer: per-stall-episode cap `MERID_DUMP_MAX_PER_STALL=3`, cooldown `MERID_DUMP_COOLDOWN_S=300`, per-process total `MERID_DUMP_MAX_TOTAL=100`, byte-growth cap `MERID_DUMP_MAX_BYTES=50MiB` over file size at first acquisition. Episode resets only on demonstrated loop progress (cycle wait completing). Applied to per-cycle stall timers and the lifetime `repeat=True` startup watchdog.

**Validation:** `tests/event_venues/kalshi/test_settlement_offloop.py` — 9 cases (slow-write loop responsiveness, delayed-ack, poll coalescing, timeout→unresolved without retry, commit-failure propagation, late-completion registration, restart idempotency, budget bounds, permit gating). **16/16 pass** with the 7-case reconciliation suite.

**Deployed:** restart 20:28:56, SHA `c636943f`, run `20261101002835_2976_af5f58b1`, `LIVE_ENTRIES_ENABLED`, all P0 checks PASS.

**Readiness enforcement (`dca277ed`, `37d54901`, deployed 20:46).**
`settlement_write_health()` is consumed by the `loop_15m` entry gate —
`not ok` blocks new entries only (reconciliation/cancel/exits continue):
- `settlement_unresolved_age:NNs` — any in-flight op pending past
  `MERID_SETTLEMENT_UNRESOLVED_MAX_AGE_S` (default 300s, provisional).
  Age clock starts at **operation admission** (task creation), covering
  executor-queue wait + worker run + caller await; queued ops accrue
  unresolved time and count in `pending_unresolved`.
- `settlement_write_failed:{tickers}` — outstanding durable write
  failure tracked **per market**; clears only via a same-market commit,
  so an unrelated settlement's success cannot hide an outstanding
  accounting failure.

**Validation:** `test_settlement_offloop.py` — 14 cases incl. the
cross-operation overlap (A fails → B commits → still blocked on A → A's
own commit recovers) and queued-op age coverage. 14/14 + 7/7 recon.

## Milestone ledger (sustained observation)

| milestone | status | evidence |
|---|---|---|
| Bucket transitions | OBSERVED (partial) | 20:45→21:00 bucket: `KX*15M-26OCT312100-00` markets cataloged 20:46:27+; ticks continue ~5s cadence through transition |
| First real settlement write | **OBSERVED 20:48:29** | `Settlement received: KXXRP-15M = YES` 20:48:14 → `[SETTLEMENT-PROCEEDS] KXXRP15M-26OCT312045-45 outcome=yes booked 2 payout leg(s)` — durable commit via worker executor; loop ticks 25–27 continued during/after; no stall, no backlog. (Note: settlement payload is exchange-authoritative for held counts; it reported both legs held though preflight positions=0 — consistent with settle-time vs fetch-time skew, worth a bookkeeping look.) |
| Contended write | NOT OBSERVED in production | covered by fault injection (`test_slow_write_keeps_loop_responsive`, delayed-ack, coalescing cases) |
| Late completion after timeout | NOT OBSERVED in production | covered by `test_late_completion_registers_on_loop` + `test_timeout_marks_unresolved_and_never_retries` |
| First eligible order (count_fp=2.0, ≥94¢) | NOT OBSERVED | candidates still reject `no_positive_executable_edge`; do not manufacture |
| Independent termination capture | OPEN | ProcDump/WER not installed; 18:21 exit remains unclassified |

**Durability boundary (explicit):** `_settlement_failed` and
`_settlement_inflight` are in-memory — a restart clears them. Startup
reconciliation does NOT currently reconstruct equivalent entry-blocking
state; a restart must not be read as recovery from an outstanding
accounting failure merely because the map starts empty. Tracked under
the restart/reconciliation assurance work, not expanded in this patch.

## Still open

- [ ] Queue-age + consumer-heartbeat metrics independent of the saturated paths.
- [ ] Capture terminal event: ProcDump/WER for the next exit; thread-stack capture before any controlled shutdown (18:21 death unclassified).
- [ ] WAL/checkpoint/reader-lifetime audit on `decision_audit.db` (19GB) during next stall, on a copy.
- [ ] Audit other sync-I/O-on-loop call sites beyond the settlement path.
- [ ] Dump file rotation (faulthandler holds the fd — rotation requires re-registering the handler, not renaming the path).
- [ ] First eligible constructed order post-fix: `count_fp=2.0`, price ≥94¢ (none yet — all candidates reject `no_positive_executable_edge`).
