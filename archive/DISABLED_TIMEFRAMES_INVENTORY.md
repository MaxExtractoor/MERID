# Disabled Timeframes Inventory

**Date:** 2026-01-15
**Purpose:** Document all disabled timeframe components for archival
**Scope:** Hourly, Daily, Weekly, Monthly, Annual crypto trading agents

---

## Disabled Agents in kalshi_agent_grid.yaml

### Explicitly Disabled (enabled: false)

| Agent Name | Line | Timeframe | Assets | Reason |
|------------|------|-----------|--------|--------|
| BTC_HOURLY | 64 | hourly | [] | SIGNAL ONLY - Focus on 15m |
| BTC_WEEKLY | 133 | weekly | [] | SIGNAL ONLY - Focus on 15m |
| ETH_HOURLY | 216 | hourly | [] | SIGNAL ONLY - Focus on 15m |
| ETH_DAILY | 250 | daily | [] | SIGNAL ONLY - Focus on 15m |
| SOL_HOURLY | 367 | hourly | [] | SIGNAL ONLY - Focus on 15m |
| XRP_HOURLY | 518 | hourly | [] | SIGNAL ONLY - Focus on 15m |
| BTC_MONTHLY | 620 | monthly | [] | SIGNAL ONLY - Focus on 15m |
| ETH_MONTHLY | 668 | monthly | [] | SIGNAL ONLY - Focus on 15m |
| SOL_MONTHLY | 715 | monthly | [] | SIGNAL ONLY - Focus on 15m |
| XRP_ANNUAL | 786 | annual | [] | SIGNAL ONLY - Focus on 15m |

### Implicitly Disabled (empty assets/timeframes but no enabled: false)

| Agent Name | Line | Timeframe | Assets | Status |
|------------|------|-----------|--------|--------|
| BTC_DAILY | 98 | daily | [BTC] | Has assets, but may be signal-only |
| ETH_WEEKLY | 284 | weekly | [ETH] | Has assets, but may be signal-only |
| SOL_DAILY | 400 | daily | [SOL] | Has assets, but may be signal-only |
| SOL_WEEKLY | 434 | weekly | [SOL] | Has assets, but may be signal-only |
| XRP_DAILY | 551 | daily | [XRP] | Has assets, but may be signal-only |
| XRP_WEEKLY | 585 | weekly | [XRP] | Has assets, but may be signal-only |
| BTC_ANNUAL | 644 | annual | [BTC] | Has assets, but may be signal-only |
| ETH_ANNUAL | 692 | annual | [ETH] | Has assets, but may be signal-only |
| SOL_ANNUAL | 739 | annual | [SOL] | Has assets, but may be signal-only |
| XRP_MONTHLY | 761 | monthly | [XRP] | Has assets, but may be signal-only |

**Note:** Agents with assets defined may still be signal-only if not actively used in 15m-focused stack.

---

## Code Files to Archive

### Agent Implementations

| File | Purpose | Status |
|------|---------|--------|
| merid/agents/btc_1h_agent.py | BTC hourly agent implementation | DISABLED - Not used in 15m stack |
| config/btc_1h_agent_spec.py | BTC hourly agent specification | DISABLED - Not used in 15m stack |

### References to Disabled Components

| File | Reference | Action Required |
|------|-----------|----------------|
| tests/test_agent_contract_validation.py | Btc1hAgent import | Remove or update tests |
| tests/test_kalshi_only_guardrails.py | Btc1hAgent in list | Remove from test |
| merid/prediction/agent_grid.py | Btc1hAgent import | Remove import and instantiation |
| merid/agents/kalshi_crypto/__init__.py | Btc1hAgent import | Remove from CRYPTO_AGENTS dict |

---

## Active 15m Agents (Do NOT Archive)

| Agent Name | File | Status |
|------------|------|--------|
| BTC_15M | merid/agents/btc_15m_agent.py | ACTIVE |
| ETH_15M | merid/agents/eth_15m_agent.py | ACTIVE |
| SOL_15M | merid/agents/sol_15m_agent.py | ACTIVE |
| XRP_15M | merid/agents/xrp_15m_agent.py | ACTIVE |
| DOGE_15M | merid/agents/doge_15m_agent.py | ACTIVE |

---

## Configuration Files with Timeframe References

These files contain timeframe-specific configuration but may be needed for other purposes:

