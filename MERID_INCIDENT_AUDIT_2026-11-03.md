# MERID Production Audit — 2026-11-03

Scope: (1) no trades for ~5h after the 9:33 AM fill, (2) `invalid_confidence` vetoes, (3) backend "dropping". Evidence: `server_output.log` (+ rotations), `data/live_runtime_state.json`, `data/kalshi_fills.db`, `data/kalshi_order_attempts.db`, `data/decision_audit.db`, source audit of `ws.py` / `ws_bridge.py` / `market_state.py` / `trade_decision.py`, Kalshi WS docs, SQLite docs.

## Executive summary

All three symptoms trace to **one infrastructure failure**: the order-book pipeline cannot keep up with a ~900–1100 msg/s Kalshi real-time stream on this host. The event loop is starved (synchronous SQLite + a 17.5 GB audit DB on a spindle disk), frames sit 2.5–4.2 s in queues against 1.5 s/4 s budgets, and the pipeline sheds/drops them. Every dropped frame leaves a `sid` sequence gap; Kalshi `seq` is contiguous per subscription, so a gap is *proof of local message loss*. Unattributed drops invalidate **all 5 books** on the shared sid at once → `book_sequence_confirmed=False` → `invalid_confidence` veto + `NOT-EXECUTABLE` router rejections → zero submissions. Books flap `HEALTHY → UNTRADEABLE → RESYNCING → DEGRADED_REST_ONLY → HEALTHY` continuously.

Separately: (a) a ~355 ms exchange-vs-ledger race at 14:33 UTC fired `fills_reconciliation_failed` → `LIVE_ENTRIES_HALTED` with **no auto-recovery** — entries stayed dead ~3 h until manual restart; (b) the strategy's economics gates (`no_positive_executable_edge`, `price_band_both_sides_disabled`, moneyness/TTE/pinned-fav) would still reject the majority of candidates even with a healthy feed; (c) "backend dropping" is two distinct failures — **silent process exits that are currently uninstrumented because the independent watchdog died 11/1–11/2**, and **alive-but-stalled** event loops (audit-write stalls up to 40–511 s → HTTP timeouts).

## Timeline (local EST)

- **09:32:58** fill: buy 2.24 YES @66c `KXXRP15M-26NOV030945-45`; exchange position 224cc immediately.
- **14:33:00.596 UTC** ledger ingests fill via `http_poller` (~1.7 s lag).
- **14:33:00.951 UTC** reconciler runs mid-flight → `exchange=224 vs ledger=0/cache=0` → `LIVE_ENTRIES_ENABLED → LIVE_ENTRIES_HALTED` (`fills_reconciliation_failed`). ~355 ms after ingest; ~2 s after exchange update.
- **09:33:27+** `WS-SID-SEQUENCE-GAP` storm (sid=1, seq 36M+, real-time stream all morning).
- **09:34:57** exit sell 4.00 @78c fills (reduce-only still works under halt — correct).
- **09:33–12:46** entries blocked ~3 h. No `live_runtime_recovery_passed` event ever fired.
- **12:46** restart pid 12788 → preflight → `LIVE_ENTRIES_ENABLED`. sid=1 accumulates 223,623 seq in ~4 min ≈ **930 msg/s → conflation flag not effective**.
- **~12:50** pid 12788 replaced by **pid 8840** (12:51) — cause uninstrumented (watchdog dead).
- **12:52+** `LIVE_ENTRIES_ENABLED` but only 2 entry attempts reach router: 13:02 `KXETH15M YES maker@75`, 13:08 `KXETH15M NO maker@25` — both `REJECTED: market_not_entry_ready:NOT-EXECUTABLE`, `submission_attempted=false`.
- **Current**: pid 8840 alive, port 8011 bound, loop evaluating continuously, books flapping, ~0 submissions.

## Issue 1 — no trades

Two independent layers, both real:

**A. Book-trust layer (blocks before economics most cycles).** `WS-SID-SEQUENCE-GAP` (~1,140 events, gaps 1–8,677), `BOOK-UNTRUSTED` (~829), `BOOK_UPSTREAM_LAG` (~968, measured `upstream_wait` 2,500–2,765 ms vs 1,500 ms bound), `BOOK_EVENT_TOO_OLD` (`event_age` ≥4,000 ms, one 55.9 s), `ws_delta_dropped_stale` (~547, `res_ms` 4,250 vs 4,000 shed bound). `ENTRY-READINESS` mostly `quote_fresh=False / quote_coherent=False`. Orders rejected `NOT-EXECUTABLE` pre-submission — Kalshi never saw them.

**B. Economics layer (dominant veto counts even when books are up).** Parsed per-cycle tallies (~1 h window): `no_positive_executable_edge` ~933, `price_band_both_sides_disabled` ~787, `SKIP_MARKET_NOT_READY` ~517, market-validation ~158, `min_tte_entry_disabled` ~92, no-contract-in-window ~77, cost-basis override ~39, `pinned_fav_maker_only` ~32, `invalid_confidence` ~25, edge-below-threshold ~25, `ENTRIES_DISABLED` ~8. Example: BTC `p_yes=0.293 / no_edge=-0.102` — model right, edge negative after fees+spread. These gates are **working as designed**; don't loosen them to force flow.

