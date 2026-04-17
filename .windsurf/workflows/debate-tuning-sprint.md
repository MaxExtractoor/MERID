---
description: Sprint 8 — Debate Protocol Tuning + Incentive Alignment
---

# Sprint 8: Debate Protocol Tuning + Incentive Alignment

## Context

Sprint 7 built the debate/teamwork/rewards infrastructure:
- `DebateCoordinatorAgent` orchestrates proposer→challenger→arbiter debates
- `DebateStore` persists sessions, arguments, teams, rewards with SQLite
- `ChallengerStrategy` and `ArbiterStrategy` generate counter-opinions and synthesized estimates
- Reward system awards points for accuracy, debate lift, explanation, timeliness
- Leaderboard + 5 badge types + 2 observability alert rules (no_debate, negative_lift)
- 72 tests passing, 12 alert rules total

The infrastructure is in place. This sprint **validates that debate actually improves accuracy** and **aligns incentives with truth-finding behavior**, using the metrics and Brier history already available.

---

## Part A: Protocol Tuning & Validation (7 tasks)

### A1. Debate Backtest Harness
**Goal:** Replay resolved markets through the debate protocol and measure debate lift empirically.

**Changes:**
- Add `DebateBacktester` class in `merid/prediction/debate.py` (or new `debate_backtest.py`)
- Takes a list of resolved markets (symbol, market_prob, outcome) from `PredictionConsensusStore`
- Runs each through `DebateCoordinatorAgent.run_debate()` with configurable strategy combos
- **Log which agent_ids and team_ids are used in each backtest run** so results map to realistic debate configurations (e.g., mean_reversion proposer vs calibration_aware proposer), not just abstract combos
- Computes aggregate stats: mean debate lift, % of markets where debate improved Brier, worst-case lift, per-agent/team breakdown
- Returns a structured report dict with agent-level and team-level lift attribution

**Tests:** backtest with synthetic resolved markets, verify lift computation, verify agent/team attribution, edge cases (all same prob, extreme probs)

### A2. Arbiter Strategy Variants
**Goal:** Test alternatives to the current confidence-weighted blend.

**Add to `merid/prediction/opinion_strategy.py`:**
- `BayesianArbiterStrategy` — treats proposer/challenger as independent signals, updates via Bayes rule
- `ExtremizingArbiterStrategy` — pushes the blended estimate further from 0.5 (research shows groups under-extremize)
- `MedianArbiterStrategy` — simple midpoint between proposer and challenger (baseline)

**Each must:**
- Implement the same `OpinionStrategy.estimate()` interface
- Produce `OpinionExplanation` with rationale
- Be registered in the strategy registry

**Tests:** verify each variant produces valid estimates, compare Brier on synthetic data

### A3. Adaptive Challenger Strength
**Goal:** Make the challenger's opposition strength depend on context, not a fixed pull.

**Changes to `ChallengerStrategy`:**
- Add `adaptive_strength` mode (default: True)
- When adaptive: opposition strength scales with (1 - proposer_confidence) × historical_accuracy_of_proposer
  - Low-confidence proposer → stronger challenge
  - Historically inaccurate proposer → stronger challenge
- Accept `proposer_historical_brier` in context dict (optional, falls back to fixed strength)

**Tests:** verify adaptive vs fixed behavior, edge cases

### A4. Debate Quality Gate
**Goal:** Suppress arbiter output when the challenger isn't adding signal.

**Changes to `DebateCoordinatorAgent.run_debate()`:**
- After challenger generates estimate, compute `disagreement_width = |proposer_prob - challenger_prob|`
- If `disagreement_width < min_disagreement` (default 0.03), skip arbiter and return proposer's estimate as post_debate_prob
- Log "debate_suppressed_low_disagreement" when this happens
- Add `debate_suppressed` boolean to the result dict

**Tests:** verify suppression at low disagreement, non-suppression at high disagreement

