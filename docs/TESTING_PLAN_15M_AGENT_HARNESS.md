# Testing Plan for 15m Agent Harness

## Overview

This document outlines the comprehensive testing strategy for the MERID 15m agent harness, organized into four layers: unit tests, integration tests, backtests, and live-like tests. Each layer validates different aspects of the system, from individual components to end-to-end behavior under stress.

## Test Layers

### Layer 1: Unit Tests

**Goal:** Verify all components behave correctly in isolation with deterministic inputs.

**Location:** `tests/pipelines/`

**Coverage:**

#### Feature Bundle & Decision Objects (`test_feature_bundle.py`)
- `TestFeatureDict` (3 tests)
  - Construction with features
  - Empty feature dict
  - Feature access and existence checks
  
- `TestFifteenMinuteFeatureBundle` (4 tests)
  - Bundle construction
  - Bundle with populated namespaces
  - Feature access methods
  - Bundle serialization to dict
  
- `TestTradeDecision` (8 tests)
  - Decision construction
  - Decision with metadata
  - Decision serialization
  - Guardrail validation (valid, invalid timeframe, invalid asset, confidence out of range, size_pct out of range, missing pipeline_id, missing decision_agent)

**Run:** `pytest tests/pipelines/test_feature_bundle.py`

#### Pre-Trade Risk Checker (`test_pre_trade_risk.py`)
- `TestPreTradeRiskChecker` (10 tests)
  - Checker initialization with custom limits
  - Decision passes all checks
  - Size clipping when exceeding max
  - Asset exposure clipping
  - Asset exposure pass
  - Frequency limit veto
  - Frequency limit pass
  - Daily loss cap veto
  - Daily loss cap pass
  - Account state update
  - Multiple sequential checks

**Run:** `pytest tests/pipelines/test_pre_trade_risk.py`

#### Observability & Metrics Exporter (`test_observability.py`)
- `TestFeatureNamespaceSummary` (2 tests)
  - Summary construction
  - Summary serialization
  
- `TestPipelineObservability` (11 tests)
  - Observability initialization
  - Trace ID generation
  - Feature fingerprint computation
  - Namespace summarization
  - Empty namespace summarization
  - Summarization with missing features
  - Starting a trace
  - Logging feature bundle
  - Logging decision
  - Logging risk checks
  - Logging execution
  - Finalizing trace
  - Health summary
  
- `TestDecisionTrace` (2 tests)
  - Trace construction
  - Trace serialization

**Run:** `pytest tests/pipelines/test_observability.py`

#### Pipeline Config & Schema Validation (`test_pipeline_schema.py`)
- `TestAgentRole` (1 test)
  - Role enum values
  
- `TestFeatureNamespace` (1 test)
  - Namespace enum values
  
- `TestFeatureAgentConfig` (2 tests)
  - Config construction
  - Config with defaults
  
- `TestExecutionAgentConfig` (2 tests)
  - Config construction
  - Config with defaults
  
- `TestExecutorConfig` (2 tests)
  - Config construction
  - Config with defaults
  
- `TestPipelineConfig` (9 tests)
  - Minimal config construction
  - Full config construction
  - Valid config validation
  - Invalid asset validation
  - Invalid timeframe validation
  - Missing decision agent validation
  - Decision agent wrong role validation
  - Decision agent asset mismatch validation
  - Decision agent timeframe mismatch validation
  - Missing executor validation
  - Execution agent in feature_agents validation
  
- `TestPipelineRegistry` (8 tests)
  - Registry initialization
  - Adding pipeline
  - Getting non-existent pipeline
  - Getting pipelines for asset
  - Validate all (valid)
  - Validate all (invalid)
  - Registry summary

**Run:** `pytest tests/pipelines/test_pipeline_schema.py`

**Total Unit Tests:** ~65 tests

---

### Layer 2: Integration Tests

**Goal:** Ensure end-to-end 15m pipeline wiring works with real agents on synthetic data.

**Location:** `tests/pipelines/test_orchestrator_integration.py`

**Coverage:**

#### Happy-Path Pipeline Runs (`TestOrchestratorHappyPath`)
- Happy-path pipeline run produces decision (3 tests)
  - Decision has correct fields
  - Observability populated
  - Disabled pipeline returns None

#### Guardrail Enforcement (`TestOrchestratorGuardrails`)
- Invalid timeframe rejected in validation
- Decision guardrail veto (size clipping)

#### Failure Handling (`TestOrchestratorFailureHandling`)
- Feature agent exception handled gracefully
- Execution agent exception handled gracefully
- Pipeline not found returns None

**Total Integration Tests:** ~8 tests

**Run:** `pytest tests/pipelines/test_orchestrator_integration.py`

---

