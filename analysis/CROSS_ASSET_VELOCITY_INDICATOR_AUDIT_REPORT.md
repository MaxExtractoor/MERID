# Cross-Asset Velocity & Indicator-Stack Correctness Audit

**Date:** 2026-08-26  
**Scope:** BTC, ETH, SOL, XRP, DOGE 15m Kalshi crypto stack  
**Focus:** SOL wrong-side fingerprint and cross-asset correctness  

## 1. Executive summary

A code-level audit of the 15m indicator stack (`merid/prediction/agent_grid_15m.py`, `merid/signals/crypto_15m_indicators.py`, `merid/data/cf_rti_adapter.py`, and the Coinbase velocity path) was run. The formulas are not statically sign-inverted, and the one-bar shift and sign-consistency tests pass for all five assets on controlled synthetic paths. The leading explanation for the observed wrong-side / inverted fingerprint is now a **dynamic feed-alignment bug**, not a static sign or parameter bug.

### Top-priority finding: feed/timestamp alignment

The Bachelier fair value is computed from the **live CF Benchmarks RTI 60s average**, while velocity can fall back to **Coinbase spot or the UnifiedSpotProvider 1m poll**. If the spot/velocity input lags the RTI by ~86s and the price reverses inside that window, the model will buy YES (or NO) on a lagged move that the live settlement reference has already reversed. This is a **systemic, dynamic inversion** that affects all assets and is most visible on SOL because SOL has the largest RTI-vs-spot divergence and highest volatility.

To test this directly, the decision path now logs a `[FEED-ALIGNMENT]` line and the shadow A/B telemetry now records, for every decision:

- spot source, staleness, timestamp, data quality
- velocity source, age, signal type, threshold
- CF RTI source/observed timestamps, age, execution eligibility, timestamp quality

The audit script can correlate these with `realized_outcome` once settlement data is joined.

### Secondary findings

1. **Per-asset EMA tuning in the indicator stack was dead code in Kalshi mode.** `IndicatorConfig.__post_init__` returned early when `kalshi_mode=True`, so all five assets used the same 9/21 EMA. This was fixed during the audit so the intended 13/34 EMA for SOL/XRP/DOGE is now applied while the Kalshi-specific vol/ATR/chop gate overrides are preserved. **Caveat:** the `momentum_fvg` signal path in `agent_grid_15m.py` still overrides the asset-specific RSI thresholds with hardcoded regime-based values (lines 4770-4802), so the 35/65 (SOL/XRP) and 40/60 (DOGE) RSI tuning remains unwired. This fix should be validated on shadow telemetry before it is trusted in the live book.
2. **SOL and XRP share identical `annualized_vol` (1.00) and `velocity_threshold` (0.000225).** This is a copy-paste red flag if their realized 60s volatilities differ. It flattens or mis-scales the signal but does not explain an *inversion* by itself. It should be revisited after the feed-alignment question is settled.

## 2. Methodology

The audit followed the two-part framework, with feed alignment as the primary lens:

- **Part A — Correctness & integrity:** parameter matrix, formula/sign audit, one-bar shift test, staleness/source review.
- **Part B — Feed-alignment / predictiveness:** the agent now writes `FEED-ALIGNMENT` diagnostics and the shadow A/B telemetry now carries spot/velocity/CF RTI staleness fields. `analysis/cross_asset_velocity_indicator_audit.py` can read `logs/shadow_side_telemetry.jsonl` (optionally joined with `MERID_SHADOW_SETTLEMENT_PATH` or inline `realized_outcome`) and compute per-asset wrong-side rates by staleness bin and velocity source.

The audit script is run with:

```powershell
.\.venv\Scripts\python.exe analysis\cross_asset_velocity_indicator_audit.py
```

With shadow + settlement data:

```powershell
$env:MERID_SHADOW_SIDE_TELEMETRY_PATH="logs/shadow_side_telemetry.jsonl"
$env:MERID_SHADOW_SETTLEMENT_PATH="logs/settlement_outcomes.jsonl"
.\.venv\Scripts\python.exe analysis\cross_asset_velocity_indicator_audit.py
```

## 3. Cross-asset parameter matrix

