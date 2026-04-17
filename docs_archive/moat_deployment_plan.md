# Phase 23 – MERID Moat Deployment Plan

_Status: Draft v0.1 (2026-01-15)_

This document captures the tasks required to operationalize the Moat Orchestrator and expose moat metrics/controls to operators.

---

## 1. Objectives

1. Run the Moat Orchestrator on a scheduled cadence (measure pillar strength, detect erosion risks, recommend actions).
2. Expose Moat status and measurement endpoints for operators and bots.
3. Integrate with telemetry (event stream + health monitor) so moat health is observable.
4. Provide controls to trigger manual re-measurement and submit new moat-aware feature proposals.

---

## 2. Components

- `moat/moat_orchestrator.py`: existing logic with measurement + validation.
- **NEW** `moat/moat_runtime.py`: async runtime managing periodic measurements and event publishing.
- `web/api/moat.py`: FastAPI router for status + controls.
- Telemetry: `social.social_aware_quant` health monitor + `event_stream` topics `moat_measurement`, `moat_risk`.
- Tests: `tests/test_moat_api.py`.

---

## 3. Deployment Steps

1. **Runtime Service**
   - Encapsulate a background loop similar to Swarm Lab.
   - On each cycle: `measure_moat_strength`, `detect_erosion_risks`, publish events.
   - Register component with health monitor and emit heartbeat metadata.

2. **API Surface**
   - `/moat/status`: live metrics + recent erosion risks.
   - `/moat/measure`: trigger immediate measurement.
   - `/moat/proposals`: submit/inspect feature proposals.
   - auth via internal service token (reuse `_require_service_token`).

3. **Telemetry + Docs**
   - Document event payloads.
   - Ensure TODO/master roadmap updated after deployment.

4. **Tests**
   - Validate API endpoints + orchestrator hooks with FastAPI TestClient.
   - Unit tests for runtime measurement cycle (mock orchestrator).

---

## 4. Operator Playbook

- Start runtime via `/moat/start` (if manual control needed) or include in system bootstrap.
- Monitor `/moat/status` for advantage ratios + erosion risks.
- Submit feature proposals via `/moat/proposals` to confirm new work respects moat.

---

## 5. Next Actions

1. Implement `MoatRuntimeService` (start/stop/cycle).
2. Add `/moat/*` API endpoints with auth + responses.
3. Integrate health monitor + telemetry events.
4. Add regression tests and update master checklist.
