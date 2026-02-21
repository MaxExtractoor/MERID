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

## Screenshots / recordings

<!-- If UI changed, paste before/after screenshots here. -->

## Notes for reviewers

<!-- Anything reviewers should pay special attention to. -->
