# MERID Makefile
# Common development commands

.PHONY: help test coverage run-paper-demo smoke-test lint golden-path preflight risk-context serve swarm-integrity-check

help:
	@echo "MERID Development Commands"
	@echo "=========================="
	@echo ""
	@echo "  make test            - Run all tests"
	@echo "  make coverage        - Run tests with coverage report"
	@echo "  make run-paper-demo  - Run paper trading demo"
	@echo "  make smoke-test      - Run smoke tests (fast sanity check)"
	@echo "  make lint            - Run linters"
	@echo ""

# Run all tests
test:
	pytest tests/ -q --tb=short

# Run tests with coverage
coverage:
	pytest tests/ --cov=trading --cov=merid --cov=core --cov-report=term-missing

# Run paper trading demo (no API keys required)
run-paper-demo:
	python scripts/run_paper_demo.py

# Run smoke tests for critical paths
smoke-test:
	pytest tests/ -m "smoke or e2e" -q --tb=short -x

# Run linters
lint:
	ruff check .
	mypy trading/ merid/ core/ --ignore-missing-imports

# Full sanity check - env, imports, coverage, smoke tests, demo
sanity:
	python scripts/sanity_check.py

# Quick sanity (faster, fewer checks)
sanity-quick:
	@echo "Running quick sanity check..."
	pytest tests/smoke/ -m smoke -q --tb=short -x
	python scripts/run_paper_demo.py
	@echo "Quick sanity passed!"

# =============================================================================
# GO-LIVE COMMANDS
# =============================================================================

# Validate configuration for go-live
validate-config:
	@echo "Validating MERID configuration..."
	python -c "from merid.settings import settings; r = settings.validate_for_go_live(); print('Mode:', r['mode']); print('Env:', r['env']); print('Ready:', r['ready']); [print('  ERROR:', i) for i in r['issues']]; [print('  WARN:', w) for w in r['warnings']]"

# Dry-run: validate config + run paper demo (no real orders)
go-live-dry-run:
	@echo "=== GO-LIVE DRY RUN ==="
	@echo ""
	@echo "Step 1: Validating configuration..."
	python -c "from merid.settings import settings; r = settings.validate_for_go_live(); exit(0 if r['ready'] else 1)"
	@echo "Step 2: Running paper trading smoke test..."
	pytest tests/smoke/test_paper_trading_smoke.py -v --tb=short
	@echo "Step 3: Simulating order flow (no real orders)..."
	python scripts/run_paper_demo.py --dry-run
	@echo ""
	@echo "=== DRY RUN COMPLETE ==="
	@echo "Review output above. If all steps passed, you can proceed to live."

# Show current trading mode and safety settings
show-mode:
	python -c "from merid.settings import settings; print(f'Trading Mode: {settings.MERID_TRADING_MODE}'); print(f'Live Unlocked: {settings.MERID_LIVE_TRADING_UNLOCKED}'); print(f'Max Order: \$${settings.MERID_MAX_ORDER_SIZE_USD}'); print(f'Max Daily Loss: \$${settings.MERID_MAX_DAILY_LOSS_USD}'); print(f'Max Position: \$${settings.MERID_MAX_POSITION_SIZE_USD}')"

# Show risk controller status (kill switches, daily P&L)
show-risk:
	python -c "from merid.risk import get_risk_status; import json; print(json.dumps(get_risk_status(), indent=2))"

# Quick risk health check via API (requires running server)
risk-health:
	python scripts/risk_health.py

# One-line risk status (for CI/monitoring)
risk-health-summary:
	python scripts/risk_health.py --summary

# Watch mode for continuous monitoring
risk-health-watch:
	python scripts/risk_health.py --watch --interval 30

# Emergency stop - halt all trading immediately
emergency-stop:
	python -c "from merid.risk import emergency_stop; emergency_stop('Manual operator stop via Makefile')"

# Reset kill switch (use with caution)
reset-kill-switch:
	python -c "from merid.risk import risk_controller; risk_controller.reset('operator')"

# ── Prediction Markets (Kalshi-first) ──────────────────────────────────
pm-test:
	python -m pytest tests/test_prediction_markets.py -v

