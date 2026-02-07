# MERID Placeholder & Stub Inventory

This document enumerates intentional placeholders, stubs, simulated behavior, and test-only artifacts discovered during a repo-wide audit. For each item, I note the location, why it exists, risk/impact, and a recommended remediation with priority.

## High-priority placeholders (should be replaced before real money)

- `trading/execution.py` — "Simulate immediate acceptance and fill (replace with real adapter later)"
  - Risk: In production, this would not execute real trades and could hide integration issues. The simulation bypasses exchange adapters and connectivity checks.
  - Recommendation: Implement an Exchange Adapter interface and add a default 'noop' adapter for dev; write integration tests that exercise a mock exchange client and a separate integration that exercises a live testnet adapter (behind a feature flag). Priority: High.

- `core/orchestrator.py` — lightweight orchestrator stub
  - Risk: Orchestration logic for strategies, scheduling, and state transitions is a stub; missing features could lead to incorrect production behavior.
  - Recommendation: Design and implement a robust orchestrator (or replace stub with the planned real implementation). Add contract tests that validate expected orchestration messages and state transitions. Priority: High.

- `db/neo4j.py` — stub neo4j storage
  - Risk: Persistence/backing store is a test stub; production needs durable, tested storage (Neo4j or Postgres/other) with migration and backup plans.
  - Recommendation: Implement a production-backed persistence layer with config-driven connection and documented migration/backup. Priority: High/Medium.

## Medium-priority placeholders (should have follow-ups soon)

- `web/static/` and `web/index.html` placeholders
  - Risk: UI static assets are placeholders; acceptable for backend-only releases but must be addressed before public-facing launches.
  - Recommendation: Add real frontend assets or a minimised static UI; ensure CI builds produce reproducible artifacts. Priority: Medium.

- `merid_trading.py`, `merid_core.py`, `merid_web.py` — compatibility shims and placeholders
  - Risk: These shims help testing and imports but could hide missing API compatibility guarantees.
  - Recommendation: Maintain clear separation: shims for compatibility in tests only; ensure production packaging and module resolution loads real modules. Add import-time checks and CI smoke tests. Priority: Medium.

## Low-priority or expected placeholders

- Test-only placeholders (e.g., `simulations/e2e.py` uses deterministic seeded RNG, `web/static/README.md`) — acceptable but should be documented as test-only.
- Vendor TODOs and stub warnings inside `.venv` packages — expected and fine.

---

## Next steps I recommend

1. Add an issue/PR per High-priority item with an implementation plan and tests. (I can create these PRs iteratively.)
2. Add integration tests that exercise real adapters (feature-flagged, run in CI staging with testnet credentials).
3. Track any remaining placeholders as documented tech debt in the release epic.

---

I can open follow-up PRs for each high-priority item in order: Exchange Adapter + integration tests, Orchestrator implementation, DB persistence work. Which should I start with next?