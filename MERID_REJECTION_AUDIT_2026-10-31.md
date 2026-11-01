# MERID rejection-correctness audit — 2026-10-31

Scope: gate-by-gate audit of the rejection distribution on run
`20261101012107_14588_f7ecd727` (PID 14588, SHA `4dc3943f`,
LIVE_ENTRIES_ENABLED 21:21:26 local).  Basis: `strategy_decisions` rows
for the run + console log transport counters + code predicates.  This is
a correctness report, not a relaxation proposal.

---

## 0. Count reconciliation (the 1,736 vs ~1,600 discrepancy resolved)

The earlier log-grep `reason=` counts mixed three different units.
Authoritative basis:

| dataset | unit | this run |
|---|---|---|
| Candidate decisions | market×side×evaluation | **5,358 rows**: 722 ENTER / 4,636 NO_TRADE (`NO_EDGE` 4,617, `DATA_QUALITY_VETO` 19). YES and NO are evaluated as separate gate sets per row. |
| Transport incidents | gap/reconnect/shed episode | **328 `WS-SID-SEQUENCE-GAP` detections** (rate-limited 1/s per sid), **628 shed-forwards**, ~**5.2M superseded deltas** cumulative, **780 book invalidations across only 20 distinct tickers** (~39 re-invalidations per book in ~40 min). |
| Failed-gate union | per-gate simultaneous failures | `yes_edge_threshold` 3564, `yes_positive_ev` 3563, `yes_cost_basis` 3563, `no_*` ~3.5k, `yes_evidence` 3314, `no_evidence` 2955, **`yes_moneyness` 1845 / `no_moneyness` 1635**, **`book_trusted` 1574**, `no_regime` 1066. |

Key reconciliations:
- One sid gap → N ticker invalidations (full-sid = ~20 books, or the shed-attributed subset).  328 detections ≠ 328 failures; invalidation count is the better unit.
- `ws_delta_dropped_stale`/`ws_sid_sequence_gap` in log-grep counts were BOOK-UNTRUSTED/WS transport lines, not candidate rejections. The DB shows only 19 DATA_QUALITY_VETO candidate rejections — the book storm leaks into decisions mainly through the `book_trusted` gate (1574 failed-gate instances).
- Moneyness gates DO fire on evaluated candidates (1.8k) — "zero moneyness vetoes" earlier referred to the lane-scoped `pinned_fav_moneyness_cap` reason only.

---

## P0-1. Policy reconciliation: cap 6 vs 2, ETH `YES=none`

**Resolved.** The 6-contract cap was an explicit operator directive
(2026-10-31), distinct from the ETH reopen — commit `4dc3943f`, audit-doc
appendix, `.env` lineage.  Preflight echo persists the resolved state
every run: `max_contracts=6.0 … proposal~638cc@94c; pinned_fav_cap=6.0
binds final qty`.  Rollback criteria declared (any 6-contract pin-break,
or single order > ~50% shard cash).  ETH `YES=none` semantics are
code-verified: unset lane cap → per-asset `..._YES_ETH` fallback (unset)
→ `None` → no in-lane cap, identical to BTC/DOGE/SOL YES; exercised by
`tests/test_eth_pinned_fav_reopen.py` (19/19) including a rollback-path
test.  No action needed — documentation is complete.

## P0-2. `ws_delta_dropped_stale` — **DEFECT CONFIRMED (clock-skew-poisoned staleness)**

**Predicate** (`ws.py:2306-2455`): a delta is shed when
(a) `_res_ms > MERID_WS_DELTA_DROP_RES_MS` (4000) — queue residence, or
(b) venue-ts path: `_age_ms0 = _time.time()*1000 − venue_ts >=
KALSHI_BOOK_MAX_EVENT_AGE_MS(4000) − margin(250) = 3750ms` when the
derived age is sane (`0 ≤ age < 4×bound`).

**Evidence**: `[WS-AUTH] Clock skew: -3.02s (server − local)` — the host
clock runs **3.02s ahead of Kalshi**.  The skew is measured and applied
to the auth signature (`ws.py:707-743`) but is a local variable — never
stored or applied to staleness math.  Observed drops:
`res_ms=938 >4000ms` — residence is healthy (~0.9s); the venue-age term
fired because `938ms + 3020ms skew ≥ 3750ms`.

**Effective bound**: 3750 − 3020 ≈ **~730ms of true delta age**.  Under
1s conflation, essentially every delta is shed → ~5.2M superseded
frames → attributed seq-gaps → 780 re-invalidations on 20 books →
`book_trusted` failing on 1,574 decision rows.

**Expected** (Kalshi docs, cited by operator): conflated deltas apply in
subscription-seq order; clocks may decrease; deltas must not be
discarded for a below-previous clock.  The implementation's *shed-on-
staleness* design is defensible only while the staleness measure is
true.  With a +3s clock it discards **valid, ordered, required** deltas —
the exact failure mode the docs warn about, arriving via the timestamp
path rather than clock-regression.

**Same defect downstream**: `market_state._book_event_timing`
(`event_age_ms = time.time()*1000 − venue_ms`, bound 4000 → effective
~980ms true age) — `BOOK_EVENT_TOO_OLD` fired 15× on frames killed
upstream.  Likely also contaminates `spot_staleness_ms` (4–8s observed)
and RTI/quote staleness anywhere venue-ts meets raw wall clock.

**Counterexample tests needed**: (1) inject `clock_skew=+3s`, feed
delta with true age 900ms → must NOT shed; (2) shed classification must
use skew-corrected age or monotonic residence only; (3) BOOK_EVENT_TOO_OLD
same case at enqueue.

**Fix direction** (proposal, not yet applied): store the auth-measured
skew (`self._clock_skew_seconds`, refreshed on reconnect) and subtract it
in every `local_wall − venue_ts` computation; when skew is unavailable,
fall back to monotonic-residence + seq-contiguity rather than raw wall
age.  Independent remediation: `w32tm /resync` on the host — a +3s drift
is an ops defect regardless of code.  Guard: log the measured skew per
connect so drift is observable.

