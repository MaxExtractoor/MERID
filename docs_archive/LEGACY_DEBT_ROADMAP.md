# MERID Legacy Debt Roadmap - Section 14

> **Mission**: Phase out legacy debt through wrap-and-extend, not rewrite. Track what needs wrapping, deprecation timelines, and migration paths.

---

## Overview

This document tracks legacy components and their modernization path. Every item follows the principle: **wrap first, replace later**.

---

## 1. Immediate Wrapping (Month 1-2)

### 1.1 Exchange Adapters
| Adapter | Status | Wrapper | Notes |
|---------|--------|---------|-------|
| kraken_adapter.py | ✅ Wrapped | VenueWrapper | Circuit breaker added |
| coinbase_advanced_adapter.py | ✅ Wrapped | VenueWrapper | Rate limiting added |
| binanceus_adapter.py | ✅ Wrapped | VenueWrapper | - |
| gemini_adapter.py | ✅ Wrapped | VenueWrapper | - |
| alpaca_adapter.py | ✅ Wrapped | VenueWrapper | - |
| ibkr_adapter.py | 🔄 In Progress | VenueWrapper | Complex API |
| okx_adapter.py | ⏳ Pending | VenueWrapper | Non-US, paper only |

**Action Items:**
- [ ] Complete IBKR adapter wrapping with proper error handling
- [ ] Add US-compliance checks to all adapter wrappers
- [ ] Document rate limits per venue in `VENUE_RATE_LIMITS.md`

### 1.2 Schema Validation
| Component | Status | Notes |
|-----------|--------|-------|
| Kafka topic producers | ✅ Done | SchemaRegistry validates all |
| Agent outputs | ✅ Done | OutputValidator enforces JSON schemas |
| API responses | 🔄 In Progress | Add Pydantic validation |
| WebSocket messages | ⏳ Pending | Need schema enforcement |

**Action Items:**
- [ ] Add schema validation to all WebSocket message handlers
- [ ] Create schema migration tool for topic evolution
- [ ] Set up schema registry backup and versioning

### 1.3 Output Validator
| Feature | Status | Notes |
|---------|--------|-------|
| JSON parsing | ✅ Done | Handles markdown code blocks |
| Schema validation | ✅ Done | Uses jsonschema library |
| Forbidden patterns | ✅ Done | Blocks injection attempts |
| Safe mode | ✅ Done | Auto-triggers after failures |
| Audit logging | ✅ Done | All validations logged |

---

## 2. Stabilization (Month 2-3)

### 2.1 Replay Tooling
| Component | Status | Priority |
|-----------|--------|----------|
| ReplayHarness | ✅ Done | High |
| Event fetcher (S3) | ⏳ Pending | High |
| Decision comparison | ✅ Done | High |
| Drift detection | ✅ Done | Medium |
| Golden test runner | ✅ Done | Medium |

**Action Items:**
- [ ] Implement S3 event source for replay
- [ ] Create RUNBOOK_REPLAY.md with step-by-step instructions
- [ ] Set up weekly replay tests on last 7 days of data
- [ ] Configure drift alerting thresholds

### 2.2 Integration Tests
| Test Suite | Coverage | Target |
|------------|----------|--------|
| Adapter tests | 65% | 80% |
| Consensus tests | 70% | 85% |
| Risk guard tests | 80% | 90% |
| Output validator | 85% | 95% |

**Action Items:**
- [ ] Add integration tests for full trade flow
- [ ] Create mock venues for deterministic testing
- [ ] Set up CI to block merge on coverage drop

### 2.3 Consensus Engine
| Feature | Status | Notes |
|---------|--------|-------|
| Quorum voting | ✅ Done | Configurable threshold |
| Veto handling | ✅ Done | Risk agent can veto |
| Timeout handling | ✅ Done | Safe default on timeout |
| Agent heartbeats | ✅ Done | Health monitoring |
| Limp mode | ✅ Done | Minimal viable swarm |

---

## 3. Deprecation Schedule (Month 3-6)

### 3.1 Deprecated Adapters
| Adapter | Deprecation Date | Replacement | Migration Guide |
|---------|-----------------|-------------|-----------------|
| *None currently* | - | - | - |

### 3.2 Deprecated Topics
| Topic | Deprecation Date | Replacement | Notes |
|-------|-----------------|-------------|-------|
| *None currently* | - | - | - |

