# Pre-Deploy Checklist

> Run this before enabling a new lane/agent, flipping to live, or merging
> a structural change. Takes < 1 minute.

## Quick Pre-Flight (copy-paste)

```bash
# 1. CI structural gate — must be green
py -m pytest tests/test_ui_backend_contract.py \
             tests/test_sse_smoke.py \
             tests/test_kalshi_only_profile.py \
             tests/test_openapi_schema_sanity.py \
             -v --tb=short --timeout=30

# 2. Contract health endpoint — verify route/SSE counts haven't regressed
curl -s http://localhost:8011/api/v1/system/contract-health | python -m json.tool

# 3. Feature flags — confirm expected state
curl -s http://localhost:8011/api/v1/system/feature-flags | python -m json.tool
```

## Detailed Checklist

### CI Gates

- [ ] `backend-structural-checks` job is **green** on the target branch.
- [ ] No new entries added to `WHITELIST` in `test_ui_backend_contract.py`
      without a justification comment.
- [ ] OpenAPI schema sanity tests pass (min path count, core operations).

### Operator Dashboard

- [ ] **ContractHealthPanel** shows all four badges green:
  - UI↔API Contract: OK
  - SSE Wiring: OK
  - Profile: `kalshi-only` (or expected profile)
  - Overall: HEALTHY
- [ ] Feature flags show expected states (no accidental overrides from
      previous debugging sessions).

### Runtime Signals

- [ ] No recent spike in `/api/v1` 404s (check Grafana `contract-health`
      dashboard or grep logs for `possible_contract_violation`).
- [ ] No SSE endpoint count regression (compare against previous deploy).
- [ ] API route count has not decreased unexpectedly.

### Feature Flags (for behavioral changes)

- [ ] New risky behavior is behind a feature flag (see `FEATURE_FLAG_PLAYBOOK.md`).
- [ ] Flag is documented in the playbook with flip-off criteria.
- [ ] Flag defaults to **ON** unless there's a reason for opt-in.

### Profile Integrity

- [ ] If adding a new router, verified it works in both `full` and
      `kalshi-only` profiles (or is correctly gated).
- [ ] Stub/mock routers are not silently promoted to real APIs without
      removing `_stub: True` metadata.

### Background Work

- [ ] Any new long-running endpoint follows a pattern from
      `BACKGROUND_WORK_PATTERNS.md` (Pattern 1 or 2).
- [ ] Background callbacks have explicit error logging.

## When to Run

| Trigger | Required? |
|---------|-----------|
| Merging to `main` | Yes — CI runs automatically |
| Enabling a new trading lane / agent | Yes — full manual checklist |
| Flipping from paper to live | Yes — full manual checklist |
| Hotfix for a non-structural bug | CI only (automated) |
| Adding a new API endpoint | Yes — verify contract tests still pass |
| Changing router registration in `main.py` | Yes — full manual checklist |