pm-status:
	python -c "from merid.prediction.venue_gate import get_venue_gate; g=get_venue_gate(); print(g.summary())"

pm-pause:
	python -c "from merid.prediction.venue_gate import get_venue_gate, TradingMode; g=get_venue_gate(); g.mode=TradingMode.SIM; print('PM paused (SIM mode)')"

pm-resume:
	python -c "from merid.prediction.venue_gate import get_venue_gate, TradingMode; g=get_venue_gate(); g.mode=TradingMode.PAPER; print('PM resumed (PAPER mode)')"

# ── Unified Pipeline (multi-venue) ────────────────────────────────────
pipeline-test:
	python -m pytest tests/test_unified_pipeline.py -v

pipeline-status:
	python -c "from merid.pipeline.mode_manager import get_mode_manager; import json; print(json.dumps(get_mode_manager().summary(), indent=2))"

pipeline-risk:
	python -c "from merid.pipeline.risk_manager import get_global_risk_manager; import json; print(json.dumps(get_global_risk_manager().summary(), indent=2))"

pipeline-instruments:
	python -c "from merid.pipeline.instruments import get_instrument_registry; import json; print(json.dumps(get_instrument_registry().summary(), indent=2))"

# ── Canonical Agents ──────────────────────────────────────────────────
agents-test:
	python -m pytest tests/test_canonical_agents.py -v

agents-summary:
	python -c "from merid.agents.base import get_canonical_registry; import json; print(json.dumps(get_canonical_registry().summary(), indent=2))"

all-pipeline-tests:
	python -m pytest tests/test_prediction_markets.py tests/test_unified_pipeline.py tests/test_canonical_agents.py tests/test_blockchain.py tests/test_blockchain_v2.py tests/test_agent_wiring.py tests/test_signals.py -v

# ── Agent Wiring & Orchestrator ──────────────────────────────────────
wiring-test:
	python -m pytest tests/test_agent_wiring.py -v

orchestrator-summary:
	python -c "from merid.agents.orchestrator import AgentOrchestrator; import json; print(json.dumps(AgentOrchestrator().summary(), indent=2))"

# ── Signals (X, Telegram, News) ─────────────────────────────────────
signals-test:
	python -m pytest tests/test_signals.py -v

signals-sentiment:
	python -c "from merid.signals.processing import get_sentiment_processor; import json; print(json.dumps(get_sentiment_processor().summary(), indent=2))"

signals-alerts:
	python -c "from merid.signals.alerts import get_alert_router; import json; print(json.dumps(get_alert_router().summary(), indent=2))"

# ── Blockchain Integration ────────────────────────────────────────────
blockchain-test:
	python -m pytest tests/test_blockchain.py tests/test_blockchain_v2.py -v

blockchain-secrets:
	python -c "from merid.blockchain.secrets import get_secrets_manager; import json; print(json.dumps(get_secrets_manager().summary(), indent=2))"

blockchain-execution:
	python -c "from merid.blockchain.execution import get_execution_service; import json; print(json.dumps(get_execution_service().summary(), indent=2))"

blockchain-wallet:
	python -c "from merid.blockchain.wallet import get_wallet_service; import json; print(json.dumps(get_wallet_service().summary(), indent=2))"

blockchain-compliance:
	python -c "from merid.blockchain.compliance import get_compliance_registry; import json; print(json.dumps(get_compliance_registry().summary(), indent=2))"

blockchain-gateway:
	python -c "from merid.blockchain.gateway import get_blockchain_gateway; import json; print(json.dumps(get_blockchain_gateway().summary(), indent=2))"

blockchain-contracts:
	python -c "from merid.blockchain.contracts import get_contract_registry; import json; print(json.dumps(get_contract_registry().summary(), indent=2))"

# ── Production Readiness Regression Tests ────────────────────────────
production-readiness-test:
	python -m pytest tests/test_production_readiness_regressions.py tests/test_system_observability.py -v --tb=short

