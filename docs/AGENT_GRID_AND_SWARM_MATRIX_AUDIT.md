# MERID Agent Grid & Swarm Matrix Audit

**Version**: 2026-03-24  
**Scope**: Kalshi-first trading swarm topology, config, and wiring audit  
**Goal**: Lock agent grid and swarm matrix into clean, bankroll-driven lanes; eliminate hardcoded constants and wiring gaps.

---

## 1. Agent Grid Schema (Single Source of Truth)

### 1.1 Grid Entry Definition

Every running agent MUST have a grid entry with these fields:

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| `agent_id` | str | Canonical identifier (e.g., `kalshi-btc_15m`, `risk-portfolio`) | `agent_grid_config.yaml` |
| `role` | str | Functional role: `trader`, `risk`, `consensus`, `execution`, `analytics`, `sentiment`, `critic` | Grid registry |
| `lane` | str | Operating lane: `signal`, `risk`, `execution`, `analytics`, `dev`, `observer` | Lane controller |
| `enabled` | bool | Active in current deployment | Runtime toggle |
| `risk_tier` | str | `conservative`, `moderate`, `aggressive` | Derived from bankroll % |
| `max_parallel` | int | Max concurrent operations | Grid config |
| `uses_bankroll` | bool | Position sizes derived from bankroll % | Risk engine |
| `config_source` | str | Path to YAML/env source | Audit trail |
| `archetype` | str | Strategy type: `directional`, `market_maker`, `arbitrage`, `contrarian`, `vol_breakout`, `regime_switch` | Agent config |
| `series_tickers` | List[str] | Kalshi market series (e.g., `KXBTC-15M`) | Market catalog |

### 1.2 Bankroll-Driven Limit Resolution

All limits MUST derive from `KALSHI_PORTFOLIO_BANKROLL_CENTS` via `merid.settings`:

```python
# RESOLVED at startup (logged with percent + dollar value)
max_notional_total = bankroll * KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT  # 50% default
max_daily_loss = bankroll * KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT  # 10% default
max_per_asset = bankroll * KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT    # 16% default
margin_util_max = KALSHI_PORTFOLIO_MAX_MARGIN_UTIL_PCT            # 75% default
```

**Audit Rule**: Startup logs must show limits as `percent_of_bankroll + resolved $value`. Naked constants = FAIL.

### 1.3 Current Grid Status

| Agent ID | Role | Lane | Risk Tier | Archetype | Status |
|----------|------|------|-----------|-----------|--------|
| `kalshi-btc_15m` | trader | signal | moderate | directional | ✅ Declared |
| `kalshi-eth_15m` | trader | signal | moderate | directional | ✅ Declared |
| `kalshi-sol_15m` | trader | signal | moderate | directional | ✅ Declared |
| `kalshi-xrp_15m` | trader | signal | moderate | directional | ✅ Declared |
| `kalshi-doge_15m` | trader | signal | moderate | directional | ✅ Declared |
| `kalshi-btc_1h` | trader | signal | moderate | directional | ✅ Declared |
| `portfolio-risk` | risk | risk | conservative | n/a | ✅ Declared |
| `taco-consensus` | consensus | execution | conservative | n/a | ✅ Declared |
| `critic-agent` | critic | observer | conservative | n/a | ✅ Declared |
| `regime-eth` | trader | signal | moderate | regime_switch | ✅ Declared |
| `regime-sol` | trader | signal | moderate | regime_switch | ✅ Declared |
| `regime-xrp` | trader | signal | moderate | regime_switch | ✅ Declared |
| `regime-doge` | trader | signal | moderate | regime_switch | ✅ Declared |
| `regime-btc1h` | trader | signal | moderate | regime_switch | ✅ Declared |
| `social-broadcaster` | analytics | analytics | n/a | n/a | ✅ Declared |

---

## 2. Swarm Matrix (Interaction Graph)

### 2.1 Matrix Edge Definition

Every agent-to-agent interaction MUST be declared:

| From | To | Purpose | Payload Type | Frequency | Gateway |
|------|-----|---------|--------------|-----------|---------|
| TradingAgent | PortfolioRiskAgent | Position check | `PositionIntent` | Per-signal | Direct call |
| TradingAgent | TaCoConsensus | Opinion submission | `AgentOpinion` | Per-cycle | Bus publish |
| TradingAgent | KalshiVenueAdapter | Order execution | `OrderRequest` | On consensus | ExecutionGate |
| PortfolioRiskAgent | ExecutionGuard | Limit enforcement | `RiskLimits` | Continuous | Direct call |
| RegimeAgent | TaCoConsensus | Regime signal | `AgentOpinion` | 60s poll | Bus publish |
| CriticAgent | TradingAgent | Critique/staleness | `CritiqueMessage` | 30s sweep | Bus publish |
| ExecutionSubscriber | OrderRouter | Route decision | `ExecutionIntent` | On decision | Direct call |
| SocialBroadcaster | Telegram/X | Alert publish | `AlertPayload` | Event-driven | Sink adapter |
| AlertManager | All Agents | Kill switch | `HaltCommand` | Emergency | Bus broadcast |
| OutcomeResolver | TradingAgent | Settlement | `OutcomeResult` | 5m cycle | Direct call |
| EdgeRecalibrator | TradingAgent | Threshold update | `EdgeConfig` | 30m cycle | Direct call |

