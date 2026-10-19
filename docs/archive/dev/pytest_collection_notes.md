# Pytest collection performance

## Symptom

Running a broad expression such as:

```bash
pytest tests -k "category_exposure"
```

can sit in **collection** for a long time on large trees (many modules import heavy dependencies during import).

## Next steps (when profiling)

1. Time collection and slow imports:

   ```bash
   pytest tests --collect-only -q --durations=0
   ```

   or run a subset with verbose collection:

   ```bash
   pytest tests -k "category_exposure" -vv --maxfail=1
   ```

2. Prefer **path-scoped** runs for focused work:

   ```bash
   pytest tests/event_venues/kalshi/test_category_exposure_per_asset.py tests/test_continuous_trader_safety.py -q
   ```

3. Consider marking very heavy suites (e.g. parts of `test_kalshi_audit_*`) with `@pytest.mark.slow_audit` and excluding them from default CI via `pytest.ini` / workflow `addopts`.
