# Production Data Guard Contract

**Last Updated:** 2026-05-14  
**Scope:** BTC/ETH/SOL/XRP/DOGE 15-minute Kalshi contracts

## Overview

This document defines the production data guard contract that all features, agents, venues, and data sources must satisfy to be eligible for production deployment in the 15m Kalshi crypto stack.

## Guard Infrastructure

### Startup Guards
- `validate_production_wiring()` - Ensures no fake/mock Kalshi modules loaded in production
- `validate_env_for_live_mode()` - Blocks production if DRY_RUN, research agents, or fake data enabled
- `validate_all()` - Orchestrates all startup validations

### Bootstrap Guards
- Type assertions against `CanonicalAgentRegistry` in `bootstrap_canonical_agents()`
- Prevents mock/fake registries from entering production

### Execution Guards
- Market ID validation against live `KalshiMarketCatalog` in `_kalshi_place_order()`
- DRY_RUN mode with noop execution backend and structured logging
- ILLEGAL_MARKET_ID error for orders against non-catalog markets

### CI Guards
- `production-data-guards.yml` - Static analysis for mock imports, fake tickers, production wiring
- `dry-run-smoke-test.yml` - DRY_RUN smoke test with mocked Kalshi catalog

### Logging Guards
- Structured JSON logs: `CANONICAL_REGISTRY_SUMMARY`, `WOULD_EXECUTE_ORDER`
- Fields: env, dry_run, assets, venues, tenors, agent_name, market_ticker

## Contract Requirements

### For New Agents
1. Add domain metadata (assets, venues, tenors) as class attributes
2. Register in canonical registry via `bootstrap_canonical_agents()`
3. Pass `validate_production_wiring()` type assertions
4. Include agent in DRY_RUN smoke test assertions

### For Catalog/Data Sources
1. Use `build_kalshi_catalog()` for all catalog instantiation (shared builder)
2. No direct Kalshi API calls outside `KalshiMarketCatalog` or `KalshiClient`
3. All market identifiers must come from `KalshiMarketCatalog.get_all_markets()`
4. Pass CI check for single catalog path enforcement

### For Execution Logic
1. All orders must pass market ID validation against live catalog
2. DRY_RUN mode must log structured JSON without side effects
3. No hardcoded tickers or fake market identifiers
4. Pass CI check for no fake tickers in production code

### For Legacy Code
1. Mark with `IS_LEGACY_MODULE = True` and header comment
2. Gate behind `MERID_ENABLE_RESEARCH_AGENTS` feature flag
3. Place under `legacy/` directory
4. Not imported from production packages (CI enforced)

## Validation Checklist

Before merging any feature that affects agents, catalog, or Kalshi wiring:

- [ ] All production guard tests pass (CI green)
- [ ] DRY_RUN smoke test passes with new changes
- [ ] `CANONICAL_REGISTRY_SUMMARY` log includes new agent with correct domain metadata
- [ ] No new imports from `tests/` or `mocks/` in production packages
- [ ] No new fake tickers (FAKE_BTC, TEST_MARKET, etc.) in production code
- [ ] If applicable, add/update DRY_RUN assertion for new registry/execution behavior

## Sentry Queries (Post-Deploy)

### Registry Sanity
```
Filter: CANONICAL_REGISTRY_SUMMARY where env="production" and dry_run=false
Checks:
- composition.legacy_agents == 0
- composition.kalshi_crypto_15m_agents >= 1
- domains.assets ⊆ {BTC,ETH,SOL,XRP,DOGE}
- domains.venues ⊆ {KALSHI}
- domains.tenors ⊆ {15m}
```

### Execution Sanity
```
Filter: WOULD_EXECUTE_ORDER or execution logs where env="production"
Checks:
- All ticker values exist in current catalog snapshot
- All asset ∈ {BTC,ETH,SOL,XRP,DOGE}
- All tenors = "15m"
- No ILLEGAL_MARKET_ID errors
```

## Enforcement

- CI automatically blocks violations of static checks
- Startup validation blocks deployment if dynamic checks fail
- Execution guards block orders against invalid markets
- Structured logging enables post-deploy audit and monitoring

## Contact

For questions about this contract or to request exceptions, consult the MERID architecture team.