## Issue 2 — `invalid_confidence`

Not a model-confidence bug — a deliberate fail-closed label. `trade_decision.py` returns `valid=False, value=None, source=uncertainty_engine` whenever hard trust reasons exist; `book_sequence_confirmed=False` → `orderbook_sequence_gap`. `gate_evaluation.py` maps it to the canonical `confidence_valid` gate. ~25 actual vetoes in-window (naive grep counts inflated by repeated counter dicts). **Do not "fix" by assigning fallback confidence** — fix the sequence integrity underneath.

## Issue 3 — backend dropping

Two distinct mechanisms; the UI can't tell them apart:

- **Alive-but-stalled**: `DECISION-AUDIT-HEARTBEAT` shows `latency_ms` 1–4 s/cycle routinely, spikes to **40,342 ms**; earlier `audit_write_wait_ms:p95=511,250` (8.5 min!). During stalls HTTP requests time out → "backend dropped". Confirmed matches the 2026-10-31 telemetry incident (sync SQLite on loop, multiple writers, QueueListener on one HDD).
- **Silent process exits**: documented 3× on 10-31, cause never found. **The independent watchdog (`watchdog_15m.ps1`) is dead** — last heartbeat 11/1 19:26 UTC, last poll 11/2 00:18, `watchdog_obs.{out,err}.log` empty since 11/1, no watchdog process running now. Today's 12:46→12:51 pid swap (12788→8840) has **zero crash instrumentation**. No traceback/WER/faulthandler evidence exists.
- `WS-SESSION-RECYCLE reason=stall` → `ConnectionClosedError 1001` → reconnect gen=2 is a *feed* drop (handled by design), distinct from process death.

## Root cause: client-side message loss on a multiplexed sid

Kalshi docs (verified): `seq` counts **emitted messages on one subscription** and stays contiguous even under `update_interval_ms` conflation; snapshots replace held changes without breaking seq. TCP can't lose frames → **every gap is a local drop**. Drop paths found, by attribution:

| Path | File | Attribution | Blast radius |
|---|---|---|---|
| Stale shed in `_process_queue` (`res_ms>4000`) | `ws.py` | `_dropped_delta_frames` (≤1024/sid; overflow→none) | per-ticker, or full-sid on overflow |
| `_msg_queue` full → `_drop_lowest_priority` / forced evict | `ws.py:2168-2186` | **none** | full-sid |
| `_check_sequence` OOO/dup `return False` | `ws.py:3182+` | **none** | full-sid |
| Bridge thread-queue full / coalesce | `ws_bridge.py:4363` | per-ticker mark only, **no seq** | per-ticker **+** full-sid on next msg |
| `async_queue` full `_drain_put_event` | `ws_bridge.py:4809-4815` | same — no seq | same |
| Reorder buffer `ResyncRequired` fast-forward | `ws_bridge.py:4792-4798` | none | full-sid |

Mass sheds (>1024 pending per sid) can't even be represented → always full-sid invalidation (e.g. `gap=8677`). The full-sid nuke is *correct* fail-closed behavior when attribution is missing — the bug is that most drop paths don't produce attribution.

**Why the consumer lags**: ~930–1,100 deltas/s wire rate; 6+ hops (WS-IO → `_msg_queue` → `_process_queue` → bridge thread queue → reorder → async queue → per-ticker drain → `market_state`); the main loop shares time with uvicorn, the decision loop, position monitor, and synchronous SQLite. `decision_audit.db` = **17.5 GB + 632 MB WAL**; audit-write waits 1–511 s starve everything. Lag → drops → invalidations → REST snapshot resyncs → more work → more lag (feedback loop).

**Conflation flag inert**: `MERID_KALSHI_OB_UPDATE_INTERVAL_MS=1000` is set and both subscribe paths send it (`ws.py:1168,1238`), but measured wire rate ≈ real-time (sid=1: 223k seq/4 min ≈ 930/s; 36M seq over the morning ≈ 1,100/s sustained). Kalshi's changelog dates `update_interval_ms` support for this API variant **Nov 5, 2026** — the param is likely being silently ignored today. The single-market subscribe path also doesn't log its payload, so this can't be confirmed from logs — add payload logging + error-code surface (Kalshi rejects interval mismatch with **error 11**; unknown int with **error 29**).

## Secondary root cause: recon race + no auto-recovery

The 14:33:00.951 UTC halt compared exchange position (224cc, updated instantly on fill) against a ledger/cache that ingests via `http_poller` on a ~1.7 s cadence — a ~355 ms transient window. Fail-closed halt was correct *per current code*, but recovery required a manual restart: no `live_runtime_recovery_passed` ever fired even though positions converged after the 09:34:57 exit (exchange 0 = ledger 0). ~3 h of dead entries from a 2-second race.

