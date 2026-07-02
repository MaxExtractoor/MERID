# Experiment Design Template

**Experiment ID**: `EXP_YYYYMMDD_KNOBNAME`
**Date**: YYYY-MM-DD
**Author**: [Your Name]
**Profile**: kalshi_crypto_15m_v2
**Execution Mode**: dry-run / live

---

## 1. Config Knob Under Test

**Knob Name**: `kelly_fraction` (example)
**Location**: `config/profiles/kalshi_crypto_15m.yaml` → `kelly.kelly_fraction`

### Baseline Value (v2.0.0)
- Value: `0.30`
- Rationale: Current production setting

### Experimental Value
- Value: `0.32` (+0.02 delta)
- Rationale: Hypothesis that slightly higher Kelly fraction will increase fill-rate without excessive drawdown

---

## 2. Hypothesis

**Primary Hypothesis**: Increasing `kelly_fraction` from 0.30 to 0.32 will:
- Increase fill-rate by 5-10% (more aggressive sizing)
- Maintain max drawdown < 5%
- Not increase edge-rejection rate (NO_EDGE_YES, NO_VALID_CONTRACT)

**Secondary Hypothesis**: Higher Kelly fraction will:
- Increase per-trade PnL variance
- Improve win-rate (more selective sizing)

---

## 3. Success Criteria

**Must-Have (P0)**:
- Max drawdown < 5% of bankroll
- No kill-switch triggers
- Fill-rate ≥ baseline (40%)
- Edge-rejection rate ≤ baseline (20%)

**Nice-to-Have (P1)**:
- Fill-rate increase ≥ 5%
- Win-rate ≥ 55%
- Per-asset PnL positive for ≥ 3/5 assets

**Exploratory (P2)**:
- Correlation between Kelly fraction and cycle duration
- Impact on order queue depth

---

## 4. Execution Plan

### Phase A: Dry-Run (Test-Before-You-Run)

**Duration**: 1-2 cycles (10-20 seconds)
**Market Data**: Use live WS data (no replay)
**Bankroll**: Simulated $36.58 (match live)

**Steps**:
1. Backup current config: `cp config/profiles/kalshi_crypto_15m.yaml config/profiles/kalshi_crypto_15m.yaml.backup`
2. Apply experimental config: Edit `kelly_fraction` to `0.32`
3. Start loop in dry-run mode: `MERID_EXECUTION_MODE=dry-run python main.py`
4. Monitor logs for:
   - `[NO_EDGE_YES]` rejections
   - `[NO_VALID_CONTRACT]` rejections
   - Fill confirmations
   - Exposure snapshots
5. After 2 cycles, stop loop
6. Generate run-summary: Check `data/run_summaries/run_summary_*.json`
7. Restore baseline config: `cp config/profiles/kalshi_crypto_15m.yaml.backup config/profiles/kalshi_crypto_15m.yaml`

**Expected Dry-Run Output**:
- 2 cycles completed
- 0-2 orders submitted (depending on market conditions)
- Run-summary JSON with metrics

---

### Phase B: Live Baseline (30-Minute Session)

**Duration**: 30 minutes (360 cycles at 5s cadence)
**Bankroll**: Live $36.58
**Config**: Baseline (kelly_fraction=0.30)

**Pre-Flight Checklist**:
- [ ] Kill-switch OFF
- [ ] Risk envelope initialized
- [ ] WS bridge connected
- [ ] Market data fresh (< 30s stale)
- [ ] Bankroll service responsive
- [ ] Grafana dashboards accessible

**Monitoring**:
- Use live-run monitoring checklist (`.ci/kalshi_deployment_safety_checklist.md`)
- Watch for P0 triggers (kill-switch, circuit breaker)
- Watch for P1 triggers (drawdown > 3%, fill-rate < 30%)
- Log first-fill report (see template below)

**Post-Run**:
- Generate run-summary JSON
- Export Grafana dashboard snapshots
- Document any anomalies