# ── Golden Path CI (canonical test suites only) ─────────────────────
golden-path:
	python -m pytest tests/test_e2e_golden_path.py tests/test_signal_layer.py tests/test_live_feeds.py tests/test_prediction_markets.py tests/test_unified_pipeline.py tests/test_canonical_agents.py tests/test_hardening.py -v --tb=short

# ── Execution Guard ─────────────────────────────────────────────────
guard-test:
	python -m pytest tests/test_hardening.py -v

guard-status:
	python -c "from merid.execution_guard import get_execution_guard; import json; print(json.dumps(get_execution_guard().summary(), indent=2))"

guard-kill:
	python -c "from merid.execution_guard import get_execution_guard; g=get_execution_guard(); g.activate_kill_switch('operator'); print('KILL SWITCH ACTIVATED')"

guard-unkill:
	python -c "from merid.execution_guard import get_execution_guard; g=get_execution_guard(); g.deactivate_kill_switch(); print('Kill switch deactivated')"

# ── Tick Log ────────────────────────────────────────────────────────
tick-log-summary:
	python -c "from merid.tick_log import get_tick_log; import json; print(json.dumps(get_tick_log().summary(), indent=2))"

tick-log-recent:
	python -c "from merid.tick_log import get_tick_log; import json; print(json.dumps(get_tick_log().recent(20), indent=2))"

# ── WebSocket Feed ──────────────────────────────────────────────────
ws-feed-status:
	python -c "from merid.signals.ws_price_feed import get_ws_feed_manager; import json; print(json.dumps(get_ws_feed_manager().status(), indent=2))"

# ── Main Loop ───────────────────────────────────────────────────────
loop-start:
	python -m merid.loop

loop-start-execute:
	python -m merid.loop --execute

loop-status:
	python -c "from merid.loop import get_merid_loop; import json; print(json.dumps(get_merid_loop().status(), indent=2))"

# ── Signal Layer ────────────────────────────────────────────────────
signal-test:
	python -m pytest tests/test_signal_layer.py tests/test_live_feeds.py -v

# ── Codebase Drift ──────────────────────────────────────────────────
codebase-drift-audit:
	python -m core.codebase_drift_auditor

codebase-drift-audit-json:
	python -m core.codebase_drift_auditor --json

codebase-drift-audit-fix:
	python -m core.codebase_drift_auditor --fix

# ── Readiness ───────────────────────────────────────────────────────
readiness:
	python -m core.merid_readiness_auditor --all

readiness-json:
	python -m core.merid_readiness_auditor --all --json

# ── Risk Context ───────────────────────────────────────────────────
risk-context:
	python -c "from merid.pipeline.risk_context import build_risk_context; import json; print(json.dumps(build_risk_context().to_dict(), indent=2))"

# ── Readiness + Hardening (combined pre-flight) ───────────────────
preflight:
	@echo "=== MERID Pre-Flight Check ==="
	@echo ""
	@echo "Step 1: Golden path tests..."
	python -m pytest tests/test_e2e_golden_path.py tests/test_signal_layer.py tests/test_live_feeds.py tests/test_prediction_markets.py tests/test_unified_pipeline.py tests/test_canonical_agents.py tests/test_hardening.py -v --tb=short
	@echo ""
	@echo "Step 2: Readiness auditor..."
	python -m core.merid_readiness_auditor --all
	@echo ""
	@echo "Step 3: Codebase drift audit..."
	python -m core.codebase_drift_auditor
	@echo ""
	@echo "Step 4: Risk context snapshot..."
	python -c "from merid.pipeline.risk_context import build_risk_context; ctx=build_risk_context(); print(f'CQI={ctx.avg_cqi:.2f} scale={ctx.size_scale_factor:.2f} boost={ctx.approval_threshold_boost:.2f} kill={ctx.global_kill_switch}')"
	@echo ""
	@echo "=== Pre-Flight Complete ==="

# ── Blueprint CI Checks ────────────────────────────────────────────
blueprint-check:
	python scripts/ci_blueprint_checks.py

swarm-integrity-check:
	python scripts/enforce_swarm_integrity.py --config .merid_safeguard.yml --snapshot tests/fixtures/swarm/healthy_snapshot.json --strict