**Impact**: this is currently the largest manufactured outage source.
Until fixed, `book_trusted` vetoes and part of the
`no_positive_executable_edge`/`data_state` volume are contaminated —
markets whose books are perpetually resyncing cannot quote executable
prices.

## P0-3. `ws_sid_sequence_gap` — predicate correct

`_check_sid_delta_sequence` (market_state.py:6434) is **sid-scoped,
called at enqueue in arrival order** — matches Kalshi semantics (seq is
per-subscription, multiplexed across markets).  `_handle_sid_sequence_gap`
correctly: attributes shed (seq,ticker) pairs → invalidates only affected
tickers; unattributed/overflow → full-sid invalidation (fail closed).
Recovery = throttled dedup'd WS snapshot + REST resync per ticker
(`_maybe_trigger_book_recovery`, `_trigger_snapshot_recovery` via the
bridge client) — consistent with the documented `get_snapshot` recovery.
Queue-drain semantics fixed the earlier livelock (drain only on first
invalidation; post-invalidation deltas buffer for post-snapshot
continuity).  **No defect in the seq/sequence-recovery layer itself** —
the gaps are real holes in applied seq order, manufactured upstream by
the skewed shed.

## P1-1. `no_positive_executable_edge` / `NO_EDGE` — math verified correct

`compute_edge` (trade_decision.py:2949): `p_no = 1 − p_yes` (single
complement), `p_selected` side-aware, `gross = p_selected − entry_price`,
`net = gross − entry_fee − exit_cost_reserve − model_risk −
adverse_selection − policy_giveback − impl_shortfall − edge_bias` — all
fractional units, `entry_price ∈ [0,1]` asserted.  Call-site prices:
maker basis uses own-side bid (correct post-only pricing); taker uses
own-side ask with **complementary-ask fallback** `yes_entry = 1 − no_bid`
/`no_entry = 1 − yes_bid` — matching Kalshi's YES-only book semantics.
Reason assignment (7615-7644) labels non-positive EPC-adjusted edge
honestly vs lane floors.  `gate_results_json` already persists per-side
`{net_edge_cents, gross_edge_cents, p_selected, min_p_selected}` — the
decomposition the operator asked for is recorded; a sampled ETH row
showed coherent arithmetic (gross +5.31c → net −0.34c after reserves).

**Open sub-items**: (a) reserve-component correctness is a measurement
question, not an arithmetic one — the inversion noted in the pinned-fav
audit is about *estimates*, verified formula is fine; (b) the reason is
over-broad as a label — recommend splitting diagnostics into
`edge_gross_nonpositive` / `edge_fee_exhausted` / `edge_reserve_exhausted`
/`edge_input_invalid` while keeping the stable top-level code;
(c) 1,574 `book_trusted` failures mean some candidates evaluated on
resyncing/degraded quotes — contaminated by P0-2.

## P1-2. `min_tte_entry_disabled` — correct predicate, dead-zone question open

Predicate: `seconds_to_expiry <= MERID_ENTRY_MIN_SECONDS_TO_EXPIRY`
(default 180s) AND not settlement-lane → `_no_trade` ("too late").
Settlement-convergence lane exempt by design.  137 log-side firings are
final-3min evaluations.  The policy dead zone the operator flagged
(convergence qualifying only after min-TTE disables entry) needs the
opportunity-episode dataset to measure — **not a defect yet; measure
before touching TTE**.

## P2-1. `pinned_fav_maker_only` — local routing suppression, not exchange

`agent_grid_15m.py:9016-9042`: when the pf lane is in maker mode, a
*taker-routed selection* is suppressed (and vice versa).  114 records =
taker-qualified candidates suppressed rather than reconstructed as maker
quotes; exchange never saw them (0 submissions).  Design question stands:
whether upstream proposal defaults generate taker candidates the lane
predictably rejects — an upstream maker-construction check would convert
or drop earlier.  Keep exchange post-only protection regardless.

## P2-2. `entry_trap_veto` — documented guard; lineage question open

`entry_trap_guard.py`: own-side ask drop ≥5c/45s, sticky-p ask drop ≥3c
with |Δp| < 0.02, flat-trap (taker only), basket same-side cap (2).
Rationale is settled-fill evidence (dip-chase -8.3c/fill study).
**Two follow-ups**: (a) triple-counting risk vs adverse_selection_reserve
+ edge_bias_correction — needs formula-lineage review per emitted veto
(P2, not disproven); (b) the veto consumes own-side ask history from the
SAME book the skew storm keeps resyncing — trap inputs may be computed
on reconstructed books; gate inputs should carry book-generation
provenance before any removal evaluation.  Shadow-only evaluation per
existing policy.

## P2-3. Shadow gate vector — partially exists

`gate_evaluation.py` already projects the consumed evidence into
per-gate PASS/FAIL rows persisted in `gate_results_json` /
`all_failed_gates_json` (schema v1).  Missing vs the operator's spec:
`NOT_EVALUABLE` marking when upstream book evidence is invalid (currently
downstream gates evaluate on whatever quote state existed), and a bounded
sampling/aggregation layer for the report questions (fail-only-one-gate
counts, overlap matrix, dead-zone windows).  Extend the existing
projection rather than building a second evaluator.

---

## Disposition

| reason | verdict |
|---|---|
| cap 6 / ETH none | resolved — authorized + verified |
| ws_delta_dropped_stale | **DEFECT — clock-skew-poisoned staleness manufactures the untrusted storm** |
| ws_sid_sequence_gap | correct seq accounting; gaps are real holes from the shed |
| NO_EDGE | arithmetic verified; label over-broad; contaminated by book storm |
| min_tte_entry_disabled | correct predicate; dead-zone = measurement task |
| pinned_fav_maker_only | local suppression; upstream-proposal question open |
| entry_trap_veto | documented guard; lineage/book-provenance questions open |
| book_trusted / DATA_QUALITY_VETO | downstream symptom of the skew defect |