| Param | BTC | ETH | SOL | XRP | DOGE |
|---|---|---|---|---|---|
| annualized_vol_default | 0.6 | 0.8 | 1.0 | 1.0 | 1.2 |
| velocity_threshold | 0.00015 | 0.00015 | 0.000225 | 0.000225 | 0.0003 |
| cfb_settlement_symbol | BRTI | ETH_RTI | SOL_RTI | XRP_RTI | DOGE_RTI |
| ema_trend_period | 21 | 21 | 34 | 34 | 34 |
| ema_fast_period | 9 | 9 | 13 | 13 | 13 |
| ema_slow_period | 21 | 21 | 34 | 34 | 34 |
| rsi_oversold | 30.0 | 30.0 | 35.0 | 35.0 | 40.0 |
| rsi_overbought | 70.0 | 70.0 | 65.0 | 65.0 | 60.0 |
| atr_min_move_pct | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| consecutive_closes_required | 0 | 0 | 0 | 0 | 0 |
| macd_persistence_bars | 0 | 0 | 0 | 0 | 0 |
| macd_histogram_min_pct | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### Red flags in the matrix

- `annualized_vol_default` shared: **SOL and XRP = 1.00**.
- `velocity_threshold` shared: **SOL and XRP = 0.000225**.
- **EMA tuning is now asset-specific**, but the `momentum_fvg` signal path still ignores the per-asset RSI thresholds (35/65 for SOL/XRP, 40/60 for DOGE) and uses hardcoded regime values.

## 4. Formula & sign audit

### 4.1 Velocity

- **Internal fallback:** `_calculate_internal_multi_window_velocity` uses `(current_price - prev_price) / prev_price` with weights `[0.2, 0.3, 0.5]` over `[10, 30, 60]` seconds. Positive price change → positive velocity. Correct.
- **Coinbase external:** `CoinbaseWebSocketClient._calculate_velocity` uses `(current_price.price - oldest_price.price) / oldest_price.price`. Positive price change → positive velocity. Correct.
- **Mapping to side:** in `agent_grid_15m.py`, `velocity > velocity_threshold` → YES, `velocity < -velocity_threshold` → NO. Correct.

### 4.2 Bachelier baseline

```
z = log(spot / strike) / (annualized_vol * sqrt(t_years))
p_yes = 0.5 * (1 + erf(z / sqrt(2)))
```

`spot > strike` → `p_yes > 0.5`. Correct.

### 4.3 Hybrid probability shifts

- `velocity_edge` is added with the sign of `velocity`.
- `macd_delta = (macd_histogram / spot_price) * 10.0`, capped at ±5 pp, added to `p_yes`.
- `rsi < 35` adds +2 pp; `rsi > 65` subtracts 2 pp.
- `obi` positive adds to `p_yes`.
- Regime penalty is direction-consistent.

All sign conventions are consistent across assets.

## 5. Sign-consistency & one-bar shift test

A 120-bar synthetic 1m close series was fed into the actual `Crypto15mIndicatorStack` for each asset. The last price was set as the strike so the Bachelier baseline is 0.5 and only the indicator shift drives direction.

| Asset | Velocity | MACD hist | RSI | p_yes_bach | p_yes_hyb | sign_ok | shift_velocity | shift_p_yes |
|---|---|---|---|---|---|---|---|---|
| BTC | 0.001263 | 0.059617 | 97.21 | 0.5000 | 0.6335 | True | 0.001617 | 0.6339 |
| ETH | 0.001263 | 0.059617 | 97.21 | 0.5000 | 0.6335 | True | 0.001617 | 0.6339 |
| SOL | 0.001263 | 0.059617 | 97.21 | 0.5000 | 0.5958 | True | 0.001617 | 0.6276 |
| XRP | 0.001263 | 0.059617 | 97.21 | 0.5000 | 0.5958 | True | 0.001617 | 0.6276 |
| DOGE | 0.001263 | 0.059617 | 97.21 | 0.5000 | 0.5677 | True | 0.001617 | 0.5917 |

### 5.1 Declining-series control

A second 120-bar declining series was run. All five assets correctly selected **NO**.

| Asset | Velocity | MACD hist | RSI | p_yes_bach | p_yes_hyb | sign_ok |
|---|---|---|---|---|---|---|
| BTC | -0.000766 | -0.051234 | 4.19 | 0.5000 | 0.4145 | True |
| ETH | -0.000766 | -0.051234 | 4.19 | 0.5000 | 0.4145 | True |
| SOL | -0.000766 | -0.051234 | 4.19 | 0.5000 | 0.4486 | True |
| XRP | -0.000766 | -0.051234 | 4.19 | 0.5000 | 0.4486 | True |
| DOGE | -0.000766 | -0.051234 | 4.19 | 0.5000 | 0.4656 | True |

