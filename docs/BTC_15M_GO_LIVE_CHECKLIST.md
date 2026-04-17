# docs/BTC_15M_GO_LIVE_CHECKLIST.md
# BTC 15m Agent Go-Live Checklist

## Overview
This checklist defines the requirements and steps for promoting the BTC 15m agent from shadow → paper → live trading.

## Phase 1: Shadow Mode Validation (Minimum 7 days)

### Performance Requirements
- [ ] **Shadow Period**: Minimum 7 continuous days of shadow operation
- [ ] **Win Rate**: ≥ 55% (target: 58% from backtest)
- [ ] **Realized Edge**: ≥ 1.5% (target: 2.4% from backtest)
- [ ] **Max Drawdown**: ≤ 10% (target: 8.7% from backtest)
- [ ] **Trade Frequency**: 8-15 trades per day (consistent with backtest)
- [ ] **Sharpe Ratio**: ≥ 1.0 (target: 1.34 from backtest)

### System Health Requirements
- [ ] **Latency**: Submit→ack p50 ≤ 50ms, p90 ≤ 100ms
- [ ] **Fill Rate**: ≥ 95% of submitted orders filled
- [ ] **Slippage**: Average slippage ≤ 2¢ per contract
- [ ] **Blocked Signals**: ≤ 20% blocked by risk gates
- [ ] **API Connectivity**: 99.9% uptime to Kalshi endpoints

### Reconciliation Requirements
- [ ] **Backtest vs Shadow**: Run reconciliation script
- [ ] **Hit Rate Delta**: Shadow hit rate within ±5% of backtest
- [ ] **Edge Delta**: Realized edge within ±0.5% of expected
- [ ] **Regime Analysis**: Trade rates consistent across market regimes

### Configuration Validation
- [ ] **Risk Parameters**: `min_edge_threshold`, `max_vol_ratio` validated
- [ ] **Size Limits**: `max_exposure_pct` appropriate for account size
- [ ] **Time Windows**: `time_to_expiry_min/max` aligned with market hours
- [ ] **Kill Switch**: Global and per-agent kill switches tested

## Phase 2: Paper Mode Validation (Minimum 14 days)

### Paper Trading Requirements
- [ ] **Paper Period**: Minimum 14 continuous days of paper trading
- [ ] **Live Orderbook**: Paper fills based on real Kalshi orderbook
- [ ] **P&L Tracking**: Paper P&L accurately calculated and recorded
- [ ] **Margin Management**: Paper margin usage within limits
- [ ] **Position Management**: Paper positions opened/closed correctly

### Performance Validation
- [ ] **Paper vs Shadow**: Paper performance within ±10% of shadow
- [ ] **Fill Simulation**: Paper fill rates match live expectations
- [ ] **Slippage Modeling**: Paper slippage realistic vs live expectations
- [ ] **Risk Controls**: Paper risk controls trigger appropriately

### Operational Requirements
- [ ] **Monitoring**: All monitoring dashboards functional
- [ ] **Alerts**: Risk alerts configured and tested
- [ ] **Backup**: Paper portfolio data backed up daily
- [ ] **Failover**: Automatic failover to shadow if issues detected

## Phase 3: Live Mode Readiness

### Pre-Live Checks
- [ ] **Account Setup**: Kalshi live account configured and funded
- [ ] **API Keys**: Live API keys configured and tested
- [ ] **Risk Limits**: Live risk limits set (lower than paper)
- [ ] **Position Limits**: Live position limits set (conservative)
- [ ] **Emergency Contacts**: Emergency contact procedures documented

### Final Validation
- [ ] **Configuration Review**: All config parameters reviewed and approved
- [ ] **Risk Review**: Risk team sign-off on parameters
- [ ] **Compliance Review**: Compliance team sign-off on trading
- [ ] **Infrastructure Review**: Infrastructure readiness confirmed

### Go-Live Steps
1. **Set Mode**: `BTC_15M_REGIME_MODE=live` via environment variable or API
2. **Size Multiplier**: Start with `BTC_15M_REGIME_SIZE_MULTIPLIER=0.5` (50% size)
3. **Monitor**: Closely monitor first 24 hours of live trading
4. **Scale Up**: If performance acceptable, increase size multiplier to 1.0
5. **Full Operation**: Continue monitoring and adjust as needed

## Emergency Procedures

### Immediate Halt
- Set `BTC_15M_REGIME_MODE=shadow` to immediately stop live trading
- Or use global kill switch via API/UI
- Investigate issue before re-enabling

### Rollback Plan
- Live → Paper: Change mode to "paper" to continue simulation
- Paper → Shadow: Change mode to "shadow" for observation only
- Document all rollbacks and root causes

## Post-Live Monitoring

### Daily Checks
- [ ] **Performance Review**: Daily P&L, win rate, drawdown review
- [ ] **Risk Review**: Risk limits and exposure review
- [ ] **System Health**: Latency, fill rates, error rates review
- [ ] **Market Conditions**: Regime changes and volatility review

### Weekly Reviews
- [ ] **Performance Analysis**: Weekly performance vs expectations
- [ ] **Parameter Tuning**: Adjust parameters based on performance
- [ ] **Risk Assessment**: Reassess risk limits and controls
- [ ] **Strategy Review**: Review strategy effectiveness and changes

## Sign-off Requirements

### Required Approvals
- [ ] **Strategy Team**: Strategy performance and parameters approved
- [ ] **Risk Team**: Risk limits and controls approved
- [ ] **Compliance Team**: Regulatory compliance approved
- [ ] **Operations Team**: Infrastructure and monitoring approved

### Documentation
- [ ] **Configuration**: All configuration parameters documented
- [ ] **Procedures**: All operational procedures documented
- [ ] **Contacts**: Emergency contacts and procedures documented
- [ ] **Review**: All checklist items completed and signed off

---

**Note**: This checklist should be completed sequentially. Each phase must be fully completed before proceeding to the next phase. Any failures should be documented and resolved before continuing.
