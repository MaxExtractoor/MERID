# Kalshi event-venues skip tracker

All `pytest.mark.skip` markers in `tests/event_venues/kalshi` must include a machine-readable reason of the form:

```
P[0-3]-<AREA>: TRACKER-XXX: human readable explanation
```

| Tracker | Priority | Module / Test | Status | Notes |
|---------|----------|---------------|--------|-------|
| TRACKER-001 | P0-EXECUTION | `test_maker_taker_awareness.py` | **replaced** | Maker/taker contract covered by `test_kalshi_p0_maker_taker_simulator.py` |
| TRACKER-002 | P0-EXECUTION | `test_order_invariants.py` | **unskipped / 50 passing** | State-machine and fill-awareness fixes landed |
| TRACKER-003 | P0-EXECUTION | `test_order_dedup_risk_skip.py` | **unskipped / 5 passing** | `mark_submitted` semantics restored |
| TRACKER-004 | P0-RECONCILIATION | `test_position_reconciliation_scenarios.py` | **replaced** | Reconciliation coverage now in `test_kalshi_p0_reconciliation_simulator.py` |
| TRACKER-005 | P0-EXECUTION | `test_pre_trade_gate_dual_pending_regression.py` | **unskipped / 6 passing** | No code changes required |
| TRACKER-006 | P0-EXECUTION | `test_orderbook_spread_direction_fixes.py` | **unskipped / 15 passing** | Score thresholds and log assertions updated to current optimizer |
| TRACKER-007 | P0-CLIENT | `test_kalshi_client_refactored.py` | **retired** | Respx-coupled legacy; replaced by `test_kalshi_p0_venue_client_port.py` |
| TRACKER-008 | P0-CLIENT | `test_kalshi_venue_client.py` | **replaced** | Venue-client contract covered by `test_kalshi_p0_venue_client_port.py` |
| TRACKER-009 | P0-SIZING | `test_kalshi_position_sizer.py` | **replaced** | Sizing/reservation coverage in `test_kalshi_p0_reconciliation_simulator.py` category-cap tests |
| TRACKER-010 | P0-RECONCILIATION | `test_btc_15m_reconciliation_e2e.py` | **replaced** | Restart/reconcile coverage in `test_kalshi_p0_reconciliation_simulator.py` |
| TRACKER-011 | P0-EXECUTION | `test_exit_order_flow_e2e.py` | **replaced** | Exit-order flow covered by `test_kalshi_p0_exit_order_simulator.py` |
| TRACKER-012 | P1-SETTLEMENT | `test_settlement_poller_boundary_probe.py` | skipped | Historical settlement is P1; simulator can cover |
| TRACKER-013 | P1-REGRESSION | `test_kalshi_regression.py` | skipped | Regression scenarios need deterministic simulator |
| TRACKER-014 | P2-INTEGRATION | `test_rate_limits.py` | skipped | Rate-limit retry logic; run in sandbox |
| TRACKER-015 | P2-INTEGRATION | `test_liquidity_monitor.py` | skipped | Liquidity monitoring depends on live book |
| TRACKER-016 | P2-INTEGRATION | `test_kalshi_market_state_pubsub.py` | skipped | Pub/sub mock assertions need live event replay |
| TRACKER-017 | P2-INTEGRATION | `test_market_state_timestamps.py` | skipped | Timestamp cross-layer checks |
| TRACKER-018 | P2-INTEGRATION | `test_md_sla_interface.py` | skipped | MD SLA interface |
| TRACKER-019 | P2-INTEGRATION | `test_md_sla_cross_layer_consistency.py` | skipped | MD SLA cross-layer consistency |
| TRACKER-020 | P2-INTEGRATION | `test_crypto_catalog.py` | skipped | Catalog/ticker registration changed |
| TRACKER-021 | P2-INTEGRATION | `test_kalshi_universe.py` | skipped | Universe / series discovery API |
| TRACKER-022 | P3-LEGACY | `test_kalshi_venue_models.py` | skipped | Venue model config tests; superseded by other suites |
| TRACKER-023 | P3-LEGACY | `test_kalshi_credentials.py` | skipped | `KalshiConfig` import errors; not used in production stack |
| TRACKER-024 | P3-LEGACY | `test_kalshi_backtest_checks.py` | skipped | Backtest logic; not live execution path |
| TRACKER-025 | P3-LEGACY | `test_kalshi_runtime_config_snapshot.py` | skipped | Runtime config diagnostics; HTTP endpoint not in live stack |
| TRACKER-026 | P3-LEGACY | `test_kalshi_sprint_a.py` | skipped | Tests deprecated `merid.prediction.consensus` |
| TRACKER-027 | P3-LEGACY | `test_kalshi_tools_signal_metadata_fix.py` | skipped | Tests deprecated `merid.prediction.kalshi_tools` |
| TRACKER-028 | P3-LEGACY | `test_price_cents_fallback_fix.py` | skipped | Tests deprecated `merid.prediction.dynamic_sizing` |
| TRACKER-029 | P3-LEGACY | `test_trading.py` | skipped | Legacy `KalshiTrader` not used in 15m stack |
| TRACKER-030 | P3-LEGACY | `test_ws_bridge_crash_loud.py` | skipped | Deprecated `merid.event_venues.kalshi.ws_bridge` |
| TRACKER-031 | P3-LEGACY | `test_ws_callback_safety.py` | skipped | Internal `CoalescingBuffer` implementation changed |
| TRACKER-032 | P3-LEGACY | `test_market_candidate_trading_enrichment.py` | skipped | Tests deprecated `merid.trading.kalshi_continuous_trader` |

## New deterministic simulator fixture

- `tests/event_venues/kalshi/deterministic_kalshi_client.py` (also a `KalshiExecutionPort`)
- `tests/event_venues/kalshi/test_kalshi_p0_execution_simulator.py` (12 passing tests)
- `tests/event_venues/kalshi/test_kalshi_p0_reconciliation_simulator.py` (8 passing tests)
- `tests/event_venues/kalshi/test_kalshi_p0_venue_client_port.py` (8 passing tests)
- `tests/event_venues/kalshi/test_kalshi_p0_exit_order_simulator.py` (6 passing tests)
- `tests/event_venues/kalshi/test_kalshi_p0_maker_taker_simulator.py` (3 passing tests)

Coverage now includes: IOC full/partial/zero fill, GTC/GTT maker/expire/cancel, reduce-only under 10c, timeout-after-submit idempotent recovery, restart state, duplicate fill replay, event vs market positions, historical settlement, category cap, same-ticker replacement, reconciliation (empty, stale, open, partial, expired, settled, restart), the normalized `KalshiExecutionPort` contract, exit-order full/partial/zero/timeout/sub-10c/cancel-race, and maker/taker GTC/IOC behavior.

## New governance scripts

- `scripts/skip_governance.py` — fail CI if any `pytest.mark.skip` lacks a `TRACKER-XXX` tag and/or `P[0-3]` priority prefix.
- `scripts/normalize_kalshi_skip_reasons.py` — bulk rewrites `tests/event_venues/kalshi` skip reasons to the tracker format.
