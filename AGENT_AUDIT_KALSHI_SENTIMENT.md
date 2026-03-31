# AGENT_AUDIT_KALSHI_SENTIMENT.md

> **Living document** — update whenever `FORMULAS_VERSION` or
> `AUDIT_SPEC_VERSION` in `merid/formulas.py` is bumped.
>
> Last updated: 2026-03-31  
> `FORMULAS_VERSION`: **1.0.0**  
> `AUDIT_SPEC_VERSION`: **1.0.0**

---

## Purpose

This document is the **audit specification** for the Kalshi sentiment stack.
It describes:

1. The authoritative formula definitions and their invariants
2. The DISCOVER → PROTECT traceability chain and its `[TRACE]` log schema
3. The R/A/G (Red / Amber / Green) health thresholds
4. Change-control obligations for every PR that touches this stack
5. Manual spot-check procedure using correlation IDs

---

## 1. Authoritative Formulas (`merid/formulas.py`)

All arithmetic that feeds the fear/greed index **must** reside in
`merid/formulas.py`.  No custom math may be re-implemented elsewhere in
the Kalshi sentiment pipeline.  The `kalshi-audit-gate` CI job enforces this.

| Symbol | Formula | Notes |
|---|---|---|
| `rolling_std(buf)` | Population σ | Returns 0 when `len(buf) < 2` |
| `normalize_vol(σ, σ_base)` | `min(1, (σ/σ_base) / 2)` | 0.5 when baseline ≤ 0 |
| `normalize_volume(cur, base)` | `min(1, (cur/base) / 3)` | 0.5 when baseline ≤ 0 |
| `book_imbalance(bid, ask)` | `\|bid−ask\| / (bid+ask)` | 0 when total ≤ 0 |
| `score_to_100(vol, volume, imbal)` | `(0.30·vol + 0.30·volume + 0.40·imbal) × 100` | Uses `COMPONENT_WEIGHTS` |
| `regime(score)` | Band lookup | See §1.1 |

### 1.1 Fear/Greed Band Boundaries

| Range | Label |
|---|---|
| 0 – 24 | `extreme_fear` |
| 25 – 49 | `fear` |
| 50 – 74 | `greed` |
| 75 – 100 | `extreme_greed` |

### 1.2 Component Weights

```python
COMPONENT_WEIGHTS = {
    "volatility":  0.30,
    "volume_heat": 0.30,
    "book_imbal":  0.40,
}
```

**Invariant**: weights must sum to exactly 1.0.  
Verified by `merid.formulas.check_invariants()` in CI and smoke tests.

---

## 2. Traceability Chain (DISCOVER → PROTECT)

Every pipeline run is bound by a single **correlation ID** created at the
entry point with `merid.formulas.generate_correlation_id()`.  The same
`corr_id` must appear in every `[TRACE]` log line for that run.

### 2.1 Log Schema

Every `[TRACE]` line follows this key=value structure:

```
[TRACE] stage=<STAGE> action=<ACTION> <domain_fields> corr_id=<UUID>
        formulas_ver=<FORMULAS_VERSION> audit_spec_ver=<AUDIT_SPEC_VERSION>
```

| Field | Values |
|---|---|
| `stage` | `DISCOVER`, `ANALYZE`, `PROTECT` |
| `action` | see §2.2 |
| `corr_id` | UUID4 string |
| `formulas_ver` | e.g. `1.0.0` |
| `audit_spec_ver` | e.g. `1.0.0` |

### 2.2 Stage / Action Inventory

| Stage | Action | Module | Trigger |
|---|---|---|---|
| `DISCOVER` | `validate_batch` | `discovery_validator.py` | `validate_markets()` called |
| `DISCOVER` | `validate_market` | `discovery_validator.py` | per-market schema check |
| `DISCOVER` | `validate_ok` | `discovery_validator.py` | market passed validation |
| `DISCOVER` | `validate_failed` | `discovery_validator.py` | market failed validation |
| `ANALYZE` | `market_registered` | `sentiment.py` | first data point for a ticker |
| `ANALYZE` | `score_updated` | `sentiment.py` | composite score recomputed |
| `PROTECT` | `kill_switch_activate` | `protection_enhancements.py` | `activate()` called |

### 2.3 End-to-End Trace Reconstruction

To reconstruct one pipeline run from logs:

```bash
# Pull all [TRACE] lines for a correlation ID
grep '\[TRACE\].*corr_id=<YOUR_ID>' /path/to/merid.log | sort -k3 -t=
```

Confirm that **all four** stages appear: `DISCOVER`, `ANALYZE`,
and (on shutdown) `PROTECT`.

---

## 3. R/A/G Health Classification

The CI gate and the Grafana dashboard use the following thresholds:

| Metric | Green | Amber | Red |
|---|---|---|---|
| Composite score drift vs prior | < 15 pts | 15 – 30 pts | > 30 pts |
| `check_invariants()` violations | 0 | — | ≥ 1 |
| Tracked markets | ≥ 1 | — | 0 |
| `FORMULAS_VERSION` drift | versions match | — | versions differ |

---

## 4. Change-Control Obligations

Any PR that modifies **any** of the following must:

- [ ] Bump `FORMULAS_VERSION` in `merid/formulas.py`  
  *(if a formula, constant, or band boundary changed)*
- [ ] Bump `AUDIT_SPEC_VERSION` in `merid/formulas.py`  
  *(if a `[TRACE]` action name, R/A/G threshold, or invariant changed)*
- [ ] Update the **tables in this document** to match the new state
- [ ] Update `FORMULAS_VERSION` / `AUDIT_SPEC_VERSION` assertions in  
  `tests/event_venues/kalshi/test_kalshi_audit_trail.py`
- [ ] Add or update at least one test that covers the changed behaviour

Covered paths:
- `merid/formulas.py`
- `merid/event_venues/kalshi/sentiment.py`
- `merid/event_venues/kalshi/discovery_validator.py`
- `merid/event_venues/kalshi/protection_enhancements.py`
- `scripts/enforce_kalshi_audit_spec.py`
- `monitoring/grafana-dashboards/kalshi-sentiment.json`

---

## 5. Manual Spot-Check Procedure

1. Pull a random `corr_id` from the "Active correlation ID" panel in
   the **MERID Kalshi Sentiment** Grafana dashboard, or from a recent
   JSON output file.
2. Run the grep in §2.3 against the production log.
3. Verify:
   - Every expected stage (`DISCOVER` → `ANALYZE`) appears.
   - `formulas_ver` matches the deployed `FORMULAS_VERSION`.
   - `audit_spec_ver` matches the deployed `AUDIT_SPEC_VERSION`.
   - No stage is missing (gap = invariant violation).
4. Log the result in the next sprint retrospective.

---

## 6. Version History

| Date | `FORMULAS_VERSION` | `AUDIT_SPEC_VERSION` | Summary |
|---|---|---|---|
| 2026-03-31 | 1.0.0 | 1.0.0 | Initial audit-as-code scaffold |
