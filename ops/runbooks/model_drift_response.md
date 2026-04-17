# Runbook: Model Drift Response

**ID:** RB-OPS-004  
**Severity:** Warning → Critical  
**Trigger:** `merid_model_drift_status` metric enters `degraded` or `critical`

## Symptoms

- Prediction accuracy drops below baseline (Brier score > 0.35)
- Strategy PnL diverges from backtest expectations
- Anomaly detector fires `drift_detected` alerts
- `core/drift_monitoring_pipeline.py` reports `DriftStatus.DEGRADED` or `CRITICAL`

## Immediate Actions (T0 — Automated)

1. Drift pipeline auto-demotes affected strategy to SIM mode
2. Alert fires to `#alerts-risk` Telegram channel
3. Affected agent's trust score reduced in consensus engine

## Triage (T1 — On-Call Engineer, < 15 min)

1. Check drift dashboard: `GET /api/metrics/radar`
2. Identify drift type:
   - **Concept drift** — market regime change (check macro indicators)
   - **Data drift** — input distribution shift (check feed staleness)
   - **Model drift** — model weights stale (check last retrain date)
   - **LLM behavioral drift** — prompt response quality degraded
3. Check recent deployments for unintended changes

## Resolution (T2 — Engineering, < 2 hours)

### Concept / Market Regime Drift
1. Pause affected strategies: `POST /api/v1/pipeline/domain/halt`
2. Review recent market events
3. Retrain model on recent data window
4. Validate on holdout set before re-enabling

### Data Distribution Drift
1. Check feed staleness: `GET /api/metrics/swarm_health`
2. Verify data contracts: check `DataContractRegistry` validation failures
3. If feed is stale → follow feed staleness runbook
4. If schema changed → update data contracts and re-validate

### Model Weight Staleness
1. Check last retrain timestamp in model metadata
2. Trigger retrain pipeline: `python -m core.retrain_pipeline --model <name>`
3. Compare new model metrics vs baseline
4. Promote if metrics improve, otherwise escalate

### LLM Behavioral Drift
1. Check LLM provider status page
2. Run LLM eval suite: `pytest tests/test_llm_eval.py`
3. If degraded → switch to fallback model or reduce LLM reliance
4. Log incident for provider review

## Recovery Verification

1. Confirm drift status returns to `STABLE`: check `merid_model_drift_status` metric
2. Verify strategy PnL returns to expected range
3. Re-enable affected strategies: `POST /api/v1/pipeline/domain/resume`
4. Monitor for 1 hour before closing incident

## Escalation

- If drift persists > 4 hours → escalate to T3 (Incident Commander)
- If multiple strategies affected simultaneously → declare incident