blueprint-check-json:
	python scripts/ci_blueprint_checks.py --json

manifest-generate:
	python scripts/generate_ts_manifest.py

manifest-check:
	python scripts/generate_ts_manifest.py --check

manifest-audit:
	python -m merid.ui_views_manifest --audit

form-check:
	node scripts/check_form_fields.js --scan-tsx

# ── Matching Engine ────────────────────────────────────────────────
matching-engine-status:
	python -c "from merid.matching_engine import init_matching_engines, all_engine_stats; init_matching_engines(); import json; print(json.dumps(all_engine_stats(), indent=2))"

# ── Prediction Market Seeder ──────────────────────────────────────
pm-seed:
	python -m merid.prediction_seed

pm-seed-simulate:
	python -m merid.prediction_seed --simulate --trades 100

# ── Promotion Report ───────────────────────────────────────────────
promotion-report:
	python -m merid.promotion_report

promotion-report-fast:
	python -m merid.promotion_report --fast

promotion-report-json:
	python -m merid.promotion_report --json

promotion-test:
	python -m pytest tests/test_promotion_report.py -v --tb=short

guard-promotion-test:
	python -m pytest tests/test_guard_promotion.py -v --tb=short

promotion-log-test:
	python -m pytest tests/test_promotion_log.py -v --tb=short

governance-test:
	python -m pytest tests/test_governance_notifier.py -v --tb=short

promotion-api-test:
	python -m pytest tests/test_promotion_api.py -v --tb=short

promotion-e2e-test:
	python -m pytest tests/test_promotion_e2e.py -v --tb=short

promotion-all-test:
	python -m pytest tests/test_promotion_report.py tests/test_guard_promotion.py tests/test_promotion_log.py tests/test_governance_notifier.py tests/test_promotion_api.py tests/test_promotion_e2e.py -v --tb=short

# ── Signal & Agent Opinion Tests ──────────────────────────────────
signal-metrics-test:
	python -m pytest tests/test_signal_metrics.py -v --tb=short

pm-agent-opinions-test:
	python -m pytest tests/test_pm_agent_opinions.py -v --tb=short

signal-metrics-integration-test:
	python -m pytest tests/test_signal_metrics_integration.py -v --tb=short

opinion-strategy-eval:
	python -m pytest tests/test_opinion_strategy_eval.py -v --tb=short

consensus-hardening-test:
	python -m pytest tests/test_consensus_store_hardening.py -v --tb=short

system-observability-test:
	python -m pytest tests/test_system_observability.py -v --tb=short

strategy-real-eval:
	python -m pytest tests/test_strategy_real_eval.py -v --tb=short

resilience-layer-test:
	python -m pytest tests/test_resilience_layer.py -v --tb=short

risk-manager-test:
	python -m pytest tests/test_risk_manager_hardening.py -v --tb=short

ws-price-feed-test:
	python -m pytest tests/test_ws_price_feed.py -v --tb=short

inference-explainability-test:
	python -m pytest tests/test_inference_explainability.py -v --tb=short

debate-teamwork-test:
	python -m pytest tests/test_debate_teamwork_rewards.py -v --tb=short

debate-tuning-test:
	python -m pytest tests/test_debate_tuning.py -v --tb=short

debate-full-test:
	python -m pytest tests/test_debate_teamwork_rewards.py tests/test_debate_tuning.py -v --tb=short

reward-engine-test:
	python -m pytest tests/test_reward_engine.py -v --tb=short

reward-full-test:
	python -m pytest tests/test_reward_engine.py tests/test_debate_teamwork_rewards.py tests/test_debate_tuning.py tests/test_system_observability.py -v --tb=short

llm-governance-test:
	python -m pytest tests/test_llm_governance.py -v --tb=short

sprint15-gaps-test:
	python -m pytest tests/test_sprint15_remaining_gaps.py -v --tb=short

ui-robustness-test:
	python -m pytest tests/test_ui_robustness.py -v --tb=short

ux-polish-test:
	python -m pytest tests/test_sprint17_ux_polish.py -v --tb=short

