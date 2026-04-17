# Sentiment & Confidence Flow Map

*Last updated: 2026-04-09 — Phase 23 audit*

This document is the authoritative end-to-end description of how raw sentiment
observations move through the MERID stack and ultimately influence Kalshi orders
and what operators see. Read this before changing any threshold, weighting
formula, or UI label in the sentiment/confidence pipeline.

---

## 1. Upstream: Sentiment Sources

### 1a. Fear/Greed Index (0–100, global market mood)

| Step | Location | Output |
|------|----------|--------|
| External CFGI / Kalshi API poll | `merid/sentiment/cfgi_client.py` | `fg_index: int` (0–100) |
| MarketMoodBus update | `merid/swarm/market_mood_bus.py` | `SentimentContext.fg_index` (0–100) |
| Snapshot injection | `merid/prediction/trading_agent.py:834` | `MarketSnapshot.sentiment_global` (0–100) |
| Strategy size factor | `merid/prediction/strategy.py:218–230` | `size_factor ∈ [0.35, 1.0]` (downside-only) |

**Scale:** 0 = extreme fear, 100 = extreme greed.  
**Usage:** `≤20 or ≥80` → `size_factor × 0.5`; `≤30 or ≥70` → `× 0.75`.

### 1b. Social Sentiment (Twitter / Reddit, −1 to +1)

| Step | Location | Output |
|------|----------|--------|
| Twitter poll (2 min interval) | `merid/sentiment/sentiment_bus.py` | `UnifiedSentiment.twitter_score` (−1 to +1) |
| Reddit poll (5 min interval) | `merid/sentiment/sentiment_bus.py` | `UnifiedSentiment.reddit_score` (−1 to +1) |
| Volume-weighted combination | `merid/signals/sentiment_integration.py:242–259` | `SentimentMetrics.combined_sentiment` (−1 to +1) |
| Confidence gate | `merid/signals/sentiment_integration.py:261–274` | `SentimentMetrics.confidence` (0–1, data-volume proxy) |
| Signal creation | `merid/signals/sentiment_integration.py:276–297` | Only if `|sentiment| > 0.3 AND intensity > 0.2` |

**Scale:** +1 = fully bullish social mood, −1 = fully bearish.

### 1c. News / FinBERT (−1 to +1 per article)

| Step | Location | Output |
|------|----------|--------|
| Headline scoring (FinBERT or VADER fallback) | `merid/sentiment/news_sentiment.py` | `NewsSentimentResult.sentiment_score` (−1 to +1) |
| 24h article aggregation | `merid/signals/sentiment_integration.py:168–219` | Average weighted by article count |
| Intensity proxy | `merid/signals/sentiment_integration.py:210` | `intensity = min(1.0, article_count / 50)` |

**NOTE:** `SentimentMetrics.confidence` here means *"how much data do we have"*, not
*"how correct is the model"*. Downstream code that reads `AgentProposal.confidence`
uses a different semantic (see §3 below).

### 1d. Kalshi Market Microstructure

| Step | Location | Output |
|------|----------|--------|
| Implied probability | `merid/prediction/model.py:implied_probabilities()` | `ImpliedProbability.yes_prob` (0–1) |
| Edge estimate | `merid/prediction/model.py:compute_edge()` | `EdgeEstimate.net_edge` (Decimal cents), `confidence` (0–1) |
| Spot–strike distance | `merid/prediction/model.py:spot_dist_prob_scale()` | Probability nudge (Decimal) |

---

## 2. Mid-Pipe: Agent Grid → Signal → Proposal

### 2a. Strategy Signal (per market, per agent)

| Step | Location | Fields |
|------|----------|--------|
| Edge computation | `merid/prediction/strategy.py:_kelly_size_with_sentiment()` | `EdgeEstimate.net_edge`, `EdgeEstimate.confidence` (0–1) |
| Sentiment size factor | `merid/prediction/strategy.py:_sentiment_size_factor()` | 0.35–1.0 multiplier from `sentiment_global` (0–100) |
| Signal output | `merid/prediction/strategy.py:StrategySignal` | `action`, `contracts`, `edge` |

