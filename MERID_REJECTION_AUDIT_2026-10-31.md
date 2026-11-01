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
