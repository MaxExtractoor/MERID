# Feature Flag Operating Playbook

> Every new risky behavior ships behind a flag + operator toggle. No exceptions.

## Flag Inventory

| Flag | Default | Env Override | What It Guards |
|------|---------|-------------|----------------|
| `auto_downsize` | ON | `MERID_FF_AUTO_DOWNSIZE=0` | Auto-reduce position size when drawdown exceeds `drawdown_downsize_pct` |
| `unusual_volume_reaction` | ON | `MERID_FF_UNUSUAL_VOLUME_REACTION=0` | React to z-score volume spikes in Kalshi markets |

## When to Flip Flags Off

### `auto_downsize` → OFF

| Scenario | Rationale |
|----------|-----------|
| Exchange maintenance / degraded API | Downsizing during an outage locks in bad prices |
| Known data-feed stale event | DD calculation uses stale HWM → false trigger |
| Post-deploy observation window | Prevent auto-action while you validate new logic |
| Manual portfolio rebalance in progress | Avoid conflicting size adjustments |

**How:** Operator Dashboard → Contract Health panel → toggle, or:
```bash
# Runtime (no restart)
curl -X PUT http://localhost:8011/api/v1/system/feature-flags/auto_downsize \
  -H 'Content-Type: application/json' -d '{"enabled": false}'

# Startup override
export MERID_FF_AUTO_DOWNSIZE=0
```

### `unusual_volume_reaction` → OFF

| Scenario | Rationale |
|----------|-----------|
| Known event-driven volume (election night, FOMC) | Expected spikes, not anomalies |
| Kalshi exchange-wide volume surge (new category launch) | Platform-level noise, not signal |
| Backtesting / replay sessions | Historical volume ≠ live anomaly |

## Adding a New Flag

1. **Register** in `core/feature_flags.py` → `_FLAG_DEFAULTS`:
   ```python
   _FLAG_DEFAULTS: Dict[str, bool] = {
       "auto_downsize": True,
       "unusual_volume_reaction": True,
       "your_new_flag": True,  # add here
   }
   ```

2. **Gate** the risky code path:
   ```python
   from core.feature_flags import is_enabled
   if not is_enabled("your_new_flag"):
       logger.info("your_new_flag disabled, skipping")
       return  # or fallback behavior
   ```

3. **Update this table** with flip-off criteria.

4. **Add to pre-deploy checklist** (see `docs/PRE_DEPLOY_CHECKLIST.md`).

## Runtime vs Startup Precedence

```
runtime override  >  env var (MERID_FF_*)  >  _FLAG_DEFAULTS
```

Runtime overrides survive until process restart. Env vars survive across
restarts. Defaults are baked into code.

## Observability

- **Operator Dashboard** → ContractHealthPanel shows all flag states.
- **API** → `GET /api/v1/system/feature-flags` returns full detail per flag.
- **Logs** → Every `set_flag` / `reset_flag` call emits a structured log line
  with `feature_flag_set` / `feature_flag_reset` event type.

## Incident Response Pattern

1. Observe anomalous behavior (unexpected downsizing, volume-spike cascade).
2. **Flip the flag off** via dashboard or API (< 5 seconds).
3. Investigate root cause without live traffic amplifying the problem.
4. Fix the underlying issue, deploy, **flip the flag back on**.
5. Add the incident to the "When to Flip" table above as a documented scenario.