### 2b. Agent Probability Estimate

After the strategy produces a signal, `KalshiTradingAgent._submit_consensus_proposal`
calls `KalshiLiveMarketStrategy.estimate()` and optional TSM strategies to refine:

```
market_prob (Kalshi price)
  ↓ KalshiLiveMarketStrategy.estimate()
  → agent_prob (0–1), confidence (0–1), signal_sources, reasoning_tag
  ↓ optional TSM blend: prob = 0.5 * tsm_prob + 0.5 * prob
```

**Default fallback:** `conf = 0.5` when `KalshiLiveMarketStrategy` fails.

### 2c. AgentProposal Construction

```
AgentProposal(
  probability = refined agent_prob  # 0–1
  confidence  = from KalshiLiveMarketStrategy  # 0–1
  direction   = "yes" | "no" | "neutral"
  edge_estimate = float(net_edge * 100)  # cents
  downweight  = True if rolling Sharpe < SHARPE_DOWNWEIGHT_THRESHOLD
)
```

`confidence` here means **"how sure is this agent of its directional call"** — a
different semantic from the news `SentimentMetrics.confidence` ("data volume").
Both are 0–1 but should not be confused.

### 2d. Consensus Aggregation (`SwarmConsensusAggregator`)

```
for each proposal p:
    weight_p = _calculate_agent_weight(p)
             = brier_weight × performance_weight × p.confidence
             × (0.5 if p.downweight else 1.0)

direction_weights[p.direction] += weight_p
weighted_prob += p.probability × weight_p      # NOTE: single-weighted
total_weight  += weight_p                       # (fixed 2026-04-09: was ×p.confidence again)

consensus_probability = weighted_prob / total_weight
agreement_ratio = max(direction_weights.values()) / sum(direction_weights.values())

consensus_confidence:
  ≥ 0.80 agreement → avg_confidence × 1.0
  ≥ 0.60 agreement → avg_confidence × 0.8
  < 0.60 agreement → avg_confidence × 0.5
  < 2 archetypes   → × 0.6 penalty (diversity requirement)

size_band:
  confidence < 0.3  OR agreement < 0.5  → "small"
  confidence < 0.5  OR agreement < 0.6  → "reduced"
  confidence ≥ 0.8  AND agreement ≥ 0.8 AND avg_edge ≥ 3¢ → "large"
  otherwise                              → "base"

status:
  proposals < min_agents     → FORMING
  archetypes < 2             → FORMING
  agreement < threshold(0.6) → CONFLICTED → auction resolution attempt
  otherwise                  → READY
```

**Key invariant:** Only `READY + usable=True` consensus enters `_verdict_log` and drives trades.

---

## 3. Downstream: Trading Decisions

### 3a. Consensus Gate in `_execute_signal_body`

```
Main decision loop (trading_agent.py ~line 1011):
  if consensus.status == READY:
    if signal_direction ≠ consensus_direction:
      BLOCK (regardless of confidence)
    else:
      signal.edge.confidence ← consensus.consensus_confidence  # overwrites model confidence
      PROCEED with size_band from consensus

_check_consensus_gate (before order placement, ~line 2754):
  STALE / None  → cap to "small" band, allow
  FORMING       → skip (full) or cap to small (soft/mm mode)
  CONFLICTED    → cap to small, allow
  READY + direction mismatch + confidence > 0.7 → BLOCK
  READY + direction match  → apply size_band scalar
```

**Size band scalars** (`_SIZE_BAND_SCALARS`):
```
"small":   0.25
"reduced": 0.5
"base":    1.0
"large":   1.5
"halted":  0   (not explicitly listed but consensus.usable=False blocks)
```

### 3b. Risk Layer

`PredictionMarketRisk.pre_trade_check()` runs after the consensus gate and validates:
- Position limits, bankroll caps
- Kill-switch state
- Loop-lag gating (degrade at 500ms, halt at 2000ms × 3 consecutive)

