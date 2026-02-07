# MERID Security + Trading-Risk v1 Audit Hardening

## Overview
Epic to track the work needed to harden MERID for v1 live trading with real capital. This documents the risk policy, blockers (must-fix before real money), should-have, and nice-to-have items.

**Assigned**: GitHub Copilot
**Status**: In Progress (first blocker assigned and marked In Progress)

---

## Concrete v1 Risk Policy
Assumptions: initial AUM range = $10k–$100k; target venue = Alpaca (spot equities).

Numeric guardrails:
- **Max daily loss**: 2% AUM (hard-stop)
- **Max per-order notional**: 1% AUM
- **Per-symbol cap**: 5% AUM
- **Max leverage**: 2×
- **Max open orders per portfolio**: as configured (default 25)

Enforcement model:
- Synchronous pre-trade checks (per-order): reject any order that violates numerical guardrails.
- Global protections: distributed Circuit Breaker and server lockdown with auditing and alerts.
- Alerts: fire at 50% of daily loss threshold and at any hard-stop trigger.

---

## Blockers before real money (Checklist)
- [x] **Wire autonomy_store → pre_trade_check and remove default account** (In Progress, assigned to GitHub Copilot)
  - Acceptance criteria:
    - `pre_trade_check` consults portfolio limits (daily loss, per-symbol cap, max open orders)
    - `place_order` requires explicit `account` or `portfolio_id`; do not use the hard-coded 1_000_000 default in prod (allow dev override via `DEV_ALLOW_DEFAULT_ACCOUNT=true`)
    - New unit tests: daily loss breach is blocked; per-symbol and open-orders caps enforced
- [ ] Make CircuitBreaker & Lockdown distributed and auditable (Redis-backed with audit entries)
- [ ] Secrets & CI hardening (detect-secrets blocking job; prefer KMS-backed signing instead of raw private keys in secrets)

---

## Should-have soon
- [ ] Integrate `autonomy_store.json` into runtime configuration and admin UI (allow safe edits)
- [ ] Add alerting/metrics for 50%/75% daily loss and CircuitBreaker trip
- [ ] Add per-venue slippage and rate limits

## Nice-to-have
- [ ] Stress test harness (Monte Carlo replays, latency injection, exchange outage simulation)
- [ ] Make exchange clients and time provider fully mockable for scenario testing
- [ ] Signed SBOM and artifact claims verification in release pipeline

---

## Notes
- Follow-up PRs should reference this file and the epic title in their description.
- When PRs are opened, add links here under the relevant checklist item and move the status accordingly.
