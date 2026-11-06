# cheap_no_settle Counterfactual Report #1 — 2026-11-06

Bounded report per scope `MERID_CHEAP_NO_COUNTERFACTUAL_SCOPE_2026-11-06.md`.
No threshold/lane change is proposed or authorized. Convention: candidate
price = own-side bid (post-only maker); settlement P&L = C(Y−P)−F;
`liquidity_role` on fills is NULL (missing) — role is *inferred* from the
submitted route + `fee_cost`, never asserted from the fill row.

## 0. Preservation status (evidence constraint)

The book archive (`data/kalshi_book_archive.db` + 9.87 GB uncheckpointed
WAL, last write ~Nov 5 15:48 local) was byte-copied verbatim to
`data/preserved_book_archive_2026-11-06/` (~14.2 GB). Readable window in
the checkpointed main file: **2026-11-04 23:43 → 2026-11-05 05:11 UTC**,
6,524,079 frames; coverage states 65 closed / 70 covering / 75 gapped.
WAL tail may extend the window once the copy is recovered; the tail copy
is torn-tolerant (WAL checksum boundaries) — any truncated trailing
commit is dropped by recovery, flagged in §B.

## A. Historical T0 — candidate settlement economics

Population: `logs/cheap_no_research.jsonl`, 193,009 side=no eval rows.
Lane gates reconstructed: own-side bid in band, TTE≥240s, yes-ask ≥55¢,
p_no(cal|raw) ≥0.12, net_edge_maker ≥ −0.10, quote ≤1s / RTI ≤2s, no
data-quality `decision_reason`. Dedup = first qualifying observation per
ticker. Settlement join: `logs/settlement_outcomes.jsonl` (47,839 tickers).

**Domain boundary:** the research shadow only records its own band —
**zero rows exist ≥25¢ in `cheap_no_research.jsonl`** (structurally
band-limited 10–25¢; verified by full-file scan, 193,009 rows). The
live-domain T0 therefore comes only from `decision_audit.db`
(`strategy_decisions.gate_results_json.executable_quotes.observed
.no_entry_price_cents`).

**Baseline extraction status (2026-11-06):** running, writing to
`logs/_baseline_2540_evals.jsonl`. Indexed range scan on
`idx_decisions_ts` over Oct-25→Nov-06; throughput ~1 kept row/s —
full census is a long-running artifact, left running. Early interim
signal (first ~6.4 min of Oct-25, 789 rows — NOT a cohort result):
bands 20–25¢:98, 25–30¢:96, 30–35¢:177, 35–40¢:175, 40–45¢:243;
assets all represented; TTE ≥600s:471 / 300–600s:318;
decisions 785 NO_TRADE / 4 ENTER; dominant failures
`no_positive_ev`/`no_edge_threshold`/`no_cost_basis` (~99%) — i.e. at
these prices the EV/cost gates bind, integrity gates mostly pass.
**T1-window sub-extraction** (Nov-04 23:43→Nov-05 05:11 UTC) running to
`logs/_t1window_2540_evals.jsonl` — pairs with the ≤25¢ side from the
research file (642 rows / 37 tickers in-window, 0 eligible).

### Expansion pocket 20–25¢ — arithmetic audited 2026-11-06 (supersedes earlier figures)

Two honest denominators (both `research_eligible=true`, fee=0 gross):

| view | n | win% | mean px | P&L/contract |
|---|---|---|---|---|
| all eligible obs (≤1/ticker/min) | 3,184 eps | 23.96% | 21.48¢ | **+2.48¢** |
| **first-per-ticker (independent markets)** | **896 markets** | 25.67% | — | **+4.05¢** |

Per-asset at first-per-ticker: DOGE n=299 +5.79¢ · SOL n=210 +3.66¢ ·
XRP n=194 +4.61¢ · ETH n=193 +1.20¢. At episode level ETH is negative
(−3.63¢/c, n=691) — later re-entries inside losing markets dilute it;
ticker-level it is marginally positive. DOGE leads either way.
Span: 2026-09-29 → Oct-15+ (≥17 calendar days, multi-week — an earlier
"2-day" epoch split was a string-slice bug, retracted).
Breakeven = equal-weighted mean entry px (21.48¢ → 21.5% needed; 25.7%
observed at ticker level). Figures are gross — the 4 reconciled fills
record `fee_cost=0.0`, so no maker fee is deducted; the shadow's modeled
0.2¢/contract column is retained only as a conservative bound, not as the
point estimate. Repeated observations per market share one settlement —
**896 is the deduplicated n** (unique tickers), not 3,184; dedupe fixes
repeated-settlement counting but does **not** by itself establish
statistical independence across markets.
Earlier "+2.21¢, n=4,183" used a looser dedupe; superseded.

