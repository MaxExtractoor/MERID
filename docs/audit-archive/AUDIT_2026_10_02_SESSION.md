# MERID Session Audit — 2026-10-02 (8h, 5 trades, 2W/3L)

**Scope:** live server under `profile=kalshi_crypto_15m_v2`, `policy_epoch=post_drawdown_2026-10-01`.
**Sources:** `logs/fill_quality.jsonl`, `bankroll_reconciliation.jsonl`, `settlement_outcomes.jsonl`,
`order_decisions.jsonl`, `decision_telemetry.jsonl*`, `rejected_candidates.jsonl` (541,988 rows,
2026-08-31→10-02), `threshold_cell_lifecycle.jsonl`, `exit_evaluations.jsonl`, `stop_candidates.jsonl`,
`late_window_shadow.jsonl`, `full.log*`.
Equity: $9.59 → $8.62 (**-97¢ net**, ~-10% of account). Ledger reconciles exactly — every fill/settle
matched bankroll with `equity_diff=0.0`, no side-inversion or unit bug.

## The five trades

| # | Ticker (ET window) | Side | Paid | Model p | Outcome | P&L | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | KXXRP15M-26OCT020230-30 | BUY_NO | 50¢ | 0.597 | yes | **-50¢** | legit model miss + toxic fill |
| 2 | KXETH15M-26OCT020300-00 | BUY_YES | 69¢ | 0.753 | no | **-69¢** | legit miss; thin edge (1.98¢) |
| 3 | KXSOL15M-26OCT020500-00 | BUY_YES | 31¢ | 0.389 | no | **-31¢** | legit miss; phantom-edge cheap YES |
| 4 | KXXRP15M-26OCT021100-00 | BUY_NO | 77¢ | 0.858 | no | **+23¢** | deep-ITM trend-aligned — the profile that wins |
| 5 | KXXRP15M-26OCT021145-45 | BUY_NO | ~70¢ | 0.762 | no | **+30¢** | same |

**Loss legitimacy:** no infrastructure defect in any of the 5. The losses are model misses inside
expected base rates (p 0.39–0.75 ⇒ 25–60% loss probability is the *expected* outcome frequency).
Pattern matches yesterday's forensic: wins = deep-ITM (≥76¢) trend-aligned NO buys; losses =
near-money or cheap-side fades. All three losing fills show negative 30s markouts (-9.5, -2.5¢,
and ETH recovered then collapsed) — passive entries filling as price moves *through* them, i.e.
classic adverse selection, exactly what `directional_regime.py` was built to prevent — but the
regime gate only blocks countertrend entries in *confirmed* regimes, and none of the three losses
was countertrend in a confirmed regime at fill time.

**Salvage check:** exits are evaluated (`EDGE_DECAY`/`expiry_liquidation`) but no hard stop-loss
fired. All three losers rode to 0. A hard stop at -8..-10¢ would have cut the day to roughly
breakeven-to-small-loss.

## Why only 5 trades — the funnel (today, telemetry-covered window)

- ~15k decision evals in ~5h of telemetry (≈1 eval/asset/6s)
- 25 intents admitted (`order_decisions.jsonl`)
- ~10 exchange orders (`order_entry` events)
- 5 fills (≈20% of intents → fill)

Terminal codes (all rotated telemetry): NO_POSITIVE_EXECUTABLE_EDGE 7,823 · NO_ELIGIBLE_PRICE_BAND
3,909 · TTE_ENTRY_CUTOFF 1,411 · EDGE_BELOW_DYNAMIC_THRESHOLD 1,150 · MARKET_UNAVAILABLE 589 ·
BOOK_NOT_TRUSTED 46 · CANDIDATE_EMITTED 16 · EVIDENCE_HARD_BLOCK 13 · RISK_OR_ALLOCATION_REJECT 6.

### Ranked constraints on trade count

1. **Edge threshold binds ~96% of evals.** Required edge ≈ 2.5–4¢+ (formula floor 2.5¢ + convexity +
   band premiums). The counterfactual report over all history says this is *miscalibrated ~2–3¢
   too tight*: candidates 0–1¢ below the gate are **+3.76¢/trade net** (n=17,315); 1–2¢: +2.96
   (n=21,375); 2–3¢: +2.69 (n=24,455); only the ≥3¢ band is flat (-0.06). Held-price decomposition:
   rejected candidates at 50–89¢ were hugely profitable (+37k…+137k cents per bucket); <50¢ and
   90-99¢ correctly rejected (negative). The gate is doing its job at the extremes and
   over-rejecting deep-ITM (the band that actually wins).
2. **Evidence cold-start starvation.** Evidence verdicts today: SPARSE_MATCHED_INSUFFICIENT 10,676 /
   SOFT_PENALTY 4,106 / CHALLENGE 1,884 vs ~1,308 total passes. Cells need live fills to build n_eff;
   gates block fills. `escape_daily_max=12`, only **4 used today** — the cap isn't the binding
   constraint, the per-cell n_eff≈0 loop is.