Confidence does not re-enter the risk layer. Once the consensus gate passes, risk
focuses purely on exposure and limits.

---

## 4. Presentation (API + UI)

### 4a. Backend API Fields

| Endpoint | Key fields returned | Scale |
|----------|---------------------|-------|
| `GET /api/v1/kalshi/swarm/grid` | `swarm_consensus_prob`, `swarm_confidence`, `swarm_usable`, `swarm_direction`, `mood_fg`, `mood_social` | prob/conf: 0–1; fg: 0–100; social: −1 to +1 |
| `GET /api/v1/kalshi/swarm/verdicts` | `probability`, `confidence`, `direction` ("bullish"/"bearish"/"neutral"), `size_band`, `agents` (array of agent IDs) | prob/conf: 0–1 |
| `GET /api/v1/kalshi/swarm/matrix` | Per-cell Sharpe, downweight flag | raw |
| `GET /api/v1/kalshi/swarm/health` | Swarm-level health metrics | varies |

### 4b. UI Components

| Component | Source endpoint | What it shows |
|-----------|-----------------|---------------|
| `SwarmSentimentGrid.tsx` | `/swarm/grid` | 5×4 asset×timeframe grid: direction, prob, confidence (color-coded), FG index, social |
| `SwarmVerdictFeed.tsx` | `/swarm/verdicts` | Rolling history of READY verdicts: direction, P(YES), conf bar, size band, # agents |
| `SwarmConsensusMatrix.tsx` | `/swarm/matrix` | Sharpe chip, downweight badge per cell |
| `OperatorDashboard.tsx` | inline + `/swarm/health` | `SwarmHealthPanel`: avg Sharpe, live cells, downweighted list |
| `KalshiGridView.tsx` | grid API | `↓ DW` badge on downweighted agents |
| `CalibrationDashboardView.tsx` | `/kalshi/metrics/ensemble` | Ensemble forecaster probabilities + confidence |

**Display scales in UI:**
- `swarm_confidence` (0–1) → multiply by 100 for `%` display
- `swarm_consensus_prob` (0–1) → multiply by 100 for `%` display
- `mood_fg` (0–100) → display as-is
- `mood_social` (−1 to +1) → multiply by 100 for `%` display

---

## 5. One-Truth Table

| Concept | Canonical source | Scale | Notes |
|---------|------------------|-------|-------|
| Global fear/greed | `SentimentContext.fg_index` | 0–100 | Propagates to `MarketSnapshot.sentiment_global` |
| Social sentiment | `UnifiedSentiment.combined_social_sentiment` | −1 to +1 | Volume-weighted Twitter + Reddit |
| News sentiment | `SentimentMetrics.news_sentiment` | −1 to +1 | FinBERT aggregate |
| Sentiment confidence (data quality) | `SentimentMetrics.confidence` | 0–1 | Data-volume proxy, NOT directional confidence |
| Agent probability | `AgentProposal.probability` | 0–1 | Refined by KalshiLiveMarketStrategy |
| Agent directional confidence | `AgentProposal.confidence` | 0–1 | "How sure is this agent?" — different semantic from sentiment confidence |
| Consensus probability | `ConsensusView.consensus_probability` | 0–1 | Weighted average of agent probs |
| Consensus confidence | `ConsensusView.consensus_confidence` | 0–1 | Agreement-adjusted avg confidence |
| Size band | `ConsensusView.size_band` | enum | "small" / "reduced" / "base" / "large" / "halted" |

---

## 6. Operator Checklist — Before Going Live

### Verify sentiment sources are fresh

- [ ] `GET /api/v1/kalshi/swarm/grid` → every cell has non-null `mood_fg` (expected 20–80 in normal
      markets). If all cells show `null`, the fear/greed poller is stalled.
- [ ] At least some cells have `mood_social ≠ 0`. A flat zero on all cells means
      the SentimentBus is not receiving Twitter/Reddit updates.
