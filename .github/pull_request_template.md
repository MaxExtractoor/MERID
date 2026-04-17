## What does this PR do?

<!-- Brief description of the change. Link to issue/ticket if applicable. -->

## Type of change

- [ ] Bug fix
- [ ] New feature / view / component
- [ ] Refactor / cleanup
- [ ] Documentation
- [ ] CI / tooling

## Frontend checklist

> Required for any PR touching `web/react/`.

- [ ] `npm run type-check:ci` passes (0 new TS errors vs baseline)
- [ ] Any new API response shapes live in `src/types/api.ts` — no ad-hoc `Record<string, unknown>`
- [ ] `npm test` shows no new failing tests
- [ ] No new `any` types without a justifying comment
- [ ] No new `@ts-ignore` without a justifying comment

> If this PR **fixes** legacy type errors, run `npm run type-check:save` and commit the updated `.tsc-baseline.json`.

## Backend checklist

> Required for any PR touching `merid/`, `web/api/`, or `tests/`.

- [ ] `make audit-fixes-test` passes
- [ ] No new `print()` — use `logger.*` instead
- [ ] No new `datetime.utcnow()` — use `datetime.now(timezone.utc)`
- [ ] No new bare `except: pass` — log with `logger.debug`
- [ ] No new `# type: ignore` without a justifying comment

## Production readiness checklist

> **Required** for any PR touching `execution/`, `trading/`, `merid/execution/`, `core/kill_switches*`, `trading/trade_mode.py`, `trading/guards/`, `merid/risk/`, or `web/api/operator_*`.
> Skip this section if none of those paths are modified.

- [ ] Kill-switch path verified — no new code path bypasses `check_execution_gate()` or `set_trade_mode()`
- [ ] Mode integrity preserved — no LIVE execution possible without `MERID_ALLOW_LIVE_TRADES=true`
- [ ] Risk limits unchanged, or change is explicitly reviewed and documented in this PR
- [ ] Rollback path documented (what to revert if this breaks in prod)
- [ ] `tests/trading/guards/` or equivalent tests added/updated for any new execution path

## Screenshots / recordings

<!-- If UI changed, paste before/after screenshots here. -->

## Notes for reviewers

<!-- Anything reviewers should pay special attention to. -->
