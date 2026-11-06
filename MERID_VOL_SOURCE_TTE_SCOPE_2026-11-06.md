# vol_source <180s Gap — Mechanism Scope & Shadow-Repair Spec — 2026-11-06

Scope order (operator): diagnostic and shadow-data repair only. No live TTE
relaxation, no gate-order change, no threshold change. The +0.65c/97%-win
120–150s counterfactual cohort must be **recomputed on the repaired cohort**;
it is not inherited.

## 1. Verified mechanism — the pipeline does not lose vol at low TTE

`compute_trade_decision` (`merid/prediction/trade_decision.py`) gate order:

| line | check | result on TTE≤180 (non-settlement) |
|---|---|---|
| 3902 | `expired_or_no_time` | TTE invalid only |
| 3913–3928 | settlement_lane eligibility | exempt lane only |
| 3938 | `final_minute_entry_disabled` ≤30s | — |
| **3948** | **`min_tte_entry_disabled` ≤180s** | **early return here** |
| 3952–3967 | data_state / regime / score finiteness | never reached |
| **4010** | `_resolve_annualized_vol` → `_compute_bachelier_components` | **never reached** |
| 4023+ | `indicators["annualized_vol"/"annualized_vol_source"/z_score...]` | never populated |

`_no_trade()` (3860–3896) returns `p_yes_calibrated = p_no_calibrated = 0.5`
and `confidence_source="pre_trade_gate"`. That is the p=0.5 placeholder the
shadow records. The veto is doing its job — but it means **no decision-level
forecast (raw or calibrated) exists below 180s**, not that vol is unavailable.

### The `missing_input_fields:["vol_source"]` label is an instrumentation artifact

`lwf_shadow` call site (`agent_grid_15m.py:10501–10506`):

```python
annualized_vol=(float(_ind_lwf.get("annualized_vol"))
                if ... else float(annualized_vol) ...),   # falls back to CALLER-LOCAL resolved vol
vol_source=_ind_lwf.get("annualized_vol_source"),          # NO fallback — reads skipped decision's indicators only
```

`_ind_lwf = decision_taker.indicators` — empty of vol fields on the
pre-vol early return. Meanwhile `annualized_vol` leaks in via the caller
local (resolved at 8133/8698/8900, or `_last_signal_vol_context` at 13344).
Result: `annualized_vol` present + `vol_source=None` → the shadow's
`_probability_status` (lwf_shadow_lane.py:256) reports
`missing_input_fields:["vol_source"]` — blaming the one field that was merely
unlabeled, while the actual missing thing (the whole forecast) shows up as
`model_evaluation_completed=false` + `p_calibrated_side=0.5`.

The source string exists three ways at the call site: caller-local
`vol_source` (8133), `market_state.annualized_vol_source` (8166/8373),
`_last_signal_vol_context["annualized_vol_source"]` (13346). None is passed.

### Vol resolution is TTE-independent — verified on live data

- `_resolve_annualized_vol` (1397–1473): env override → realized →
  market-implied → default. **No TTE branch.** `market_implied` needs only
  `tte>0` + non-extreme `market_prob` + direction agreement (1260–1295).
- `_fetch_realized_vol` (1375) → `RealizedVolTracker.annualized_vol`: EWMA
  over the RTI tick stream, keyed by **asset** (not ticker). Constraints:
  ≥60 samples, ≥120s span, last tick ≤60s old (realized_vol.py:108–131).
  Nothing references contract TTE — the estimate carries across rollovers.
- `_compute_signal_vol_context` (13316–13354) already resolves
  strike+vol+z early **at any TTE ≥1s** purely for rejection telemetry.
- `late_window_shadow.jsonl` (30–90s records): `annualized_vol_source`
  distribution = realized 5,997 / realized_clamped 2,864 / default 90 /
  unknown 4,067 — real resolved vol down to the 30–40s band.

### An upstream model p exists below 180s and refreshes

The signal-path Bachelier (8133–8154, `effective_seconds=max(tte,1.0)` — no
floor) publishes `market_state.model_fair_prob`, `model_fair_prob_ts`,
`annualized_vol_source` at 8165–8168/8374–8375. `pinned_fav_maker_shadow`
reads it as `p_selected`/`p_source="market_state.model_fair_prob"`.

Post-Nov-1 pf-shadow records: TTE<180 with p_selected populated = **2,453**
(vs 66 null). Example KXDOGE15M-26OCT312015-15: p 0.723@180.2s →
0.723@177.1s → 0.838@167.1s → 0.853@157.5s — **fresh, updating**, not a stale
carryover (verify per-record via `model_fair_prob_ts` before use).

