# MERID Architecture Overview

Components:

- `web/` - FastAPI app exposing the HTTP server, SSE endpoint, admin endpoints, and metrics.
- `core/` - Orchestrator and small helpers used to create `energy` objects and run cycles.
- `trading/` - Execution and risk checks (place/cancel/modify orders, circuit breaker, pre-trade checks).
- `db/` - In-memory stores used for development tests (`order_store`, `audit_store`).
- `background/` - Simple background queue to offload synchronous work from the event loop.
- `simulations/` - E2E and other harnesses for automated testing and behavior validation.
- `generated/schemas/` - Committed JSON schema artifacts exported from Pydantic models used by front-end type generation.

Key design points:

- Test-first and TDD approach: each subsystem has focused unit tests and the CI run collects them.
- Safety-first: operator lockdown, audit logs, and a basic circuit breaker protect execution flows.
- Incremental productionization: in-memory stores are intentionally simple to make tests deterministic. Replace with durable stores for production.

Observability & DevTools:

- A small in-process `web/metrics.py` offers counters/gauges/summaries and a `/metrics` text endpoint for scraping.
- CI validates schema artifacts and runs Flutter tests.

Deployment:

- `Dockerfile` and `docker-compose.yml` provide a minimal local deployment story.
- A `docker-build` job in CI builds the image (no push by default).