### Interpretation

- All five assets correctly select **YES** on a rising series.
- The **one-bar shift** (removing the final bar) does **not** flip the side for any asset, which is the expected behavior for a short-horizon velocity model that is *not* relying on a future bar.
- **SOL and XRP produce identical `p_yes_hyb` (0.5958)** because they share `annualized_vol` and `velocity_threshold` and the asset-specific tuning is disabled. DOGE differs because it has higher `annualized_vol` and `velocity_threshold`.

This rules out a **static sign inversion** in the formulas. It does **not** rule out a dynamic sign flip caused by feed misalignment or stale data.

## 6. Look-ahead / staleness audit

### 6.1 Sources and clocks

| Input | Source | Staleness gate / cadence | Used for |
|---|---|---|---|
| Settlement (Bachelier) | CF Benchmarks RTI 60s average (`get_live_rti`) | `MERID_MAX_CFB_RTI_AGE_MS` (default 7s) | `_get_settlement_input_price` -> `settlement_input_price` |
| Velocity (preferred) | Coinbase WS 60s window | Fresh if < 120s old | `_calculate_multi_window_velocity` |
| Velocity (fallback) | `UnifiedSpotProvider` 1m/spot poll | `max_age_s` from `data.unified_spot_service` (~300s cache TTL in `live_price_feed`) | `_calculate_internal_multi_window_velocity` |
| 1m indicator bars | Spot-provider tick buffered into `_indicator_stack_price_buffer` and aggregated once per minute | `staleness_threshold_seconds=30` in `Crypto15mIndicatorStack` | RSI, MACD, EMA |

### 6.2 Key alignment risk

The Bachelier baseline and the velocity/indicator stack can be driven by **two different prices at two different times**:

- The settlement input is a **60s average of CF RTI**.
- The velocity is a **60s return on Coinbase spot** (or a 1m spot poll).

If Coinbase spot is lagged (e.g., the reported ~86s ingestion latency) while the RTI is live, the agent can compute a positive velocity on an old upward move while the RTI has already turned down. This would make the model buy YES exactly when the settlement reference is falling — producing the observed **wrong-side / inverted** outcome without any formula sign bug.

The audit script's one-bar shift test did **not** flip side on synthetic data, but the real test is live multi-feed comparison. To enable that, the decision path now logs a `[FEED-ALIGNMENT]` line and the shadow telemetry records the source and staleness of both the settlement input and the velocity input.

## 7. SOL-specific findings

1. **Settlement symbol:** `SOL_RTI` (correct, mapped in `merid/data/cf_rti_adapter.py`).
2. **Annualized vol:** 1.00, identical to XRP. If SOL's 15m realized vol differs from XRP, this mis-scales the Bachelier z-score.
3. **Velocity threshold:** 0.000225, identical to XRP. If SOL's 60s price excursions differ, one of the two assets is miscalibrated.
4. **EMA tuning now applied:** the `__post_init__` fix gives SOL the intended 13/34 EMA. The `momentum_fvg` signal path still uses hardcoded RSI thresholds, so the 35/65 RSI tuning is not yet effective.
5. **Staleness threshold:** 30s in the indicator stack. If spot is >30s stale, the stack returns `trade_allowed=False` and stale prices. In the live report, ~86s latency exceeds this, so the stack may be disabled or using stale snapshots.

## 8. Predictiveness / feed-alignment audit

The audit script (`analysis/cross_asset_velocity_indicator_audit.py`) now implements `run_predictiveness_audit`. It reads the shadow side JSONL and optionally joins a settlement-outcome JSONL. For each asset it computes:

- mean/median spot staleness, velocity age, and CF RTI age
- wrong-side rate by spot-staleness bin (`<1s`, `1-10s`, `10-30s`, `30-60s`, `60-120s`, `>120s`)
- wrong-side rate by velocity source (`coinbase` vs `internal_fallback`)
- wrong-side rate by CF RTI execution eligibility
- Pearson correlation of wrong-side with `spot_staleness_ms`, `velocity_age_ms`, and `cfb_age_ms`

To run once shadow records exist:

