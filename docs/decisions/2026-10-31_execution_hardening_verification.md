# Execution-Hardening Verification Record â€” 2026-10-31

Immutable evidence record for the targeted execution-chain hardening pass
(feed integrity, endpoint validation, canonical fees, own-liquidity/STP depth,
fingerprints, independent oracle). Status model: I = implemented on live path,
S = statically reviewed, R = runtime-verified.

## Identity

- Tested tree: `C:\Dev\MERID`, HEAD `900db57706ffb6f7e89d9029f0dbb7a1d509966f`
  **plus uncommitted working-tree changes** (see Modified Files).
- Baseline SHA (clean-worktree comparison): `900db577` â€” same commit, no
  working-tree changes.
- Modified production files (uncommitted): `client.py`, `executable_quote.py`,
  `maker_taker_policy.py`, `market_state.py`, `order_intent_contract.py`,
  `order_manager.py`, `parabolic_fees.py`, `position_cache.py`,
  `resting_order_monitor.py` (all under `merid/event_venues/kalshi/` except),
  `merid/execution/submit_revalidation.py`, `merid/hedging/engine.py`,
  `merid/position_management/position_monitor.py`.
- New files: `merid/audit/economics_oracle.py`,
  `merid/event_venues/kalshi/contract_fingerprint.py`,
  `tests/test_execution_hardening_2026_audit.py`.
- Modified test files: `test_market_state_sid_sequence.py`,
  `test_parabolic_fees_and_policy.py`, `test_crypto_hedge_engine.py`,
  `test_hedge_50c_minimum.py`, `test_kalshi_client.py`.

## Environment profile (secrets excluded)

- OS shell: PowerShell functional; Git Bash broken
  (`Top-level not found: C:\Program Files\Git\bin`) â€” all runs via PowerShell.
- Interpreter: `C:\Dev\MERID\.venv\Scripts\python.exe`, Python 3.11.9.
- Test runner: pytest 9.0.2.
- `.env` present in working tree, gitignored, contains production flags
  (e.g. `MERID_EXIT_EVIDENCE_ENVELOPE=1`, `MERID_PROVISIONAL_*`) NOT pinned by
  `tests/conftest.py` â€” materially affects `test_suspension_recovery.py`.
  Baseline worktree lacked `.env` until deliberately copied for attribution.
- conftest pins: `MERID_ENV=testing`, `MERID_PM_TRADING_MODE=mock`,
  `KALSHI_API_KEY_ID=""`, durable-state paths redirected to per-process tempdir.
- No secrets or credentials were used; no live orders placed. Note: a direct
  `merid` import outside pytest does perform a live balance fetch at module
  init (~30s); under pytest the pinned env prevents credential use.

## Commands and file selection

All runs: `python -m pytest <files> -q` from the respective workdir.

- Hardening pack: `tests/test_execution_hardening_2026_audit.py`
- Regression batch 1 (37 files): submit_revalidation_maker, executable_quote,
  orderbook_executable_gate, parabolic_fee_exact, parabolic_fees_and_policy,
  order_intent_contract, fuzzing_order_intent_parsing, resting_order_monitor
  (+side_fix, dedup, lifecycle, yes_no_fixes, events, fallback),
  position_cache (health, sync, snapshot_fill_dedupe, rebuild_from_fills),
  kalshi_market_state (+regression, sid_sequence, snapshot_recovery,
  untrusted_ladder, schema), kalshi_client, kalshi_order_manager,
  hedging (crypto_engine, 2026_07_29_fixes, auto_exit_startup),
  maker_taker (economics_fix, gate_split, awareness), executable_edge
  (alignment, calculation_fix), executable_cost_ev_gate, hedge_50c_minimum,
  hedging_bug_fixes.
- Regression batch 2 (subset re-run, 4 files): parabolic_fees_and_policy,
  market_state_sid_sequence, kalshi_client, hardening pack â€” overlaps batch 1.
