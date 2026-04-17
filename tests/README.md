# MERID Test Suite

## Kalshi Targeted Tests

The supported smoke test for Kalshi functionality is the trio command below:

```bash
py -m pytest tests/test_kalshi_signals.py \
             tests/web/test_kalshi_signals_api.py \
             tests/prediction/test_consensus_kalshi.py \
             --override-ini "addopts="
```

This command:
- Runs the 3 core Kalshi test files
- Uses local stubs to isolate from production dependencies
- Bypasses pytest.ini coverage options that cause plugin conflicts
- Returns: 20 passed, 10 skipped

## Full Test Suite Status

**Current state**: Full `py -m pytest` requires fixes for:
- `pytest.ini` addopts coverage options causing plugin recognition issues
- 301 collection errors from missing imports (Redis, Neo4j, external services)
- Service dependency stubs needed for unit-level isolation

**When running full suite**: Use `--override-ini "addopts="` to bypass coverage conflicts.

## Test Categories

- **Kalshi Core**: Signal generation, API contracts, consensus logic
- **Trading**: Adapters, agents, execution, paper trading
- **Web**: API endpoints, dashboard, institutional features
- **Integration**: Requires external services (Redis, Neo4j, exchanges)

## Development Workflow

1. Run Kalshi trio as reliable regression test
2. Use `--override-ini "addopts="` for broader runs during development
3. Full suite normalization is a separate infra task