### Layer 3: Backtests & Stress Scenarios

**Goal:** Validate system behavior under normal and stress conditions with historical data.

**Location:** `tests/pipelines/test_backtest_harness.py`

**Coverage:**

#### Backtest Harness Components (`TestBacktestScenario`, `TestBacktestResult`, `TestHistoricalDataProvider`)
- Scenario construction
- Result construction and serialization
- Provider initialization
- Getting candles (empty by default)
- Orderbook snapshot stub
- Stub feature agent output (sentiment, volatility, generic)

#### Backtest Execution (`TestBacktestHarness`)
- Run backtest with normal conditions
- Run backtest with high volatility scenario
- Run backtest with data outage scenario
- Backtest when no decisions generated
- Backtest when pipeline raises exception

#### Stress Test Suite (`test_run_stress_tests`)
- Run standard stress test suite (3 scenarios: normal, high_volatility, data_outage)
- Verify all scenarios execute
- Verify metrics collected

#### Scenario Modifiers (`TestScenarioModifiers`)
- High volatility modifier increases volatility
- Data outage modifier zeros volume
- No modifiers leaves context unchanged

**Total Backtest Tests:** ~15 tests

**Run:** `pytest tests/pipelines/test_backtest_harness.py`

**Stress Scenarios:** 13 scenarios in `config/kalshi_stress_scenarios.yaml`
- CPI announcement day
- FOMC decision day
- BTC ETF announcement
- SEC regulatory enforcement
- Stablecoin depeg
- Exchange outage
- Flash crash
- ETH merge upgrade
- SOL exchange contagion
- XRP regulatory ruling
- DOGE celebrity tweet
- Low volatility regime
- High volatility regime

---

### Layer 4: Live-Like Tests

**Goal:** Validate behavior against real Kalshi endpoints before full production.

**Location:** Manual testing in paper/live environment

**Procedure:**

#### Paper Trading Mode
1. Wire `KalshiTradingAgent` to paper/sandbox Kalshi environment
2. Run 15m orchestrator in paper mode for one asset (BTC)
3. Validate:
   - Orders are created, amended, canceled as expected
   - Account state, exposure, PnL match backtest predictions (within noise)
   - Grafana dashboard shows healthy metrics
   - Latency stays within budget (feature build < 500ms, decision < 200ms)
   - Error rates and veto rates match backtest expectations

#### Throttled Real Trading
1. Start with very small size limits in `PreTradeRiskChecker` (e.g., 0.5% of bankroll)
2. Enable only one asset (BTC) while others stay in paper mode
3. Monitor Grafana dashboard for:
   - Latency within budget
   - Error and veto rates behaving as in backtests
   - No unexpected feature sparsity or drift
   - PnL tracking correctly
4. Gradually increase size limits as confidence builds
5. Roll out to other assets (ETH, SOL, XRP, DOGE) sequentially

**Live-Like Test Checklist:**
- [ ] Paper mode orders execute correctly
- [ ] Account state matches expectations
- [ ] Grafana metrics populate correctly
- [ ] Latency budgets respected
- [ ] Risk checks fire appropriately
- [ ] Feature agents respond within time limits
- [ ] No unexpected errors in logs
- [ ] PnL tracking accurate
- [ ] Gradual size increase successful
- [ ] Multi-asset rollout successful

---

## Running the Tests

### Unit Tests (Fast, < 1 minute)
```bash
# Run all unit tests
pytest tests/pipelines/test_feature_bundle.py \
       tests/pipelines/test_pre_trade_risk.py \
       tests/pipelines/test_observability.py \
       tests/pipelines/test_pipeline_schema.py \
       -v

# Run with coverage
pytest tests/pipelines/ \
       --cov=merid/pipelines \
       --cov-report=html
```

### Integration Tests (Medium, ~2 minutes)
```bash
pytest tests/pipelines/test_orchestrator_integration.py -v
```

### Backtest Tests (Slow, ~5-10 minutes)
```bash
pytest tests/pipelines/test_backtest_harness.py -v
```

### All Pipeline Tests
```bash
pytest tests/pipelines/ -v
```

### Combined with Existing Test Suite
```bash
# Run all tests including existing MERID tests
pytest tests/ -v
```

---

## Performance Thresholds

### Unit Tests
- **Target:** 100% pass rate
- **Duration:** < 60 seconds
- **Coverage:** > 90% for pipeline modules

### Integration Tests
- **Target:** 100% pass rate
- **Duration:** < 120 seconds
- **Latency:** Feature build < 500ms, decision < 200ms

### Backtest Tests
- **Target:** 100% pass rate
- **Duration:** < 600 seconds
- **Metrics:**
  - Sharpe ratio ≥ 0.5 (baseline)
  - Max drawdown ≤ 10% (baseline)
  - Decision rate ≥ 50%
  - Execution failure rate ≤ 5%
  - Feature sparsity ≤ 50%