- Regression batch 3 (2 files): hedge_50c_minimum, crypto_hedge_engine â€”
  overlaps batch 1.
- Scenario batch (35 files): order_identity_recovery, postrestart_fixes,
  post_restart_safety_fixes, journal_recovery,
  market_state_recovery_state_machine, p0_preflight_fill_recovery,
  kalshi_p0_partial_fill_reconciliation, race_condition_invariants,
  per_asset_limit_race_condition_fix, market_state_race_conditions,
  exit_attempt_submitting_wedge, exit_order_chaos, exit_reconcile_ioc_dead,
  exit_reconciliation, chaos_order_submission,
  attempt_store_terminalization, order_attempt_store,
  order_router_ioc_tif_reconciliation, event_ordering_idempotency,
  idempotency_key_pattern, order_identity_exit_idempotent,
  loop_balance_idempotency, reconciliation_invariants,
  position_reconciliation, canonical_exposure_reconciliation,
  exit_reconcile_market_terminal, suspension_recovery,
  reconciliation_gate_transitions, chaos_compound_failures,
  chaos_position_reconciliation, chaos_risk_enforcement,
  market_state_snapshot_recovery, ws_snapshot_recovery,
  position_reconciliation_scenarios, queue_overflow_recovery.
- Baseline comparisons (worktree `MERID_head_baseline` at 900db577):
  (a) 6-file failing subset, no `.env`: 18F/64P.
  (b) `test_suspension_recovery.py` alone, no `.env`: 2F/27P.
  (c) `test_suspension_recovery.py` alone, `.env` copied: 5F/24P.
  (d) my tree, same file: 4F/25P.

## Results (batches reported separately; re-runs overlap batch 1)

- Hardening pack: **30/30 passed** (50.6s).
- Regression batch 1: **565 passed, 7 failed** (pre-repair; see Fixes).
- Regression batch 2 (overlapping): **114 passed**.
- Regression batch 3 (overlapping): **53 passed**.
- Scenario batch: **388 passed, 17 skipped, 20 failed** (299s).

## Contract changes vs test repairs vs production fixes

Intended contract changes (tests updated, not production reverted):
- Missing/unparseable `seq` on an **initialized, tracked** orderbook now
  invalidates execution â€” test split: `_FakeBook(last_seq=100)` + no seq â†’
  `(False, 101, None)`. **Preserved distinction:** with no seq baseline
  (`last_seq=None`) the validator stays permissive `(True, None, None)`;
  executability in that window is governed by the separate
  bootstrap/sequence-confirmation gates, not by this validator. Do NOT
  summarize as "all missing-seq messages are rejected."
- `reduce_only`+non-IOC rejected at intent and serializer; the V2 wire test
  now exercises the valid IOC path.
- `estimate_fee_for_sizing` returns the canonical fractional bound (17.33c
  for 55cÃ—10 taker) instead of whole-cent ceil 18.

Production fixes made during verification:
- `maker_taker_policy.py`: `RoleDecision.fee_cents_estimate` restored to
  declared `int` via `math.ceil` at all 8 sites â€” the exact sub-cent value
  still feeds the `edge_net_of_fees_pct` gate; downstream
  `intent.estimated_fee_cents` (`Optional[int]`) consumers remain inside the
  pending fee call-graph sweep.

Stale-test repairs (pre-existing rot, not production changes):
- `test_hedge_50c_minimum.py` Ã—2: added `mock_config.auto_exit =
  Mock(reduce_on_exposure_flip=False)` â€” instance attr invisible to spec'd
  mock; failure reproduced on HEAD.
- `test_crypto_hedge_engine.py::test_constant_in_file`: frontend constant
  `KALSHI_METRICS_HEDGE` was deliberately removed in the documented
  dead-route cleanup; test now asserts the documented-absence contract
  (backend route still covered by `test_endpoint_file_has_route`).