assistant-test:
	python -m pytest tests/test_sprint19_assistant.py -v --tb=short

loading-states-test:
	python -m pytest tests/test_sprint20_loading_states.py -v --tb=short

error-states-test:
	python -m pytest tests/test_sprint21_error_states.py -v --tb=short

accessibility-test:
	python -m pytest tests/test_sprint22_accessibility.py -v --tb=short

code-quality-test:
	python -m pytest tests/test_sprint23_code_quality.py -v --tb=short

empty-mutation-test:
	python -m pytest tests/test_sprint24_empty_mutation.py -v --tb=short

keyboard-a11y-test:
	python -m pytest tests/test_sprint25_keyboard_a11y.py -v --tb=short

polling-constants-test:
	python -m pytest tests/test_sprint26_polling_constants.py -v --tb=short

api-base-url-test:
	python -m pytest tests/test_sprint27_api_base_url.py -v --tb=short

button-types-test:
	python -m pytest tests/test_sprint28_button_types.py -v --tb=short

auth-token-key-test:
	python -m pytest tests/test_sprint29_auth_token_key.py -v --tb=short

cleanup-warn-test:
	python -m pytest tests/test_sprint30_cleanup_warn.py -v --tb=short

console-error-imports-test:
	python -m pytest tests/test_sprint31_console_error_imports.py -v --tb=short

aria-labels-test:
	python -m pytest tests/test_sprint32_aria_labels.py -v --tb=short

textarea-aria-test:
	python -m pytest tests/test_sprint33_textarea_aria.py -v --tb=short

console-error-components-test:
	python -m pytest tests/test_sprint34_console_error_components.py -v --tb=short

console-log-catch-test:
	python -m pytest tests/test_sprint35_console_log_catch.py -v --tb=short

polling-constants-components-test:
	python -m pytest tests/test_sprint36_polling_constants_components.py -v --tb=short

hardcoded-urls-test:
	python -m pytest tests/test_sprint37_hardcoded_urls.py -v --tb=short

duplicate-interfaces-test:
	python -m pytest tests/test_sprint38_duplicate_interfaces.py -v --tb=short

any-type-reduction-test:
	python -m pytest tests/test_sprint39_any_type_reduction.py -v --tb=short

chart-colors-test:
	python -m pytest tests/test_sprint40_chart_colors.py -v --tb=short

react-memo-test:
	python -m pytest tests/test_sprint41_react_memo.py -v --tb=short

displayname-timeouts-test:
	python -m pytest tests/test_sprint42_displayname_timeouts.py -v --tb=short

status-enums-test:
	python -m pytest tests/test_sprint43_status_enums.py -v --tb=short

icon-aria-test:
	python -m pytest tests/test_sprint44_icon_aria_labels.py -v --tb=short

hooks-quality-test:
	python -m pytest tests/test_sprint45_hooks_quality.py -v --tb=short

backend-logging-test:
	python -m pytest tests/test_sprint47_backend_logging.py -v --tb=short

localhost-urls-test:
	python -m pytest tests/test_sprint48_localhost_urls.py -v --tb=short

backend-imports-test:
	python -m pytest tests/test_sprint49_backend_imports.py -v --tb=short

resilience-sprint-test:
	python -m pytest tests/test_resilience_layer.py tests/test_risk_manager_hardening.py tests/test_ws_price_feed.py tests/test_system_observability.py -v --tb=short

sports-betting-test:
	python -m pytest tests/test_sports_live_betting.py -v --tb=short --timeout=120

sports-integration-test:
	python -m pytest tests/test_sports_betting_integration.py -v --tb=short --timeout=120

sports-full-test:
	python -m pytest tests/test_betting_layer.py tests/test_sports_live_betting.py tests/test_sports_betting_integration.py -v --tb=short --timeout=120

debate-calibration-viz-test:
	python -m pytest tests/test_debate_calibration_viz.py -v --tb=short --timeout=120

live-odds-slo-viz-test:
	python -m pytest tests/test_live_odds_slo_viz.py -v --tb=short --timeout=120