### Stress Scenarios
- **Target:** All scenarios complete without pipeline crashes
- **Metrics:**
  - Risk envelope behaves as intended (increased veto/size clipping)
  - No catastrophic failures (unbounded leverage, pipeline crashes)
  - Performance within thresholds defined in scenario config

---

## CI/CD Integration

### Pre-Merge Checklist
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Backtest tests pass for at least BTC and ETH
- [ ] Code coverage ≥ 90% for changed files
- [ ] No new linting errors
- [ ] Gateway criteria satisfied for new agents

### Automated Test Runs
```yaml
# .github/workflows/pipeline-tests.yml
name: 15m Pipeline Tests

on:
  push:
    paths:
      - 'merid/pipelines/**'
      - 'config/kalshi_15m_pipelines.yaml'
      - 'tests/pipelines/**'

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run unit tests
        run: pytest tests/pipelines/test_feature_bundle.py tests/pipelines/test_pre_trade_risk.py tests/pipelines/test_observability.py tests/pipelines/test_pipeline_schema.py -v
  
  integration-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run integration tests
        run: pytest tests/pipelines/test_orchestrator_integration.py -v
  
  backtest-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run backtest tests
        run: pytest tests/pipelines/test_backtest_harness.py -v
```

---

## Regression Testing

### Baseline Metrics Capture
Run baseline backtests for all assets and capture:
- PnL, Sharpe, max drawdown
- Risk check veto rates
- Feature sparsity and failure rates
- Latency metrics (95th percentile)

### Scenario Regression
Run all 13 stress scenarios and assert:
- Sharpe ≥ X in baseline (asset-specific thresholds)
- Max drawdown ≤ Y (asset-specific thresholds)
- No more than Z% scenario runs with pipeline errors

### Performance Regression
Before deploying new code:
1. Run full backtest suite
2. Compare metrics against baseline
3. Require non-degradation in key metrics:
   - Sharpe ratio: Δ ≥ -0.1
   - Max drawdown: Δ ≤ +0.02
   - Decision rate: Δ ≥ -0.1

---

## Troubleshooting

### Unit Test Failures
- **Symptom:** Individual component tests fail
- **Action:** Check logic of specific component, verify test data is valid
- **Example:** `TradeDecision.validate_guardrails()` failing → check asset/timeframe values

### Integration Test Failures
- **Symptom:** End-to-end pipeline tests fail
- **Action:** Check agent wiring, verify mock agent returns, check observability integration
- **Example:** No decision produced → check execution agent mock returns valid decision

### Backtest Test Failures
- **Symptom:** Backtest or stress tests fail
- **Action:** Check data provider stubs, verify scenario modifiers, check orchestrator mocks
- **Example:** High volatility scenario not applying → check `_apply_scenario_modifiers` logic

### Live-Like Test Failures
- **Symptom:** Paper/live tests fail
- **Action:** Check Kalshi connection, verify account state, check risk limits
- **Example:** Orders rejected → check risk checker limits, verify account exposure

---

## Test Data

### Synthetic Data
- Unit tests use synthetic feature dicts and decisions
- Integration tests use mock agent registries with static returns
- Backtest tests use stub historical data providers

### Historical Data
- Production backtests should use real historical Kalshi data
- Stress scenarios should use known event dates (CPI, FOMC, ETF announcements)
- Data should include OHLCV, orderbook snapshots, sentiment feeds

---

## Test Maintenance

### When to Update Tests
- Adding new feature namespaces
- Modifying risk check logic
- Changing pipeline schema
- Adding new stress scenarios
- Modifying orchestrator behavior

### Test Review Cadence
- Review test coverage monthly
- Update baseline metrics quarterly
- Review stress scenarios annually or after major market events
- Audit gateway criteria semi-annually

---

## References

- TestRigor: [How to Test a Multi-Agent Ecosystem Effectively](https://testrigor.com/blog/how-to-test-a-multi-agent-ecosystem-effectively/)
- Reddit: [Unit Tests for Trading Systems](https://www.reddit.com/r/algotrading/comments/11frc71/unit_tests_for_trading_systems/)
- QuestDB: [Pre-Trade Risk Checks](https://questdb.com/glossary/pre-trade-risk-checks/)
- ExactPro: [Reference Test Harness for Algorithmic Trading](https://exactpro.com/sites/default/files/attachments/Reference-test-harness-for-algorithmic-trading-platforms.pdf)
- Galileo: [Stability Strategies for Dynamic Multi-Agents](https://galileo.ai/blog/stability-strategies-dynamic-multi-agents)