**Recommended order**: fix clock-skew handling in venue-ts staleness
math (+ host `w32tm /resync`) → observe whether the untrusted storm and
`book_trusted` failures collapse → re-measure the rejection distribution
on a clean feed before any gate-level changes.  The next report should
then be able to say whether `no_positive_executable_edge` volume is
honest opportunity absence rather than a contaminated evaluation.

---

## Clock-skew remediation — implemented `9849e9ee`, live-verified

**Fix** (committed `9849e9ee`):

- New shared clock domain `merid/event_venues/kalshi/venue_clock.py`:
  process-wide `server_minus_local_seconds` calibration (sign convention
  identical to WS auth: `s = server − local`; corrected age =
  `(local_wall + s) − venue_ts`) with declared `source`,
  `precision_seconds` (HTTP Date granularity + measured RTT/2), monotonic
  expiry (`MERID_VENUE_CLOCK_MAX_OFFSET_AGE_S`, default 1800s), and
  host-clock-step invalidation (`MERID_VENUE_CLOCK_STEP_TOLERANCE_S`,
  default 0.5s) anchored on `time.monotonic()`.
- Explicit statuses, never silent-fresh: `measured`,
  `unverified_no_offset`, `unverified_offset_expired`,
  `unverified_host_clock_step`, `no_venue_ts`,
  `anomaly_negative_age` (corrected age < −1500ms tolerance is reported,
  not clamped), `anomalous_venue_ts`.
- `ws.py` auth records the measurement each (re)connect with request
  RTT captured (previously function-local only).
- `ws.py` shed: residence (monotonic, authoritative overload bound) and
  corrected-venue-age are separate predicates; per-reason counters;
  unverifiable/anomalous venue age never sheds a required ordered delta —
  it forwards with status rather than a fabricated age.  A shed frame
  still flows through attributed seq-invalidatation + snapshot recovery
  (transport integrity unchanged).
- `market_state._book_event_timing`: corrected age when measured;
  labelled `bridge_recv_wall(unverified_*)` local-domain fallback when
  not; `venue_age_status` / `raw_venue_age_ms` / `corr_venue_age_ms` /
  `offset_s` / `off_src` now flow into every untrusted diagnostic;
  `ws_last_event_age_status`/`_src` stamped on state; `wire_ms_corrected`
  added to hop forensics.
- Thresholds unchanged: res bound 4000ms, age bound
  `4000−250=3750ms`, upstream-wait 2500ms — no relaxation.

**Host note (OPEN)**: `w32tm` service is stopped and this shell lacks
elevation to start it — the skew persists (measured -2.63s on the latest
calibration, drifting vs the earlier -3.08s) and is *handled*, but host
synchronization is **open ops debt**, not closed: an administrator still
needs `Start-Service W32Time; w32tm /resync` plus verification that the
stored offset invalidates and a fresh measurement lands without a false
freshness/stale-drop transition.  No freshness-threshold change needed.

**Live verification** (run `20261101030426_10272_cbfb4b9b`,
`LIVE_ENTRIES_ENABLED` 23:04:49):

- `[WS-AUTH] Clock skew: -3.08s` → `[VENUE-CLOCK] kalshi offset=-3.084`
  recorded with `off_src=kalshi_ws_auth_date_header`.
- Drop lines now self-describing, e.g.
  `reason=corrected_venue_age res_ms=4000 res_bound_ms=4000
  raw_age_ms=6863 corr_age_ms=3779 age_bound_ms=3750 offset_s=-3.084
  off_age_s=159 freshness=measured` — 6863−3084=3779 confirmed live.
- Peak-rollover window (23:04–23:08, ~4min): 50 untrusted, 40 sid-gaps,
  2 too-old, 1 overflow — every drop `corrected_venue_age` verified-stale
  (true ~3.8s upstream lag during the rollover burst + startup catch-up).
  Matched rollover comparison (pre-fix 02:15–02:20 vs post-fix
  03:15–03:17): drops/min ~19→~2.5 (−87%), untrusted/min ~47→~12 (−74%),
  sid-gaps/min ~91→~24 (−74%).  `book_trusted` decision failures
  34%→7.3% of decisions (~41→~9/min).
  **Reporting qualification**: the compared windows differ in duration
  and may differ in message rate; per-minute rates are shown, and the
  `[BOOK-TIMING-ROLLUP]` aggregate (below) now supplies applied/s and
  per-stage denominators for drops-per-received-delta accounting.  The
  accurate claim is: *no skew-induced false drops were observed in the
  inspected post-fix window* — not that the manufactured component is
  categorically gone.
- Two pre-existing test issues fixed en route: an uncalibrated stale-ts
  test now records calibration explicitly, and the preserve-drain test
  sets `live_sequence_confirmed` to exercise the first-invalidation
  drain it documents (pre-existing failure since `8a2a2fbc`, not caused
  by this patch).

### 2026-10-31 follow-up: boundary verification, policy record, instrumentation

**Residence precedence — explicit policy revision.**  Prior behavior
(2026-10-06, `5b7a7bbd` lineage): a verified-fresh venue timestamp could
*override* a queue-residence breach and forward the frame.  Current
behavior: monotonic residence is **authoritative** — a residence breach
sheds regardless of venue freshness (`MERID_WS_DELTA_DROP_RES_MS=4000`,
unchanged).  Rationale: residence is the skew-free overload bound; a
queue already holding a frame >4s cannot deliver trustworthy downstream
evidence even if the venue ts looks fresh.  Consequence is unchanged —
the shed frame flows through attributed seq-invalidation + snapshot
recovery.  Predicate correctness is not threshold optimality: the 4000ms
bound is retained as-is and is not to be reverted merely to reduce
rejection counts.  Coverage: `test_residence_bound_is_authoritative`,
`test_missing_venue_ts_falls_back_to_residence` (unverifiable venue age
still forwards — residence is the *only* shed predicate that can fire
without a calibration).

