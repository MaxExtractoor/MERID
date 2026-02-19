# Phase 2/3 Hardening Tickets

**Baseline:** Commit `c25d2702` - Kalshi WS Bridge + Explainability Integration

## Overview

This directory contains detailed specifications for Phase 2/3 hardening work following the Phase 1 foundation implementation of Kalshi WebSocket bridge, explainability API, and trading agent integration.

## Phase 2: Production Resilience (High Priority)

### 1. [WS Resilience Tests](./phase2-ws-resilience-tests.md)
Test disconnect/reconnect with exponential backoff, sequence gap recovery, and malformed message handling for Kalshi orderbook WebSocket ingestion.

**Key Requirements:**
- Exponential backoff respects Kalshi rate-limit tiers
- Sequence gaps trigger REST snapshot refresh
- Malformed messages dropped without crash

**Test File:** `tests/event_venues/kalshi/test_ws_resilience.py`

---

### 2. [Rate-Limit Enforcement Tests](./phase2-rate-limit-enforcement-tests.md)
Validate 429 response handling, self-throttling, and proper rejection of non-retryable 4xx errors.

**Key Requirements:**
- Honor `Retry-After` headers on 429 responses
- Self-throttle to stay within tier limits (Basic: 20 read/10 write per sec)
- Never retry 400/401/403 errors

**Test File:** `tests/event_venues/kalshi/test_rate_limits.py`

---

### 3. [Risk Rejection Explainability Tests](./phase2-risk-rejection-explainability-tests.md)
Verify all risk rejection scenarios emit complete explainability records with rule IDs, thresholds, and human-readable reasoning.

**Key Requirements:**
- Exposure cap blocks include current exposure and threshold
- Daily loss limit blocks capture P&L state
- Swarm health blocks include degraded component details

**Test File:** `tests/prediction/test_trading_agent_explainability.py`

---

### 4. [Swarm Health Gating Integration](./phase2-swarm-health-gating.md)
Integrate swarm health checks into trading decisions and dashboard APIs to enforce 100% health requirement.

**Key Requirements:**
- Trading agent blocks orders when health < 100%
- Dashboard APIs surface health warnings or block output
- Explainability records capture health state

**Test File:** `tests/integration/test_swarm_health_gating.py`

---

## Phase 3: Stress & End-to-End Validation (Medium Priority, Gates Live)

### 5. [High-Load Stress & E2E Validation](./phase3-stress-and-e2e-validation.md)
Validate system under production-like load with concurrent agents, high-frequency decisions, and end-to-end latency targets. **This phase gates live deployment.**

**Key Requirements:**
- 10 concurrent agents @ 100 decisions/sec each
- End-to-end latency <100ms at P95
- Full Kalshi integration suite (mock/paper/live modes)
- Observability validation (logs, metrics, alerts)

**Performance Targets:**
- Decision recording P99: <10ms
- End-to-end P95: <100ms
- Memory usage delta: <500MB

**Test File:** `tests/integration/test_kalshi_e2e_stress.py`

---

## Next Steps

1. **Create GitHub Issues:** Convert each ticket to a GitHub issue, linking back to commit `c25d2702`
2. **Assign Owners:** Distribute Phase 2 tickets across team members
3. **Stage/Paper Deployment:** Deploy Phase 1 to staging/paper mode for validation
4. **Monitor Metrics:** Track WS reconnect frequency, decision latency, orderbook freshness
5. **Phase 3 Sign-off Required:** Complete Phase 3 validation before live deployment

## References

- [Kalshi API Documentation](https://docs.kalshi.com)
- [Kalshi Rate Limits](https://docs.kalshi.com/getting_started/rate_limits)
- [Kalshi WebSocket Guide](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [Kalshi Orderbook Schema](https://docs.kalshi.com/getting_started/orderbook_responses)
