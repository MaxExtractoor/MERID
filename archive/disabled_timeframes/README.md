# Disabled Timeframes Archive

**Archive Date:** 2026-01-15  
**Reason:** Focus on 15-minute crypto trading stack (BTC, ETH, SOL, XRP, DOGE)  
**Scope:** Hourly, daily, weekly, monthly, annual trading agents and configurations  

---

## Archived Components

### Agent Implementations
- `btc_1h_agent.py` - BTC hourly range contracts agent

### Agent Specifications
- `btc_1h_agent_spec.py` - BTC hourly agent specification

### Configuration Sections
- Disabled agent entries from `kalshi_agent_grid.yaml`:
  - BTC_HOURLY
  - BTC_WEEKLY
  - ETH_HOURLY
  - ETH_DAILY
  - SOL_HOURLY
  - XRP_HOURLY
  - BTC_MONTHLY
  - ETH_MONTHLY
  - SOL_MONTHLY
  - XRP_ANNUAL

---

## Why These Were Archived

The 15-minute Kalshi trading stack focuses exclusively on 15-minute crypto prediction markets for BTC, ETH, SOL, XRP, and DOGE. Other timeframes (hourly, daily, weekly, monthly, annual) are not actively used in the current production configuration.

Archiving these components:
- Reduces code surface area
- Eliminates confusion about which agents are active
- Simplifies maintenance
- Focuses development on 15m timeframe

---

## Restoration Instructions

If hourly/daily/weekly trading needs to be re-enabled:

1. **Restore files from archive:**
   ```bash
   # Restore agent implementation
   cp archive/disabled_timeframes/agents/btc_1h_agent.py merid/agents/
   
   # Restore agent specification
   cp archive/disabled_timeframes/configs/btc_1h_agent_spec.py config/
   ```

2. **Restore agent entries in kalshi_agent_grid.yaml:**
   - Add back the disabled agent entries
   - Set `enabled: true` for agents you want to activate
   - Configure assets and timeframes

3. **Restore code references:**
   - Add imports back to `merid/prediction/agent_grid.py`
   - Add imports back to `merid/agents/kalshi_crypto/__init__.py`
   - Restore test references if needed

4. **Verify configuration:**
   - Ensure agent specifications are loaded correctly
   - Check that agent grid configuration is valid
   - Test agent instantiation

---

## Code Changes Made

### Files Modified
- `merid/prediction/agent_grid.py` - Removed Btc1hAgent import and instantiation
- `merid/agents/kalshi_crypto/__init__.py` - Removed Btc1hAgent from CRYPTO_AGENTS dict
- `tests/test_agent_contract_validation.py` - Removed Btc1hAgent tests
- `tests/test_kalshi_only_guardrails.py` - Removed Btc1hAgent from test list
- `config/kalshi_agent_grid.yaml` - Removed disabled agent entries

### Files Moved to Archive
- `merid/agents/btc_1h_agent.py` → `archive/disabled_timeframes/agents/`
- `config/btc_1h_agent_spec.py` → `archive/disabled_timeframes/configs/`

---

## Active 15m Agents (Not Archived)

The following agents remain active and are NOT archived:
- `merid/agents/btc_15m_agent.py` - BTC 15-minute agent
- `merid/agents/eth_15m_agent.py` - ETH 15-minute agent
- `merid/agents/sol_15m_agent.py` - SOL 15-minute agent
- `merid/agents/xrp_15m_agent.py` - XRP 15-minute agent
- `merid/agents/doge_15m_agent.py` - DOGE 15-minute agent

---

## Configuration Files Preserved

The following configuration files contain timeframe-specific settings but are preserved for other purposes:
- `config/kalshi_crypto_hedging.yaml` - Hedge configuration for adjacent horizons
- `config/kalshi_distance.yaml` - Distance caps for all timeframes
- `config/crypto_threshold_matrix.yaml` - Edge thresholds for all timeframes
- `config/tiered_profit_template.yaml` - TP templates with timeframe configs

These files are NOT archived because:
- They are used by the active 15m stack
- They serve as reference for signal generation
- They contain configuration for multiple systems

---

## Validation Checklist

Before considering this archive complete:
- [ ] All disabled agent files moved to archive
- [ ] All code references to disabled components removed
- [ ] No broken imports in codebase
- [ ] Archive documented with restoration instructions
- [ ] 15m agents still function correctly
- [ ] Test suite passes (after test updates)

---

## Contact

For questions about this archive or restoration procedures, refer to the main audit report at:
`analysis/15M_KALSHI_TRADING_STACK_AUDIT_REPORT.md`