- `test_execution_hardening_2026_audit.py::test_submit_maker_stp_skips_own_and_passes`:
  corrected assertion â€” `eligible_qty_cc` is capped at requested qty (500),
  not external depth (600); added an 800cc request case proving the cap.

## Scenario failures â€” all pre-existing (verified on unmodified HEAD)

`test_exit_order_chaos_2026_07_23` (7): `test_exit_registry_maintains_state_during_lag`,
`test_cancelled_order_removed_from_registry`,
`test_quantity_coverage_detects_insufficient_partial_fills`,
`test_multiple_partial_exits_sum_correctly`,
`test_registry_authority_overrides_exchange_heuristics`,
`test_registry_syncs_on_order_completion`,
`test_timeout_allows_retry_after_failed_exit` â€” the production
`[EXIT-REGISTRY] Refusing to register exit order for removed/unknown position`
guard (position_monitor.py ~2500) rejects registration for positions the test
never registers; guard behavior is deliberate, tests are stale. Open question:
whether tests, guards, or both need repair â€” safety-relevant, tracked.
`test_attempt_store_terminalization_2026_09_07::test_acknowledged_record_not_regressed_by_rejection`;
`test_order_attempt_store::test_exit_attempt_lifecycle_and_concurrency` â€”
attempt-store lifecycle/concurrency coverage broken; relevant to Group C.
`test_idempotency_key_pattern` (4): `test_order_intent_has_idempotency_key`,
`test_client_order_id_format`, `test_idempotency_key_added_to_headers`,
`test_duplicate_intent_different_keys` â€” open whether naming-expectation rot
or substantive duplicate-protection gap.
`test_exit_reconcile_market_terminal_2026_10_27` (3):
`test_expired_market_attempt_closes_out`, `test_real_evidence_beats_inference`,
`test_history_bounded_with_tombstone` â€” terminal-market cleanup/exposure
accounting undemonstrated.
`test_suspension_recovery` (4 in my tree; 5 on baseline+.env, superset):
`test_router_rejects_are_execution_class_not_losses`,
`test_economic_suspension_waits_longer_than_execution`,
`test_missing_artifact_never_production_qualifies`,
`test_markout_suspension_is_exec_quality_and_waits_longer` â€” `.env`-driven
(`MERID_EXIT_EVIDENCE_ENVELOPE=1` et al.); behavior expected under a
controlled environment is undecided. `test_bid_basis_prices_not_verified_as_asks`
fails on baseline but passes in my tree (net âˆ’1 for the changes).

Attribution: **no new failures attributable to the hardening changes were
identified in the exercised suites.** "Pre-existing" establishes attribution,
not harmlessness â€” several failures sit inside the resting-exit/restart/
idempotency domain under review.

## Skips (unexecuted coverage, reasons preserved)

17 skips, all `tests/event_venues/kalshi/test_position_reconciliation_scenarios.py`
marked `P0-RECONCILIATION: TRACKER-004: Reconciliation is live-critical` â€”
scenario coverage explicitly gated off, not demonstrated.

## Closure statement

Groups A, B, and the completed portions of D are closed at IÂ·SÂ·R for the
invariants the executed tests demonstrate. Fingerprint-change enforcement,
durable reservationâ†”intent single-commit binding, mode-aware crossed-book
policy, the resting-exit aggregate-quantity bound, and the remaining
fee-helper call-graph sweep stay open. Skipped scenarios and pre-existing
broken safety coverage remain tracked separately. Production correctness and
profitability are not claimed.

## Addendum — pre-existing failure repair (2026-10-31, same build SHA)

The 20 scenario failures attributed to baseline/environment above were repaired
as five separate reviewable changes. Reproduction preceded every expectation
change. Per-failure classifications follow; all node IDs are the original
failing nodes from the scenario batch.

### Cluster 1 — attempt-store terminalization/concurrency (19/19 pass)

