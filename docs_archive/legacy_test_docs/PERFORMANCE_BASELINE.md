# Dev Swarm Test Performance Baseline

**Captured:** 2026-02-06 (updated after speed optimizations)  
**Total tests:** 290 (273 in test_dev_swarm.py + 17 in test_dev_swarm_xdist_invariants.py)  
**Total time:** 63.20s (1m 03s)  
**Platform:** Windows 10, Python 3.11.9, pytest 8.3.4

## Speed Optimizations Applied

| Test | Before | After | Technique |
|------|--------|-------|-----------|
| `TestShutdown::test_shutdown_with_active_tasks` | 60.01s | ~0.1s | Patched `asyncio.wait_for` timeout from 60s to 0.1s |
| `TestTaskLifecycle::test_task_cancellation` | 10.02s | ~2s | Reduced mock pipeline sleep from 10s to 2s |
| **Total suite** | **124.25s** | **63.20s** | **49% reduction** |

## Current Top Slowest Tests

| Rank | Duration | Test | Category |
|------|----------|------|----------|
| 1 | ~9.5s | `TestIntegration::test_multi_agent_pipeline` | Integration |
| 2 | ~9.5s | `TestAPIRoutes::test_create_and_get_task` | API |
| 3 | ~9.4s | `TestAPIRoutes::test_create_task` | API |
| 4 | ~6.6s | `TestReadinessAuditor::test_cli_entrypoint_exit_zero` | CLI |
| 5 | ~6.5s | `TestHistoricalCommitmentsAuditor::test_cli_entrypoint_exit_code` | CLI |
| 6 | ~2s | `TestTaskLifecycle::test_task_cancellation` | Lifecycle |
| 7 | ~1s | `TestAgentPhaseErrors::test_agent_phase_timeout` | Error |

## Marked subset: `devswarm or auditor`

| Tests | Time |
|-------|------|
| 40+ | ~8s |

All marked tests complete in ≤0.01s each. Overhead is fixture setup only.

## Notes

- CLI entrypoint tests (ranks 4-5) spawn subprocesses, adding ~13s combined.
- All behavior, load, and benchmark tests are sub-second.
- Regression threshold recommendation: flag if total exceeds **90s** or any single test exceeds **30s**.