**Unverified-fallback boundary — verified and closed.**  Audit found the
boundary violated: `get_quote_gate_state` read `ws_last_event_age_ms`
without status, so a `bridge_recv_wall(unverified_*)` fallback (~30ms
receipt age) satisfied the ≤2000ms `ws_entry_event_age_ms` leg and made
`ws_fresh` true — a recently-received-but-unverifiable frame became
"venue fresh."  Fix: the event-age leg now counts only when the applied
frame's status is `measured`.  `unverified_*`/`anomaly_*` fail closed,
and `no_venue_ts` is classified *receipt-recent; venue age unavailable* —
Kalshi's `orderbook_delta` schema always carries `ts`/`ts_ms`, so a
delta without one is malformed rather than a legitimate no-ts class;
it is retained for ordered reconstruction but does not satisfy venue
freshness.  The gate exports `ws_event_age_basis`
(`measured_venue_age` / `receipt_only_no_venue_ts` / `unverified` /
`legacy_unstamped`) so decision telemetry distinguishes the basis.  The REST-degrade
fallback in `loop_15m` is unaffected — it trusts an independent fresh
REST mirror under the explicit degraded-entry policy, never the WS
receipt fallback.  E2E tests: `test_unverified_venue_age_does_not_pass_
freshness_gate` (retained-for-reconstruction → status stamped → gate
fails closed), `test_measured_venue_age_passes_freshness_gate`,
`test_no_venue_ts_delta_is_malformed_not_verified` (malformed no-ts
delta retained for reconstruction, fails freshness closed).
`agent_grid_15m` now freezes `ws_last_event_age_status`/`_src` into
decision indicators for the audit chain.

**Residual rollover backpressure — instrumentation, not capacity.**
`[BOOK-TIMING-ROLLUP]` (bounded 60s aggregate on the apply path) reports
applied-count, applied/s, and mean|max per stage: `wire_ms_corrected`,
`corr_venue_age_ms`, `pq_wait_ms` (socket→WS-IO dequeue), `bridge_in_ms`
(socket→bridge enqueue), `queue_residence_ms` (bridge recv→apply),
`ticker_queue_wait_ms` (per-ticker queue wait), `apply_ms` (book apply),
`recv_to_now_ms` (socket→apply total) — plus the freshness-status
distribution.  This locates where the residual ~3.8s accumulates before
any capacity/concurrency change; subscription ordering is untouched.

**Residual lag located (00:00 rollover windows, `book_timing_rollup.jsonl`).**
The ~3.8s is *not* book-apply or per-ticker queue backpressure.  Peak
window (838 applied/s): `pq_wait_ms` mean **3185**/max 3860 —
socket-recv → `_process_queue` dequeue inside `ws.py`'s `_msg_queue` —
while `queue_residence` fell to 21ms, `ticker_queue_wait` 13ms,
`apply_ms` ~0, `recv_to_now` ≈ `pq_wait` (≈100% of in-process lag), and
`wire_ms_corrected` stayed ~135ms.  Sustained windows show pq_wait
oscillating 0.4s↔1.8s tracking arrival rate (~650/s→~800/s): the single
`kalshi-ws-processor` drain task (sequential `await` per message) plus
recv-loop synchronous work on the same asyncio loop saturates near
~700/s; bursts backlog `_msg_queue` (maxsize 131072, so nothing drops —
it queues, which is why lag, not loss).  `freshness_status` was 100%
`measured` throughout — the clock domain held through the burst.
Implication for the capacity choice: the effective lever is the drain
task's per-message cost and/or event-loop contention upstream of the
bridge — not the per-ticker queue, book apply, or snapshot path.  The
bypassed `_coalescing_buffer` (disabled "TEMPORARY FIX") is a candidate
at exactly this hop.  Any concurrency change must preserve the single
ordered drain per subscription.  Note: apply-path rollup rows emitted
from multiple drain threads initially duplicated; serialized in
`7d061001`.

**Drain-path profiler (next measurement).**  `_process_queue` now emits
a bounded 60s aggregate to `logs/pq_drain_profile.jsonl` splitting
per-message cost (`shed_eval_ms`, `dispatch_ms`, `handler_duty_ms_per_s`)
from scheduling starvation (`sched_gap_ms` while a backlog exists,
`idle_wait_ms`, `nonempty_iter_share`) — distinguishing "per-message
work too expensive" from "loop does not schedule it" before any
drain-path change.  Both durable channels write through
`merid/utils/rollup_writer.BoundedJsonlWriter` — bounded records,
size-capped rotation, counted write failures, single-owner emission.

**Process-termination track — still unclassified.**  The silent-death
signature (PID 8052, ~35s into import, no traceback/WER/faulthandler)
is a distinct reliability incident, *not* assumed to share the
settlement-stall cause.  `watchdog_15m.ps1` now provides independent
termination capture: WMI-detached, records process inventory (PID, PPID,
executable, command line, launch method) at start, polls the server PID,
and on disappearance writes a JSONL termination record (last-seen state,
exit timestamp, WER lookup window) to `logs/process_watchdog.jsonl` —
outside the application's own log path.  Controlled kills it has
recorded so far show `exit_code=null` — that is **exit status
unavailable** (a killed process may not expose ExitCode through the
limited handle); it does *not* establish an external force-kill, and
the session-tree explanation remains a hypothesis.  Single-instance
enforcement is preserved: the watchdog observes only; the launched
child still passes `start_15m.ps1` → lifespan single-instance guard.

**Deployed-vs-committed note**: production runs `7d061001` (code) —
the later commit `a600f6f7` is a documentation-only change and is not
expected to alter the deployment sha reported by the running process.

**5.2M "superseded" counter scope**: `_ent[0]` counts *dropped frames per
ticker since process start* — cumulative, not per-incident.  The new
per-reason counters (`_stale_drop_by_reason`) + split log fields now
attribute each drop to `queue_residence` vs `corrected_venue_age`.