Also: `lwf_shadow` already computes `q_phi_diagnostic` (lwf_shadow_lane.py:443–447)
from its own ref/strike/vol inputs — an endpoint-normal Φ estimate exists on
every in-window record today (diagnostic-only, not labeled as a forecast).

### Hypothesis dispositions (per operator's list)

| hypothesis | verdict |
|---|---|
| insufficient historical observations | REJECTED — EWMA is asset-keyed, ≥60 samples/120s span; spans rollovers |
| stale underlying-price data | orthogonal; 60s tick-age gate exists; ref was 955ms fresh on the failing trace |
| sequence-gap contamination | separate layer (`confidence_valid`); not the vol_source path |
| **explicit TTE-dependent branch** | **CONFIRMED — trade_decision.py:3948, before vol/forecast** |
| timestamp/window alignment | no evidence |
| unit mismatches (s vs annualized) | none found — SECONDS_PER_YEAR consistent both paths |
| **fallback converts missing p → 0.5** | **CONFIRMED — `_no_trade` p=0.5 placeholders (3867–3870)** |

Additional finding: `_resolve_annualized_vol` builds a `tried` list
(1428–1442) of attempted sources and **discards it** — branch-attempt
telemetry was half-built and never wired out.

## 2. Failing vs valid decision trace (live, 2026-11-06 02:29–02:30 UTC)

**FAILING** — `logs/lwf_shadow.jsonl`, DOGE `KXDOGE15M-26NOV052130-30`,
`cand_8a06db7f0c3f6af4f57c9091:maker`, tte=125.08s:

```
engine_decision_reason = "min_tte_entry_disabled"
model_evaluation_completed = false      probability_status = "INPUTS_MISSING"
missing_input_fields = ["vol_source"]   p_calibrated_side = 0.5   p_raw_side = null
z_score_model = null   log_moneyness = null   fe_final_p_* = null
annualized_vol = 0.5116   vol_source = null        # vol present, label missing
strike = 0.072057   ref_price = 0.0720311 (cfb_rti_live, 955ms)   spot = 0.07199
quote_age_ms = 297   yes ask/bid = 21/20
q_phi_diagnostic = 0.6379   sigma_rem_frac = 0.001019   trend = "expanding"
engine_would_reject_tte = true
```

**VALID-CONTRAST A (same starved TTE region, vol resolved+labeled)** —
`logs/late_window_shadow.jsonl`, BTC `KXBTC15M-26NOV052130-30`, tte=60.2s:

```
annualized_vol = 0.4998   annualized_vol_source = "realized"
strike = 76043.02   spot = 76035.51   rejection_reason = "tte_entry_cutoff"
```

**VALID-CONTRAST B (upstream p refreshing below 180s)** —
`logs/pinned_fav_maker_shadow.jsonl` sequence on KXDOGE15M-26OCT312015-15:
p_selected 0.723→0.853 across 180→157s, source `market_state.model_fair_prob`.

Conclusion: inputs (vol, ref, strike, spot, book) and an upstream
uncalibrated p all exist at 120–150s. The missing object is the
decision-level calibrated forecast — gated, not unavailable.

## 3. Repair spec — shadow/instrumentation only

### R1. Fix the vol_source label (lwf_shadow call sites) — coherent bundles only

At `agent_grid_15m.py` post-engine site (10506) and the pre-engine site
(16421+), do NOT independently pick the first non-null vol value and the
first non-null source label. The fallback must carry a coherent resolution
bundle:

```
{vol_value, vol_source, resolved_at_ts, asset, ticker/context_id,
 vol_pre_clamp, vol_post_clamp, resolution_id (or equivalent lineage)}
```

Precedence: the decision's own bundle first (when it exists); otherwise
exactly one complete caller/context bundle (`market_state` block or
`_last_signal_vol_context`). Never attach a current source label to an older
value, or vice versa. If the bundle's identity/timestamp does not match the
record being written, treat the field as missing and mark it so.

**Acceptance: every successful shadow forecast identifies the exact
volatility resolution it used (value + source + timestamp + lineage).**

### R2. Shadow-side forecast fields (no engine change)

In `lwf_shadow_lane.py`, alongside the existing `q_phi_diagnostic`, emit a
first-class shadow forecast computed from the record's own inputs via
`_compute_bachelier_components(spot_basis, strike, tte, resolved_vol)`:

- `p_shadow_bachelier`, `z_shadow`, `log_moneyness_shadow`,
  `spot_basis ∈ {settlement_avg, rti_tick}` plus the selected input's
  **identity and timestamp** (e.g. `ref_price` + `ref_price_ts_utc`, or the
  RTI observation's source/observed ts), `vol_value`,
  `vol_source_resolved`, `vol_resolution_branches`.
- **Measurement basis vs settlement-target semantics.** The replay must
  distinguish (a) a forecast using the current RTI tick, (b) a forecast
  using an available settlement-related input (60s average /
  `settlement_input_price`), and (c) the precise settlement target each
  forecast is intended to estimate (final-minute average vs strike — not
  "spot>strike at close"). Records are not pooled merely because both use
  `_compute_bachelier_components`: before comparing calibration or
  economics, establish that each input/model combination estimates the
  same event. Sharing the model *form* is not evidence the result is a
  validated probability below 180s.
- This is the ENGINE's own model form (lognormal digital + Ito term,
  1241–1250), not a new model. It is still **uncalibrated** — the
  tail-cap/EPC calibration applied to p_raw→p_calibrated (8389–8398) has no
  low-TTE analog; calibration must be applied offline at replay from the
  loaded artifact, and reported as `p_shadow_calibrated_replay` distinct
  from any live field.
- Extend coverage: lwf env knobs (`MERID_LWF_TTE_LO_S=120`,
  `_TTE_HI_S=150`) → add records for the 90–120 and 150–180 pockets the
  pf audit flagged uninstrumented; extend pf-maker shadow band toward the
  live 94–98 window. Shadow config only — no entry-path effect.

### R3. Vol-resolution branch telemetry

`_resolve_annualized_vol`: wire out the existing `tried` list with per-branch
failure reasons — `env_override:{set|parse_error}`, `realized:{ok|None:
no_estimate|stale|insufficient_span|zero_var|exception}`,
`market_implied:{ok|None: atm|extreme_prob|direction_disagree|invalid_tte}`,
`default:{requested}`. Include `resolved_vol_pre_clamp`, band (mn,mx),
`clamped` flag. One structured log/indicator dict per call — enables the
operator's "resolution" instrumentation row verbatim.

For `p_shadow_calibrated_replay`, persist alongside every transformed value:
calibration artifact id/version, training-data cutoff, the artifact's
supported domain (assets, probability range, TTE range), and a boolean
`within_supported_domain` for the record. Loading an existing artifact does
not qualify a low-TTE forecast as validated — report **raw**, **replay-
transformed**, and **in-supported-domain** results as separate columns.

### R4. Fix the `unknown` backfill cohort

`late_window_shadow` `annualized_vol_source="unknown"` = 4,067 records
(concentrated 50–70s): `_last_signal_vol_context` empty on those paths —
`_compute_signal_vol_context` either not invoked on that rejection route or
excepted (strike resolution → {}). Make the vol context resolution
unconditional per (asset, ticker) evaluation and record its own failure
reason instead of silently writing 0.0/"unknown".

### R5. Freshness provenance on reused fields

Every record carrying `market_state.model_fair_prob` or `_last_signal_vol_context`
fields must also persist `model_fair_prob_ts` / context build ts so replay
can separate fresh-below-180 estimates from stale carryover.

### What this does NOT change

- Engine gate order (3948 stays exactly where it is); `min_tte_entry_disabled`
  remains the decision verdict below 180s.
- `p_calibrated` semantics: a `0.5` placeholder stays distinguishable from a
  computed 0.5 only via `probability_status`/markers — R1–R2 make that
  separation legible; no field is repurposed.
- Fail-closed: missing/invalid inputs still produce INPUTS_MISSING records
  and vetoes; the repair adds measurement, not admission.

## 4. Acceptance criteria

1. Shadow records at 90–180s carry `vol_source` (no `vol_source`-only
   INPUTS_MISSING artifacts) and a shadow Bachelier forecast with explicit
   spot basis, or an explicit per-input failure reason.
2. Point-in-time replay: every field reconstructable from asof data; no
   future observations (verify by re-deriving a sampled record's
   `p_shadow_bachelier` from stored inputs).
3. Unit tests at TTE {181, 180, 150, 149, 121, 120, 119, 90, 89, 30}s —
   boundary records exist for both sides of 120/150/180; `seconds` vs
   `t_years` conversion covered.
4. `probability_status` taxonomy unchanged; p=0.5 placeholder and computed
   0.5 remain distinguishable.
5. Recompute the 120–150s maker-band counterfactual on the repaired cohort;
   report side-by-side vs the +0.65c/97% figure before any policy question
   is reopened.
6. `late_window` unknown-source share measured before/after R4.
7. **No change to admission behavior.** `ENTRY_MIN_SECONDS_TO_EXPIRY`, lane
   floors, gate order, and routing are untouched; the resolver telemetry
   (R3) may touch production code but must be observational only — verified
   by replay-equivalence of the decision path on recorded inputs.