- [ ] `GET /api/v1/health/sentiment` shows `status: "ok"` and a recent `last_updated` timestamp.

### Verify agent confidences are in range

- [ ] `GET /api/v1/kalshi/swarm/matrix` — `consensus_confidence` for live cells should be
      0.35–0.85. Values persistently at 0.0 indicate no live proposals. Values at exactly
      0.5 with `status=neutral` mean the cell is idle (expected for new sessions).
- [ ] `GET /api/v1/kalshi/swarm/verdicts` → `confidence` field per verdict is 0–1 (displayed
      as 0–100% in the UI). Verdicts with `confidence < 0.3` will produce `size_band=small`.
- [ ] No cell should show `size_band=halted` unless a kill switch is active or the kill-
      switch endpoint confirms it (`GET /api/v1/risk/kill-switch`).

### Verify sentiment/conviction panels display correctly

- [ ] `SwarmSentimentGrid` (dashboard) — green cells = `confidence ≥ 0.6`, amber = 0.35–0.6,
      grey = `< 0.35` or `usable=false`. Direction badge should say YES / NO / HOLD.
- [ ] `SwarmVerdictFeed` — each card shows `P(YES)` as a percentage (e.g. 63%), a 5-block
      confidence bar (filled blocks = `confidence * 5`), and a size band label matching the
      backend vocabulary: `small` | `reduced` | `base` | `large` | `halted`.
- [ ] `SwarmConsensusMatrix` — downweighted cells (`↓ DW`) should correspond to agents with
      rolling Sharpe below `SHARPE_DOWNWEIGHT_THRESHOLD` (check `config/trading_constants.py`).

### Interpret a live market

To answer "what do our agents believe and how did that drive this trade?":
1. Find the market's asset×timeframe cell in `SwarmSentimentGrid` or `SwarmConsensusMatrix`.
2. `swarm_direction` = the consensus call (yes/no/neutral).
3. `swarm_confidence` × 100 = % alignment across voting agents.
4. `size_band` = how aggressively the system sized in (small/reduced/base/large).
5. Click through to `SwarmVerdictFeed` — find the entry by asset+timeframe+timestamp.
   `agents` field shows which agents contributed; `rationale` is the consensus rationale.
6. For individual agent signals, check `GET /api/v1/kalshi-grid/performance/...` for that
   agent's win_rate, Sharpe, and edge history.

### What to look for when behaviour seems off

| Symptom | Likely cause | Where to look |
|---------|--------------|---------------|
| All cells `idle` / `no signal` | Agents not in ACTIVE lifecycle, or no Kalshi markets in window | `GET /api/v1/kalshi-grid/agents/status` |
| `size_band=small` on every trade | Swarm degraded (no consensus for > `MERID_PM_SWARM_SOLO_SECONDS`) | `swarm_degraded` flag in agent state; check `last_consensus_at` |
| `confidence=0` everywhere | CalibrationStore or PerformanceTracker unavailable | `GET /api/v1/kalshi/metrics/calibration-curve`; check `merid.metrics.calibration` |
| Direction flip without data cause | Social sentiment spike or sudden fear/greed extreme | `mood_social` and `mood_fg` in `SwarmSentimentGrid`; check `SentimentBus` poll interval |
| `SwarmVerdictFeed` shows 0% probability | API field `probability` (0–1) not being multiplied by 100 in display | Should be fixed; verify frontend `SwarmVerdictFeed.tsx` uses `v.probability * 100` |
| All cells `conflicted` | Many agents posting opposite directions | Check individual agent logs for divergent `prob` values; look for a news event causing split |

---

*This document is generated from code audit and must be updated whenever:*
- *Sentiment scale or combination formula changes in `sentiment_integration.py`*
- *Consensus weighting formula changes in `consensus_aggregator.py`*
- *Size band thresholds change in `consensus_aggregator.py:_calculate_size_band`*
- *New sentiment sources are added*
- *UI display of sentiment/confidence values changes*
