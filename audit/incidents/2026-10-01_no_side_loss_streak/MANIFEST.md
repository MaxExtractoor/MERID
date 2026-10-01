# Incident: NO-side loss streak — 2026-10-01

## Frozen at
- build_sha: `9a49e01d973d2f99879522616ce0da9a72eed1fe` (feature/15m-phase01-legacy-removal)
- Bankroll: ~$4.06, drawdown breaker OPEN at 20.10%
- policy_epoch (new): `post_drawdown_2026-10-01`

## The 7 consecutive losses (all fills are TRUSTED_LIVE_V1, post-only maker)

| # | Ticker | Held | Fill (sel-side) | Spot vs ref at decision | Settle | PnL |
|---|--------|------|-----------------|--------------------------|--------|-----|
| 1 | KXBTC15M-26SEP301930-30 | YES | 77c | 83713.96 vs 83710.81 (+0.99σ) | YES=0 | -77c |
| 2 | KXXRP15M-26SEP301945-45 | NO | 55c | 1.48693 vs 1.4874 (-0.35σ) | YES=100 | -55c |
| 3 | KXXRP15M-26SEP302045-45 | NO | 75c | 1.48632 vs 1.4866 (-1.04σ) | YES=100 | -75c |
| 4 | KXETH15M-26SEP302115-15 | NO | 34c | 2684.32 vs 2685.16 (~flat) | YES=100 | -34c |
| 5 | KXXRP15M-26SEP302300-00 | NO | 54c | 1.48858 vs 1.4886 (-0.45σ) | YES=100 | -54c |
| 6 | KXBTC15M-26OCT010000-00 | NO | 42c | 83663.5 vs 83676.1 (~at) | YES=100 | -42c |
| 7 | KXSOL15M-26OCT010000-00 | NO | 34c | 118.40 vs 118.42 (+0.21σ) | YES=100 | -34c |

Total: -371c on ~$4.06 bankroll.

## Forensic verdict (see decision_bundle.json / fills.json)

- **Side inversion: DISPROVED.** Accounting (selected_side <-> sell-YES fill <-> YES=100 -> loss) is
  self-consistent; model sign convention correct (below-strike -> p_no lean, above -> p_yes); the one
  YES pick also lost, ruling out a systematic flip.
- **Root cause cluster:**
  1. Strike-persistence bias — model over-confident that the current side of the strike holds
     (65-84% claims at |z|<1.1 near the money); trending tape crosses the strike frequently.
  2. Adverse selection — every losing fill executed below decision-time ask (filled when informed
     flow hit our resting bid); XRP-2300 30s markout -12.5c vs 0.5c reserve.
  3. Low-conviction entries — BTC-0000 p_no=50.1% (coin flip) entered on price gap alone.
  4. No same-side loss-streak suppression — 6 straight NO losses across assets in one session.
- Counterfactual: opposite side wins 7/7 (mechanical in binary), but every opposite side had
  NEGATIVE claimed net_ev at decision — the gates could never have taken the winning side.

## Artifacts
- `decision_bundle.json` — all 4 audit tables for the 7 decision_ids
- `fills.json` — 8 kalshi_fills rows (XRP-2045 was a 2-part fill)
- `current_build_provisional_lane.json`, `threshold_cell_lane.json` — lane state at freeze
- `live_entry_evidence.json` — evidence floor artifact at freeze
- `regime_attribution_13.json` — full 13-trade win/loss regime attribution
- `replay_verdicts.json` — per-trade verdict of the post_drawdown gates
- Configs: kalshi_15m_thresholds / kalshi_agent_grid / threshold_cells_live /
  live_session_guardrails / risk_limits

## Win/Loss regime attribution (13 trades — regime_attribution_13.json)

| Feature | Wins (n=6) | Losses (n=7) |
|---|---|---|
| p_selected (cal) | mean 0.80, median 0.83 | mean 0.62, min 0.501 |
| \|p-0.5\| | mean 0.30 | mean 0.17 |
| z-score | mean -1.02 (deep ITM) | mean -0.07 (at the money) |
| own r60 | -0.018% | +0.016% |
| breadth60 (pos/5) | 0-2 | 3-5 on 4/7 |
| fill vs decision ask | -0.3c | -2.7c (adverse) |
| net_ev claimed | 4.42c | 3.73c |

Wins were deep-ITM NO buys in flat/falling tape; losses were near-money
entries (6 NO + 1 YES) into a synchronized rally.

## Gate replay (replay_verdicts.json — post_drawdown controls)

| Trade | Result | Gate that would have fired |
|---|---|---|
| All 7 losses | **5/7 blocked** (-219c of -371c) | countertrend_no_rally_regime, side_suspended (streak), low_conviction |
| Unblocked losses | BTC YES -77 (p=0.84, NEUTRAL), XRP NO -75 (p=0.82, NEUTRAL) | none — genuine calibration failures, no state-gate applies |
| 6 wins | 4/6 still trade (+92c of +160c) | — |
| False rejection | XRP +50 at p_no=0.567 | low_conviction (dist 0.067 < delta 0.07 — marginal) |

Conclusions:
- Gates are regime/conviction-selective, not a NO ban: 2 of the unblocked
  losses are high-conviction miscalibration; 1 win is marginally rejected.
- The conviction deltas (BTC/ETH 0.06, SOL/XRP 0.07, DOGE 0.08) are
  provisional — the 0.067-vs-0.07 marginal rejection shows they need
  data-driven calibration, not tightening.
- Countertrend lanes (rally-NO / selloff-YES) stay in cold-start until >=20
  regime-tagged current-build markouts exist (MERID_ASR_COUNTERTREND_MIN_MARKOUTS).
- Side throttle seeded from all 210 settled outcomes: `no` side at 6-loss
  epoch streak and `yes` side at 3-loss epoch streak -> both suspended
  pending manual review. Drawdown breaker remains open.

## Controls shipped (policy_epoch = post_drawdown_2026-10-01)

- `merid/prediction/directional_regime.py` — shared cross-asset regime
  (RALLY_CONFIRMED needs >=4/5 positive 60s RTI breadth + positive BTC),
  conviction distance gate, book-flow confirmation, same-side loss-streak
  suspension (2/60min windowed, 3+ epoch -> manual review), strip
  concentration cap.
- `compute_trade_decision` — all five gates evaluated per side, stamped in
  indicators, AND-ed into yes_qualifies/no_qualifies, surfaced in
  yes_block/no_block and the no_trade_reason chain.
- `current_build_provisional.adverse_selection_reserve_cents` — Q75 of the
  adverse-cost (-markout) distribution, regime-stratified and epoch-scoped,
  floor 1c / cap 5c; `regime_markout_sample_count` backs the cold-start gate.
- `policy_epoch` stamped on strategy_decisions, strategy_decision_outcomes,
  kalshi_fills, cell outcomes, and the throttle state file.
- Settlement hook: `record_side_settlement` fires inside
  `_attribute_settlement` for every newly-settled fill; reconciled
  historicals seeded explicitly via scripts/_seed_throttle.py.