**Incident note**: the deployed process (PID 8052) died silently ~35s
into module import at 22:57:29 with no traceback/WER/faulthandler
record — the same signature as the unclassified 18:21 event.  The
relaunch used `Win32_Process.Create` (WMI) so the launcher+child sit
outside the interactive session's process tree; the working hypothesis
is an external/console-teardown kill of session-spawned process trees.
PID 13096 (launcher) and its uvicorn child remain alive at report time —
independent termination capture stays on the watch list.

---

## Drain workstream — capacity attribution and the migrated bottleneck (2026-11-01)

**Method**: bounded stage profiler in `_process_queue` + recv-side frame cost +
loop-lag chain + py-spy wall-clock attribution on the live process.  No feed
semantics, ordering, threshold, or trading-path change was made for
measurement; the only capacity change is transport-side (see below).

**Stage attribution (live, 60s rows, `logs/pq_drain_profile.jsonl`)**

| stage | measured cost | share of WS-loop |
|---|---|---|
| recv handler (stamp→enqueue: parse, stats, classify, seq-check, put) | `recv_ms_mean` 0.03–0.05 ms/frame | ~30–75 ms/s duty (~3–7%) |
| shed predicate eval | 0.03–0.04 ms/item | — |
| dispatch (parse + awaited bridge enqueue) | 0.04–0.08 ms/item | — |
| whole-item body (unpack→handler done) | 0.06–0.12 ms/item | — |
| **drain task total** | — | **~60–150 ms/s duty (~6–15%)** |
| sched gap between iterations (starvation) | mean ~0.03 ms, max ~60 ms | ≈0 |

The drain task is cheap and never starved more than ~60 ms between
iterations — yet effective drain throughput capped ~1600–1700 items/s under
burst (`nonempty_iter_share` 0.85–1.0 = standing backlog while duty stayed
~15%).  Offline replay of the *same* `_process_queue` code drained 5000/s
with pq_wait max 78 ms — the ceiling is **process-wide GIL contention**, not
drain mechanics.

**Dominant co-tenant (py-spy, live)**: ~70% of all wall samples sat inside
`urllib3.connection.connect → ssl_wrap_socket` on `run_in_executor` threads —
every public spot-API fetch in `data/unified_spot_service.py` used bare
`requests.get()` → a **fresh TCP+TLS handshake per call**.  Process CPU
≈1.7 cores.

**Capacity patch applied (`a9c7e43e`)**: module-level `requests.Session`
with pooled keep-alive for the five public-API fetch sites.  Transport-only;
same endpoints/params/timeouts/parsing.  Result on the same live process:

- process CPU **1.68 → 1.09 cores (−35%)**; `ssl_wrap_socket` **55% → 0%** of samples
- next rollover (05:15): **`drops` 42,240/min → 0/min**, `nonempty_iter_share` ≤0.35,
  `pq_wait` mean **2522 ms → 274–332 ms peak**, max **4187 → ~1450 ms**
- queue-age now **recovers within the same minute** after the burst

