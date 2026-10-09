# Skipped Tests Analysis - Kalshi Event Venues

**Total Skipped: 804 tests**
**Total Passed: 1123 tests**

## Phase-Based Categorization

### Phase 1: WebSocket Tests (HIGH PRIORITY - Critical for Production)
- **test_ws.py** - 34 tests
- **test_ws_hardening.py** - 32 tests (skipped: complex async setup)
- **test_ws_bridge.py** - 1 test (skipped: singleton RuntimeError)
- **test_ws_bridge_crash_loud.py** - 18 tests (skipped: complex async setup)
- **test_ws_callback_safety.py** - 17 tests (skipped: complex async setup)
- **test_ws_resilience.py** - 12 tests (skipped: complex async setup)
- **test_ws_reconnect.py** - 13 tests
- **test_ws_event.py** - 23 tests
- **test_ws_message_processing_fix.py** - 7 tests
- **test_ws_message_processing_simple.py** - 6 tests
- **test_ws_fill_action_extraction.py** - 6 tests
- **test_ws_metrics.py** - 1 test
- **test_ws_trade_action_infer.py** - 3 tests

**Total WebSocket Tests: ~173 tests**

### Phase 2: Order Flow Tests (HIGH PRIORITY - Critical for Trading)
- **test_order_invariants.py** - 50 tests (skipped: complex state setup)
- **test_order_router_guardrails.py** - 51 tests (skipped: complex setup)
- **test_order_errors.py** - 63 tests
- **test_order_constraints.py** - 30 tests
- **test_order_deduplication.py** - 17 tests (skipped: complex setup)
- **test_order_dedup_risk_skip.py** - 5 tests (skipped: complex setup)
- **test_order_gate_orphan_gc.py** - 14 tests
- **test_pre_trade_gate_dual_pending_regression.py** - 6 tests (skipped: complex setup)
- **test_orderbook_spread_direction_fixes.py** - 15 tests (skipped: complex setup)
- **test_position_reconciliation_scenarios.py** - 17 tests (skipped: complex setup)
- **test_kalshi_order_manager.py** - 35 tests
- **test_marketable_limit_orders.py** - 32 tests
- **test_parabolic_fees_and_policy.py** - 32 tests
- **test_order_errors_contract.py** - 7 tests
- **test_order_errors_integration.py** - 7 tests
- **test_order_router_cached_bankroll.py** - 2 tests

**Total Order Flow Tests: ~378 tests**

### Phase 3: Market State & MD SLA Tests (HIGH PRIORITY - Critical for Data Freshness)
- **test_kalshi_market_state.py** - 53 tests (skipped: expiry assertion errors)
- **test_market_state_timestamps.py** - 21 tests (skipped: complex setup)
- **test_md_sla_interface.py** - 35 tests (skipped: complex setup)
- **test_md_sla_cross_layer_consistency.py** - 15 tests (skipped: complex setup)
- **test_kalshi_market_state_pubsub.py** - 9 tests (skipped: mock assertion errors)
- **test_kalshi_market_state_regression.py** - 11 tests
- **test_market_state_race_conditions.py** - 4 tests
- **test_market_catalog_normalization.py** - 15 tests
- **test_market_catalog_filtering_integration.py** - 18 tests
- **test_catalog_discovery.py** - 16 tests
- **test_catalog_discovery_retry.py** - 11 tests
- **test_catalog_lagging_semantics.py** - 11 tests
- **test_catalog_market_fixes.py** - 10 tests
- **test_catalog_metrics.py** - 1 test
- **test_catalog_refresh_interval_fix.py** - 15 tests
- **test_market_filter.py** - 24 tests (skipped: config assertion errors)
- **test_kalshi_market_filter.py** - 24 tests (skipped: config assertion errors)
- **test_allowed_market_policy.py** - 12 tests
- **test_flat_trap_filter.py** - 18 tests
- **test_ticker_collector.py** - 24 tests
- **test_kalshi_lag_classification.py** - 46 tests
- **test_sla_config_regression.py** - 12 tests

**Total Market State & MD SLA Tests: ~375 tests**

### Phase 4: Position Sizer & Risk Management Tests (MEDIUM PRIORITY)
- **test_kalshi_position_sizer.py** - 63 tests (skipped: division errors)
- **test_kalshi_bracket_risk.py** - 24 tests
- **test_kalshi_ruin_simulator.py** - 20 tests
- **test_liquidity_monitor.py** - 26 tests (skipped: API changes)
- **test_maker_taker_awareness.py** - 13 tests (skipped: API changes)
- **test_position_cache_health.py** - 18 tests
- **test_position_divergence.py** - 5 tests
- **test_category_exposure_per_asset.py** - 11 tests
- **test_invariants_crypto_universe.py** - 9 tests
- **test_kalshi_backtest_checks.py** - 26 tests (skipped: logic changes)
- **test_kalshi_backtest_viz.py** - 20 tests
- **test_kalshi_historical_sim.py** - 18 tests
- **test_risk_posture_snapshot.py** - 2 tests

**Total Position Sizer & Risk Tests: ~255 tests**

### Phase 5: Venue Client & Models Tests (MEDIUM PRIORITY)
- **test_kalshi_client_refactored.py** - 27 tests (skipped: SyntaxError in global_execution_guard)
- **test_kalshi_venue_client.py** - 7 tests (skipped: assertion errors)
- **test_kalshi_venue_models.py** - 18 tests (skipped: config changes)
- **test_kalshi_credentials.py** - 6 tests (skipped: ImportError)
- **test_kalshi_rsa_signing.py** - 15 tests
- **test_kalshi_adapter_constraints_integration.py** - 6 tests
- **test_kalshi_execution.py** - 1 test
- **test_kalshi_business_reject_refund.py** - 5 tests
- **test_kalshi_time_in_force_api.py** - 3 tests
- **test_kalshi_regression.py** - 2 tests (skipped: assertion errors)
- **test_kalshi_runtime_config_snapshot.py** - 2 tests (skipped: 404 errors)
- **test_exchange_availability.py** - 4 tests
- **test_kalshi_deployment.py** - 31 tests
- **test_kalshi_archiver.py** - 17 tests
- **test_kalshi_collector.py** - 16 tests
- **test_kalshi_performance_comparator.py** - 36 tests