### A5. Strategy Combo Evaluation
**Goal:** Find which proposer×challenger×arbiter combinations maximize debate lift.

**Changes:**
- Add `evaluate_strategy_combos()` to `DebateBacktester`
- Tests all registered proposer strategies × arbiter variants
- **Each combo run logs the concrete agent_ids and team_id used**, so results are traceable to specific agent configurations (e.g., "mean_reversion proposer + bayesian arbiter on team-alpha")
- Returns ranked list of combos by mean debate lift, with per-agent attribution
- Stores results in a structured dict for API exposure

**Tests:** verify combo enumeration, ranking logic, agent/team attribution in results

### A6. Reward Parameter Sensitivity
**Goal:** Understand how reward constants affect agent behavior incentives.

**Changes:**
- Add `RewardParameterSweep` class
- Varies the 5 reward constants (ACCURACY_BASE, BRIER_BONUS, DEBATE_LIFT_BONUS, EXPLANATION_BONUS, COOPERATION_BONUS)
- For each parameter set, computes total rewards for a synthetic agent history
- Reports which parameters most affect the ranking of "accurate debater" vs "spammy participant" vs "silent accurate agent"

**Tests:** verify sweep produces valid results, parameter sensitivity is non-zero

### A7. Debate Lift Regression Test
**Goal:** Ensure future changes don't degrade debate lift.

**Changes:**
- Add `test_debate_lift_regression.py` with golden-value tests
- Pin expected Brier improvement for known synthetic scenarios
- If mean debate lift drops below a threshold (e.g., 0.0), fail the test with a clear message

**Tests:** golden-value assertions for each arbiter variant

---

## Part B: Incentive Alignment (6 tasks)

### B1. Accuracy-Gated Debate Rewards
**Goal:** Only award debate_lift bonus when the agent's individual Brier also improved.

**Changes to `DebateStore.compute_rewards_for_resolution()`:**
- Before awarding debate_lift bonus, check that the agent's own probability was closer to outcome than the pre-debate swarm prob
- Add `individual_lift` field to the reward detail string
- If agent's Brier > pre_debate Brier, skip debate_lift bonus (they free-rode)

**Tests:** verify gating logic, edge cases

### B2. Time-Decay for Leaderboard Points
**Goal:** Prevent stale accuracy from dominating leaderboards.

**Changes to `DebateStore.compute_leaderboard()`:**
- Apply exponential decay: `effective_points = points × exp(-λ × age_days)` where λ = 0.03 (half-life ≈ 23 days)
- Add `decay_lambda` parameter to `compute_leaderboard()`
- **Expose `MERID_LEADERBOARD_DECAY_LAMBDA` as a setting in `merid/settings.py`** (default 0.03) so the half-life can be tuned via config/env without code changes
- **Surface current decay_lambda in `/system/observability` → `collaboration_health` section** so operators can see the active decay rate
- Raw points still stored; decay applied at query time only

**Tests:** verify decay reduces old rewards, recent rewards unaffected, config override works

### B3. Anti-Spam Gates for Debate Rewards
**Goal:** Require minimum quality to earn debate rewards.

**Changes to `DebateStore.compute_rewards_for_resolution()`:**
- Require `disagreement_width >= 0.03` for debate_lift bonus (no reward for trivial debates)
- Require explanation attached for explanation bonus (already done) AND rationale != empty
- Add `min_disagreement_for_reward` parameter (default 0.03)

**Tests:** verify spam rejection, legitimate debates still rewarded

### B4. Tiered Badges
**Goal:** Bronze/silver/gold thresholds for each badge type.

**Changes to `DebateStore.compute_badges()`:**
- Each badge now has 3 tiers with escalating thresholds:
  - `explainer`: bronze (60%), silver (80%), gold (95%)
  - `debate_champion`: bronze (1× threshold), silver (3×), gold (5×)
  - `reliable_contrarian`: bronze (3× threshold), silver (5×), gold (10×)
  - `consensus_builder`: bronze (3 debates), silver (5), gold (10)
  - `team_player`: bronze (1× threshold), silver (2×), gold (4×)
