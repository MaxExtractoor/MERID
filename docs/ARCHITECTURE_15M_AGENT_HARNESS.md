# MERID 15m Agent Harness Architecture

## Overview

MERID runs a **15-minute, multi-agent Kalshi trading system** across BTC/ETH/SOL/XRP/DOGE with a single, heavily guarded execution surface. All other agents are feature producers feeding into a structured feature bundle, with role-based access controls preventing trade leakage across timeframes or categories.

The system is **observable and testable end-to-end** with Kalshi-specific stress scenarios, per-agent health/latency/contribution metrics, pre-trade risk checks, and post-trade PnL/Sharpe/DD reporting.

## Core Architecture

### Execution Surface

**Only 15m Kalshi crypto agents can produce trades:**
- 5 execution agents: `BTC_15M`, `ETH_15M`, `SOL_15M`, `XRP_15M`, `DOGE_15M`
- Role-based guardrails: Only agents with `role=execution` may emit `TradeDecision`
- Timeframe enforcement: Only agents with `timeframe="15m"` can trade
- Asset enforcement: Only assets in {BTC, ETH, SOL, XRP, DOGE} allowed

**Guardrails:**
- Type-level: Config validation rejects non-15m/non-crypto agents from execution
- Role-level: Feature agents have no access to trading client
- Runtime: `TradeDecision.validate_guardrails()` checks before execution
- Metadata: Every order includes `asset`, `timeframe`, `pipeline_id`, `decision_agent`, `features_fingerprint`

### Feature Graph

**76 feature agents produce structured inputs:**
- `sentiment` — News/social sentiment (CRYPTO_NEWS_SENTIMENT, CRYPTO_SOCIAL_FLOW, etc.)
- `microstructure` — Lower timeframe (1m, 5m) features
- `regime` — Higher timeframe (1h, 4h, daily, weekly) regime flags
- `macro` — Cross-asset macro features
- `volatility` — Volatility regime features
- `confidence` — Ensemble/confidence features

**Feature Bundle:**
```python
@dataclass
class FifteenMinuteFeatureBundle:
    ts_15m: FeatureDict              # Native 15m technicals
    ts_lower_tf: FeatureDict         # 1m/5m microstructure
    ts_higher_tf: FeatureDict        # 1h/4h/daily regime
    sentiment: FeatureDict           # News/social sentiment
    macro: FeatureDict               # Cross-asset features
    confidence_signals: FeatureDict  # Meta/ensemble confidence
    volatility: FeatureDict          # Volatility regime
```

### Pipeline Configuration

**YAML-driven pipeline definitions:**
```yaml
btc_15m_pipeline:
  asset: BTC
  timeframe: 15m
  feature_agents:
    - CRYPTO_NEWS_SENTIMENT
    - CRYPTO_SOCIAL_FLOW
    - BTC_DAILY
    - CRYPTO_VOL_REGIME
  decision_agent: BTC_15M
  executor: KXBTC
  risk_agents:
    - PortfolioRiskAgent
```

**Validation:**
- Asset must be in {BTC, ETH, SOL, XRP, DOGE}
- Timeframe must be "15m"
- Decision agent must have `role=execution`
- No execution agents in feature_agents list
- Asset alignment checks

## Observability

### Decision Tracing

Every 15m decision has a complete trace:
- `trace_id` — Unique identifier
- `feature_summaries` — Per-namespace statistics (count, mean, std, missing)
- `features_fingerprint` — SHA256 hash for auditability
- `feature_time_window` — Explicit [t_start, t_end] range
- `risk_checks` — Pre-trade risk check outcomes
- `timing_metrics` — feature_build_ms, decision_ms, risk_check_ms, execution_ms

### Prometheus Metrics

**30+ metrics organized by category:**

**Pipeline-Level:**
- `merid_pipeline_decisions_total` — Counter per asset/pipeline/side
- `merid_pipeline_decisions_confidence` — Histogram
- `merid_pipeline_success_rate` — Gauge
- `merid_pipeline_cycles_total` — Counter

**Timing:**
- `merid_pipeline_feature_build_duration_seconds` — Histogram
- `merid_pipeline_decision_duration_seconds` — Histogram
- `merid_pipeline_risk_check_duration_seconds` — Histogram
- `merid_pipeline_execution_duration_seconds` — Histogram

