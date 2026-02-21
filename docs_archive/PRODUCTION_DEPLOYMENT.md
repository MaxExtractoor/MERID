# MERID Swarm - Production Deployment Checklist

**Complete pre-deployment validation for production trading.**

---

## Overview

This checklist ensures the swarm system is ready for production deployment. **All items must be completed and verified** before enabling live trading.

**Deployment Phases**:
1. **Simulation** (1-2 weeks) - Test with simulated execution
2. **Paper Trading** (2-4 weeks) - Test with paper accounts
3. **Limited Live** (1-2 weeks) - Small position sizes
4. **Full Production** - Normal operation

---

## Phase 1: Simulation Validation

### Environment Setup

- [ ] `.env` file configured with all required settings
- [ ] `RUN_MODE=simulation` in `.env`
- [ ] `LIVE_MODE_AUTHORIZED=false` in `.env`
- [ ] All API keys configured (even if not used in simulation)
- [ ] Logging configured with appropriate levels
- [ ] Database connections tested (if applicable)

### Code Validation

- [ ] All strategy agents wired with `SwarmAgentMixin`
- [ ] All agents emit `StrategyOpinion` events
- [ ] All agents have heartbeat loops running
- [ ] Consensus coordinator subscribed to opinions
- [ ] Execution coordinator subscribed to consensus
- [ ] Order router configured for simulation mode
- [ ] Watchdog agents configured and running

### Testing

- [ ] E2E test passes: `python tests/test_swarm_e2e.py`
- [ ] Pipeline verification passes: `python scripts/verify_swarm_pipeline.py`
- [ ] Readiness check passes: `python scripts/swarm_readiness.py`
- [ ] 1-hour rehearsal passes with 0 failures
- [ ] 24-hour rehearsal completes successfully
- [ ] Graceful degradation test passes (kill agent mid-session)

### Metrics & Monitoring

- [ ] Telemetry capturing all events
- [ ] Prometheus metrics exporting correctly
- [ ] All 4 watchdog types operational
- [ ] Alert notifications configured
- [ ] Log aggregation working
- [ ] UI components displaying real-time data

### Documentation

- [ ] All agents documented with wiring status
- [ ] Rehearsal logs captured for 7 consecutive days
- [ ] No critical issues in any rehearsal
- [ ] Incident response procedures documented

---

## Phase 2: Paper Trading Validation

### Environment Setup

- [ ] Switch to `RUN_MODE=paper` in `.env`
- [ ] Paper trading accounts configured (Alpaca, IBKR, etc.)
- [ ] Paper account credentials verified
- [ ] `LIVE_MODE_AUTHORIZED` still `false`
- [ ] Separate paper trading `.env.paper` file created

### Broker Integration

- [ ] Paper orders executing successfully
- [ ] Order status updates received
- [ ] Fill notifications working
- [ ] Position tracking accurate
- [ ] Balance updates correct
- [ ] Commission calculations accurate

### Testing

- [ ] 72-hour paper trading session completes
- [ ] Order ancestry fully traceable (Order → Intent → Consensus → Opinions)
- [ ] No mode violations (no live calls in paper mode)
- [ ] Telemetry shows healthy metrics throughout
- [ ] UI displays accurate paper trading data
- [ ] All watchdog alerts investigated and resolved

### Performance Validation

- [ ] Opinion generation rate: 10-50/minute
- [ ] Consensus formation rate: 3-15/minute
- [ ] Order execution latency: <5 seconds (opinion→order)
- [ ] Agent participation rate: >90%
- [ ] Consensus success rate: >80%
- [ ] Pipeline latency: <10 seconds end-to-end

### Risk Validation

- [ ] Risk checks preventing oversized orders
- [ ] Position limits enforced correctly
- [ ] Correlation limits working
- [ ] Leverage limits enforced
- [ ] Daily loss limits enforced
- [ ] Emergency stop working

### Stability

- [ ] 7-day continuous paper trading with 0 crashes
- [ ] Memory usage stable (no leaks)
- [ ] CPU usage reasonable (<50% sustained)
- [ ] Network errors handled gracefully
- [ ] Broker API rate limits respected
- [ ] Automatic reconnection working