### Research band 10–20¢ (5,393 unique eps, 5,375 settled)

| px | n | win% | avg px | P&L/c (fee=0) |
|---|---|---|---|---|
| 10–15 | 923 | 13.7% | 12.6¢ | +1.08¢ |
| 15–20 | 4,452 | 19.5% | 17.6¢ | +1.86¢ |

Candidate-level positive across the band, strongest at 20–25¢.
Caveat: audit's ENTER-cohort numbers (33%/38% at 20–40¢) used a different
denominator (engine-admitted, not lane-eligible) — direction consistent,
magnitude not comparable.

## B. Archive-window T1 scenarios — NOT RUN

Book reconstruction (delta replay over the preserved window) is a
separate job; no scenario results are claimed. When run: scenarios only
(`fill_optimistic` depletion=fill / `fill_conservative` depletion=cancels,
trade-through only / `fill_impossible`), pinned policy params, 24h-window
T0 compared against §A to expose recent-population drift. T2 (queue-aware)
remains unsupported — no prints, no queue depth.

## C. Lifecycle reconciliation — all 15 attempts

Statuses are row-state, not terminal. Joined via full client_order_id
(prefix-truncation caused the earlier false "no fills").

| attempt | ticker / quote | terminal | economics | confidence |
|---|---|---|---|---|
| oa_b61aea… | ETH 10-26, buy_no×2@~26¢ | **FILLED** (fee 0) → exit no-sell@49¢ (+3.5¢ fee) | realized ≈ **+19.5¢/c**; settle=YES → held −26¢/c | verified fill + verified exit |
| oa_c4296658 | SOL 11-01, buy_no×6@28¢ | **FILLED** 1.36+4.64 (fee 0) → exit no-sell×6@47¢ (+10.5¢) | realized ≈ **+17.5¢/c**; settle=no won → held +72¢/c | verified fill + verified exit |
| oa_3a96c594 | ETH 11-02, buy_no×6@33¢ | **FILLED** ×6 (fee 0), no exit row → held to settlement | settle=no won → **+67¢/c realized** | verified fill + settlement |
| oa_a1e4bda8 | SOL 11-03, buy_no×6@31¢ | **FILLED** ×6 (fee 0) → exit yes-buy×6@52¢ (cover NO@48, +10.5¢) | realized ≈ **−16.7¢/c**; settle=YES → held −33¢/c | verified fill + verified exit |
| oa_1a873934 | SOL 11-02, buy_no×6@37¢ | ACK → **expired unfilled at market close** | submit 1793623611 → market settle 1793624434 (rested 823s); no fill in canonical ledger; no explicit expire event type exists — expiry inferred from market lifecycle | verified no-fill + inferred expiry |
| oa_2b9dca85 | ETH 11-03, buy_no×6@27¢ | ACK → **expired unfilled at market close** | submit 1793691215 → settle 1793691958 (743s); no fill joined | verified no-fill + inferred expiry |
| oa_302f6f7b | ETH 11-03, buy_no×6@27¢ | ACK → **expired unfilled at market close** | submit 1793740806 → settle 1793741566 (760s); no fill joined | verified no-fill + inferred expiry |
| oa_a6fab849 | ETH 11-03, buy_no×6@30¢ | ACK → **expired unfilled at market close** | submit 1793745274 → settle event 1793751057 (poller lag; order life bounded by market close); no fill joined | verified no-fill + inferred expiry |
| oa_9367d854 | ETH 10-31 @25¢×6 | REJECTED pre-submission | `net_of_cost:zero_or_negative_edge` (submission_attempted=false). **No decision-audit lifecycle exists for this candidate** (`cand_47c932f8` has zero `strategy_decision_events` rows); classification rests solely on the `kalshi_order_attempts` ledger row — its selection/submission timestamps and transitions remain unknown | terminal, provenance incomplete |
| oa_d08ff560 | ETH 11-01 @33¢×6 | REJECTED pre-submission | legacy payload — no `route_reason` field | terminal, reason unknown |
| oa_5d5df10e | SOL 11-01 @28¢×6 | REJECTED pre-submission | `market_not_entry_ready:NOT-EXECUTABLE` | terminal |
| oa_849c9604 | ETH 11-02 @30¢×6 | REJECTED pre-submission | legacy payload — no `route_reason` field | terminal, reason unknown |
| oa_08b36a05 | SOL 11-02 @37¢×6 | REJECTED pre-submission | `market_not_entry_ready:NOT-EXECUTABLE` | terminal |
| oa_bd22c321 | ETH 11-03 @33¢×6 | REJECTED pre-submission | `net_of_cost:book_not_initialized` | terminal |
| oa_28f69e9c | ETH 11-03 @25¢×6 | REJECTED pre-submission | `market_not_entry_ready:NOT-EXECUTABLE` | terminal |