### 3.3 Legacy Field Names
| Field | Location | Replacement | Status |
|-------|----------|-------------|--------|
| `ccxt_order_id` | Adapter responses | `order_id` | 🔄 Migrating |
| `raw_response` | API responses | Remove | ⏳ Pending |
| `_legacy_*` | Various | Remove prefix | ⏳ Pending |

**Action Items:**
- [ ] Audit all adapter responses for vendor-specific fields
- [ ] Create field mapping for normalization
- [ ] Add deprecation warnings for legacy field access
- [ ] Set removal dates and communicate to dependents

---

## 4. Architecture Decisions Log

### Decision 1: Wrap, Don't Replace Adapters
- **Date**: 2026-02-05
- **Decision**: Wrap legacy CCXT adapters behind VenueWrapper instead of rewriting
- **Rationale**: Preserves working exchange connectivity, adds resilience layer
- **Status**: Implemented

### Decision 2: Schema Validation at Producer
- **Date**: 2026-02-05
- **Decision**: Validate schemas at Kafka producer, not consumer
- **Rationale**: Prevents invalid data from entering the system
- **Status**: Implemented

### Decision 3: Consensus with Safe Defaults
- **Date**: 2026-02-05
- **Decision**: On consensus failure/timeout, default to "no action" not "close positions"
- **Rationale**: Conservative approach minimizes unexpected losses
- **Status**: Implemented

### Decision 4: Agents Never Access Secrets
- **Date**: 2026-02-05
- **Decision**: LLM agents can USE secrets through governed APIs but never SEE values
- **Rationale**: Prevents credential leakage through prompt injection
- **Status**: Implemented

---

## 5. Component Inventory

### 5.1 Wrapped Components (Stable Interface)
```
core/venue_wrapper.py          - VenueWrapper with circuit breaker
schemas/events.py              - Canonical event schemas
schemas/validator.py           - Schema validation
agents/manifest.py             - Agent role definitions
agents/output_validator.py     - LLM output validation
consensus/consensus_coordinator.py - Enhanced consensus
risk/risk_guard.py             - Global risk limits
security/secrets_manager.py    - Secret management
testing/replay_harness.py      - Replay testing
data/ingestion/data_ingestion.py - Data source framework
bots/bot_integration.py        - Telegram/Twitter bots
core/reuse_guardrails.py       - Non-reinvention checks
```

### 5.2 Legacy Components (To Be Wrapped)
```
trading/agents/execution_agent.py - Needs OutputValidator integration
core/venues/*.py                  - Individual adapters need VenueWrapper
streaming/*.py                    - Need schema validation
```

### 5.3 New Components (Post-Checklist)
```
web/react/src/components/charts/AgentOpinionChart.tsx
web/react/src/components/charts/MarketHeatmap.tsx
```

---

## 6. Metrics & Tracking

### 6.1 Wrapping Progress
- **Adapters wrapped**: 7/14 (50%)
- **Topics with schemas**: 20/25 (80%)
- **Tests with >80% coverage**: 4/8 (50%)

### 6.2 Quality Metrics
- **Schema validation rate**: 100% of producers
- **Replay test coverage**: 0% (pending S3 source)
- **Agent output compliance**: 100%

### 6.3 Technical Debt Score
| Category | Score | Target |
|----------|-------|--------|
| Adapters | 6/10 | 8/10 |
| Schemas | 8/10 | 9/10 |
| Testing | 5/10 | 8/10 |
| Documentation | 7/10 | 9/10 |
| **Overall** | **6.5/10** | **8.5/10** |

---

## 7. Next Steps

### Immediate (This Week)
1. Complete integration tests for sections 1-7
2. Set up S3 event source for replay
3. Document all API endpoints in OpenAPI spec

### Short-term (This Month)
1. Wrap remaining exchange adapters
2. Add schema validation to WebSocket handlers
3. Set up weekly replay testing

### Medium-term (Next Quarter)
1. Migrate legacy field names to normalized versions
2. Achieve 80% test coverage across all modules
3. Complete bot integrations (Telegram, Twitter)

---

## 8. Contacts & Ownership

| Component | Owner | Backup |
|-----------|-------|--------|
| Venue Adapters | TBD | TBD |
| Consensus Engine | TBD | TBD |
| Risk System | TBD | TBD |
| UI/Dashboard | TBD | TBD |

---

*Last Updated: 2026-02-05*
*Next Review: 2026-02-12*