loop-orchestration-test:
	python -m pytest tests/test_loop_orchestration_ui.py -v --tb=short --timeout=120

cognitive-ui-test:
	python -m pytest tests/test_cognitive_ui.py -v --tb=short --timeout=120

dev-swarm-test:
	python -m pytest tests/test_dev_swarm.py -v --tb=short --timeout=600

backend-test:
	python -m pytest tests/ -v --tb=short --timeout=300

frontend-build:
	cd web/react && npm run build

swarm-metrics:
	python -c "from core.dev_swarm_metrics import get_metrics; print('metrics OK')"

dev-swarm-governance-test:
	python -m pytest tests/test_dev_swarm_governance.py -v --tb=short --timeout=120

audit-fixes-test:
	python -m pytest tests/test_signal_metrics.py tests/test_pm_agent_opinions.py tests/test_signal_metrics_integration.py tests/test_opinion_strategy_eval.py tests/test_consensus_store_hardening.py tests/test_system_observability.py tests/test_strategy_real_eval.py tests/test_resilience_layer.py tests/test_risk_manager_hardening.py tests/test_ws_price_feed.py tests/test_inference_explainability.py tests/test_debate_teamwork_rewards.py tests/test_debate_tuning.py tests/test_reward_engine.py tests/test_llm_governance.py tests/test_betting_layer.py tests/test_sports_live_betting.py tests/test_sports_betting_integration.py tests/test_wiring_audit.py tests/test_debate_calibration_viz.py tests/test_live_odds_slo_viz.py tests/test_loop_orchestration_ui.py tests/test_cognitive_ui.py tests/test_dev_swarm_governance.py tests/test_sprint15_remaining_gaps.py tests/test_ui_robustness.py tests/test_sprint17_ux_polish.py tests/test_sprint19_assistant.py tests/test_sprint20_loading_states.py tests/test_sprint21_error_states.py tests/test_sprint22_accessibility.py tests/test_sprint23_code_quality.py tests/test_sprint24_empty_mutation.py tests/test_sprint25_keyboard_a11y.py tests/test_sprint26_polling_constants.py tests/test_sprint27_api_base_url.py tests/test_sprint28_button_types.py tests/test_sprint29_auth_token_key.py tests/test_sprint30_cleanup_warn.py tests/test_sprint31_console_error_imports.py tests/test_sprint32_aria_labels.py tests/test_sprint33_textarea_aria.py tests/test_sprint34_console_error_components.py tests/test_sprint35_console_log_catch.py tests/test_sprint36_polling_constants_components.py tests/test_sprint37_hardcoded_urls.py tests/test_sprint38_duplicate_interfaces.py tests/test_sprint39_any_type_reduction.py tests/test_sprint40_chart_colors.py tests/test_sprint41_react_memo.py tests/test_sprint42_displayname_timeouts.py tests/test_sprint43_status_enums.py tests/test_sprint44_icon_aria_labels.py tests/test_sprint45_hooks_quality.py tests/test_sprint47_backend_logging.py tests/test_sprint48_localhost_urls.py tests/test_sprint49_backend_imports.py tests/test_sprint50_test_coverage.py tests/test_sprint51_silent_except.py tests/test_sprint52_utcnow.py tests/test_user_settings_persistence.py tests/test_bugfix_regressions.py tests/test_guardrails.py tests/test_kalshi_deep_integration.py tests/test_kalshi_grid_wiring.py tests/test_resilience_api.py tests/test_routing_policy.py tests/test_telemetry.py -v --tb=short

risk-suite-test:
	python -m pytest tests/test_risk_management.py tests/test_risk_monitor.py tests/test_risk_guard.py tests/test_portfolio_optimizer_extended.py tests/test_position_sizing.py tests/test_capital_ladder.py tests/test_paper_ladder.py tests/test_paper_reconciliation.py tests/test_paper_session.py tests/test_season5_completion.py tests/test_season7_completion.py tests/test_sidebar_wiring.py tests/test_swarm_integrity_guard.py tests/test_venue_registry.py tests/test_consensus_bridge.py tests/test_edge_model.py tests/test_end_to_end_kalshi.py tests/test_integration_alpaca_paper.py tests/test_integration_coinbase.py tests/test_integration_kalshi.py tests/test_kalshi_client.py tests/test_kalshi_e2e.py tests/test_kalshi_grid_integration.py tests/test_kalshi_only_views.py tests/test_kalshi_reconciler.py tests/test_kalshi_signals.py tests/test_kalshi_ui_api.py tests/test_kalshi_venue_adapter.py tests/test_loop_kalshi_integration.py -v --tb=short

