# MERID Learning Eligibility Manifest — v1.0

Date: 2026-11-02. Build: `5a227a0c`. Contract: `canonical-fill-view/1.0`.

This manifest defines which durable records are eligible for each
learning/validation task, and the versioned rebuild plan for artifacts
computed on polluted data. It does not delete or rewrite any record; raw
rows stay retained under the canonical contract's quarantine classes.

## 1. Eligibility classes

| Class | Meaning | Source of truth |
|---|---|---|
| `eligible` | Verified-canonical record on the clean path | canonical view `verified_venue` fills; audit rows `is_eligible_for_research=1` |
| `eligible_provisional` | Retained but unverified — usable for provenance, not economics | `provisional_unverified` coverage, `unpaired_provisional` fills |
| `ineligible_mirror` | Duplicate representations of a venue fill | `mirror_matched`/`mirror_partial` fills (`_superseded_mirror_fills`) |
| `ineligible_conflict` | Side-conflict quarantine — cannot be interpreted as executed fact | `side_conflict` fills (d3ae: both representations) |
| `ineligible_gap` | Records missing/dropped during an infrastructure incident | decision_audit writer-failure ledger + heartbeat gaps |
| `ineligible_stale_contract` | Derived artifact computed under the pre-canonical contract | see §3 rebuild list |
| `resolved_exchange` | Local rows corrupt/incomplete; economics verified at exchange settlement/cost-basis | `GET /portfolio/settlements` records — see §2 |

## 2. Record-level exclusions (durable)

| Market | Class | Reason |
|---|---|---|
| `KXXRP15M-26SEP241000-00` (d3ae) | `ineligible_conflict` for fill-level pipelines; `resolved_exchange` for episode economics | RESOLVED 2026-11-02 at exchange truth: buy-NO 1.0@~69.9c entry + buy-YES 1.0@40c hedge → pair paid $1.00 at YES win → **−13.06c**. Raw venue rows retain inverted `action`/`side` labels and complement-priced proceeds; canonical net-delta cannot represent a hedged pair — episode economics live in the settlement record, not the fill rows. All fill-level records still excluded; decision/outcome rows usable only with resolution-note economics |
| `KXXRP15M-26SEP251730-30` (da6e) | `resolved_exchange` | RESOLVED 2026-11-02: exchange fill `0723b3d4` exists (never ingested — 09-25 fills-poller gap); settlement shows held 1.0 NO cost $0.64 at YES win → **−65.62c real loss**, not phantom. Episode verified at exchange truth; venue fill is a backfill candidate (`fills_poller_gap_backfill` marker) — until landed, canonical projections still exclude it |

## 3. Artifact-level rebuild list (versioned)

Artifacts computed on the pre-canonical (mirror-polluted) dataset are
`ineligible_stale_contract` until rebuilt on canonical data:

| Artifact | Records | Action |
|---|---|---|
| `exit_counterfactuals` on the 22 mirror-affected markets | 14 rows | Rebuild under contract 1.0 (v2, keep v1 rows annotated) |
| `bankroll_reconciliation` settlement-trigger telemetry | 468 rows | Preserve as `v1_telemetry`; recompute affected settlements on canonical fills |
| Calibration outputs on the 22 changed markets | 22 market-buckets | Re-fit per-market tail curves on canonical fill set before reusing in eligibility |
| decision-audit episode aggregates (A-basis totals) | full history | Label A-basis totals `as_computed_legacy`; C-basis (verified-only: −4384.53c/−3301.68c/−1082.85c, 798 eps) is the reference benchmark, not a bound; **complete-history at exchange truth: −4463.21c ≈ −$44.63** (d3ae −13.06c + da6e −65.62c added) |
| `kalshi_fills` backfill: da6e venue fill `0723b3d4` | 1 row | Ingest with `ingestion_source=fills_poller_gap_backfill`, `fill_source` trusted (exchange-verified via fills feed + settlement cost basis); mirror `live_router_01a0da6e` then classifies `mirror_with_side_conflict` |
| d3ae raw venue rows (3 fills) | 3 rows | Retain as ingested (evidence immutable). Label-corrupt `action`/`side`/proceeds handled at projection layer via `resolved_exchange` note — do not rewrite raw rows |

## 4. Incident-gap ineligibility (durable windows)

| Window | Class | Reason |
|---|---|---|
| 2026-11-02 02:16:04–02:58:29 ET (server run on 142b5419) | `ineligible_gap` for decision-audit evidence | shared writer conn poisoned `SQLITE_READONLY` during WAL recovery; ~1529 audit writes dropped + ~400 backlog at second boot. Fills/trading unaffected (separate DBs); heartbeat rows during window undercount `decisions_persisted` — cross-check against `decision_audit_writer_failures.jsonl` before using heartbeat coverage metrics |
| 2026-11-01 shutdown (unclean) | watch | stale 8.3MB `-wal` left; recovered cleanly at next boot — verify no row loss via heartbeat continuity around the boundary |
| 2026-11-02 04:22+ UTC (run `20261102082501_12096`) | watch | WS-SID sequence-gap storm — gaps up to 915 every few seconds; all books invalidating repeatedly, REST resync each time. Decisions during storm windows ran on degraded/invalidated book state; reconcile `market_state` freshness before treating window decisions as clean-cohort |

## 5. Task-level eligibility matrix

| Task | Eligible input |
|---|---|
| Entry model/calibration refit | `verified_venue` fills only; d3ae market usable only via `resolved_exchange` note (hedged-pair economics); exclude mirror windows' duplicated cash flows; da6e episode usable at exchange-truth −65.62c (NO-side loss) |
| Exit-policy (profit_only_v1) evaluation | Canonical round-trips C-basis; entries post-5a227a0c carry `original_persisted` provenance — prior sessions' `no_exit` episodes include quarantine-blocked cases that must not be read as policy intent |
| Fill-rate/maker-execution stats | All live fills incl. mirrors flagged; mirrors carry router-provisional identity useful for latency analysis |
| Cooldown/bankroll adjustments | Canonical PnL only — the 22 changed markets differ materially (worst: SOL-210915 +162.4c→−29.6c) |
| Session-performance reporting | Current-build prospective cohort only (sessions on ≥142b5419), each labeled with coverage metadata |

## 6. Versioned rebuild procedure (proposed, needs review)

1. Freeze v1 artifacts: rename/annotate `exit_counterfactuals`, calibration buckets, bankroll telemetry with `contract_version='pre-canonical'` markers (annotation, not deletion).
2. Recompute on canonical inputs under `contract_version='canonical-fill-view/1.0'`:
   - 14 counterfactual rows from verified fills + persisted entry intents.
   - 468 bankroll telemetry rows from settlement pseudo-fills + canonical residuals.
   - 22 market calibration buckets.
3. Publish rebuilt artifacts as v2 with `rebuilt_from` provenance pointers to the canonical fill_ids used.
4. Dual-record during transition: keep v1 rows readable with `ineligible_stale_contract` tags until v2 is reviewed and promoted.
5. Verification gate: rebuilt episode totals must reproduce the C-basis partition (fully 482 / partial 4 / no_exit 312 = 798) before promotion.
