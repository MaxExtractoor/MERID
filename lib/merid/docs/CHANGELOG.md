# Changelog

All notable changes to this project will be documented in this file.

## Unreleased

### Added

- (placeholder for future changes)

## v0.1.0 (2026-01-31)

### Added

- Core orchestrator stub with SSE streaming (`core/orchestrator.py`) and tests.
- Trading & Risk engine (`trading/*`) with pre-trade checks, circuit breaker and execution logic.
- Admin lockdown endpoints and token-based admin auth (`web/admin.py`, `web/auth.py`).
- Background Job Queue (`background/queue.py`) with tests and instrumentation.
- In-process metrics with `/metrics` endpoint and instrumentation for background queue (`web/metrics.py`).
- Schema sharing & validation using Pydantic models (`web/schemas.py`) and exported JSON schema artifacts (`generated/schemas/`).
- CI workflows: lint, pytest, Flutter tests, Docker image build, E2E smoke, nightly E2E, and failure alerting via issue creation.
- E2E simulation harness and runner (`simulations/e2e.py`, `scripts/run_e2e.py`) with CI checks.
- Audit logging (in-memory and optional file-backed persistence) with admin audit endpoints (`db/audit_store.py`, `db/audit_backend.py`, `web/admin.py`).
- Deployment scaffolding: `Dockerfile`, `docker-compose.yml`, `Makefile`.
- Flutter frontend safety UX improvements (lockdown integration with backend) and widget tests.
- Documentation: `docs/` (Usage, Architecture, Contributing) and release helpers.

### Fixed

- Pydantic v2 compatibility: migrated to `model_validate` usage and exported compatible JSON schemas.
- Hardened SSE validation and template signature deprecation fixes.
- Various test stability fixes and CI improvements.

### Tests

- Comprehensive test coverage for all components (unit and integration tests).