---

## Phase 3: Limited Live Trading

### Pre-Live Checklist

- [ ] **CRITICAL**: Get written approval from 2+ reviewers
- [ ] **CRITICAL**: Complete incident response plan
- [ ] **CRITICAL**: Test emergency stop procedure
- [ ] **CRITICAL**: Verify all compliance requirements met
- [ ] **CRITICAL**: Review all open tickets/issues

### Environment Setup

- [ ] Create separate production `.env.production` file
- [ ] Switch to `RUN_MODE=live` in production env
- [ ] Set `LIVE_MODE_AUTHORIZED=true` (with extreme caution)
- [ ] Configure live broker accounts
- [ ] Set very conservative position limits initially
- [ ] Configure maximum daily loss limits
- [ ] Set up real-time alerting (PagerDuty, etc.)

### Risk Controls (EXTRA CONSERVATIVE)

- [ ] Maximum position size: 1% of portfolio (initially)
- [ ] Maximum daily loss: 0.5% of portfolio
- [ ] Maximum number of simultaneous positions: 3
- [ ] Minimum confidence threshold: 0.7 (higher than normal)
- [ ] Maximum leverage: 1x (no leverage initially)
- [ ] Symbols whitelist (only most liquid assets)
- [ ] Trading hours restriction (market hours only)

### Monitoring

- [ ] 24/7 on-call rotation established
- [ ] Real-time position monitoring
- [ ] Real-time P&L tracking
- [ ] Anomaly detection alerts configured
- [ ] Correlation breach alerts
- [ ] Order fill anomaly alerts
- [ ] Heartbeat failure alerts
- [ ] Consensus failure alerts

### Testing

- [ ] Execute 1 live trade manually and verify
- [ ] Verify order fills at expected prices
- [ ] Verify commissions are correct
- [ ] Verify position tracking accurate
- [ ] Test emergency stop (with tiny position)
- [ ] Verify all alerts fire correctly

### First Week Live

- [ ] Start with absolute minimum position sizes
- [ ] Trade only 1-2 symbols initially
- [ ] Increase limits 10% per day maximum
- [ ] Review every trade manually
- [ ] Investigate every alert immediately
- [ ] Daily team review of all trades
- [ ] Keep paper trading running in parallel for comparison

---

## Phase 4: Full Production

### Gradual Ramp

- [ ] Week 1: 10% of normal position sizes
- [ ] Week 2: 25% of normal position sizes  
- [ ] Week 3: 50% of normal position sizes
- [ ] Week 4: 75% of normal position sizes
- [ ] Week 5+: 100% (if all metrics healthy)

### Production Readiness

- [ ] 30 days of successful limited live trading
- [ ] Zero critical incidents
- [ ] All performance metrics within targets
- [ ] Sharpe ratio meets expectations
- [ ] Maximum drawdown within limits
- [ ] Win rate within historical range
- [ ] Slippage analysis acceptable

### Ongoing Operations

- [ ] Daily health checks automated
- [ ] Weekly performance reviews scheduled
- [ ] Monthly system audits scheduled
- [ ] Quarterly disaster recovery drills
- [ ] Continuous rehearsal validation (weekly)
- [ ] Regular code reviews for any changes

---

## Deployment Commands

### Simulation

```bash
# Set environment
export MERID_ENV=simulation
cp .env.simulation .env

# Start system
python scripts/start_swarm_system.py --mode simulation --verify

# Verify
python scripts/swarm_readiness.py

# Start backend
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000
```

### Paper Trading

```bash
# Set environment
export MERID_ENV=paper
cp .env.paper .env

# Verify paper accounts
python scripts/verify_broker_connections.py --mode paper

# Start system
python scripts/start_swarm_system.py --mode paper --verify

# Monitor
tail -f logs/merid.log | grep -E "(Order|Fill|Error)"
```

### Limited Live (EXTREME CAUTION)