utcnow-test:
	python -m pytest tests/test_sprint52_utcnow.py -v --tb=short

silent-except-test:
	python -m pytest tests/test_sprint51_silent_except.py -v --tb=short

test-coverage-test:
	python -m pytest tests/test_sprint50_test_coverage.py -v --tb=short

alphabetical-sprints-test:
	python -m pytest tests/test_sprint_bc.py tests/test_sprint_d.py tests/test_sprint_d_g.py tests/test_sprint_e.py tests/test_sprint_f.py tests/test_sprint_g.py tests/test_sprint_h.py tests/test_sprint_h_i.py tests/test_sprint_m.py tests/test_sprint_n_o.py tests/test_sprint_q_r.py -v --tb=short

forecasters-metrics-test:
	python -m pytest tests/test_forecasters.py tests/test_metrics.py tests/test_sentiment_bus.py tests/test_sentiment_config.py tests/test_sentiment_gaps.py tests/test_sentiment_integration.py -v --tb=short

user-settings-test:
	python -m pytest tests/test_user_settings_persistence.py -v --tb=short

orphaned-passing-test:
	python -m pytest tests/test_adapter_integration.py tests/test_agent_credit_ledger.py tests/test_alerting_config.py tests/test_audit_anchor.py tests/test_audit_chain_integrity.py tests/test_compliance_report.py tests/test_data_contracts.py tests/test_distributed_execution.py tests/test_feed_staleness.py tests/test_full_pipeline_integration.py tests/test_gamified_security.py tests/test_mev_rewards.py tests/test_mode_gate.py tests/test_negotiation_protocol.py tests/test_no_fake_payloads.py tests/test_order_sanity_check.py tests/test_plain_language_explainer.py tests/test_position_reconciliation.py tests/test_prediction_consensus.py tests/test_quadratic_funding_api.py tests/test_rewards_api.py tests/test_risk_api_endpoints.py tests/test_secrets_guard.py tests/test_sections_8_14.py tests/test_smoke_experimental.py tests/test_swarm_e2e.py tests/test_swarm_vs_single_agent_benchmark.py tests/test_venue_compliance.py tests/test_betting.py tests/test_cognitive_layer.py tests/test_trading_halt.py tests/test_flow.py tests/test_sections_1_7.py tests/test_dev_swarm.py tests/test_consensus.py tests/test_notifications.py tests/test_realfirst_endpoints.py tests/test_golden_path.py tests/test_sandbox_integration.py tests/test_dev_swarm_xdist_invariants.py -v --tb=short

# ── Agent Gauntlet ─────────────────────────────────────────────────
gauntlet:
	python -m merid.agent_gauntlet --cycles 10

gauntlet-fast:
	python -m merid.agent_gauntlet --cycles 5

gauntlet-json:
	python -m merid.agent_gauntlet --cycles 10 --json

gauntlet-test:
	python -m pytest tests/test_agent_gauntlet.py -v --tb=short

# ── Paper Trading Matrix Test ──────────────────────────────────────
paper-matrix-test:
	python -m pytest tests/test_paper_trading_matrix.py -v --tb=short

# ── Wiring Audit ──────────────────────────────────────────────
smoke-test:
	python scripts/smoke_test_wiring.py

smoke-test-json:
	python scripts/smoke_test_wiring.py --base http://localhost:8000

wiring-audit-test:
	python -m pytest tests/test_wiring_audit.py -v --tb=short

# ── Web Server ─────────────────────────────────────────────────────
serve:
	uvicorn web.main:create_app --factory --host 0.0.0.0 --port 8000 --reload