Counts: FILLED 4 / ACK→**inferred** expired-unfilled 4 / REJECTED-local 7 = 15. ✓
All mutually exclusive terminal classes now. The 4 unfilled ACKs carry an
*inferred* expiry label — resting timelines through market close with no
canonical fill; the audit table records no explicit exchange expiry event.
Rejection profile: 3× `market_not_entry_ready:NOT-EXECUTABLE` (book not
executable at routing time), 1× `net_of_cost:zero_or_negative_edge`,
1× `net_of_cost:book_not_initialized`, 2× legacy-schema unknown —
the two unknowns are **not** classified as quote-decay; their payload
schema predates `route_reason`. **None reached the exchange**
(`submission_attempted=false`) — local router rejections, not exchange
rejects.
Fill arithmetic (descriptive, not a rate estimate): 4 fills / 8 orders
that actually posted = 50%; 4/15 of model-selected intents. The 4
expired-unfilled quotes rested 743–823s to market close untouched.

### Selection→submission latency (measured, n=14 of 15)

Endpoint precision: `ORDER_SUBMITTED` is an **internal audit event**
recorded when the routing/submission attempt is staged — it appears on
locally-rejected paths too and does **not** mean "request sent to
exchange." Exchange submission is only verified where
`exchange_order_id` is non-null (the 8 posted orders); on the 7
rejected paths (`submission_attempted=false`) it marks routing-entry.

`MODEL_SELECTED`→`ORDER_SUBMITTED` deltas (seconds): fills 7.0, 7.4,
39.1, 76.6 · expired 11.7, 13.1, 14.0, 15.7 · rejected 6.3, 12.3,
21.1, 22.1, 76.9, 100.9 (+1 with **no audit events at all**:
`cand_47c932f8` — separate provenance gap).
Median ≈13.6s, range 6.3–100.9s. Expired orders cluster 11.7–15.7s;
rejections spread across the tail. Descriptive only — n is too small to
attribute outcome to wait time; what changed during the wait is the
unknown the path instrumentation below must capture.

### Path instrumentation required (selection→posting)

Existing audit captures selection and submission timestamps only.
Missing per-candidate: book-view age at selection, routing-start ts,
final revalidation ts + its observed book state (price/size/trust/
sequence/net-edge), submission-attempted boundary, exchange-ACK ts,
explicit terminal event (fill/cancel/expire — expire currently absent).
Report elapsed-time distributions and outcome transitions; classify the
7 rejections' wait cause (queue vs recheck vs routing work) before any
remedy — instrumentation only, no admission-behavior change.

**Realized (not counterfactual) summary:** 4 fills → 3 exited before
settlement (+19.5, +17.5, −16.7¢/c), 1 held (+67¢/c). In 2 of 3 exit
cases the exit beat hold-to-settlement (−26 vs +19.5; −33 vs −16.7);
in the third it forfeited +72¢. The observed exits are an exit-policy
result and do not validate the hold-to-settlement assumption.

## D. Fee reconciliation

| observation | value |
|---|---|
| cheap_no fills (4) | `fee_cost=0.0` recorded — **zero maker fee on this series** |
| research shadow models | `fee_cents_maker=0.2` — **overstates realized by ~0.2¢/contract** |
| nonzero-fee buys in window | match taker parabolic exactly (6@91.9→3.13¢; 6@99.4→0.26¢) — the pf "~2.3¢/fill-event" mixes taker-routed fills, different scope |
| exits (2 observed) | ~10.5¢/6-contract = ~1.75¢/c charged (taker-priced exits) |

## Verdict (updated 2026-11-06, post-reconciliation)

Per the bounded gates: **continue research; nothing here supports a
live change.** All 15 attempts are now terminally classified: 4 verified
zero-fee maker fills, 4 verified-expired-unfilled at market close, 7
local pre-submission rejections (never reached the exchange — quote
validity lapse and cost-gate causes, not exchange behavior). Expansion
pocket 20–25¢: +4.05¢/c at the independent-ticker denominator (896
markets, ≥17 days, all-asset-positive at ticker level) — candidate-level
economics only; fillability unknown. Named remaining gaps: the 25–40¢
live-domain T0 (decision_audit extraction — running) and T1 scenario
replay on the preserved ~5.5h window (Nov 4 23:43 → Nov 5 05:11 UTC —
coverage stated exactly, not "24h"). Canonical `yes sell` fill mapping:
a `buy_no` intent is canonicalized as `yes`+`sell` at price (100−no_px);
collateral = NO max-loss = no_px×qty — recorded explicitly per §C rows.