**Total Venue Client & Models Tests: ~192 tests**

### Phase 6: Deprecated Module Tests (LOW PRIORITY - May Need Rewrites)
- **test_kalshi_sprint_a.py** - 44 tests (skipped: deprecated consensus module)
- **test_kalshi_universe.py** - 56 tests (skipped: API changes)
- **test_kalshi_tools_signal_metadata_fix.py** - 3 tests (skipped: deprecated methods)
- **test_price_cents_fallback_fix.py** - 1 test (skipped: deprecated module)
- **test_market_candidate_trading_enrichment.py** - 3 tests (skipped: deprecated module)
- **test_trading.py** - 26 tests (skipped: legacy KalshiTrader)
- **test_yes_no_arbitrage.py** - 10 tests (skipped: disabled in production)
- **test_signal_metadata_fix.py** - 4 tests
- **test_signal_universe_service.py** - 12 tests
- **test_prediction_markets.py** - 11 tests
- **test_prediction_risk_singleton.py** - 7 tests
- **test_prediction_audit_regressions.py** - 5 tests
- **test_crypto_prediction_agent_confidence.py** - 4 tests
- **test_predictions_integration.py** - 7 tests

**Total Deprecated Module Tests: ~193 tests**

### Phase 7: Settlement & Other Tests (LOW PRIORITY)
- **test_settlement_poller_boundary_probe.py** - 24 tests (skipped: assertion errors)
- **test_cfb_settlement_and_quarantine.py** - 25 tests
- **test_settlement_inference_gate.py** - 3 tests
- **test_fills_ledger.py** - 24 tests
- **test_fills_ledger_action_upsert.py** - 7 tests
- **test_fills_ledger_invariants.py** - 3 tests
- **test_fills_ledger_cached_bankroll.py** - 2 tests
- **test_fills_ledger_prior_day_close.py** - 1 test
- **test_fills_poller_intervals.py** - 7 tests
- **test_fills_poller_reconciliation.py** - 1 test
- **test_fill_rate_tracking.py** - 6 tests
- **test_exit_order_flow_e2e.py** - 7 tests (skipped: API change)
- **test_live_open_order_registry.py** - 1 test
- **test_resting_order_monitor_events.py** - 3 tests
- **test_contract_normalization.py** - 29 tests
- **test_expiry_fallback.py** - 5 tests
- **test_timestamp_manager.py** - 30 tests
- **test_coalescing_buffer.py** - 23 tests
- **test_queue_overflow_recovery.py** - 10 tests
- **test_rate_limit_coordinator.py** - 9 tests
- **test_rate_limits.py** - 17 tests (skipped: complex async setup)
- **test_microstructure.py** - 20 tests
- **test_policy_sanity_harness.py** - 19 tests
- **test_code_quality_invariants.py** - 11 tests
- **test_no_legacy_router_imports.py** - 2 tests
- **test_15m_smoke.py** - 13 tests
- **test_production_integration_vertical_slice.py** - 9 tests
- **test_btc_15m_reconciliation_e2e.py** - 6 tests
- **test_multi_asset.py** - 4 tests
- **test_portfolio_pnl_computer_single_account.py** - 2 tests
- **test_snapshot_replay.py** - 3 tests
- **test_cycle_snapshot_schema.py** - 2 tests
- **test_execution_audit.py** - 1 test
- **test_polymarket.py** - 1 test
- **test_kalshi_stop_loss.py** - 1 test (skipped: deprecated)
- **test_robustness.py** - 1 test (skipped: deprecated)
- **test_trading_system.py** - 1 test (skipped: legacy)
- **test_websocket_deterministic.py** - 13 tests
- **test_crypto_catalog.py** - 12 tests

**Total Settlement & Other Tests: ~380 tests**

## Summary by Priority

### HIGH PRIORITY (Critical for Production)
- WebSocket Tests: ~173 tests
- Order Flow Tests: ~378 tests
- Market State & MD SLA Tests: ~375 tests
**Total HIGH: ~926 tests**

### MEDIUM PRIORITY (Important for Risk Management & API Integration)
- Position Sizer & Risk Tests: ~255 tests
- Venue Client & Models Tests: ~192 tests
**Total MEDIUM: ~447 tests**

### LOW PRIORITY (Deprecated or Lower Impact)
- Deprecated Module Tests: ~193 tests
- Settlement & Other Tests: ~380 tests
**Total LOW: ~573 tests**

## Notes

1. **Legacy Tests**: test_trading.py (26 tests) - explicitly marked as legacy KalshiTrader not used in production
2. **Disabled Features**: test_yes_no_arbitrage.py (10 tests) - arbitrage disabled in production (min_arb_edge=1.0 = 100%)
3. **Deprecated Modules**: test_kalshi_sprint_a.py references merid.prediction.consensus which doesn't exist
4. **API Changes**: Many tests skipped due to API incompatibilities (KalshiConfig imports, OrderIntent field changes)
5. **Syntax Errors**: test_kalshi_client_refactored.py has SyntaxError in global_execution_guard.py line 602
6. **Complex Async Setup**: WebSocket tests require complex async mocking, better suited for integration tests
