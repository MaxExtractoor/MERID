# 15m Crypto Calibration Playbook

**Scope:** kalshi_crypto_15m_v2 profile, assets = BTC, ETH, SOL, XRP, DOGE, 15m timeframe only

**Objective:** Tune min_edge, distance filters, and Kelly bands based on realized EV and win rate from forensics + fills (not intuition).

**Driver:** Data-driven calibration using:
- Forensics JSON: bucketed EV/win rate by (prob_band × phase × distance)
- Guard reason counts: which filters are blocking trades
- Realized PnL from fills ledger

---

## Calibration Contract

### Parameters Under Tuning

1. **Edge thresholds per asset & phase** (`kalshi_crypto_15m.yaml`)
   - `min_edge_early`, `min_edge_mid`, `min_edge_late`, `min_edge_terminal`
   - Controls minimum edge required to trade

2. **Distance filters** (`kalshi_crypto_15m.yaml` or `kalshi_distance_config.py`)
   - `max_distance_pct`: maximum spot-to-strike distance
   - `max_z_distance`: maximum sigma-based distance

3. **Kelly parameters** (`kalshi_crypto_15m.yaml`)
   - `kelly_hard_cap`: maximum Kelly fraction
   - `kelly_min_edge_pct`, `kelly_max_edge_pct`: edge bounds for Kelly sizing

### Parameters NOT Under Tuning (Fixed by Risk Envelope)

- Capital allocation (capital_usd, profile_capital_usd)
- Daily loss limits (max_daily_loss_pct, max_daily_loss_usd)
- Per-asset caps (asset_max_notional_usd)
- Venue caps (max_single_order_notional, max_total_notional)
- Drawdown thresholds (drawdown_halt_pct, drawdown_unwind_pct)

---

## Tuning Rules

### Rule 1: Negative EV Buckets

**Trigger:** A bucket (prob_band × phase × distance) has:
- Trades ≥ 20 (minimum sample size)
- EV per dollar < 0 OR EV per dollar < 0.005 (below minimal threshold)

**Action:** Choose ONE of:
- Raise `min_edge_*` for that phase (e.g., late: 3.0% → 3.3%)
- Tighten `max_distance_pct` (e.g., 4.0% → 3.5%)
- Disallow that bucket entirely by adjusting distance/edge thresholds

**Example:**
> On 2026-05-18, DOGE late-window 3-4% distance bucket had −EV (−0.02, 25 trades). Increased DOGE late min_edge from 3.0% → 3.3% and reduced max_distance_pct from 4.0% → 3.5%.

### Rule 2: Strong Positive EV Buckets (Underutilized)

**Trigger:** A bucket has:
- Trades ≥ 20
- EV per dollar ≥ 0.02 (strongly positive)
- Trade count is low relative to opportunity (underutilized)

**Action:** Consider:
- Slightly lower `min_edge_*` for that phase (e.g., 3.0% → 2.8%)
- Loosen `max_distance_pct` (e.g., 3.0% → 3.5%)

**Constraint:** Do not loosen below risk envelope limits or Kalshi's per-order caps.

### Rule 3: Guard-Reason-Driven Tuning

**Trigger:** Guard reason analysis shows:
- `edge_too_low` dominates rejections for an asset
- Realized EV is strong where trades do fire

**Action:** min_edge may be too strict; consider small reduction (0.2-0.3% increments).

**Trigger:** `distance_too_far` dominates and bad buckets are at large distance

**Action:** Tighten `max_distance_pct` to exclude low-EV far-distance trades.

**Trigger:** `kill_switch` appears in guard reasons

**Action:** Review daily loss limit and realized PnL; do NOT tune parameters while kill-switch is active.

### Rule 4: Phase-Specific Behavior

**Early window (first 3-4 minutes):**
- Higher uncertainty, lower liquidity
- Default: stricter edge (higher min_edge_early)
- If early EV is strong and consistent: consider slight relaxation

**Late window (last 2-3 minutes):**
- Higher liquidity, lower edge opportunities
- Default: looser edge (lower min_edge_late)
- If late EV is negative: tighten significantly

### Rule 5: Asset-Specific Adjustments

**BTC/ETH (high liquidity, tight spreads):**
- Can afford tighter distance filters (max_distance_pct ~1-2%)
- Lower min_edge thresholds acceptable (2-3%)

