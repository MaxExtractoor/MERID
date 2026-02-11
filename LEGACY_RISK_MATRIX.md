# Legacy Risk Matrix

## Domain 1: Trading Execution

Known risk zones and quarantine lists for the MERID platform.

### Quarantine Categories

- **iocp_hang**: Windows IOCP event loop hangs under high async load
- **redis_dependent**: Tests requiring Redis connection
- **contracts_broken**: Broken API contracts from refactoring

### CI Coverage Gate

All dev swarm tests must pass with:
```
pytest tests/test_dev_swarm.py --cov-fail-under=90
```

### Coverage Snapshot

| Domain | Coverage |
|--------|----------|
| **Dev Swarm Domain Combined** | **92.5%** |
| Core modules | 91.0% |
| API routes | 94.0% |

## Domain 2: Risk Controls

Risk control modules with strict coverage requirements.

## Domain 3: Agent Coordination

Agent coordination and consensus modules.