**Feature Namespace:**
- `merid_feature_namespace_sparsity` — Gauge per namespace
- `merid_feature_agent_invocation_duration_seconds` — Histogram per agent
- `merid_feature_agent_healthy` — Gauge (0/1)

**Risk Checks:**
- `merid_risk_check_veto_rate` — Gauge per check type
- `merid_risk_check_failed` — Counter per check type

**Execution:**
- `merid_execution_pnl` — Gauge (cumulative)
- `merid_execution_sharpe_ratio` — Gauge
- `merid_execution_max_drawdown` — Gauge

### Grafana Dashboard

14-panel dashboard showing:
- Pipeline status overview
- Decision rate and success rate by asset
- Confidence and edge estimate distributions
- Feature namespace sparsity heatmap
- Latency breakdown (feature build → decision → risk check → execution)
- Risk check veto rates
- Execution success rate and cumulative PnL
- Feature agent health table
- Overall pipeline health status

## Risk Management

### Pre-Trade Risk Checker

**Independent risk layer before execution:**
- Max position size (default 2% of bankroll)
- Asset exposure limits (default 10% per asset)
- Order frequency limits (default 20 trades/day)
- Daily loss cap (default 5%)

**Actions:**
- Can veto trades completely
- Can clip position size
- Independent of agent logic

### Gateway Criteria

**7 criteria for adding new agents:**
1. Registry entry completeness (role, feature_namespace, assets, timeframes)
2. Clear semantics and documentation (docstring, invariants)
3. Unit tests (correctness, graceful failure, bounded output, latency)
4. Backtest performance check (Sharpe, drawdown thresholds)
5. Latency budget (feature: 500ms, execution: 200ms)
6. Inter-agent hygiene (no direct calls, no trading client access)
7. Configuration validation (YAML validation)

See `docs/AGENT_GATEWAY_CRITERIA.md` for details.

## Testing

### Backtest Harness

**Deterministic replay with historical data:**
- Historical candle replay
- Scenario-based stress testing
- Performance metrics (PnL, Sharpe, drawdown)
- Agent failure rate tracking
- Feature sparsity monitoring

### Stress Scenarios

**13 Kalshi-specific scenarios:**

**Macro Events:**
- `cpi_announcement_day` — CPI release with 3x volatility
- `fomc_decision_day` — Fed rate decision with correlation spike

**Binary Events:**
- `btc_etf_announcement` — ETF approval/rejection (5x volatility)
- `xrp_regulatory_ruling` — Court ruling with binary outcome

**Contagion/Regulatory:**
- `sec_regulatory_enforcement` — SEC action sentiment crash
- `stablecoin_depeg` — Cross-crypto contagion
- `sol_exchange_contagion` — Exchange failure

**Infrastructure:**
- `major_exchange_outage` — Data gaps and delays
- `flash_crash` — Sudden 15% drop, liquidity evaporation

**Asset-Specific:**
- `eth_merge_upgrade` — Protocol upgrade uncertainty
- `doge_celebrity_tweet` — Social viral pump

**Regime Drift:**
- `low_volatility_regime` — Extended low vol (24h)
- `high_volatility_regime` — Elevated vol (24h)

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                     Pipeline Config (YAML)                      │
│  kalshi_15m_pipelines.yaml                                    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Pipeline Registry                            │
│  Validates: asset, timeframe, role, wiring                    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                  15m Orchestrator                                │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │ 1. Invoke Feature Agents (parallel)                    │  │
│  │ 2. Build FifteenMinuteFeatureBundle                      │  │
│  │ 3. Call Execution Agent (15m only)                      │  │
│  │ 4. Pre-Trade Risk Check                                 │  │
│  │ 5. Execute via Kalshi Trading Agent                      │  │
│  └─────────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌─────────────────────┐  ┌─────────────────────┐
│  Observability       │  │  Risk Management     │
│  - Decision Traces   │  │  - Pre-Trade Check   │
│  - Prometheus Metrics│  │  - Size/Exposure     │
│  - Grafana Dashboard │  │  - Frequency/Loss    │
└─────────────────────┘  └─────────────────────┘
```

## File Structure

```
merid/pipelines/
├── feature_bundle.py          # FifteenMinuteFeatureBundle, TradeDecision
├── pipeline_schema.py         # PipelineConfig, validation
├── pipeline_loader.py         # YAML config parser
├── kalshi_15m_orchestrator.py # Main orchestrator
├── pre_trade_risk.py          # Risk checker
├── observability.py          # Tracing and metrics
├── backtest_harness.py       # Backtest and stress testing
└── __init__.py                # Public exports