### 2.2 Cross-Lane Prohibitions

| Prohibited Call | Violation | Correct Path |
|-----------------|-----------|--------------|
| TradingAgent → OrderRouter (direct) | Bypasses ExecutionGuard | TradingAgent → PortfolioRiskAgent → ExecutionGate → OrderRouter |
| DevSwarm → LiveTradingLane | Contamination risk | DevSwarm → PaperLane only |
| AnalyticsAgent → ExecutionLane | Observer writes | AnalyticsAgent → Log only |
| SentimentAgent → OrderRouter | Signal → execution gap | SentimentAgent → TradingAgent → ... |

### 2.3 Trace Requirements

Every matrix edge MUST include:
- `trace_id`: UUID for full conversation tracking
- `parent_span`: Caller span ID
- `correlation_id`: Business event identifier
- `lane_tag`: Signal/Risk/Execution/Analytics/Dev

---

## 3. Lane Control Boundaries

### 3.1 Lane Definitions

#### Signal Lane (Input → Decision)
**Allowed Roles**: `trader`, `sentiment`, `consensus`  
**Allowed Systems**: Market catalog, sentiment service, mood bus, TaCo  
**Gate Controls**: `MERID_ENABLE_LIVE_PRICE_FEEDS`, `KALSHI_ONLY`  
**Entry Point**: `AgentGrid.start()` → agent cycles  
**Exit Point**: Consensus decision → Execution lane

#### Risk Lane (Continuous Monitoring)
**Allowed Roles**: `risk`, `critic`, `analytics`  
**Allowed Systems**: Portfolio risk engine, execution guard, adaptive limits  
**Gate Controls**: `KALSHI_PORTFOLIO_*_PCT` settings  
**Entry Point**: Position intents, fill events  
**Exit Point**: Halt/downsized/allow decisions

#### Execution Lane (Decision → Fill)
**Allowed Roles**: `execution`, `consensus`  
**Allowed Systems**: Order router, Kalshi client, paper session  
**Gate Controls**: `MERID_TRADING_MODE`, `MERID_LIVE_TRADING_UNLOCKED`  
**Entry Point**: ExecutionGuard approval  
**Exit Point**: Fill events → Ledger → UI

#### Analytics Lane (Observer Only)
**Allowed Roles**: `analytics`, `social`  
**Allowed Systems**: Read-only APIs, event bus  
**Gate Controls**: None (always safe)  
**Entry Point**: All events  
**Exit Point**: Logs, alerts, social posts

#### Dev Lane (Code/Testing)
**Allowed Roles**: `dev`, `test`  
**Allowed Systems**: Sandbox APIs, mock venues  
**Gate Controls**: `MERID_ENV=development`, `MERID_USE_MOCK_*`  
**Entry Point**: DevSwarmControlCenter  
**Exit Point**: PR → CI → Merge

### 3.2 CI Guards

| Check | Fail Condition |
|-------|---------------|
| `agent_in_grid` | Agent class exists but no grid entry |
| `no_hardcoded_max` | `MAX_*` constant not in whitelist |
| `lane_clean` | Dev agent imported in production lane |
| `bankroll_derived` | Limit expressed as naked $ value in code |

### 3.3 Runtime Lane Enforcement

```python
# In Production Lane (kalshi-only profile)
if MERID_PROFILE == "kalshi-only":
    # These are BLOCKED
    assert not dev_swarm_loaded
    assert not mock_data_enabled
    assert not archive_agents_running
```

---

## 4. Bug/Egg/Hardcode Hunt Results

### 4.1 Hardcoded Constants Found

| File | Line | Constant | Current Value | Should Derive From |
|------|------|----------|---------------|-------------------|
| `kalshi_risk_engine.py` | 126 | `max_risk_per_trade_pct` | 1.5% | `KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT` |
| `kalshi_risk_engine.py` | 128 | `max_position_per_market` | 2 (TIGHT) | Risk tier config |
| `kalshi_risk_engine.py` | 129 | `max_open_positions` | 3 (TIGHT) | Bankroll / position size |
| `kalshi_risk_engine.py` | 130 | `max_total_exposure_pct` | 12% (TIGHT) | `KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT` |
| `_prediction_risk.py` | 95 | `max_contracts` (crypto) | 500 | Position sizing formula |
| `_prediction_risk.py` | 100 | `max_contracts` (economics) | 300 | Position sizing formula |
| `agent_grid_config.py` | 57 | `max_yes_position` | 3000 | Risk tier + bankroll |
| `agent_grid_config.py` | 58 | `max_no_position` | 3000 | Risk tier + bankroll |
| `agent_grid_config.py` | 60 | `max_notional_usd` | $500 | `max_per_asset_cents` |

