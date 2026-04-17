## MERID Module Boundaries (Canonical vs Legacy)

This document captures the **current, enforced module boundaries** that address the duplication issues called out in `DUPLICATES_COLLISIONS_REPORT.md`.

- **Canonical prediction-market stack**
  - **Canonical packages**: `merid.event_venues.kalshi.*`, `merid.prediction.*`, `merid.reconciliation.*`, `merid.resilience.*`, `merid.settings`.
  - **Legacy/compat packages**: `trading.*`, `web.api.kalshi_*`, `trading.integrations.kalshi_client`.
  - **Rule**: New code that touches prediction markets, Kalshi, or reconciliation **must import from `merid.*`**, not from `trading.*` or legacy web API helpers.

- **Settings and configuration**
  - **Canonical**: `merid.settings.Settings` (Pydantic-based env loader).
  - **Compat shim**: `config.settings` (small dataclass wrapper with `DeprecationWarning`).
  - **Rule**: New code must use `from merid.settings import settings` (or `Settings`), not `config.settings` or `core.settings` for environment flags.

- **Risk, reconciliation, and kill switches**
  - **Canonical risk controls**: `merid.prediction.risk`, `merid.risk.kill_switches`, `merid.reconciliation` package.
  - **Legacy**: `trading.reconciliation` (paper-ledger-only checks).
  - **Rule**: Venue reconciliation and execution gating must go through `merid.reconciliation` and `merid.risk.kill_switches`, not standalone reconciliation modules.

- **Circuit breakers and resilience**
  - **Canonical**: `merid.resilience.circuit_breaker` (used by Kalshi client, metrics, and system observability).
  - **Legacy/scope-local**: `hardening.circuit_breaker`, `web.middleware.circuit_breaker` (left in place for backwards compatibility).
  - **Rule**: New circuit-breaker usage in trading or venue clients must import from `merid.resilience.circuit_breaker`.

- **Agent registries and stores**
  - **Canonical singletons**:
    - `agents.agent_framework.get_agent_registry`
    - `core.consensus_store.get_consensus_store`
    - `core.notifications.get_notification_store`
  - **Web API wrappers**: `web.api.missing_endpoints.get_agent_registry/get_consensus_store/get_notification_store` (lazy-import shims only).
  - **Rule**: Core logic should call the canonical singleton functions; web/API layers may use the shims for lazy imports only.

- **Archived/legacy scripts**
  - **Archived**: `archive/legacy_scripts/` (no `__init__.py`, intentionally not importable as a package).
  - **Rule**: No production code may import from `archive.legacy_scripts.*`. If a script is still needed, promote it into `tools/` or `scripts/` under the `merid.*` boundary.

