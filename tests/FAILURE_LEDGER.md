# Test Failure Ledger

Classification of known test failures found during the Phase A audit
(2026-11-12).  Every entry records whether the failure reproduces on the
parent of the Phase A commits (`be22b526`), its failure class, the
authoritative source of the expected behavior, production risk, and
resolution.

Classes: `obsolete_expectation`, `env_config_leakage`,
`real_production_defect`, `time_dependent`, `nondeterministic`,
`unsupported_legacy`.

| test_id | reproduces_on_parent | failure_class | expected_behavior_source | production_risk | resolution |
|---|---|---|---|---|---|
| `test_order_router_depth_sizing_slot_limit.py::test_requested_count_greater_than_1_capped_to_1` | yes — `MAX_CONTRACTS_PER_ORDER` raised 3→6 in `811db09f`; request count 5 no longer exceeds cap | obsolete_expectation | `global_slot_allocator.MAX_CONTRACTS_PER_ORDER` (=6; `.env` `MERID_MAX_CONTRACTS_PER_ORDER=6`) | none — test-only | FIXED: request now `int(_CAP)+5` so it always exceeds the configured cap |
| `test_order_router_depth_sizing_slot_limit.py::test_requested_count_greater_than_1_with_zero_liquidity_capped_to_1` | yes — same cap drift; count 3 < 6 | obsolete_expectation | same | none | FIXED: request now `int(_CAP)+3` |
| `test_bounded_lane_edge_authority.py::test_expected_lanes_present` | yes — `reversal_scalp` added deliberately in `bf16e0c8` (2026-11-08) | obsolete_expectation | `trade_decision.BOUNDED_POST_ONLY_LANES` is the lane registry; membership changes are reviewed commits | none | FIXED: added `reversal_scalp` to expected set with provenance comment |
| `test_order_router_ioc_tif_reconciliation.py::test_maker_is_gtc_with_future_expiration` | yes — fixture ticker window ended 2026-08-09; `_resolve_gtc_expiration` clamps GTC expiry to `window_end - 120s` | time_dependent | `order_router._resolve_gtc_expiration` settlement clamp | none | FIXED: inject `_now_unix_s` 600s inside the window; assert `exp == now + 180` rest horizon |
| `test_order_router_ioc_tif_reconciliation.py::test_gtc_honors_explicit_order_expiration_ts` | yes — same stale window; explicit ts clamped below explicit value | time_dependent | same | none | FIXED: same clock injection; assert explicit ts honored |
| `test_order_router_liquidity_integration.py::test_fallback_calls_real_kalshi_market_state_store` | yes — submit-revalidation gate (fail-closed, default on) added after test; rejects `submit_inputs_missing` before `_route_live` liquidity branch | env_config_leakage | `MERID_SUBMIT_REVALIDATION_ENABLED` gate is a separate control with its own tests | none | FIXED: `monkeypatch.setenv(...,"0")` — same isolation pattern as `test_execution_gate_fail_closed_order_paths.py` |
| `test_order_router_slot_allocator_integration_2026_07_14.py::test_can_allocate_respects_exposure_cap` | yes — cap $1→$6 (`811db09f`) and entry band floor 25c reject the 20c probe before the exposure check | obsolete_expectation | `GlobalSlotAllocator.can_allocate` check order: price band → contract cap → per-asset → exposure | none | FIXED: inject `max_exposure_usd=1.00`, in-band prices, exact-fit/over/fractional boundary cases |
| `test_hard_exposure_cap_fix_2026_07_13.py::TestEndToEndExecutionFlow::test_full_flow_enforces_exposure_cap` | yes — asserted $3 cap; production default is $6 | obsolete_expectation | `MERID_FIXED_EXPOSURE_CAP_USD=6.00` (`.env`, `811db09f`) | none | FIXED: inject `allocator.max_exposure_usd = 3.00` to preserve the scenario arithmetic |
| `test_capital_insufficient_sizing.py::test_max_notional_below_contract_cost_rejects` | yes — sizing moved to centi-contract grid (`CONTRACT_COUNT_QUANTUM=0.01`) | obsolete_expectation | `unified_sizing.compute_order_size` rejects only when `max_by_notional < 0.01` contracts | none | FIXED: split into fractional-size-allowed test + true sub-centi-contract reject test |
| `test_unified_edge_fixes.py::test_edge_computer_initialization` | yes — `min_edge_cents` retuned 4.0→1.25 on 2026-07-10 | obsolete_expectation | `unified_edge.py:338` (`self.min_edge_cents = 1.25`) | none | FIXED: assert 1.25 with provenance comment |
| `test_crypto_kalshi_sizing_fix.py` (collection error) | yes — `merid.prediction.dynamic_sizing` deleted | unsupported_legacy | module no longer exists; cycle-cap concept superseded by profile/window-plan sizing | collection abort masked other results | FIXED: `pytest.importorskip` module-level skip |
| `test_unified_edge_integration.py` (collection error) | yes — `KalshiTradingAgent` renamed/archived (now `LeanAgent15m`) | unsupported_legacy | class absent from `agent_grid_15m` | collection abort masked other results | FIXED: module-level `pytest.skip` when class missing |
| `test_dispatch_disposition_coverage.py::TestSuppressionBranch::test_entries_disabled_event_records_control` | latent — fixed-char 3000-byte window; `decision_id` stamping sits 3375 chars after the BLOCKED event (between it and RECEIVED at 4218) | brittle_source_slice (env_config_leakage-adjacent) | suppression→RECEIVED ordering in `_run_loop` candidate loop | none — guard only | FIXED: window bounded by next `to_state=` emit instead of char count |
| *(defect found by new tests, not a test failure)* `_mark_reject` unbound | n/a — latent since method extraction | real_production_defect | `loop_15m.py` bind block binds all module-level self-methods except `_mark_reject` | **telemetry corruption**: every `self._mark_reject(...)` in `_execute_candidate` (~40 sites) raised AttributeError → outer except stamped `stage=execute_exception`, incremented `router_exception`, discarded named gate/reason. Orders still rejected (fail-safe direction preserved) but all rejection attribution was wrong | FIXED: `Kalshi15mLoop._mark_reject = _mark_reject` binding + audit confirms no other unbound self-methods |

## Verification notes

- Phase A commits `76636385` + `a851b26e` touched only
  `_apply_risk_based_order_sizing` in `order_router.py` plus loop/router
  plumbing — none of the functions asserted by the failures above.  All
  entries therefore reproduce on the parent commit.
- `tests/event_venues/kalshi/` full sweep after repairs:
  **2148 passed, 419 skipped, 0 failed** (~11 min).
- `tests/test_loop_15m_bugfixes.py`: 77/77 pass.
- `test_order_router_caller_restrictions.py` was excluded from the sweep
  (repo-scan slowness, pre-existing); classify on next baseline pass.
- Behavioral (non-source-scan) coverage added 2026-11-12:
  `test_hedge_bankroll_fail_closed.py` (6 tests — unavailable/stale/error
  equity → 0 cents → no hedge intents) and
  `test_execute_candidate_early_rejects.py` (4 tests — missing
  ticker/side/action return False with named `_reject_detail`).  The latter
  caught the unbound `_mark_reject` defect above.  Deeper `_execute_candidate`
  gates remain guarded by the AST disposition-coverage test; full behavioral
  conversion is deferred (heavy router/market-state dependency graph).
