# Pinned-Fav Calibration Audit — 2026-11-05

Scope: does the model's predicted settlement probability match observed outcomes
*within each execution-price band*, and does the confidence→EV bridge charge each
adjustment exactly once? Dataset: `_pf_audit_decisions.jsonl` (Oct 25–26 extract,
111,395 rows / 1,674 pinned-fav decision rows), deduplicated to **unique
(ticker, side) opportunity episodes** and joined to `settlement_outcomes.jsonl`
(47,809 settled tickers). 90 unique episodes settled.

This is a forecast-calibration result, NOT an executable-profit counterfactual:
maker fillability, taker VWAP, and route-level economics are addressed
separately where data permits.

## 1. Reliability: implied execution price × predicted-probability band

| implied px | p-band | n | win% | mean_p | gap | verdict |
|---|---|---|---|---|---|---|
| 94–98 | p≥0.95 | 18 | 100% | 0.976 | −0.02 | calibrated |
| 94–98 | 0.90–0.95 | 6 | 100% | 0.935 | −0.07 | calibrated (conservative) |
| 90–93 | p≥0.95 | 1 | 100% | 0.978 | — | insufficient (n=1) |
| 90–93 | 0.90–0.95 | 9 | 67% | 0.920 | **+0.25** | **overconfident** |
| 90–93 | 0.80–0.90 | 10 | 50% | 0.882 | **+0.38** | **overconfident** |
| <90 | <0.80 | 40 | 18% | 0.051 | −0.12 | understates underdog* |
| px? / other | — | 6 | — | — | — | unpriced evals |

\* <0.80 cells are mostly the non-selected side's win probability (underdog
evaluation); observed 18% vs predicted ~5% means the model understates the
short side, but these are never traded.

**Headline: the model is calibrated inside the trading band and miscalibrated
one band below it.** In the live 94–98¢ band all 24 settled episodes won —
consistent with the realized 100% contract win rate on fills. At 90–93¢ the
same model claims p=0.88–0.92 and realizes 50–67%. The +0.25/+0.38 gap is the
pin-break failure the model cannot see: it treats a 92¢ favorite the same as a
96¢ one while the settlement distribution is materially different.

**The 94¢ floor is therefore a calibration boundary, not merely an empirical
one.** Loosening the EV haircut or min_p inside 90–93 cannot fix this — the
input probability itself is wrong there. Any future band expansion needs
recalibrated probabilities, not relaxed gates.

By TTE (all prices): p≥0.95 cells won 20/20 at both 180–300s and 300–600s;
no valid-p data exists below ~150s (INPUTS_MISSING) — unchanged conclusion.

Uncertainty: Wilson 95% CI on the 94–98/p≥0.95 cell is [0.81, 1.00] (18/18) —
24 wins supports ≥~0.86 lower bound, i.e. the sample is consistent with the
model but too small to certify p=0.98 against a true 0.90.

## 2. Confidence→EV ledger (pf ENTER decisions)

Reconstructed per row: `implied_px = p·100 − gross_edge`; `costs = gross − net`.

| p | implied_px | gross¢ | costs¢ | net¢ | min_p |
|---|---|---|---|---|---|
| 0.910 | 93.00 | −1.99 | 2.61 | −4.60 | 0.982 |
| 0.910 | 93.00 | −1.99 | 5.68 | −7.67 | 0.987 |
| 0.944 | 95.00 | −0.64 | 1.47 | −2.11 | 1.005 |
| 0.944 | 95.00 | −0.64 | 5.97 | −6.61 | 1.010 |
| 0.910 | 92.00 | −0.96 | 7.09 | −8.05 | 1.031 |

Findings:
- **The cost adder is state-dependent, not constant** — 1.47¢ to 7.09¢ on
  identical (p, price) economics. The variable component is the
  adverse-selection/spread/vol haircut fluctuating with book state. It is NOT
  a flat ~2c fee: audits must model it as `costs(p, px, book_state)`.