- `tests/test_attempt_store_terminalization_2026_09_07.py::test_acknowledged_record_not_regressed_by_rejection`
  - Expected: local `rejected` route result must not regress ACKNOWLEDGED. Actual: regressed to REJECTED.
  - Production branch: `order_router._finalize_attempt_store_for_result` broad `rejected` arm.
  - Classification: production defect (narrow) — local-only rejection (no venue contact) cannot prove a venue-acked order dead; venue-evidenced rejection terminalization (dead-COID 409-loop fix) must be preserved.
  - Correction: `order_router.py` — the `rejected` branch now regresses ACKNOWLEDGED only when `submission_attempted=True` or `submission_certainty="rejected"`; test split into local-reject negative case + venue-evidenced positive case.
  - Safety property: acknowledged orders never downgraded on local verdicts; dead-COID rebind loop still stopped on venue verdicts.
- `tests/event_venues/kalshi/test_order_attempt_store.py::test_exit_attempt_lifecycle_and_concurrency`
  - Expected: `NOT_ACCEPTED_CONFIRMED -> FILLED` returns None. Actual: returned record.
  - Classification: stale test — the edge is deliberate (2026-10-18 incident: exchange fill racing a stale REST "not accepted").
  - Correction: replaced the invalid-edge check with `NOT_ACCEPTED_CONFIRMED -> RESTING`; the FILLED edge is asserted allowed as the documented late-fill path.
  - Safety property: authoritative late fills still supersede local terminal verdicts; genuinely invalid transitions still rejected.

### Cluster 2 — idempotency-key pattern (9/9 pass; no production changes)

- `test_order_intent_has_idempotency_key`, `test_client_order_id_format`, `test_duplicate_intent_different_keys`
  - Expected: construction-time `client_order_id` in `client_`+16hex format. Actual: `None` at construction.
  - Classification: stale tests — durable identity is intentionally bound by `finalize_order_identity` immediately pre-wire (`merid_`+20hex), so retries share identity by fingerprint dedup.
  - Correction: tests now assert `idempotency_key` unique at construction, `client_order_id` None until finalize, identical-fingerprint dedup shares identity while unresolved, distinct fingerprints get distinct identities, terminal attempts consume their coid permanently, re-entry retains identity. Substantive duplicate/concurrency/unknown-outcome coverage already exists in `test_order_identity_recovery.py` (passing).
- `TestIdempotencyKeyInClient::test_idempotency_key_added_to_headers`
  - Expected: `Idempotency-Key` header on the wire. Actual: never reached header construction.
  - Classification: fixture defect — `VenueOrder` lacked `outcome_id`; the direction guard blocked upstream.
  - Correction: added `outcome_id="yes"`; the negative sibling (`test_idempotency_key_not_added_when_missing`) received the same fix (it had been passing vacuously).

### Cluster 3 — exit-registry chaos (18/18 pass; no production changes)