## Web research applied

- **Kalshi orderbook WS** (docs.kalshi.com): `seq` per-sid contiguous; `clock` is cross-connection but *can decrease under conflation* (not a completeness watermark); gap recovery = `get_snapshot` for all subscribed markets, or unsubscribe→unsubscribed→re-subscribe; one orderbook subscription per connection — repeated `subscribe` adds markets to the same sid and must reuse the same `update_interval_ms` (omission = 0, mismatch = error 11). Kalshi's own SDK uses **one bounded queue per subscription** + gap→snapshot recovery — the model to converge toward.
- **SQLite** (sqlite.org + production hardening refs): every `sqlite3` call blocks the calling thread; `fsync`/checkpoint stalls freeze an asyncio loop entirely. Fix = single dedicated writer thread (`ThreadPoolExecutor(max_workers=1)` or aiosqlite) + `PRAGMA synchronous=NORMAL`, `busy_timeout`, periodic `wal_checkpoint(PASSIVE)` in idle gaps, `TRUNCATE` during maintenance. One writer is a structural invariant — parallel writers only produce `SQLITE_BUSY`.
- **Silent exits on Windows**: enable `faulthandler` (`PYTHONFAULTHANDLER=1` or `-X faulthandler`) for SIGSEGV/SIGABRT traces; Sysinternals **ProcDump** (`-e -ma`) or WER local dumps for hard crashes. Both are cheap and must be armed *before* the crash.

## Recommended fixes (fail-closed semantics preserved)

**P0 — ops, no code risk, do first:**
1. **Relaunch `watchdog_15m.ps1`** against pid 8840 — it is currently dead; every drop is uninstrumented.
2. Set `PYTHONFAULTHANDLER=1` in `start_15m.ps1`/`.env`; consider ProcDump `-e -ma -x dumps\ python.exe` for the next silent exit.
3. Maintenance window: `PRAGMA wal_checkpoint(TRUNCATE)` on `decision_audit.db`, then archive/rotate the 17.5 GB DB (e.g. monthly tables or a dated file); reclaim WAL.
4. Verify conflation: log `WS-SUBSCRIPTION-PAYLOAD` on the single-market path too, and log Kalshi error responses (code 11/29). If interval is ignored until Nov 5, `update_interval_ms` can't save you — treat 900+/s as the design rate.
5. Reduce log volume (the giant `COUNTER-SANITY-CHECK` dicts + INFO heartbeats every few seconds share the same HDD as SQLite).

**P1 — code, correctness of the loss pipeline:**
6. **Plumb seq attribution through every drop path.** Feed bridge drops (`BRIDGE_QUEUE_FULL`, `ASYNC_QUEUE_FULL`, coalesce, reorder-reset) and ws.py drops (`_drop_lowest_priority`, forced evict, `_check_sequence` OOO) into the same `(seq → ticker)` attribution the stale-shed path uses → invalidation stays per-ticker instead of nuking all 5 books. Still fail-closed; strictly smaller blast radius.
7. Raise/represent attribution capacity (cap 1024/sid is < one burst) — or fast-forward `last_seq` explicitly when a mass drop is detected so recovery is immediate rather than repeated-gap invalidation.
8. Bound each hop and shed *earliest* (drop at ingress beats applying stale): today frames age 4 s before the shed path sees them. Per-subscription bounded queues (Kalshi SDK model) isolate a hot ticker from the other four.
9. Recon grace for in-flight fills: if `exchange_qty − ledger_qty` is fully covered by fills inside the trusted watermark's ingest window, schedule one re-check instead of immediate halt; and wire `live_runtime_recovery_passed` so a resolved transient doesn't cost 3 h.

**P2 — structural:**
10. Move **all** SQLite off the event loop into a single writer thread; batch audit writes; add WAL auto-checkpoint cadence + reader-lifetime bounds.
11. Keep full-sid invalidation as the fallback when attribution is genuinely unknown (per contract — lose provenance ⇒ halt that sid's books).

**Do NOT**: raise `invalid_confidence`, widen `entry_confidence`/`book_trusted` gates, bump buffers (131k queue already just means older drops), auto-resume halts, or loosen economics gates to force trades.

## Verification plan

- Unit: synthetic sid stream with injected drops at each path → assert per-ticker-only invalidation when attributed, full-sid when not; recon grace: mock exchange-ahead-by-one-fill → assert re-check not halt.
- Replay/soak: replay a 5-ticker burst through the real pipeline while injecting a 5 s loop stall → expect sheds attributed, no full-sid nukes, recovery via `get_snapshot`.
- Live canary of the fix itself: none needed — changes are in the *invalidation/attribution* path only; entry gates unchanged.
- Watch: `WS-SID-SEQUENCE-GAP` rate, `BOOK-UNTRUSTED`, `upstream_wait`/`event_age` p95, `audit_write_wait_ms` p95, `queue_depth`, `live_runtime_state` transitions, `ORDER-SUBMIT` count.