- `min_p_selected` is a **derived breakeven probability** (price+costs → p*),
  frequently > the lane floor of 0.90. The pf lane's bounded-lane override
  admits p≥0.90 even where the generic cost-basis gate demands p≥~1.0 —
  expected behavior for BOUNDED_POST_ONLY_LANES, but it means the lane
  systematically enters at *claimed* negative EV.
- No double-charging was observed within a single row (one cost adder), but
  the adder's internal composition (fee + haircut + ?) needs decomposition
  instrumentation — the components are not separately logged.

## 3. Realized & veto-interaction evidence

- Unique ENTER episodes (Oct 25–26): **45 settled, 37 won (82%)** — the losses
  are the below-floor 90–93¢ cohort, consistent with −1020¢ realized on
  85–93¢ fills. In-band episodes: 24/24 (100%).
- Per-row veto tallies (independently-applicable failures on pf rows):
  generic `positive_ev`(1598), `cost_basis`(1644), `edge_threshold`(1646),
  `yes_moneyness`(1674), `no_*` gates (~all) fail even on ENTERed rows —
  bounded-lane override is by design. `no_book_flow`(514),
  `book_trusted`(65), `no_depth`(66) — integrity gates fire in-lane.
- Polling inflation confirmed: 1,674 ENTER rows = 45 episodes (~37 evals per
  episode). Any per-row statistic must dedupe by (ticker,side) or market
  episode to avoid ~37× overcounting.

## 4. Four-confidence-layer separation

| layer | current implementation | audit verdict |
|---|---|---|
| data integrity | `confidence_valid` → orderbook_sequence_gap/not_initialized/stale | retain fail-closed; repair recovery |
| probability calibration | `p_selected` (Bachelier+tail-cal) | calibrated 94–98¢; overconfident 90–93¢; no valid p <~150s TTE |
| estimation uncertainty | `min_p_selected` breakeven + lane floors | not an interval estimate; no per-p uncertainty is logged |
| execution confidence | bid-basis maker EV, state-dependent haircut | fill-conditional p not modeled; haircut variance unexplained |

## 5. Dispositions (per reviewer matrix)

- 94¢ floor: **RETAIN** — now supported as a calibration boundary.
- 35% stake cap: **RETAIN** (unchanged by this audit).
- EV floor/haircut in-band (94–98): **COLLECT MORE EVIDENCE** — p is calibrated
  but the claimed net-EV is systematically negative on winners (admitted via
  bounded-lane override); the haircut's state-dependent composition must be
  decomposed before adjusting.
- Any 90–93¢ change: **REJECT** — model p is overconfident +0.25/+0.38 there;
  no gate relaxation can fix a wrong input.
- invalid_confidence/book vetoes: **RETAIN** — integrity layer unchanged.
- min_p floor 0.90: **COLLECT MORE EVIDENCE** — the 0.90–0.95 in-band cell is
  6/6 but tiny; the floor's real work is excluding the sub-0.90 evals that
  would be miscalibrated.
- Shadow expansion (94–98 in-band, 90–120/150–180s TTE): **REQUIRED** before
  any calibration change — current evidence rests on 24 in-band episodes.
- Stage B sizing clip: **verify live trace** on next restart per §1 caveat
  (patch committed, not yet running).

## 6. Evidence limitations

- 90 unique settled episodes is small; CIs are wide except directionally.
- Extract covers Oct 25–26 only; Nov 1–5 decisions were not extracted (DB
  contention). Reliability should be re-run on the full window once the
  decision export completes.
- `implied_px` is reconstructed from `p·100 − gross_edge` (assumes the gross-
  edge definition); if the codebase defines gross edge differently, price
  bands shift. Verify against the EV code before treating band boundaries as
  exact.
- Fill-conditional maker outcomes and taker VWAP are not measurable from
  decisions alone — requires the expanded shadow/execution logging in the
  pending Stage-C work.