- `test_exit_registry_maintains_state_during_lag`, `test_cancelled_order_removed_from_registry`, `test_quantity_coverage_detects_insufficient_partial_fills`, `test_multiple_partial_exits_sum_correctly`, `test_registry_authority_overrides_exchange_heuristics`, `test_registry_syncs_on_order_completion`
  - Expected: `_register_exit_order` registers. Actual: refused ("removed/unknown position").
  - Classification: fixture defects — the 2026-09-24 guard legitimately requires the position in `_open_positions`; fixtures never seeded it (and `add_position` cannot be used: it also rejects the fixtures' expired test ticker).
  - Correction: `_seed_open_position` helper seeds `_open_positions` directly — the unit under test is the registry, not add_position's market-validity gates.
  - Safety property: the orphan-registry guard is unchanged; new negative test `test_registry_refuses_exit_for_unmonitored_position` proves unauthorized registration still fails.
- `test_timeout_allows_retry_after_failed_exit`
  - Expected: timeout releases the in-flight lock. Actual: TypeError (dict-shaped flight record subscripted by stale float write) — and timeout now transitions to SUBMISSION_UNKNOWN, still blocking.
  - Classification: stale test + fixture-shape defect — 2026-08-09 contract: unknown outcomes are never silently dropped.
  - Correction: rewritten — timeout => SUBMISSION_UNKNOWN (still blocks), `_mark_exit_intent_reconciled` => retry allowed.
  - Safety property: a timed-out exit can never be silently resubmitted while its outcome is unproven.

### Cluster 4 — market-terminal exit reconciliation (10/10 pass; no production changes)

- `test_expired_market_attempt_closes_out`, `test_real_evidence_beats_inference`, `test_history_bounded_with_tombstone`
  - Expected: `arbitrate` submits on `KXSOL15M-26OCT181930-30` so reconcile can infer terminal. Actual: `status="market_terminal"`, no attempt minted.
  - Classification: stale tests — the 2026-10-29 step-3.5 gate (live incident: ~46 never_transmitted attempts wedging on a settled market) correctly refuses fresh mints on terminal markets; the reconcile-inference path under test exists for *pre-existing* unresolved attempts.
  - Correction: `_mint_wedged` helper writes the unresolved SUBMITTING attempt row directly (the real incident shape: minted while live, expired while wedged). New negative test `test_arbitrate_refuses_fresh_mint_on_terminal_market` pins the gate.
  - Safety property: terminal markets can never mint replacement exits; pre-existing unresolved attempts still reconcile via `market_terminal_inferred`.

### Cluster 5 — suspension recovery (29/29 pass; no production changes)

- `test_router_rejects_are_execution_class_not_losses`
  - Expected: 2 consecutive rejects suspend. Actual: stayed PROVISIONAL.
  - Classification: stale test — threshold deliberately raised 2->3 on 2026-10-14 (`MERID_CBP_ROUTER_CONSEC_SUSPEND`; degraded-WS reject-burst incident).
  - Correction: pins `MERID_CBP_ROUTER_CONSEC_SUSPEND=2` and asserts the boundary (1 reject does not suspend).
- `test_economic_suspension_waits_longer_than_execution`, `test_markout_suspension_is_exec_quality_and_waits_longer`
  - Expected: econ/exec-quality floors 24h. Actual: released at .env-pinned shorter floors.
  - Classification: environment dependency — recovery floors are env-tunable and the developer .env sets them.
  - Correction: `lanes` fixture now pins every exercised `MERID_CBP_RECOVERY_*`/`MERID_CBP_PROBATION_*`/`MERID_THRESHOLD_CELL_*` knob to its documented default.
- `test_missing_artifact_never_production_qualifies`
  - Expected: net_edge=1.0 fails empty-evidence economics. Actual: `EVIDENCE_ARTIFACT_MISSING_PASS` allowed.
  - Classification: environment dependency — .env lowers `MERID_EVIDENCE_SPARSE_UPLIFT_C` and enables bounded lanes whose negative floors substitute for the generic uplift inside their price bands.
  - Correction: new `evidence_env` fixture pins `MERID_EVIDENCE_SPARSE_UPLIFT_C=2.0`, cell-policy/escape flags, a hermetic escape state path, and disables pinned-fav/drift/cheap-NO floor substitution; applied to all three artifact tests.
  - Safety property: missing/stale artifacts still admit only via the bounded escape lane; the env-tunable floors remain production config, now exercised deterministically.

### Post-repair totals

`test_attempt_store_terminalization_2026_09_07.py` + `test_order_attempt_store.py`: 19/19.
`test_idempotency_key_pattern.py`: 9/9. `test_exit_order_chaos_2026_07_23.py`: 18/18.
`test_exit_reconcile_market_terminal_2026_10_27.py`: 10/10. `test_suspension_recovery.py`: 29/29.
All original failing nodes pass for explained reasons; each cluster carries a negative control proving the guard under test still rejects the unauthorized path. Production changes in this addendum: one (the ACKNOWLEDGED-local-reject narrowing) with regression coverage. Deferred architectural controls remain open and unaffected.