---

## 5. Results

### Dry-Run Results

**Run ID**: `run_summary_YYYYMMDD_HHMMSS.json`

**Metrics**:
- Cycles completed: _
- Orders submitted: _
- Orders filled: _
- Fill-rate: _%
- NO_EDGE_YES rejections: _
- NO_VALID_CONTRACT rejections: _
- Simulated PnL: $_
- Max drawdown: _%

**Observations**:
- _
- _

**Verdict**: [PASS / FAIL / INCONCLUSIVE]

---

### Live Baseline Results

**Run ID**: `run_summary_YYYYMMDD_HHMMSS.json`

**Metrics**:
- Cycles completed: _
- Orders submitted: _
- Orders filled: _
- Fill-rate: _%
- NO_EDGE_YES rejections: _
- NO_VALID_CONTRACT rejections: _
- Realized PnL: $_
- Max drawdown: _%
- Win-rate: _%

**Per-Asset Breakdown**:
- BTC: PnL=$_, trades=_
- ETH: PnL=$_, trades=_
- SOL: PnL=$_, trades=_
- XRP: PnL=$_, trades=_
- DOGE: PnL=$_, trades=_

**First-Fill Report**:
```
Timestamp: YYYY-MM-DD HH:MM:SS UTC
Market: KXBTC15M-XXXXX
Side: YES/NO
Contracts: _
Price: $_ cents
Execution: IOC / GTC
Fill latency: _ms
```

**Observations**:
- _
- _

**Verdict**: [PASS / FAIL / INCONCLUSIVE]

---

## 6. Comparison

### Dry-Run vs Dry-Run (Baseline vs Experimental)

| Metric | Baseline (0.30) | Experimental (0.32) | Delta | % Change |
|--------|-----------------|---------------------|-------|----------|
| Fill-rate | _% | _% | _% | _% |
| Orders/cycle | _ | _ | _ | _% |
| NO_EDGE_YES | _ | _ | _ | _% |
| NO_VALID_CONTRACT | _ | _ | _ | _% |
| Simulated PnL | $_ | $_ | $_ | _% |

**Conclusion**: _

### Dry-Run vs Live (Experimental vs Baseline Live)

| Metric | Dry-Run (0.32) | Live Baseline (0.30) | Delta | % Change |
|--------|----------------|----------------------|-------|----------|
| Fill-rate | _% | _% | _% | _% |
| Realized PnL | $_ | $_ | $_ | _% |
| Max drawdown | _% | _% | _% | _% |
| Win-rate | _% | _% | _% | _% |

**Conclusion**: _

---

## 7. Decision

**Recommendation**: [ADOPT / REJECT / NEED_MORE_DATA]

**Rationale**:
- _
- _

**Next Steps**:
- _
- _

---

## 8. Appendix: First-Fill Report Template

```
=== FIRST-FILL REPORT ===
Experiment ID: EXP_YYYYMMDD_KNOBNAME
Timestamp: YYYY-MM-DD HH:MM:SS UTC
Profile: kalshi_crypto_15m_v2
Execution Mode: live

ORDER DETAILS:
- Market ID: KXBTC15M-XXXXX
- Side: YES/NO
- Contracts: _
- Price: $_ cents
- TIF: IOC/GTC
- Client Tag: _

EXECUTION:
- Submitted at: YYYY-MM-DD HH:MM:SS UTC
- Filled at: YYYY-MM-DD HH:MM:SS UTC
- Fill latency: _ms
- Partial fill: [YES/NO]
- Slippage: _ cents

MARKET CONTEXT:
- Mid price: $_ cents
- Spread: _ cents
- Seconds to expiry: _
- Model probability: _
- Implied probability: _
- Edge: _%

RISK CHECKS:
- Kill switch: [OFF/ON]
- Risk envelope band: _
- Per-asset exposure: $_
- Portfolio exposure: $_

OUTCOME:
- Realized PnL: $_
- Cycle number: _
```