```bash
# Set environment
export MERID_ENV=production
cp .env.production .env

# Triple-check configuration
python scripts/verify_production_config.py

# Verify risk limits
python scripts/verify_risk_limits.py

# Start system with verification
python scripts/start_swarm_system.py --mode live --verify

# WATCH CLOSELY
python scripts/monitor_live_trading.py --alert-threshold 0.01
```

---

## Emergency Procedures

### Emergency Stop

If anything goes wrong:

```bash
# Immediate stop
python scripts/emergency_stop.py --mode live --close-all-positions

# Or kill everything
pkill -9 -f "uvicorn web.main"
pkill -9 -f "strategy_agent"
```

### Rollback to Paper

```bash
# Switch back to paper immediately
export MERID_ENV=paper
cp .env.paper .env

# Restart in paper mode
python scripts/start_swarm_system.py --mode paper
```

### Investigation

```bash
# Capture current state
python scripts/capture_system_state.py --output investigation_$(date +%Y%m%d_%H%M%S)

# Export logs
tar -czf logs_$(date +%Y%m%d_%H%M%S).tar.gz logs/

# Generate incident report
python scripts/generate_incident_report.py --since "2 hours ago"
```

---

## Sign-Off Requirements

Before each phase, get written sign-off from:

### Simulation → Paper
- [ ] Lead Developer
- [ ] QA Lead
- [ ] Risk Manager

### Paper → Limited Live
- [ ] CTO/Technical Director
- [ ] CEO/Managing Director
- [ ] Compliance Officer
- [ ] Risk Manager
- [ ] 2+ Senior Developers

### Limited Live → Full Production
- [ ] Executive Leadership
- [ ] Risk Committee
- [ ] Compliance Review
- [ ] External Audit (if required)

---

## Key Performance Indicators (KPIs)

Track these metrics at each phase:

### System Health
- Agent participation rate: >90%
- Consensus success rate: >80%
- Opinion→Order latency: <5s p99
- Error rate: <0.1%
- Uptime: >99.9%

### Trading Performance
- Sharpe ratio: >1.5 (target)
- Maximum drawdown: <10%
- Win rate: >55%
- Average trade duration: Variable
- Slippage: <5 bps

### Risk Metrics
- VaR (95%): <2% of portfolio
- Correlation with market: <0.7
- Beta: 0.8-1.2
- Position concentration: <20% in single asset

---

## Continuous Validation

Even in production, continue running:

```bash
# Weekly rehearsal
python scripts/paper_rehearsal.py --mode simulation --duration 3600

# Monthly full readiness check
python scripts/swarm_readiness.py --extended

# Daily health check
python scripts/daily_health_check.py

# Continuous monitoring
python scripts/live_monitor.py --continuous
```

---

## Compliance & Audit

- [ ] Trading logs retained for required period (7+ years)
- [ ] Audit trail complete (Opinion→Consensus→Order)
- [ ] All configuration changes logged
- [ ] Access logs maintained
- [ ] Incident reports documented
- [ ] Performance reports generated monthly
- [ ] Regulatory reporting automated

---

## Final Checklist Before Live

**DO NOT ENABLE LIVE TRADING UNTIL ALL OF THESE ARE TRUE**:

- [ ] Simulation ran successfully for 2+ weeks
- [ ] Paper trading ran successfully for 4+ weeks
- [ ] All tests passing for 30+ consecutive days
- [ ] Zero critical bugs in issue tracker
- [ ] All team members trained on emergency procedures
- [ ] Emergency stop tested successfully
- [ ] On-call rotation established
- [ ] Insurance/risk coverage in place
- [ ] Legal approval obtained
- [ ] Compliance approval obtained
- [ ] Executive sign-off received
- [ ] Incident response plan reviewed
- [ ] Disaster recovery plan tested

---

## Post-Deployment

After going live:

- **First 48 hours**: Continuous monitoring by team
- **First week**: Daily team review of all trades
- **First month**: Weekly performance review
- **Ongoing**: Monthly audit, quarterly review

---

**Remember**: You can always run in paper mode indefinitely. There's no rush to go live. Better to be conservative and confident than fast and risky.

---

**Last Updated**: 2026-02-06  
**Version**: 1.0  
**Owner**: [Your Name/Team]