**Migrated bottleneck (honest residual)**: the backlog moved downstream —
`queue_residence_ms` (bridge-enqueue → apply hop) rose to mean ~650–840 ms /
max ~2.9 s at the 05:17–18 burst minute; `corr_venue_age` mean ~1.2 s stayed
under the 3750 ms freshness bound (no false freshness).  Binding constraint
is now the **forwarder → per-ticker-queue → apply chain at ~700–800/s** —
the next hop in the user's measurement list (`publication → candidate
consumption`), and a *separate* capacity decision; not patched here.

**Instrumentation now live**: `pq_drain_profile.jsonl` rows (`ws_drain`,
`ws_recv` kinds, `drain_task` id, `MERID_PQ_PROF_INTERVAL_S` knob);
WS-loop lag chain re-enabled and populating (`avg_loop_lag_ms` ~10 ms,
`max` ~750–925 ms — periodic stall events worth their own look);
`MERID_WS_LOOP_DEBUG=1` + `MERID_WS_SLOW_CB_MS` give opt-in asyncio
slow-callback naming for targeted diagnostic runs; py-spy available at
`%LocalAppData%\Programs\Python\Python311\Scripts\py-spy.exe` for
repeatable wall attribution.

**Ordering/equivalence**: bounded dequeue batching (50/200 adaptive) +
sequential per-item awaits already existed — the user's preferred pattern;
nothing was reordered and no per-message tasks were spawned.  The bypassed
`_coalescing_buffer` remains **unused**: Kalshi quantity deltas are
incremental (apply-in-order); "latest-wins" aggregation would corrupt both
the book and path-dependent features (trap-guard ask history).  Any future
aggregation proposal must pass exact sequential-reference equivalence, not
final-book equality.

**Deployed vs committed**: production = `a9c7e43e` (verified via
`deployment_sha` in `live_entries_enabled`); earlier `a600f6f7` was doc-only.

### 2026-11-01 follow-up: no recent executions

The local fill ledger's latest non-settlement execution at inspection was
2026-11-01 00:57:52 UTC. The pinned-favorite UTC-day counter reached 480
at approximately 08:34 UTC. It counts decision emissions before allocation
and routing, not confirmed exchange submissions. It remains exhausted for
the UTC day; do not reset it to induce trading.

The order-attempt ledger contains 66 local `stake_at_risk_cap` rejections
since UTC midnight: configured six-contract candidates exceeded the 35%
shard-cash limit. All 66 record `submission_attempted=false`. Of these,
63 have selected-side net EV in the decision ledger and all 63 are
non-positive; the other three could not be joined to a recorded value.
Shrinking those candidates or changing the budget does not establish
positive executable edge and must not bypass the independent risk and EV
gates. Recent decision telemetry is also dominated by no-positive-edge
rejections. The effective live configuration at inspection uses a
six-contract per-order and pinned-favorite cap, not the two-contract cap
stated in the earlier handoff.

Correction to the drain-workstream interpretation above: the sampled TLS
stacks measure thread wall time, not GIL ownership or CPU consumption.
The before/after windows and synthetic traffic were not controlled replay
comparisons. They do not establish GIL contention, a causal effect of
session reuse, zero false freshness, or a migrated capacity ceiling.
Treat those explanations as hypotheses pending matched replay and
independent profiling.

### 2026-11-01 follow-up: sizing and daily budget

The pinned-favorite counter is an emission budget, not an exchange-order or
fill counter. Its UTC-day reset was already lazy: yesterday's count is ignored
on the first read after midnight, and the next emission records the new date.
The current day's 480 emissions have not been reset. Local changes serialize
in-process updates, block on invalid or future-dated state, and suppress an
emission when its counter cannot be persisted. Single-instance enforcement
remains required; the counter is not a cross-process lock.

Local sizing changes use a recent cache entry for the candidate's actual
exchange shard, apply the existing shard-cash stake percentage, and round down
on the centi-contract grid. The router's independent stake and collateral
checks remain in place. A candidate made routable by the resize additionally
requires positive recorded selected-side net EV and a positive final EV
recheck; this is not evidence that the previously rejected candidates have
positive edge. If the exact shard balance is unavailable or stale, no
stake-based resize is attempted and the router still decides.

These changes are not deployed or live-accepted. The 480/day budget can
still be exhausted before midnight because it counts emissions rather than
wire submissions; changing its accounting or limit is a separate risk-policy
decision. Rollover-feed replay acceptance, host time synchronization, and the
process-termination investigation remain open.

At 13:17 UTC the live drain profile reported 41,120 drops in its 60-second
window, and the book rollup reported `unverified_offset_expired` for all
28,378 applied events. The first inspected expired-status rollup began at
05:40 UTC. The code records the venue-clock calibration at WebSocket
authentication and expires it after 1,800 seconds by default, but no periodic
refresh was found. This explains the persistent unverified status; it does
not by itself establish the cause of the drop burst. Host synchronization and
live acceptance of calibration refresh remain open. The local refresh candidate
uses the existing live REST Date clock, samples off the WS loop before expiry,
and fails closed on request failure, cached responses, clock steps, delayed
delivery, or an older sample. It has mocked offline tests only; network
provenance, scheduling, and rollover behavior require live verification.

A further entry-readiness boundary defect was found: the WS-owned quote branch
could mark ownership trusted from a fresh REST mirror even when `ws_fresh` was
false. That did not establish that the priced quote was REST-owned. The local
fix requires the actual WS owner to pass `ws_fresh`; an independently fresh
REST quote remains eligible only when REST owns the effective quote and the
degraded-entry policy permits it. This safety fix is also not deployed.

At approximately 13:33 UTC, authorized read-only exchange checks returned zero
resting orders and zero nonzero positions, with no pagination cursor. The
local unified-health response reported zero cached open positions, but the
authenticated reconciliation endpoint returned HTTP 401 and settlement
worker drain state was not available. No restart was attempted: zero orders
and positions alone do not prove reconciliation and settlement readiness.

At 13:40 UTC a subsequent startup on `ed37a86b` passed the P0 preflight,
including exchange reconciliation with no open orders or positions, and
enabled live entries. The settlement poller started, but its backlog was not
independently verified. A later read-only live probe found that the periodic
clock refresh's HEAD request received HTTP 404 while GET returned HTTP 200.
The fallback to a separately timed GET was added and tested locally; a direct
live sample succeeded. The fallback is not active in the running `ed37a86b`
process and requires deployment and post-deploy verification.

### Historical unknown-submission investigation

On 2026-11-01, a read-only audit found 168 durable `SUBMISSION_UNKNOWN`
attempts dated 2026-08-18 through 2026-08-27 and 30 `SUBMITTING` attempts
dated 2026-08-26 through 2026-09-03. All have client-order and intent IDs.
None of their intent IDs remains in the current durable intent index, and
none of their client tags matches the expired-market sweep's ticker parser.
Consequently that sweep cannot identify a ticker for these records. The
poller's full submission-unknown reconciliation reads the in-memory
pre-trade gate, not this durable historical set. Its separate stale-record
prune can mark in-memory unknowns rejected after a TTL without an exchange
confirmation; that is not evidence that the historical attempts were rejected.

Kalshi's reported order-archive cutoff was 2026-10-18, and its historical
fill cutoff was 2026-09-02. Searching only the current endpoints or the local
fills ledger is insufficient: the local ledger's earliest fill was
2026-09-14. A paginated historical-order search for 2026-08-17 through
2026-09-06 returned 861 orders across five pages, with exactly two matching
the 198 client-order IDs. Time-filter controls matched known archived orders
and fills. The other 168 unknown and 28 submitting IDs had no matching order
in that bounded archive search. That is not proof that they were never
submitted, nor permission to rewrite their status.

The two matching `SUBMITTING` attempts are confirmed executed orders:

- BTC `KXBTC15M-26AUG282100-00`: order
  `01a04b03-90c0-732f-aee2-2594130c954b`, client order
  `exit_5a7092fcb267f1326e9e`, fill
  `0721670d-cfd9-bfbe-2f37-87af3d30d1e5`, one contract on 2026-08-29.
- SOL `KXSOL15M-26SEP010430-30`: order
  `01a05c13-d230-7ac1-80d6-41bbd8373388`, client order
  `merid_e841ff42c62e49e6aea7`, fill
  `07212c5c-9af1-93ab-887d-9ca0776b2c3b`, one contract on 2026-09-01.

Both exchange markets are finalized with result NO. Neither fill appears in
the current fills database or its applied-fill-ID index; this does not prove
they were never ingested because those stores do not cover the period. The
trade-attribution database retains the SOL fill and settlement events for
both markets, but their accounting has not been independently reconciled.

One further submitting attempt, client order `exit_243de9e364daa57f35f7`,
has a local pending-order attribution event for XRP market
`KXXRP15M-26SEP031300-00` and order
`01a06832-aa50-7dcd-a83d-5a59b6868e7a`. The ticker-filtered archive and
current order lookup did not confirm that order; the ticker's archived entry
and settlement are separate records. Its submission outcome remains unknown.
Four submitting records share an intent with a different later canceled
attempt; that does not establish the earlier attempts' individual outcomes.

No attempt status, fill, position, or trading policy was changed during this
investigation. At the operator's explicit direction, live entries remain
enabled; the running build remains `ed37a86b`, without the committed
`78f74205` clock-refresh fallback. Recovery and settlement-drain verification
remain prerequisites for a further restart.

The 14:11 UTC book-timing rollup recorded 57,090
`unverified_offset_expired` and 464 `measured` statuses. The runtime state
still reported `LIVE_ENTRIES_ENABLED` with PID 8144. WS-owned quotes must
fail their freshness gate when venue age is unverified; a REST-owned quote
may still be eligible under the existing degraded-entry policy. No entry
halt or second restart was requested by the operator during this audit.

### Recovery hardening and restart assessment

The subsequent read-only exchange check at approximately 14:26 UTC returned
no resting orders and no nonzero positions. Current canonical reconciliation
logs remained matched, but those checks do not resolve the historical
attempts or establish a drained settlement pipeline.

Local changes now preserve submitted/unknown gate records across TTL cleanup,
keep expired order attempts unresolved without terminal evidence, and require
fully matched, trusted live fill quantities before the expired-exit sweep can
mark an exit filled. Fast and background submission recovery no longer treat
empty or failed order lookups as authoritative non-submission, and reject
unmatched client identities rather than applying them to the wrong attempt.
An atomic durable submission claim is now required before the exchange
request; a failed or already-claimed attempt is not sent. Route cleanup also
keeps ambiguous outcomes unknown when the pre-wire marker was missing.
P0 now checks the durable attempt store read-only, without an age cutoff, for
unknown and submitting orders and exits. Against the current production
database this check fails with `order_attempts=198 exit_attempts=0`.

The settlement poller logged seven new settlements and its graded-key file
grew from 1129 to 1136 records. This confirms activity, not a drained or
correctly published backlog: the running lean server does not mount the
poller's status router. The ungraded-backlog count cannot independently prove
missing grading because the production code does not call `mark_graded`.
Further, callback exceptions are logged and swallowed before the dedupe key is
persisted, so a graded key alone does not prove all callbacks succeeded.

The operator requested a commit and restart after the remaining work. A
restart is not safe while those submission outcomes and settlement-drain
conditions remain unresolved. The current lifespan raises on a P0 failure,
so restarting with the new guard would also terminate startup rather than
keep protective services available. The clock-refresh fallback in `78f74205`
remains committed but is not active in the running process.

### Follow-up: stopped process and settlement recovery

At approximately 14:56 UTC on 2026-11-01, PID 8144, its launcher, and its
watchdog were no longer present; port 8011 was not listening. The last
watchdog heartbeat was at 14:53:17 UTC. There was no subsequent launcher
exit record, so the cause and exit status remain unknown. The persisted
`LIVE_ENTRIES_ENABLED` state is stale and does not represent a running server.
With explicit operator approval, read-only Kalshi checks at 14:58 UTC found
zero resting orders, zero nonzero market positions, and 19 fills in the last
24 hours, the latest at 00:57 UTC. Zero current positions does not resolve
the historical attempts or establish settlement accounting completeness.

Settlement-poller defects identified in the local follow-up:

- Ticker normalization rebuilt a subset of the settlement record and lost
  fractional exchange counts, raw payload, revenue, and reconciliation
  fields. Normalization now preserves the original fields.
- The account-settlement scan stopped on a short page despite a nonempty
  cursor, and returned incomplete/error scans as successful results. It now
  follows cursors until empty, deduplicates repeated records, and fails
  visibly on pagination limits, repeated cursors, malformed pages, or timeouts.
- The live API documents `min_ts`/`max_ts` in Unix seconds, not the previous
  `settled_after`/`settled_before` parameters.
- The batch audit join only processed the final settlement in each batch.
  It now processes every valid settlement.
- Callback failures were logged but still received a durable success
  watermark. Failed callbacks now remain unwatermarked and can be retried;
  the ledger, position-cache, outcome-export, and configured grading callback
  errors propagate rather than appearing successful. Redelivery is at least
  once and callback side effects must be idempotent.
- Failed watermark writes retain their dirty keys for a later attempt.

These changes do not establish a fully durable event-bus outbox or prove that
previously watermarked callbacks completed; both remain open. Startup still
cannot safely enable entries while the historical attempts remain unresolved,
and a failed P0 startup currently exits rather than preserving the protective
services. No restart or live order has been attempted in this follow-up.

External references: Kalshi's
https://docs.kalshi.com/api-reference/portfolio/get-settlements ,
https://docs.kalshi.com/getting_started/pagination , and
https://docs.kalshi.com/getting_started/historical_data document the current
settlement filters, cursor behavior, and distinct live/archive cutoffs.
https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html
describes durable outbox and idempotent-consumer requirements; the existing
in-memory pending-publish set does not meet that guarantee.

### Further account-evidence and fill-poll findings

Read-only cross-checks of `logs/order_decisions.jsonl` found ticker-bearing
events for all 30 old `SUBMITTING` attempts; none of the 168
`SUBMISSION_UNKNOWN` attempts matched by the durable IDs in this file.
These are local intent/firewall events, not venue acknowledgements. Several
client IDs appear in repeated attempts, so a local rejection of one event
does not establish that every submission with that identity was unsent.
No durable order statuses were changed.

Paginated historical order and bounded historical fill scans independently
confirmed the two prior matches, each one YES contract on exchange shard 2:

- BTC `exit_5a7092fcb267f1326e9e`: fill
  `0721670d-cfd9-bfbe-2f37-87af3d30d1e5` at $0.2900 plus $0.0145 fee.
- SOL `merid_e841ff42c62e49e6aea7`: fill
  `07212c5c-9af1-93ab-887d-9ca0776b2c3b` at $0.0580 plus $0.0039 fee.

Both fill IDs are absent from the retained `kalshi_fills` ledger. The SOL
fill is in the attribution database; the BTC fill has no linked attribution
row there. Event-filtered, paginated `GET /portfolio/positions` with
`settlement_status=settled` returned a zero position and zero market exposure
for each market. The market-level realized PnL and fees are aggregate
account results and cannot be attributed to either particular fill without
reconstructing every execution. The corresponding historical-position
queries returned no records; Kalshi documents a buffered handoff, so the
live settled-position records are the relevant observations here.

An unbounded historical-fills request using `order_id` reached the page
limit; no conclusion was drawn from that incomplete request. The confirmed
fill matches above use the documented time bounds and client-side order-ID
matching, with complete pagination.

The resilient live fills client had sent millisecond `since_ts` values as
Kalshi's `min_ts`, which is documented in Unix seconds. The fills poller,
canonical reconciler, and uncertain-order recovery all supply milliseconds;
their empty results therefore cannot be assumed complete historical evidence.
The shared client now converts milliseconds at the HTTP boundary, follows
all cursors, and reports failed, malformed, repeated-cursor, and page-limited
scans as incomplete. The execution port propagates failed fills, positions,
and open-order lookups instead of translating them to empty snapshots; open
orders now query Kalshi's documented `resting` status. P0 uses explicit
snapshot results, rejects failed ledger load/ingest/cache sync, and requires
fresh valid RTI observations for every requested asset.

The focused client, port, P0, submission-recovery and canonical-snapshot
suite passes 80 tests. Ten canonical-snapshot tests initially failed because
their static August tickers had expired; the fixture now also isolates the
settlement-pending quarantine, without changing production expiry policy.
The daemon logging monitor emitted closed-stream warnings during test exit.

The WS reconnect and book-recovery paths can currently call
`complete_preflight` without the fresh reconciliation, trusted fill
watermark, and durable recovery proof required by the runtime contract. The
runtime state machine now rejects this unverified recovery, retains exits,
and does not emit false preflight-success telemetry. This is a fail-closed
interim safeguard, not a complete automatic recovery coordinator: entries
remain halted until a new verified startup. Sixty-seven focused runtime,
book, bridge, and unknown-submission tests passed.

P0 now compares exact signed-YES centi-contracts per active ticker across
the exchange, a trusted ledger-fill projection, and the cache. It rejects
untrusted, unmatched, provisional, duplicate, and identity-incomplete live
fills; it checks the independent ledger projection before syncing the cache.
Expired and closed-but-unsettled markets use the canonical quarantine policy.
Position-monitor, allocator, and reservation reconciliation are not yet
proven by this change.

A related persistence gap affected the SQLite fills schema: it did not retain
`is_live`, `unmatched`, `unmatched_reason`, `derived_id`, or
`confirmed_by_rest`. New nullable columns preserve those values, side-conflict
and exposure-mismatch flags, and the exchange shard on future writes. Legacy
rows retain unknown live provenance and are treated as unmatched, rather than
being silently promoted to trusted live fills. They still need authoritative
recovery; this migration does not backfill assertions about their identities.
The current ledger has 1,781 retained rows. Restore now
reports failures and detects its 10,000-row cap; P0 fails closed if restore
is incomplete. A scalable complete restore remains to be implemented before
the cap is reached. Neither these checks nor the logged settled positions
resolve the 198 order attempts.

The fills poller's periodic reconciliation also treated failed, malformed, and
divergent snapshots as completed work and could clear position-monitor, slot,
and window-risk state after an empty positions response. It now halts entries
on those conditions, compares independent signed ledger/exchange/cache
projections, and verifies the unchanged cache under its mutex before updating
REST freshness. It does not clear reservations merely because positions are
empty. An unavailable drift check fails closed. A 404 market lookup does not
mark settlement delivery complete. Sixty focused reconciliation, restore,
and P0 tests pass; runtime auto-recovery and the startup protective-service
ordering remain open.

Startup and cache construction also contained unconditional or empty-cache
resets of window exposure, category notional, and slot reservations. Those
resets have been removed: an empty newly constructed cache does not prove
that pending orders or risk reservations are absent. This preserves safety
but does not itself reconstruct or reconcile the allocator. P0 currently
completes before the protective trading stack is confirmed started, and
failed P0 startup exits before that stack starts; both ordering defects
remain open and the server remains down.

The 15-minute loop also cleared every slot at rollover regardless of position
count and cleared cache/ledger positions when the cache appeared empty. The
order router similarly cleared slots after an allocation rejection based on
an empty asset cache. Those implicit resets are removed. The separate risk
envelope now retains executed and resting exposure across its window rollover
and blocks on cache-only exposure drift rather than rewriting the ledger.
Individual releases cannot deduct another agent's reservation. However,
same-agent duplicate releases still require order-level durable identities,
and full reservation reconstruction and independent reconciliation remain
open before live use.

The position monitor separately treated expired or missing cached positions
and empty order lookups as terminal submission outcomes. It now retains
unknown exit intents, validates the client order and market identity, and
requires a matched terminal zero-fill order plus a successful durable
transition before clearing the lock. Cancellation acknowledgements and
orders with filled or unknown quantities remain locked pending complete
fill/position reconciliation; the exchange order payload is recorded on the
successful terminal transition. The complete exit-recovery coordinator and
protective-service startup verification remain open.

The exit-state transition to SUBMITTING is best-effort and is separate from
the canonical order submission claim. Consequently, a stale INTENT_PERSISTED
exit record, including a migrated legacy JSON record, is not evidence of
non-submission. The timeout and obligation sweep now retain these records and
schedule reconciliation instead of marking them TERMINAL_UNFILLED and dropping
their in-flight locks.
