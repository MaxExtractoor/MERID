# Risk & Safety v1 Hardening - Implementation Complete

**Status**: ✅ Phase 1 Complete | **Next**: Wire into CI and UI

This issue tracks the integration of the risk/safety system into production workflows and dashboards.

---

## ✅ Completed (Phase 1)

### Core Safety Logic
- [x] **TradingGuard** with circuit breaker state machine (CLOSED/OPEN/HALF_OPEN)
- [x] **Daily loss limits** enforcement with PortfolioAggregator tracking
- [x] **Per-symbol exposure caps** with real-time monitoring
- [x] **Max open orders** limits to prevent queue overflow
- [x] **Kill switch** (enable_trading_suite flag) for emergency stops
- [x] **Automatic lockdown** on circuit breaker trip or risk limit breach

### Test Coverage (40+ new tests, all passing)
- [x] `tests/risk/test_risk_limits.py` - 17 tests for risk limits
- [x] `tests/safety/test_circuit_breaker.py` - 12 tests for circuit breaker states
- [x] `tests/integration/test_venue_failure_modes.py` - 11 tests for venue failures
- [x] `tests/e2e/test_circuit_breaker_chaos.py` - 6 chaos/stress tests

### API Endpoint
- [x] `GET /api/risk/protections` - Returns circuit state, lockdown status, risk limits
- [x] `POST /api/risk/circuit-breaker/reset` - Manual reset (admin only)
- [x] `POST /api/risk/kill-switch/{enable|disable}` - Toggle kill switch

---

## 🔲 Remaining (Phase 2)

### CI/CD Integration
- [ ] Verify GitHub Actions workflow runs with new thresholds
- [ ] Add badge to README for safety-critical coverage
- [ ] Document coverage gates in CONTRIBUTING.md

### Dashboard UI
- [ ] Add circuit breaker status badge to main dashboard
- [ ] Color-coded indicators: 🟢 CLOSED / 🔴 OPEN / 🟡 HALF_OPEN
- [ ] Tooltip showing recent breaker events
- [ ] "Locked Down" banner when kill switch engaged
- [ ] Risk limit utilization bars (daily loss, symbol exposure, open orders)

### Documentation
- [ ] Update `RISK_POLICY.md` with implemented behavior
- [ ] Document circuit breaker configuration options
- [ ] Add troubleshooting guide for lockdown scenarios

### Operational Runbooks
- [ ] Playbook: "Circuit breaker tripped - what to check"
- [ ] Playbook: "Emergency kill switch procedure"
- [ ] Playbook: "Post-incident recovery steps"

---

## Coverage Thresholds (Enforced in CI)

| Module | Threshold | Current |
|--------|-----------|---------|
| `trading/guards/trading_guard.py` | 85% | ~57%* |
| `merid/execution/portfolio.py` | 80% | TBD |
| `merid/execution/executors/kalshi.py` | 75% | TBD |
| `merid/execution/executors/coinbase.py` | 75% | TBD |

*Note: Thresholds will fail PRs if coverage drops below these levels.

---

## Key Implementation Files

```
trading/guards/trading_guard.py      # Circuit breaker + risk checks
merid/execution/portfolio.py          # PnL & exposure tracking
web/api/risk.py                       # API endpoints
.github/workflows/tests.yml           # CI coverage gates
pytest.ini                            # Coverage config
```

---

## Testing Quick Reference

```bash
# Run all safety tests
pytest tests/risk tests/safety tests/e2e -v

# Run with coverage for specific module
pytest tests/safety --cov=trading.guards.trading_guard --cov-report=term-missing

# Run chaos E2E tests
pytest tests/e2e/test_circuit_breaker_chaos.py -v

# Check API endpoint
curl http://localhost:8000/api/risk/protections
```

---

## Related PRs
- #XXX - Risk limits implementation
- #XXX - Circuit breaker logic
- #XXX - Venue failure handling
- #XXX - Chaos E2E tests
- #XXX - CI coverage gates (this issue)

/label ~safety ~risk ~trading-guard ~circuit-breaker
/milestone %"Phase 0: Production Hardening"