config/
├── kalshi_15m_pipelines.yaml # Pipeline configurations
└── kalshi_stress_scenarios.yaml # Stress test scenarios

grafana/dashboards/
└── merid_15m_pipeline_health.json # Grafana dashboard

scripts/
└── scan_agent_registry.py     # Agent discovery and role classification

docs/
└── AGENT_GATEWAY_CRITERIA.md  # Criteria for adding agents
```

## Quick Start

### 1. Scan Agent Registry
```bash
python scripts/scan_agent_registry.py
```

### 2. Load Pipeline Config
```python
from merid.pipelines import load_pipeline_config

registry = load_pipeline_config("config/kalshi_15m_pipelines.yaml")
```

### 3. Run Pipeline
```python
from merid.pipelines import Kalshi15mOrchestrator, PreTradeRiskChecker, PipelineObservability

orchestrator = Kalshi15mOrchestrator(
    pipeline_registry=registry,
    agent_registry=agent_registry,
    risk_checker=PreTradeRiskChecker(),
    observability=PipelineObservability(),
)

decision = await orchestrator.run_pipeline(
    pipeline_id="btc_15m_pipeline",
    context=market_context,
    account_state=exposure_state,
)
```

### 4. Run Stress Tests
```python
from merid.pipelines.backtest_harness import run_stress_tests

results = await run_stress_tests(orchestrator, asset="BTC")
```

### 5. Export Metrics
```python
from merid.pipelines.metrics_schema import PipelineMetricsExporter

exporter = PipelineMetricsExporter()
exporter.export_trace(trace)
```

## Operational Guidelines

### Strategy Iteration
1. Modify pipeline YAML (add/remove feature agents, adjust risk limits)
2. Run backtest with stress scenarios
3. Review Grafana metrics (latency, sparsity, success rate)
4. Deploy to one asset in paper mode
5. Monitor for 1 week
6. Roll out to other assets if metrics are healthy

### Incident Response
1. Identify anomaly in Grafana (e.g., increased veto rate, feature sparsity)
2. Pull DecisionTrace for affected cycles
3. Inspect per-namespace metrics to identify failing agent
4. Disable problematic agent in YAML
5. Run stress test to validate fix
6. Re-enable agent after fix

### Portfolio Steering
1. Review per-asset PnL, Sharpe, drawdown in Grafana
2. Identify underperforming pipelines
3. Evaluate feature agent contributions via traces
4. Add/remove agents or adjust risk limits
5. Monitor impact over rolling window

## Future Extensions

### Circuit Breakers
- Auto-de-risk when veto rates spike
- Auto-disable unhealthy feature agents
- Performance threshold enforcement

### Cross-Pipeline Coordination
- Portfolio coordinator agent
- Adjust risk limits for correlated assets
- Macro stress coordination

### Continuous Evaluation
- Periodic stress scenario regression testing
- Require non-degradation before promotion
- Automated performance regression detection

## References

- Agent Harness Pattern: [TradingAgents GitHub](https://github.com/tauricresearch/tradingagents)
- Multi-Agent Systems: [arXiv 2508.00554](https://arxiv.org/html/2508.00554v1)
- Pre-Trade Risk: [ExactPro Reference](https://exactpro.com/sites/default/files/attachments/Reference-test-harness-for-algorithmic-trading-platforms.pdf)
- Observability: [Real Kinetic Blog](https://blog.realkinetic.com/the-observability-pipeline-3010484eb931)
- Stress Testing: [Galileo Blog](https://galileo.ai/blog/stability-strategies-dynamic-multi-agents)
- Production Readiness: [Fintech Weekly](https://www.fintechweekly.com/magazine/articles/enterprise-ai-agents-stress-testing-production-readiness)