### 4.2 Wiring Gaps / Eggs

| Location | Issue | Risk |
|----------|-------|------|
| `AgentGrid._feed_mood_bus()` | Hardcoded asset mapping (BTC/ETH/SOL/XRP/DOGE) | New assets won't be detected |
| `AgentGrid._volume_poll_loop()` | No trace spans for mood bus updates | Unobservable flow |
| `RegimeAgent.get_opinion()` | Score thresholds (-0.3, +0.3) hardcoded | No config adjustment |
| `TradingAgent._execute_signal()` | No correlation ID propagation | Can't trace fill → consensus |
| `PaperSession` | Daily loss limits hardcoded per cell | Should derive from cluster config |

### 4.3 Calibration Gates Needed

| Gate | Threshold | Action on Breach |
|------|-----------|------------------|
| Brier Score | > 0.25 (worse than random) | Demote to observer only |
| Realized Edge | < 0 (negative after fees) | Halt agent, trigger review |
| Win Rate | < 40% after 50 trades | Demote to paper-only |
| Drawdown | > 8% of cell bankroll | Auto-downsize 50% |
| Latency P95 | > 500ms | Alert, degrade confidence |

---

## 5. Pass/Fail Checklist

### Grid Integrity
- [ ] Every agent class has grid entry
- [ ] Every grid entry has running implementation
- [ ] No `MAX_*` constants outside config (whitelisted exceptions documented)
- [ ] Startup logs show `percent_of_bankroll + $value` for all limits
- [ ] Agent `summary()` includes `series_tickers` resolved from grid

### Matrix Clarity
- [ ] All agent→agent interactions in matrix table
- [ ] No cross-lane calls bypassing gateways
- [ ] Every interaction has trace_id + correlation_id
- [ ] Bus publish/subscribe pairs documented

### Lane Control
- [ ] CI fails on `agent_not_in_grid`
- [ ] CI fails on `hardcoded_max_constant`
- [ ] CI fails on `dev_agent_in_production_lane`
- [ ] Runtime asserts block archive/dev agents in `kalshi-only` profile

### Data Contracts
- [ ] Signal → Risk → Execution fields match schemas
- [ ] No "TODO" placeholders in lane data contracts
- [ ] Logs include IDs tieable to matrix edges
- [ ] Truth endpoints (risk, reconciliation) confirm lane state

### Calibration
- [ ] Brier score threshold gate active
- [ ] Realized edge tracking per agent
- [ ] Auto-promote/demote based on calibration
- [ ] Human-in-loop for threshold changes

---

## 6. Action Items (Prioritized)

### High Priority (Block Live Trading)
1. **Move all `MAX_*` constants to settings** with bankroll-derived formulas
2. **Add correlation ID propagation** through signal→risk→execution chain
3. **Implement Brier score gate** preventing poorly-calibrated agents from live voting
4. **Add lane violation runtime asserts** in `kalshi-only` profile
5. **Script**: `scripts/audit_agent_grid.py` scanning for undeclared agents/constants

### Medium Priority (Observability)
6. Add trace spans to mood bus and volume poll loops
7. Document all bus publish/subscribe pairs in matrix
8. Make regime agent score thresholds config-driven
9. Add `agent_grid summary` CLI command for operator visibility

### Low Priority (Polish)
10. Auto-generate matrix visualization from code
11. Add lane contamination alerts (dev code in prod path)
12. Create calibration dashboard showing Brier/edge per agent

---

## Appendix A: Whitelisted Constants

These `MAX_*` constants are acceptable as they are cosmetic or protocol-level:

| Constant | Location | Justification |
|----------|----------|---------------|
| `_MIN_CUTOFF_MINUTES = 2` | `agent_grid_config.py:184` | Kalshi protocol minimum (hard exchange limit) |
| `MAX_ORDERS_PER_CYCLE = 1/2` | `kalshi_risk_engine.py` | Rate limiting (not risk sizing) |
| `MAX_CONCURRENT_REQUESTS = 10` | `settings.py:251` | HTTP connection pool sizing |

---

## Appendix B: Grid Entry Template

```yaml
# config/kalshi_agent_grid.yaml
agents:
  - name: btc_15m
    agent_id: kalshi-btc_15m
    role: trader
    lane: signal
    risk_tier: moderate
    archetype: directional
    series_tickers:
      - KXBTC-15M
    risk_limits:
      max_notional_pct: 0.08        # 8% of bankroll
      max_position_contracts: null  # derive from notional
    config_source: config/agents/btc_15m.yaml
```

---

*Audit conducted: 2026-03-24*  
*Next review: After grid schema implementation (Task 2 complete)*
