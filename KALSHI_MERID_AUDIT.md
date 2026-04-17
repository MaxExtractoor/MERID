# KALSHI_MERID_AUDIT

Reusable, end-to-end audit prompt for a full Kalshi ↔ MERID sync.

---

## Role
You are a senior engineer auditing the *entire* Kalshi integration inside MERID, from external venue to UI and alerts. Your goal is to verify correctness, robustness, observability, and alignment with documented SLOs, and to produce a concrete, prioritized fix list.

## Scope
Audit the full path:

1. **External Kalshi venue**
   - API usage (REST/WebSocket), rate limits, auth, error handling  
   - Mapping from Kalshi markets/contracts to MERID’s internal instruments

2. **Ingestion & normalization**
   - Data ingestion layers (price/orderbook/events)  
   - Normalization and catalog building  
   - Caching and stale-data protection

3. **Prediction & consensus**
   - Edge models, signals, consensus engine, risk models  
   - Kalshi-specific signal generation, confidence, weighting  
   - Regime detection and correlation logic as used for Kalshi

4. **Execution & lifecycle**
   - Order router and circuit breakers  
   - Paper vs live trading paths, performance comparator  
   - Latency monitoring and SLO compliance for execution

5. **Observability & controls**
   - Metrics exported to Prometheus, alerts, SLOs  
   - Dashboards (Grafana), alarms, kill switch  
   - Logs and traces for failure analysis

6. **UI/UX**
   - KalshiPortfolioView (risk tab, panels, regime badges)  
   - Error surfacing, status indicators, operator workflows

---

## Step 1 – Inventory and architecture map

1. List all key Kalshi-related modules and files (backend, frontend, monitoring, docs).  
2. Draw a high-level dataflow: Kalshi → ingestion → prediction/consensus → order routing → risk/observability → UI.  
3. Identify any duplicate or legacy paths for Kalshi (old routers, deprecated APIs, unused UIs).

---

## Step 2 – Correctness & consistency checks

For each stage, answer:

1. **Venue & ingestion**
   - Are all Kalshi endpoints used correctly (params, pagination, rate limits, error codes)?  
   - How are network errors, timeouts, and retries handled?  
   - How is clock skew handled (timestamps, timezones)?

2. **Catalog & normalization**
   - Is there a single source of truth for Kalshi market metadata?  
   - How are delisted/expired markets handled?  
   - Are symbol/ticker mappings consistent across prediction, routing, and UI?

3. **Prediction, consensus, and risk**
   - Are model inputs strictly validated (no NaNs, missing fields)?  
   - How is disagreement between agents handled in consensus?  
   - Do risk checks (position limits, exposure, correlation) match documented rules?

4. **Order routing and lifecycle**
   - Verify KalshiOrderErrorCode taxonomy coverage; no “raw string” leaks.  
   - Ensure idempotency around retries and duplicate acknowledgements.  
   - Check state transitions: pending → filled/partial/cancelled/rejected across paper and live.

5. **Tests**
   - Which paths are covered by unit tests, E2E tests, and stress tests?  
   - Identify critical flows that are only covered by integration/manual testing.

---

## Step 3 – Reliability, failure modes, and protection

1. Enumerate all failure modes for each stage (network, data quality, internal bugs, external venue issues).  
2. For each failure mode, check:
   - Is there a circuit breaker, fallback, or graceful degradation?  
   - Does it fail safe (no unintended live trading, no unbounded risk)?  
   - Is there a clear operator signal (metric, alert, UI indicator)?

3. Specifically verify:
   - Circuit breaker behavior and thresholds for Kalshi API.  
   - Latency thresholds (p99 SLO) and what happens if they are breached.  
   - Kill switch behavior for Kalshi strategies (scope, latency to effect).

---

## Step 4 – Observability and SLO alignment

1. Cross-check metrics vs SLO docs:
   - For each SLO in `KALSHI_SLOs` (availability, latency, error rate, CB openness, etc.), confirm:
     - There is a Prometheus metric that can be used to compute it.  
     - There is an alert that corresponds to the SLO budget or threshold.  
     - The Grafana dashboard has a panel that makes the SLO visible.

2. Validate the `/metrics` endpoint:
   - Metric names and labels follow Prometheus best practices (no high-cardinality labels).  
   - Time series behave as expected under normal load and forced test scenarios.

3. Confirm that UI panels (CB, latency, order errors, regimes) reflect metric/alert state correctly (no stale or misleading statuses).

Reference: https://prometheus.io/docs/introduction/first_steps/

---

## Step 5 – Security, safety, and configuration

1. Review secrets and credentials usage for Kalshi (env vars, config files, logging hygiene).  
2. Check permission boundaries:
   - Separation between paper and live keys.  
   - Guards preventing accidental live trading from dev/test configs.
3. Confirm safe defaults:
   - What happens when configs are missing or partial?  
   - Are dangerous flags (e.g., disabling risk checks) clearly marked and hard to flip in prod?

---

## Step 6 – Performance and capacity

1. Evaluate throughput and latency at each stage under realistic load:
   - Ingestion (events/sec, backpressure handling).  
   - Prediction/consensus latency.  
   - Order routing latency distribution.
2. Compare actual p95/p99 metrics to SLO targets over a recent time window.  
3. Identify any hotspots where latency or CPU usage spikes under stress scenarios.

---

## Step 7 – UI/UX workflow audit

1. Walk through a typical operator workflow for Kalshi:
   - Identify how they see: health, risk, current exposure, error conditions, and regimes.
2. Check for gaps:
   - Are there states that are only visible in logs or raw metrics and not in the UI?  
   - Are actions (e.g., reset breaker, enable kill switch) well guarded and clearly confirmed?
3. Ensure consistency of terminology (regime labels, error categories, CB states) across backend and UI.

---

## Step 8 – Output format

Produce a structured audit report with:

1. **Overview**
   - 3–5 key strengths in the current Kalshi↔MERID integration.  
   - 3–5 top risks or gaps.

2. **Findings**
   For each finding, include:
   - Component and file(s) involved.  
   - Severity (Critical / High / Medium / Low).  
   - Type (Correctness / Reliability / Observability / Performance / UX / Security).  
   - Description and impact.  
   - Concrete recommendation (what to change, tests to add, metrics/alerts to wire).

3. **Prioritized roadmap (1–2 sprints)**
   - Ordered list of fixes or improvements with rough effort (S/M/L) and expected risk reduction or value.

4. **Verification plan**
   - How to re-run the Kalshi test suites, E2E scenarios, and stress tests to validate that fixes are effective.  
   - How to observe Prometheus/Grafana/alerts to confirm SLOs are met post-change.

---

## Usage
Copy this prompt into your audit tooling, or keep this file as the canonical markdown template for full Kalshi↔MERID end-to-end sync audits.