| File | Purpose | Action |
|------|---------|--------|
| config/kalshi_crypto_hedging.yaml | Hedge configuration for adjacent horizons | KEEP - Used by hedge engine |
| config/kalshi_distance.yaml | Distance caps for all timeframes | KEEP - Used for reference |
| config/crypto_threshold_matrix.yaml | Edge thresholds for all timeframes | KEEP - Single source of truth |
| config/tiered_profit_template.yaml | TP templates with timeframe configs | KEEP - May be referenced by active agents |
| config/ta_engine.yaml | TA engine timeframe list | KEEP - General configuration |

---

## Strategy Files (Review Required)

| File | Purpose | Action |
|------|---------|--------|
| merid/strategies/backtest_15m_meanrev.py | 15m backtest | KEEP - Active timeframe |
| merid/strategies/band_backtest_15m.py | 15m backtest | KEEP - Active timeframe |
| merid/strategies/band_strategy_15m.py | 15m strategy | KEEP - Active timeframe |
| merid/strategies/crypto_15m_strategy.py | 15m strategy | KEEP - Active timeframe |
| merid/strategies/engine_15m.py | 15m engine | KEEP - Active timeframe |
| merid/strategies/kalshi_15m_backtest.py | 15m backtest | KEEP - Active timeframe |
| merid/strategies/kalshi_15m_microstructure_backtest.py | 15m backtest | KEEP - Active timeframe |
| merid/strategies/production_strategy_15m.py | 15m strategy | KEEP - Active timeframe |
| merid/strategies/risk_15m.py | 15m risk | KEEP - Active timeframe |
| merid/strategies/signals_15m.py | 15m signals | KEEP - Active timeframe |
| merid/strategies/strategy_integration_15m.py | 15m integration | KEEP - Active timeframe |
| merid/strategies/trade_book_15m.py | 15m trade book | KEEP - Active timeframe |

**Note:** All 15m strategy files should be kept. Review if any strategy files exist for disabled timeframes.

---

## Archive Plan

### Phase 1: Archive Explicitly Disabled Components

1. Create archive structure:
   ```
   archive/disabled_timeframes/
   ├── agents/
   ├── configs/
   ├── tests/
   └── README.md
   ```

2. Move files:
   - merid/agents/btc_1h_agent.py → archive/disabled_timeframes/agents/
   - config/btc_1h_agent_spec.py → archive/disabled_timeframes/configs/

3. Remove disabled agent entries from kalshi_agent_grid.yaml:
   - Remove BTC_HOURLY, BTC_WEEKLY, ETH_HOURLY, ETH_DAILY, SOL_HOURLY, XRP_HOURLY, BTC_MONTHLY, ETH_MONTHLY, SOL_MONTHLY, XRP_ANNUAL
   - Keep BTC_DAILY, ETH_WEEKLY, SOL_DAILY, SOL_WEEKLY, XRP_DAILY, XRP_WEEKLY, BTC_ANNUAL, ETH_ANNUAL, SOL_ANNUAL, XRP_MONTHLY for review (may be signal-only)

4. Update code references:
   - Remove Btc1hAgent imports from all files
   - Remove Btc1hAgent from test files
   - Remove Btc1hAgent from agent_grid.py
   - Remove Btc1hAgent from kalshi_crypto/__init__.py

### Phase 2: Review Implicitly Disabled Agents

1. Determine if agents with assets defined are actually used
2. If signal-only only, archive their configuration entries
3. If still needed for signal generation, keep but document as signal-only

### Phase 3: Validation

1. Search codebase for any remaining references to archived components
2. Verify no broken imports
3. Run test suite to ensure no test failures
4. Verify 15m agents still function correctly

---

## Restoration Instructions

If hourly/daily/weekly trading needs to be re-enabled:

1. Restore files from archive/disabled_timeframes/
2. Restore agent entries in kalshi_agent_grid.yaml
3. Restore imports in agent_grid.py and kalshi_crypto/__init__.py
4. Restore test references if needed
5. Set enabled: true for restored agents

---

## Acceptance Criteria

- [ ] All explicitly disabled agent files moved to archive
- [ ] All code references to disabled components removed
- [ ] No broken imports in codebase
- [ ] Archive documented with restoration instructions
- [ ] 15m agents still function correctly
- [ ] Test suite passes (after test updates)
