# MERID Makefile
# Common development commands

.PHONY: help test coverage run-paper-demo smoke-test lint

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
	python -m pytest tests/test_prediction_markets.py tests/test_unified_pipeline.py tests/test_canonical_agents.py tests/test_blockchain.py tests/test_blockchain_v2.py -v

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