**SOL/XRP/DOGE (lower liquidity, wider spreads):**
- Need looser distance filters (max_distance_pct ~3-4%)
- Higher min_edge thresholds (3-5%) to compensate for spread cost

---

## Calibration Workflow

### Step 1: Generate Forensics Report

After accumulating 50-100 trades per asset (or daily if volume is low):

```bash
# Parse logs and generate forensics JSON
python scripts/analyze_15m_forensics.py --log-file server_diag.log --output data/forensics/15m/YYYYMMDD_HHMM.json

# Generate performance report
python scripts/report_15m_performance.py --forensics-dir data/forensics/15m --output data/forensics/15m_performance_report.md
```

### Step 2: Review Performance Report

For each asset:
- Check overall win rate and EV per dollar
- Identify best/worst buckets
- Review guard reason counts

### Step 3: Apply Tuning Rules

Based on the report, apply the relevant tuning rules:
- Identify buckets violating Rule 1 (negative EV) or Rule 2 (underutilized positive EV)
- Check guard reasons for Rule 3 patterns
- Consider phase-specific behavior (Rule 4) and asset characteristics (Rule 5)

### Step 4: Make Profile YAML Change

Edit `config/profiles/kalshi_crypto_15m.yaml`:
- Change ONLY the parameters identified in Step 3
- Document the change with a comment referencing the forensics report
- Example: `# Tuned based on 2026-05-18 forensics: DOGE late min_edge 3.0%→3.3% (negative EV in 3-4% bucket)`

### Step 5: Validate and Deploy

1. Run validation script:
   ```bash
   python scripts/validate_profile_envelope_capability.py
   ```
   OR rely on startup preflight gate (will run automatically on next restart)

2. Restart 15m worker:
   ```bash
   # Check startup logs for:
   # - Preflight gate pass/fail
   # - Profile diff (confirm only intended parameters changed)
   ```

3. Monitor for next calibration window (1-3 days or N trades)

### Step 6: Evaluate and Decide

After calibration window:
- Run performance report again
- Compare to previous report
- Decide:
  - **Keep changes** if performance improved or stable
  - **Tighten further** if negative EV persists
  - **Roll back** using previous snapshot/YAML if performance degraded

---

## Rollback Procedure

If a parameter change degrades performance:

1. Restore previous YAML from `data/profile_snapshots/last.json` (timestamped snapshot)
2. Re-run validation
3. Restart worker
4. Document rollback reason in calibration notes

---

## Guardrails

### Never Tune These (Risk Envelope)

- capital_usd, profile_capital_usd (bankroll allocation)
- max_daily_loss_pct, max_daily_loss_usd (daily risk budget)
- asset_max_notional_usd (per-asset caps)
- max_single_order_notional_usd, max_total_notional_usd (venue caps)
- drawdown_halt_pct, drawdown_unwind_pct (drawdown limits)

### Change Incrementally

- Adjust edge thresholds in 0.2-0.3% increments
- Adjust distance in 0.5% increments
- Allow at least 50-100 trades between changes per asset

### No Parameter Flapping

- Do not make multiple changes to the same parameter within a single calibration window
- If a change doesn't work, roll back before trying a different adjustment

---

## Documentation Requirements

Every parameter change must be documented with:

1. **Date** of change
2. **Forensics report reference** (YYYYMMDD_HHMM)
3. **Bucket evidence** (prob_band × phase × distance, EV, trade count)
4. **Rule applied** (Rule 1, 2, 3, 4, or 5)
5. **Parameter changed** (before → after)
6. **Expected outcome**

Example entry:
```
2026-05-18: DOGE late min_edge 3.0%→3.3%
- Forensics: 2026-05-18_1200
- Evidence: late window, 3-4% distance bucket, EV=-0.02, 25 trades
- Rule: Rule 1 (negative EV bucket)
- Expected: Reduce late-window negative EV trades
```

---

## Success Metrics

A well-calibrated profile should show:

- Overall win rate ≥ 55% across all assets
- EV per dollar ≥ 0.01 across all assets
- No single bucket with ≥20 trades and EV < 0
- Balanced guard reasons (no single reason dominating >70% of rejections unless intentional)
- Stable performance across calibration windows (no large swings in EV/win rate)