3. **Router re-check kills ~half of admitted intents.** `fill_adjusted_edge_below_threshold` fired
   ~32× today (e.g. SOL 0830: decision edge 3.5¢ → repricer moved 31→worse → fill_edge 1.9¢ < 3.46¢
   → rejected pre-submit). Structural double-jeopardy: repricer moves price toward mid for fill
   odds, which erodes the edge the second gate then enforces.
4. **Execution/label mismatch.** Every admission lane forces `post_only=True` — including
   `:taker` candidates that were edge-evaluated *net of the ~0.9–1.7¢ taker fee*. Worst of both:
   taker-fee haircut in admission, maker uncertainty in execution. Today's 3 unfilled orders
   (DOGE 0200, BTC 0215, XRP 0930) all expired `rest_ttl_expired` while running +9¢/+19.5¢/+8.5¢
   markouts — all three *settled in their favor* (≈+78¢ foregone).
5. **Structural caps.** Sequential + $2 fixed exposure cap; entry window t≈2–10min only
   (TTE_ENTRY_CUTOFF + price-band eligibility remove ~35% of evals); 1-contract clips.
6. **Feed health.** 1.08M WS orderbook sequence gaps (`total_gaps`); spot staleness observed at
   23.8s on DOGE. Drives MARKET_UNAVAILABLE/BOOK_NOT_TRUSTED rejects and stale-snapshot repricer
   aborts.

### Minor defects (cosmetic/telemetry)

- `resting_ms` negative on several fills (fill ts precedes recorded entry ts — clock/ordering bug).
- `fill_price_cents` unit inconsistency on BUY_NO fills (records YES-complement, e.g. limit 82 →
  fill 18). Ledger interprets via "yes sell @X" semantics and reconciles correctly, but the field
  mixes units and will mislead any consumer that reads it literally.
- `series_ticker`/`asset` fields sometimes blank in settlement outcomes (`KXXRP-15M`, asset "").

## External research applied

- **botforkalshi 15m study (6,298 windows):** buying the leading side nets +0.67¢ gross vs ~1.55¢
  avg taker fee → crossing the spread is structurally -EV; maker fee on this series ≈ 0.
  Validates post-only *preference* but only with toxicity cancels.
- **arXiv 2502.18625 (maker fill/return trade-off):** maker fill probability is negatively
  correlated with post-fill return ("negative drift of maker orders") — exactly the observed
  markout signature. Mitigation = cancel/requote on adverse signal + an extra side signal,
  not passive abandonment.
- **Vela (github.com/routsiddharth/vela):** KX*15M settles on a **60s TWAP**, not the last tick —
  once most of the 60 samples print, the outcome is near-determined while the book still quotes
  live. MERID blocks entries below `MERID_ENTRY_MIN_SECONDS_TO_EXPIRY=180` — the structural edge
  sits inside the excluded zone.
- **kalshibacktest depth profile:** depth peaks 5–7min into the window, collapses 60–70% in the
  final 60s. The middle band (MERID's t300–600 cells) is the right venue; last-minute entries
  need a different (TWAP-aware) model, not the velocity/regime model.

## Recommendations (priority order)

**P0 — trade count, low risk, config-level:**
1. Loosen the edge gate ~1–2¢ **only in the 50–89¢ held-price band** (counterfactual-backed). Do
   not loosen <50¢ or ≥90¢.
2. Make `:taker` intents actually take — marketable limit/IOC at the ask — when edge clears the
   taker fee by ≥2¢. Converts the ~40% of taker intents that currently rest-and-miss.
3. Raise `MERID_EVIDENCE_ESCAPE_DAILY_MAX` 12→24 and let `bounded_live_execution_validation`
   admit one canary per sparse cell per window. Breaks the n_eff=0 → no-fills → n_eff=0 loop.
4. Reconcile repricer vs fill-edge gate: evaluate edge *at the repriced limit* (worst-case fill),
   or freeze price once admitted — today they fight each other pre-submit.

**P1 — loss prevention:**
5. Mid-flight cancel on resting entries when mid crosses the limit with momentum against the
   position (the `bookflow`/`rti` signals already exist at entry; reuse them post-entry). The
   XRP-0230 fill (−50¢) filled on a break with −9.5¢ 30s markout — avoidable.
6. Hard stop-loss at −8..−10¢ (profile `dynamic_risk` already defines 6–10¢ bands; it's not wired
   to execution). Would have turned today's −150¢ of losses into ~−25¢.

**P2 — throughput:**
7. Fix WS bridge sequence-gap storm (1.08M gaps) — resync on gap, fall back to REST poll when
   book uninitialized.
8. Widen TTE: add a t90–180s shadow band first (late_window_shadow already logs these —
   join it to outcomes before enabling live).
9. More surface area: the 5-asset × 15m grid yields ~20 windows/hr; consider hourly crypto
   binaries and/or more 15m assets once fill rate improves.

**Data caveat:** marginal-band counterfactuals assume fills at `held_price_cents`; real fill rates
on resting orders are lower and adversely selected — treat +3.76¢/trade as an upper bound, but the
sign and band shape (deep-ITM profitable, cheap correctly rejected) are robust.