- Badge dict includes `tier` field: "bronze", "silver", "gold"

**Tests:** verify each tier for each badge type

### B5. Team Composition Scoring
**Goal:** Reward strategy diversity within teams.

**Changes:**
- Add `compute_team_diversity_score()` to `DebateStore`
- Measures how many distinct strategies team members use (from debate arguments)
- Teams using only 1 strategy get diversity_score = 0.0
- Teams using 3+ strategies get diversity_score = 1.0
- Add `diversity_bonus` reward type: `REWARD_DIVERSITY_BONUS × diversity_score`
- Wire into `compute_rewards_for_resolution()` for team members

**Tests:** verify scoring for 1-strategy, 2-strategy, 3+ strategy teams

### B6. Calibration-Based Rewards
**Goal:** Reward agents whose probability estimates are well-calibrated across buckets.

**Changes:**
- Add `compute_calibration_score(agent_id)` to `DebateStore` — **this becomes the single source of truth** for all calibration-related features (badges, rewards, UI, future calibration plots)
- **Reuse existing Brier history from `PredictionConsensusStore.compute_brier_scores()`** to pull resolved opinions rather than re-querying; accept an optional `brier_data` dict to avoid redundant DB hits
- Buckets agent's historical predictions into 10 bins (0.0-0.1, 0.1-0.2, ..., 0.9-1.0)
- For each bin, computes actual outcome rate vs predicted probability
- Calibration score = 1 - mean absolute calibration error
- Returns full calibration curve (bin edges, predicted_mean, actual_rate, count) alongside the scalar score — reusable by any future UI or badge logic
- Add `calibration_bonus` reward type: awarded when calibration_score > 0.8
- Wire into `compute_rewards_for_resolution()`

**Tests:** verify calibration computation, bonus gating, reuse of Brier data, edge cases (few predictions, empty bins)

---

## Part C: Integration (3 tasks)

### C1. API Endpoints for New Features
- `GET /consensus/debate-backtest` — run backtest and return results
- `GET /consensus/strategy-combos` — ranked strategy combinations
- `GET /consensus/calibration/{agent_id}` — agent calibration curve

### C2. Observability Updates
- Add `debate_quality` section to `/system/observability` (suppression rate, avg disagreement, combo rankings)
- Add `DebateLiftRegressionAlert` — fires if rolling mean debate lift < 0

### C3. Tests + Makefile + AUDIT_REPORT §22
- Comprehensive tests for all new features
- `debate-tuning-test` Makefile target
- §22 in AUDIT_REPORT.md documenting the sprint

---

## Execution Order

1. A1 (backtest harness) — needed by A5, A6, A7
2. A2 (arbiter variants) — needed by A5
3. A3 (adaptive challenger) — independent
4. A4 (quality gate) — independent
5. A5 (combo evaluation) — depends on A1, A2
6. B1 (accuracy-gated rewards) — independent
7. B2 (time-decay) — independent
8. B3 (anti-spam gates) — independent
9. B4 (tiered badges) — independent
10. B5 (team diversity) — independent
11. B6 (calibration rewards) — independent
12. A6 (reward parameter sweep) — depends on B1-B6
13. A7 (regression test) — depends on A1, A2
14. C1 (API endpoints) — depends on A1, A5, B6
15. C2 (observability) — depends on A4, A7
16. C3 (tests + docs) — last

## Key Principles

- **Empirical over theoretical** — every tuning decision backed by Brier score comparison on real/synthetic data
- **No new plumbing** — extend existing DebateStore, strategies, and observability; don't create parallel systems
- **Incentive alignment** — reward truth-finding, not participation volume
- **Regression safety** — golden-value tests prevent future degradation
- **Same spine** — all new features plug into the opinion/consensus/observability backbone