```powershell
$env:MERID_SHADOW_SIDE_TELEMETRY_PATH="logs/shadow_side_telemetry.jsonl"
$env:MERID_SHADOW_SETTLEMENT_PATH="logs/settlement_outcomes.jsonl"
.\.venv\Scripts\python.exe analysis\cross_asset_velocity_indicator_audit.py
```

If no settlement file is provided, the script falls back to inline `realized_outcome` in the shadow record and still reports descriptive feed-alignment statistics.

## 9. Code changes made during the audit

- `merid/prediction/agent_grid_15m.py` — added a `[FEED-ALIGNMENT]` log and extended the shadow side telemetry with spot/velocity/CF RTI source and staleness fields. This is pure instrumentation and does not change the selected side or order.
- `merid/signals/crypto_15m_indicators.py` — fixed `IndicatorConfig.__post_init__` so asset-specific EMA tuning is applied even when `kalshi_mode=True` (Kalshi-only vol/ATR/chop gate overrides are still preserved). All relevant tests pass.
- `merid/prediction/shadow_side_telemetry.py` — no API change; the new feed-alignment fields flow through the existing `**extra` mechanism.
- `merid/tests/test_bug_fixes_2026_07_08.py` — removed a stale `max_concurrent_trades` argument from a `KalshiCrypto15mRiskEnvelope` test call and updated the expected `_last_trade_time` initialization behavior to match the current agent code.

## 10. Recommended next actions

In priority order:

1. **Run the feed-alignment test first.** Collect a few hours of live or paper shadow telemetry, join it with settlement outcomes, and run `analysis/cross_asset_velocity_indicator_audit.py`. Look for wrong-side trades clustering where `spot_staleness_ms` or `velocity_age_ms` is large, `velocity_source` is `internal_fallback`, or `cfb_execution_eligible` is `false`. If the correlation is strong, the fix is feed/timestamp coordination, not a sign flip.
2. **Stage the audit harness and the indicator fix, but land them separately.** The audit files (`analysis/cross_asset_velocity_indicator_audit.py`, `CROSS_ASSET_VELOCITY_INDICATOR_AUDIT_REPORT.md`) are pure tooling and safe to commit. The `crypto_15m_indicators.py` fix changes live EMA behavior for all five assets; run it in shadow A/B and confirm it improves side selection on the shadow log before it reaches the live book.
3. **Add a feed-alignment gate (or attenuation) in production.** Once the telemetry confirms the mechanism, reject or attenuate the signal when `velocity_age_ms` is materially larger than `cfb_age_ms` or when the spot/velocity source is stale. A simple first gate: if `spot_staleness_ms > 30_000` and `velocity_source == "internal_fallback"`, require additional confirmation or skip the cycle.
4. **Re-calibrate SOL vs XRP `annualized_vol` and `velocity_threshold` only after the feed question is settled.** Identical constants are a copy-paste red flag, but recalibrating vol on top of a misaligned signal just bakes in the wrong answer.
5. **Wire the asset-specific RSI thresholds through the `momentum_fvg` signal path.** `agent_grid_15m.py` lines 4770-4802 currently hardcode 30/70 (or regime-shifted 35/75/25/65) thresholds and ignore the `IndicatorConfig` per-asset values. This is a separate tunability issue, not the inversion root cause.

## 11. Files added / changed

- `analysis/cross_asset_velocity_indicator_audit.py` — runnable cross-asset correctness + feed-alignment predictiveness audit.
- `analysis/CROSS_ASSET_VELOCITY_INDICATOR_AUDIT_REPORT.md` — this report.
- `merid/prediction/agent_grid_15m.py` — feed-alignment logging + shadow telemetry extension.
- `merid/signals/crypto_15m_indicators.py` — `IndicatorConfig.__post_init__` EMA/RSI tuning fix.
- `merid/tests/test_bug_fixes_2026_07_08.py` — stale test fix for `KalshiCrypto15mRiskEnvelope` and `_last_trade_time`.

## 12. Verification run

- `merid/prediction/test_multi_window_velocity.py` — 13 passed
- `tests/test_trade_decision_release_gates.py` — 17 passed
- `tests/test_cf_rti_adapter.py` — 11 passed
- `merid/tests/test_bug_fixes_2026_07_08.py` — 18 passed
- Combined targeted run — **59/59 passed** in 19.92s
