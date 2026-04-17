# MERID Kalshi Crypto Pipeline — End-to-End Agent & Formula Audit Spec

**Version:** 1.0  
**Date:** 2026-03-30  
**Scope:** Full Discover→Protect lifecycle for Kalshi crypto prediction market agents

---

## 1. Executive Summary

This document provides a file-by-file audit checklist and explicit formula specifications for the MERID Kalshi crypto trading pipeline. It maps the three dimensions of the system:

- **Data/Feature Agents:** News, social, hashtag, sentiment ingestion
- **Governance/Decision Agents:** Proposal, debate, consensus, veto layers
- **Lifecycle Stages:** Discover → Analyze → Consensus → Size → Execute → Monitor → Promote → Protect

---

## 2. Module Inventory by Lifecycle Stage

### 2.1 DISCOVER — Data Acquisition

| Module | Path | Purpose | Output Schema |
|--------|------|---------|---------------|
| **HashtagAgent** | `merid/sentiment/hashtag_agent.py` | Scrapes X/Twitter + Reddit for hashtag sentiment per Kalshi event/asset | `HashtagSentiment(tag, score, volume, category, asset, timestamp)` |
| **NewsIngestionAgent** | `merid/sentiment/news_ingestion_agent.py` | Fetches headlines from NewsAPI + RSS, scores with VADER/FinBERT | `NewsSentiment(headline, vader_score, finbert_score, combined_score, asset, category)` |
| **RedditScraper** | `merid/sentiment/reddit_scraper.py` | Polls subreddits for asset mentions, VADER scoring | `SentimentResult(score, confidence, volume, subreddit_breakdown)` |
| **X Agent** | `streams/x_agent.py` | Twitter/X scanning and consensus-based posting | Energy packets → core.run_cycle() |
| **MarketSelector** | `merid/event_venues/kalshi/market_selector.py` | Maps agent names → Kalshi series tickers → live market IDs | Series tickers: `KXBTC15M`, `KXETH`, etc. |

**Key Formulas — Discover Stage:**

```python
# Series ticker resolution (market_selector.py:59-72)
resolve_series_ticker(coin, timeframe) -> str:
    base = CRYPTO_SERIES_BASE[coin.upper()]  # BTC→KXBTC, ETH→KXETH, etc.
    suffix = TIMEFRAME_SERIES_SUFFIX[timeframe.lower()]  # 15m→15M, 1h→""
    return f"{base}{suffix}"

# Volume-weighted sentiment aggregation (hashtag_agent.py:530-531)
wt_score = sum(i.score * i.volume for i in items) / total_vol

# Reddit sentiment confidence (reddit_scraper.py:386-390)
confidence = 0.25 + (0.75 * volume_factor * engagement_factor)
where:
    volume_factor = min(posts / 30.0, 1.0)
    engagement_factor = min(avg_engagement / 50.0, 1.0)
```

---

### 2.2 ANALYZE — Feature Engineering & Sentiment

| Module | Path | Purpose | Key Outputs |
|--------|------|---------|-------------|
| **Crypto15mIndicatorStack** | `merid/signals/crypto_15m_indicators.py` | Full technical indicator stack for 15m crypto contracts | `IndicatorSnapshot` with EMA, RSI, MACD, ATR, FVG |
| **SentimentBusV2** | `merid/sentiment/sentiment_bus_v2.py` | Central sentiment aggregation bus | `SentimentSnapshot` per (asset, timeframe) |
| **SentimentGating** | `merid/sentiment/sentiment_gating.py` | Validates signals against sentiment thresholds | `SignalValidity` (allowed, score, checks[]) |
| **NewsSentiment** | `merid/sentiment/news_sentiment.py` | Headline scoring and aggregation | `AggregatedNewsSentiment` |

**Key Formulas — Analyze Stage:**

```python
# EMA calculation (crypto_15m_indicators.py)
EMA(today) = Price(today) * k + EMA(yesterday) * (1 - k)
where k = 2 / (N + 1)
# Periods: EMA(50) trend, EMA(5)/EMA(20) crossover

# RSI(8) calculation
RSI = 100 - (100 / (1 + RS))
where RS = avg_gain / avg_loss over 8 periods

# MACD(8,21,5) — scalping-tilted
MACD_Line = EMA(8) - EMA(21)
Signal_Line = EMA(MACD_Line, 5)
Histogram = MACD_Line - Signal_Line

# ATR(14) gate — dead market detection
atr_move_ok = (ATR / price) >= 0.0003  # 0.03% minimum

# Realized volatility (30-bar annualized)
realized_vol = stdev(returns) * sqrt(365 * 24 * 4)  # 15m bars → annualized

# Fee-aware EV calculation (crypto_15m_indicators.py:91-98)
fee = ceil(0.07 * contracts * price * (1 - price/100))  # Kalshi fee formula
net_ev = gross_ev - fee
min_ev_cents = 1.5  # minimum edge threshold
```

---

### 2.3 CONSENSUS — Aggregation & Debate

| Module | Path | Purpose | Key Outputs |
|--------|------|---------|-------------|
| **PredictionConsensusStore** | `merid/prediction/consensus.py` | SQLite persistence for opinions, plans, Brier scoring | `PredictionOpinion`, `PredictionPlan`, consensus summaries |
| **DebateStore** | `merid/prediction/debate.py` | Multi-agent debate sessions, arguments, rewards | `DebateSession`, `DebateArgument`, `RewardEntry` |
| **ConsensusBridge** | `merid/prediction/consensus_bridge.py` | Adapter between Kalshi markets and consensus store | `KalshiConsensusAdapter` |
| **SwarmConsensusAggregator** | `merid/swarm/consensus_aggregator.py` | Aggregates agent proposals into consensus | `AgentProposal`, `ConsensusView` |

**Key Formulas — Consensus Stage:**

```python
# Confidence-weighted swarm probability (consensus.py:619-627)
swarm_prob = sum(p * c for p, c in zip(probabilities, confidences)) / sum(confidences)
if no opinions: swarm_prob = 0.5

# Edge calculation
edge = swarm_prob - market_implied_prob

# Stance classification (consensus.py:629-639)
if edge >= 0.10: stance = "strong_yes"
elif edge >= 0.03: stance = "weak_yes"
elif edge <= -0.10: stance = "strong_no"
elif edge <= -0.03: stance = "weak_no"
else: stance = "neutral"

# Brier score (consensus.py:641-729)
Brier = (forecast_prob - actual_outcome)²  # lower is better
# Per-agent Brier tracked for weighting

# Debate lift calculation (debate.py:348-352)
pre_brier = (pre_debate_prob - outcome)²
post_brier = (post_debate_prob - outcome)²
lift = pre_brier - post_brier  # positive = debate improved accuracy

# Reward calculation (debate.py:466-600)
base_points = 10  # for timely opinion submission
accuracy_bonus = 50 * (1 - brier)  # Brier-based bonus
debate_lift_bonus = 30 * min(lift * 4, 1.0)  # if agent improved through debate
explanation_bonus = 5  # if opinion has explanation attached
```

**Debate Rules (debate.py:312-341):**
- Debate requires ≥1 arbiter argument to close (H3 fix)
- Same-model debates discounted 20% (no epistemic diversity)
- Lift reward zeroed if no argument contains numeric data reference

---

### 2.4 SIZE — Position Sizing & Risk

| Module | Path | Purpose | Key Outputs |
|--------|------|---------|-------------|
| **KalshiStrategy** | `merid/prediction/strategy.py` | Edge thresholds, quarter-Kelly sizing, exit rules | `StrategySignal` with target size, EV, confidence |
| **KalshiRiskEngine** | `merid/prediction/risk/kalshi_risk_engine.py` | Bankroll management, drawdown halt, fee-aware edge | `RiskSnapshot` with vol_band, drawdown_pct, TIGHT status |
| **StopLossRules** | `merid/event_venues/kalshi/stop_loss.py` | Position-level stop loss and take-profit | `TrackedPosition` with SL/TP levels |
| **PredictionMarketRisk** | `merid/prediction/risk/_prediction_risk.py` | Pre-trade 10-point risk check | `PreTradeCheck` result |

**Key Formulas — Size Stage:**

```python
# Quarter-Kelly position sizing (strategy.py implied)
size_contracts = (bankroll * kelly_fraction * 0.25) / price_cents
where kelly_fraction = edge / (1 - edge)  # simplified

# Volatility band classification (kalshi_risk_engine.py)
vol_band = "low" if realized_vol < 0.30 else "mid" if realized_vol < 0.70 else "high"

# Drawdown tiers
warning_at = 0.05    # 5% — orange badge
downsize_at = 0.08   # 8% — TIGHT mode (half position size)
halt_at = 0.12       # 12% — auto-halt all trading

# Fee-aware edge scaling (kalshi_risk_engine.py)
net_edge = gross_edge - (kalshi_fee_pct / 100)
trade_allowed = net_edge > min_ev_threshold  # typically 1-2%

# Anti-churn hysteresis
if last_trade_was_loss: cool_down_seconds *= 1.5
if fee_drag_30d > 0.30: halt_trading  # 30% fee drag threshold
```

---

### 2.5 EXECUTE — Order Management

| Module | Path | Purpose | Key Outputs |
|--------|------|---------|-------------|
| **KalshiTradingAgent** | `merid/prediction/trading_agent.py` | Per-agent decision loop, order placement | `OrderResult`, `AgentState` |
| **KalshiContinuousTrader** | `merid/trading/kalshi_continuous_trader.py` | Server-mode continuous trading for BTC 15m | `BankrollSnapshot`, `CycleDigest` |
| **OrderRouter** | `merid/event_venues/kalshi/order_router.py` | TIF resolution, order submission | `KalshiOrderIntent` |
| **Crypto15mExecution** | `merid/kalshi/crypto_15m_execution.py` | Execution logic for 15m contracts | Fill notifications, position updates |

**Key Formulas — Execute Stage:**

```python
# Lifecycle states (trading_agent.py:64-70)
STOPPED -> STARTING -> WARMING_UP (_WARMUP_SECONDS=60) -> ACTIVE <-> DRAINING -> STOPPED

# Degraded mode triggers (trading_agent.py:56-104)
if solo_seconds > _MAX_SOLO_SECONDS (120s):
    swarm_degraded = True
    size_band = "small"  # cap position size
    
if solo_trades_degraded >= _MAX_SOLO_TRADES_DEGRADED (3):
    halt_agent()
    
if degraded_session_seconds > _MAX_SOLO_WALL_SECONDS (1800s):
    halt_agent()

# TIF selection (order_router.py)
if seconds_to_expiry < 60: tif = "IOC"  # immediate-or-cancel near expiry
elif seconds_to_expiry < 300: tif = "GTC"  # good-til-cancel
else: tif = "GTD"  # good-til-date

# Order deduplication
dedup_window = 60 seconds  # same agent+symbol opinion deduped within window
```

---

### 2.6 MONITOR — Tracking & Observability

| Module | Path | Purpose | Key Outputs |
|--------|------|---------|-------------|
| **TradeNotifier** | `merid/alerts/trade_notifier.py` | Structured Telegram notifications for fills | `FillRecord`, `CycleDigest` |
| **KalshiMarketStateStore** | `merid/event_venues/kalshi/market_state.py` | Live orderbook, spread, depth tracking | `KalshiMarketState` per ticker |
| **SessionGuard** | `merid/prediction/session_guard.py` | Trading hours enforcement | `SessionStatus` |
| **ProbAccuracyTracker** | `merid/prediction/prob_accuracy_tracker.py` | Tracks prediction accuracy vs outcomes | Accuracy metrics per agent |

**Key Formulas — Monitor Stage:**

```python
# Cycle digest message types (trade_notifier.py)
if cycle_number % digest_every == 0:
    send_full_digest = True  # balance, total value, peak, PnL, drawdown, fee drag, fills
elif fills_this_cycle > 0:
    send_fill_batch = True  # compact fill summary
else:
    quiet_cycle = True  # no message

# Market state tracking (market_state.py)
spread_cents = best_ask - best_bid
mid_cents = (best_ask + best_bid) / 2
depth_10c = sum(size for price, size in book if abs(price - mid) <= 10)
seconds_to_expiry = expiry_timestamp - now

# Brier score tracking (consensus.py:641-729)
swarm_brier = mean((swarm_prob - outcome)² for all resolved)
market_brier = mean((market_prob - outcome)² for all resolved)
calibration = actual_rate vs expected_rate per decile bucket
```

---

### 2.7 PROMOTE — Agent Elevation

| Module | Path | Purpose | Key Outputs |
|--------|------|---------|-------------|
| **PromotionReport** | `merid/prediction/promotion_report.py` | Elevation criteria, eligibility checks | `PromotionVerdict` |
| **AgentGrid** | `merid/prediction/agent_grid.py` | Multi-agent orchestration | `AgentGridSummary` |
| **DebateOrchestrator** | `merid/prediction/debate_orchestrator.py` | Triggers debate on high-variance opportunities | `DebateSession` |

**Promotion Criteria (inferred from codebase):**

```python
# Agent elevation checklist (conceptual, from promotion_report.py)
eligible_for_promotion = (
    brier_score < 0.15 and
    calibration_error < 0.10 and
    min_trades >= 20 and
    win_rate > 0.45 and  # better than random on Kalshi fees
    max_drawdown < 0.10 and
    debate_lift_contribution > 0  # improved swarm accuracy
)

# Promotion actions
promotion_tiers = {
    "observation": {"max_contracts": 10, "max_orders_per_window": 2},
    "enabled": {"max_contracts": 50, "max_orders_per_window": 5},
    "elevated": {"max_contracts": 200, "max_orders_per_window": 15},
    "trusted": {"max_contracts": 1000, "max_orders_per_window": 50}
}
```

---

### 2.8 PROTECT — Safety & Veto

| Module | Path | Purpose | Key Outputs |
|--------|------|---------|-------------|
| **VenueGate** | `merid/prediction/venue_gate.py` | SIM/PAPER/LIVE mode enforcement | `VenueStatus` |
| **PredictionAlertManager** | `merid/prediction/alerts.py` | Risk breach alerts with dedup | `PredictionAlert` |
| **KillSwitches** | `merid/risk/kill_switches.py` | Emergency halt mechanisms | `KillSwitchStatus` |
| **ExecutionGate** | `core/execution_gate.py` | Pre-flight execution checks | `ExecutionStatus` |

**Protection Rules:**

```python
# Kill switch triggers (from various modules)
triggers = {
    "manual_operator": instant,
    "drawdown_12pct": instant,
    "fee_drag_30pct": 5_minute_delay,
    "reconciliation_failure": instant,
    "circuit_breaker_3_errors": 30_second_cooldown,
    "kalshi_api_5xx": exponential_backoff,
}

# Pre-trade 10-point check (risk.py implied)
checklist = [
    "kill_switch_armed",
    "order_size_within_limits", 
    "notional_within_limits",
    "daily_loss_within_limits",
    "spread_within_threshold",
    "depth_sufficient",
    "no_duplicate_in_window",
    "mode_allows_trading",
    "session_hours_open",
    "agent_not_degraded"
]

# Veto conditions (debate.py implied)
veto_conditions = {
    "max_disagreement": 0.30,  # 30% prob spread between agents
    "min_arbiters": 1,  # debate requires arbiter to close
    "no_data_reference": True,  # zero lift reward if no data reference
}
```

---

## 3. File-by-File Audit Checklist

### 3.1 Data/Feature Agents Audit

#### `merid/sentiment/hashtag_agent.py`
- [ ] **Schema compliance:** `HashtagSentiment` includes `(asset, category, timestamp)` for all outputs
- [ ] **Volume spike detection:** `_abuse_volume_suspect()` uses `MERID_HASHTAG_ABUSE_VOLUME_MULT` env var
- [ ] **Contrarian logic:** FG divergence check (≤20 fear + bullish hashtags, ≥80 greed + bearish)
- [ ] **Spam filtering:** Rolling window history per tag, suspect flag for coordinated volume
- [ ] **Bus integration:** `update_hashtags()` pushes to `SentimentBusV2`

#### `merid/sentiment/news_ingestion_agent.py`
- [ ] **Multi-provider:** NewsAPI primary, RSS fallback per category
- [ ] **Scoring:** VADER (fast) + FinBERT (accurate) with weighted blend
- [ ] **Asset inference:** `infer_asset_from_title()` maps headlines to BTC/ETH/SOL/etc.
- [ ] **Deduplication:** MD5 hash of headline+URL, 12-char prefix
- [ ] **Time decay:** `NEWS_MAX_AGE_HOURS=6` default

#### `merid/sentiment/reddit_scraper.py`
- [ ] **Subreddit list:** Bitcoin, CryptoCurrency, Kalshi, ethtrader, Solana
- [ ] **VADER scoring:** Weighted by engagement, quality, discussion, length
- [ ] **Confidence formula:** 0.25 + 0.75 * volume_factor * engagement_factor
- [ ] **Cache TTL:** 5 minutes per asset:time_filter
- [ ] **Mood bus integration:** `update_mood_bus()` feeds `MarketMoodBus`

#### `merid/event_venues/kalshi/market_selector.py`
- [ ] **Series mapping:** All 5 coins (BTC, ETH, SOL, XRP, DOGE) × 4 timeframes
- [ ] **Agent map completeness:** 35 agents in `AGENT_SERIES_MAP`
- [ ] **Catalog resolution:** `get_agent_market_tickers()` filters by `min_volume`
- [ ] **WS subscription:** `enable_kalshi_agent()` subscribes via WS bridge
- [ ] **Fallback path:** `discover_crypto_via_series()` if catalog search fails

---

### 3.2 Consensus/Debate Audit

#### `merid/prediction/consensus.py`
- [ ] **Opinion schema:** `PredictionOpinion` has `(agent_id, symbol, probability, confidence, reasoning)`
- [ ] **Dedup window:** `OPINION_DEDUP_WINDOW = 60.0` seconds
- [ ] **Aggregation:** Confidence-weighted swarm probability
- [ ] **Edge thresholds:** Strong=10%, Weak=3%
- [ ] **Brier computation:** Per-agent and swarm Brier on resolved markets
- [ ] **Calibration:** Decile bucket actual vs expected rates
- [ ] **Event publishing:** `kalshi:consensus_decision` for |edge| ≥ 5%

#### `merid/prediction/debate.py`
- [ ] **Debate lifecycle:** open → closed → resolved
- [ ] **H3 arbiter gate:** `has_arbiter_argument()` required to close debate
- [ ] **Lift calculation:** `pre_brier - post_brier`
- [ ] **Anti-spam:** Disagreement width ≥ 3% required for lift reward
- [ ] **Same-model discount:** 20% reduction if all args share rationale prefix
- [ ] **Data reference gate:** Zero lift if no argument has numeric data reference
- [ ] **Rewards:** Base 10 + accuracy bonus (Brier-based) + debate lift 30 + explanation 5

---

### 3.3 Strategy/Execution Audit

#### `merid/signals/crypto_15m_indicators.py`
- [ ] **EMA periods:** 50 (trend), 5/20 (crossover)
- [ ] **RSI period:** 8 (fast), zones at 30/70
- [ ] **MACD:** 8-21-5 scalping-tilted
- [ ] **ATR gate:** 0.03% minimum (dead market detection)
- [ ] **Vol bands:** Low < 0.15, High > 1.20 annualized
- [ ] **Fee EV:** `min_ev_cents = 1.5`
- [ ] **FVG detection:** Gap size ≥ 1.5 ATR, max age 50 bars
- [ ] **Composite gate:** `vol_gate_ok AND atr_move_ok AND liquidity_ok AND chop_gate_ok`

#### `merid/prediction/trading_agent.py`
- [ ] **Lifecycle:** STOPPED → STARTING → WARMING_UP (60s) → ACTIVE
- [ ] **Degraded mode:** 120s solo threshold, 3 solo trades max, 1800s wall
- [ ] **Position sync:** `_sync_open_positions()` on start
- [ ] **Stop-loss:** `StopLossRules` monitors open positions
- [ ] **Consensus bridge:** `_submit_to_consensus()` submits opinions
- [ ] **Error circuit:** 5 consecutive errors pauses agent

#### `merid/trading/kalshi_continuous_trader.py`
- [ ] **Bankroll tracking:** Balance, peak, drawdown, PnL
- [ ] **Vol band sizing:** TIGHT mode at high vol
- [ ] **Fee drag tracking:** 30% halt threshold
- [ ] **Cycle digest:** Every N cycles (configurable)
- [ ] **Telegram alerts:** Start/stop/halt notifications

---

## 4. Wiring Diagram — End-to-End Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DISCOVER PHASE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  HashtagAgent ──→ X/Twitter API                                             │
│         │                                                                     │
│         ├───────→ Reddit API ────→ RedditScraper                            │
│         │                                                                     │
│         └───────→ Kalshi Events ──→ MarketSelector                          │
│                           │                                                   │
│  NewsIngestionAgent ──────┴───→ NewsAPI + RSS                               │
│                           │                                                   │
│                           ▼                                                   │
│                    SentimentBusV2                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ANALYZE PHASE                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│  SentimentBusV2 ──→ SentimentSnapshot per (asset, timeframe)                │
│                           │                                                   │
│  Crypto15mIndicatorStack ─┴──→ IndicatorSnapshot                            │
│         ↑                                                                     │
│         └───────→ Spot price feeds (CoinGecko/Coinbase/Binance)            │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          CONSENSUS PHASE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│  TradingAgent ──→ PredictionOpinion ──→ PredictionConsensusStore            │
│                           │                                                   │
│                           ├──────→ DebateOrchestrator                       │
│                           │              │                                    │
│                           │              ▼                                    │
│                           │         DebateSession                             │
│                           │         (requires arbiter)                        │
│                           │                                                   │
│                           ▼                                                   │
│                    SwarmConsensusAggregator                                   │
│                           │                                                   │
│                           ▼                                                   │
│                    ConsensusView (swarm_prob, edge, stance)                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                            SIZE PHASE                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│  KalshiStrategy ──→ StrategySignal                                        │
│         │                                                                     │
│         ├───────→ Quarter-Kelly sizing                                      │
│         ├───────→ Edge thresholds (3%/10% weak/strong)                    │
│         └───────→ Vol band adjustment                                       │
│                           │                                                   │
│  KalshiRiskEngine ────────┴──→ RiskSnapshot                                 │
│         │                                                                     │
│         ├───────→ Drawdown tiers (5%/8%/12%)                                │
│         ├───────→ Fee-aware edge scaling                                    │
│         └───────→ Anti-churn hysteresis                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          EXECUTE PHASE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  TradingAgent ──→ PreTradeCheck ──→ OrderRouter ──→ Kalshi API            │
│         │                                                                     │
│         ├───────→ WARMING_UP (60s) before LIVE orders                       │
│         ├───────→ Degraded mode caps (solo trading)                         │
│         └───────→ StopLossRules monitoring                                  │
│                           │                                                   │
│  KalshiContinuousTrader ──┴──→ Server-mode execution                        │
│                           │                                                   │
│                           ▼                                                   │
│                    KalshiOrderIntent → REST/WebSocket                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MONITOR PHASE                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│  TradeNotifier ──→ Telegram alerts (cycle digests, fills)                   │
│  KalshiMarketStateStore ──→ Live orderbook, spread, depth                 │
│  ProbAccuracyTracker ──→ Brier scoring, calibration                         │
│  SessionGuard ──→ Trading hours enforcement                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PROMOTE/PROTECT PHASE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  PromotionReport ──→ Elevation criteria (Brier < 0.15, WR > 45%, etc)      │
│  VenueGate ──→ SIM/PAPER/LIVE mode enforcement                              │
│  PredictionAlertManager ──→ Risk breach dedup (30s CRITICAL)               │
│  KillSwitches ──→ Emergency halt (drawdown, fee drag, API errors)             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Formula Quick Reference

### Sentiment Scoring
```python
# Volume-weighted hashtag sentiment
wt_score = Σ(score_i × volume_i) / Σ(volume_i)

# Reddit confidence
confidence = 0.25 + 0.75 × min(posts/30, 1) × min(avg_engagement/50, 1)

# Contrarian detection
if fg_index <= 20 and wt_score > 0.2: direction = "contrarian"
if fg_index >= 80 and wt_score < -0.2: direction = "contrarian"
```

### Consensus Aggregation
```python
# Confidence-weighted swarm probability
swarm_prob = Σ(prob_i × conf_i) / Σ(conf_i)

# Edge and stance
edge = swarm_prob - market_prob
stance = strong_yes if edge >= 0.10 else weak_yes if edge >= 0.03 else ...

# Brier score
Brier = (forecast_prob - outcome)²

# Debate lift
lift = (pre_prob - outcome)² - (post_prob - outcome)²
```

### Position Sizing
```python
# Quarter-Kelly
kelly_fraction = edge / (1 - edge)
size = bankroll × kelly_fraction × 0.25 / price

# Vol band adjustment
if vol_band == "high": size *= 0.5  # TIGHT mode

# Drawdown tiers
if drawdown >= 0.12: halt_all_trading()
elif drawdown >= 0.08: size *= 0.5   # TIGHT
elif drawdown >= 0.05: warn_only()
```

### Fee-Aware EV
```python
# Kalshi fee formula
fee_cents = ceil(0.07 × contracts × price × (1 - price/100))

# Net EV
gross_ev = contracts × |edge| × payout
net_ev = gross_ev - fee

# Minimum threshold
trade_allowed = net_ev >= 1.5  # cents
```

---

## 6. Audit Sign-Off Checklist

Before deploying any agent to production, verify:

### Schema Consistency
- [ ] All agent outputs include `(symbol, timeframe)` or `series_ticker`
- [ ] No hard-coded BTC references (must use parameterized assets)
- [ ] All timestamps are UTC with timezone info
- [ ] Correlation IDs traceable through full lifecycle

### Formula Validation
- [ ] Sentiment aggregation uses volume weighting
- [ ] Consensus uses confidence weighting (not uniform)
- [ ] Edge calculation subtracts fees for net EV
- [ ] Kelly sizing uses quarter-Kelly (not full Kelly)
- [ ] Drawdown tiers at 5%/8%/12%

### Safety Gates
- [ ] Degraded mode activates after 120s solo
- [ ] WARMING_UP period (60s) before live orders
- [ ] Debate requires arbiter argument to close
- [ ] Kill switches trigger on drawdown ≥ 12%
- [ ] Fee drag halt at 30%

### Observability
- [ ] All trades logged to `data/trade_audit.jsonl`
- [ ] Brier scores computed per-agent and swarm
- [ ] Telegram alerts for fills and halts
- [ ] Prometheus metrics for execution counts

---

## 7. Appendices

### A. Environment Variables
```bash
# Sizing/Risk
MERID_MAX_SOLO_SECONDS=120
MERID_WARMUP_SECONDS=60
MERID_LEADERBOARD_DECAY_LAMBDA=0.0

# Sentiment
MERID_HASHTAG_ABUSE_VOLUME_MULT=4.0
NEWS_MAX_AGE_HOURS=6

# Trading
MERID_MIN_EDGE_EARLY=0.05
MERID_MIN_EDGE_MID=0.04
MERID_MIN_EDGE_LATE=0.03
MERID_PAPER_EDGE_BOOST=0.10  # testing only
```

### B. Series Ticker Reference
| Asset | 15m | 1h | Daily | Weekly |
|-------|-----|-----|-------|--------|
| BTC | KXBTC15M | KXBTC | KXBTCD1 | KXBTCW1 |
| ETH | KXETH15M | KXETH | KXETHD1 | KXETHW1 |
| SOL | KXSOL15M | KXSOL | KXSOLD1 | KXSOLW1 |
| XRP | KXXRP15M | KXXRP | KXXRPD1 | KXXRPW1 |
| DOGE | KXDOGE15M | KXDOGE | KXDOGED1 | KXDOGEW1 |

### C. File Paths Quick Reference
```
# Core pipeline
merid/event_venues/kalshi/market_selector.py
merid/sentiment/hashtag_agent.py
merid/sentiment/news_ingestion_agent.py
merid/sentiment/reddit_scraper.py
merid/signals/crypto_15m_indicators.py
merid/prediction/consensus.py
merid/prediction/debate.py
merid/prediction/strategy.py
merid/prediction/trading_agent.py
merid/prediction/risk/kalshi_risk_engine.py
merid/trading/kalshi_continuous_trader.py

# Config
config/kalshi_agent_grid.yaml
config/kalshi_universe.py

# Tests
tests/test_kalshi_market_consensus.py
tests/test_crypto_15m_indicators.py
tests/test_sprint_bc.py
```

---

**Document Owner:** MERID Architecture Team  
**Review Cycle:** Per-sprint or on major pipeline changes  
**Related Docs:** `KALSHI_FILTER_PIPELINE_INTEGRATION.md`, `CT_PIPELINE_AUDIT.md`  
**Formula Module:** `merid/formulas.py` (SOURCE_OF_TRUTH)  
**Formula Tests:** `tests/test_formulas_source_of_truth.py`

---

## 8. Explicit Invariants Per Lifecycle Stage

These invariants **must always hold**. Any violation is a bug.

### 8.1 DISCOVER Invariants

| # | Invariant | Enforcement | Log on Violation |
|---|-----------|-------------|------------------|
| D1 | Every discovered series maps to valid `(asset, timeframe)` | `market_selector.py:resolve_series_ticker()` raises `ValueError` if unknown | `ERROR: Unknown series ticker {ticker} for agent {agent}` |
| D2 | Missing mappings are logged and dropped, never defaulted | `AGENT_SERIES_MAP.get(agent, [])` returns `[]`, no fallback to BTC | `WARNING: No series mapping for agent {agent}` |
| D3 | All sentiment scores are in `[-1, 1]` before aggregation | `validate_sentiment_inputs()` rejects out-of-range | `ERROR: Invalid sentiment score {score} not in [-1, 1]` |
| D4 | Volume is always non-negative | Dataclass validation + runtime checks | `ERROR: Negative volume {volume}` |
| D5 | Zero denominator in weighted mean returns 0 with warning, never crashes | `volume_weighted_sentiment()` checks `total_volume == 0` | `WARNING: ZERO_DENOMINATOR: no volume for weighted sentiment` |
| **D6** | **News feed (Finnhub) failures can only inform conviction, never block execution** | `core/execution_gate.py:check_execution_gate()` — news_feed source ALWAYS uses `severity="warning"` (never critical) | `WARNING: News feed {status}: Finnhub — informing conviction only` |
| **D7** | **News feed starvation triggers LIMITED mode, never BLOCKED** | `NewsFeedHealthAlert` fires with severity=warning; `check_execution_gate()` gate_state can be LIMITED but never BLOCKED solely due to news | `INFO: News feed degraded — reducing confidence, trading continues` |

### 8.2 ANALYZE Invariants

| # | Invariant | Enforcement | Log on Violation |
|---|-----------|-------------|------------------|
| A1 | All indicator outputs include `asset` and `timeframe` fields | `IndicatorSnapshot` dataclass requires fields | `ERROR: Missing asset/timeframe in indicator snapshot` |
| A2 | EMA values are monotonic with price (no sudden jumps) | Rolling window with `max_bars` limit | `WARNING: EMA discontinuity detected` |
| A3 | ATR gate blocks dead markets (ATR/price < 0.03%) | `IndicatorSnapshot.atr_move_ok` boolean | `INFO: ATR gate blocked: {asset} {timeframe} below min move` |
| A4 | Realized volatility is annualized correctly | `realized_vol * sqrt(365 * 24 * 4)` for 15m bars | `ERROR: Vol calculation overflow` |
| A5 | Fee EV calculation never returns negative for valid inputs | `max(0, net_ev)` clamp | `WARNING: Negative EV blocked: {net_ev}` |

### 8.3 CONSENSUS Invariants

| # | Invariant | Enforcement | Log on Violation |
|---|-----------|-------------|------------------|
| C1 | `swarm_prob` is always in `[0, 1]` | Output clamp: `max(0.0, min(1.0, swarm_prob))` | `ERROR: Swarm probability {prob} outside [0,1]` |
| C2 | All consensus records include full list of contributing agents and weights | `opinions` list stored with each consensus record | `ERROR: Missing agent list in consensus for {symbol}` |
| C3 | Brier score is always in `[0, 1]` | Formula: `(forecast - outcome)²` inherently bounded | `ERROR: Brier score {score} outside [0,1]` |
| C4 | Debate requires ≥1 arbiter argument to close | `has_arbiter_argument()` check in `close_debate()` | `ERROR: Debate {id} close rejected: no arbiter` |
| C5 | Opinion dedup window is strictly enforced (60s) | `OPINION_DEDUP_WINDOW = 60.0` constant | `DEBUG: Dedup: skipping opinion from {agent} on {symbol}` |
| C6 | Lift calculation preserves sign: positive = debate helped | `pre_brier - post_brier` | `INFO: Debate lift {lift} for {symbol}` |

### 8.4 SIZE Invariants

| # | Invariant | Enforcement | Log on Violation |
|---|-----------|-------------|------------------|
| S1 | Position size is 0 when edge ≤ 0 | `quarter_kelly_size()` returns 0 with warning | `WARNING: NO_EDGE: edge <= 0, no position` |
| S2 | Size respects both per-market max and bankroll-fraction caps | `apply_sizing_constraints()` applies caps in sequence | `INFO: {constraint} applied: {original} -> {final}` |
| S3 | Kelly fraction is never full Kelly (max 0.25 default) | `fractional_kelly=0.25` parameter default | `ERROR: Kelly fraction {kelly} exceeds quarter-Kelly limit` |
| S4 | Drawdown tier "tight" applies exactly 0.5x sizing | `apply_sizing_constraints()` halves contracts | `INFO: TIGHT_TIER: 0.5x sizing applied` |
| S5 | Drawdown tier "halt" blocks 100% of new positions | Returns 0 contracts immediately | `CRITICAL: HALT_TIER: all new positions blocked` |

### 8.5 EXECUTE Invariants

| # | Invariant | Enforcement | Log on Violation |
|---|-----------|-------------|------------------|
| E1 | WARMING_UP period (60s) completes before LIVE orders | `lifecycle == LifecycleState.ACTIVE` gate | `INFO: Agent {name} in WARMING_UP, skipping execution` |
| E2 | Degraded mode caps solo trades to max 3 | `solo_trades_this_degraded_session` counter | `WARNING: Solo trade limit reached: {count}/{max}` |
| E3 | Pre-trade check passes all 10 gates before order submission | `PreTradeCheck` dataclass validation | `ERROR: PreTradeCheck failed: {reason}` |
| E4 | Order deduplication prevents identical orders within window | `OPINION_DEDUP_WINDOW` applied to orders | `DEBUG: Order dedup: skipping duplicate for {symbol}` |
| E5 | Stop-loss monitoring runs every cycle for open positions | `_check_stop_losses()` called in `_run_cycle_body()` | `ERROR: Stop-loss check failed for {position}` |

### 8.6 MONITOR Invariants

| # | Invariant | Enforcement | Log on Violation |
|---|-----------|-------------|------------------|
| M1 | All trades logged to `data/trade_audit.jsonl` with causality chain | `record_intent()` → `record_fill()` sequence | `CRITICAL: Audit logging failed: {error}` |
| M2 | Brier scores computed within 5 minutes of market resolution | `compute_brier_scores()` triggered on resolution event | `ERROR: Brier computation delayed for {symbol}` |
| M3 | Telegram alerts fire within 10s of fill for CRITICAL severity | Async fire-and-forget with 10s timeout | `WARNING: Telegram alert timeout` |
| M4 | Market state updates within 1s of orderbook change | WS message handler updates `KalshiMarketStateStore` | `WARNING: Market state stale: {age}s` |

### 8.7 PROMOTE/PROTECT Invariants

| # | Invariant | Enforcement | Log on Violation |
|---|-----------|-------------|------------------|
| P1 | Agent elevation requires min 20 trades and Brier < 0.15 | `promotion_report.py` eligibility check | `INFO: Agent {name} not eligible: {reason}` |
| P2 | VenueGate blocks LIVE orders when mode is SIM/PAPER | `get_venue_gate().can_trade()` returns False | `ERROR: VenueGate blocked LIVE order in {mode} mode` |
| P3 | Kill switch triggers within 1s of threshold breach | `fire_kill_switch()` sets flag immediately | `CRITICAL: Kill switch fired: {reason}` |
| P4 | CRITICAL alerts deduped to 30s minimum interval | `_SUPPRESS_BY_SEVERITY[CRITICAL] = 30.0` | `DEBUG: CRITICAL alert suppressed (within 30s window)` |
| P5 | Human override required to resume after halt tier | Manual API call to `resume_after_halt()` | `AUDIT: Halt override by operator {user}` |

---

## 9. Traceability Hooks for 8 Stages

Each lifecycle stage **must** emit a trace event with a correlation ID that survives end-to-end.

### 9.1 Correlation ID Format

```python
# Format: {timestamp}_{asset}_{timeframe}_{uuid8}
correlation_id = f"{ts}_{asset}_{tf}_{uuid8}"
# Example: "20260330_143022_BTC_15m_a1b2c3d4"
```

### 9.2 Required Trace Fields Per Stage

| Stage | Required Trace Field | Log Level | Destination |
|-------|---------------------|-----------|-------------|
| **DISCOVER** | `discovered_series` (list of series tickers) | INFO | `data/trade_audit.jsonl` + `sentiment_bus` |
| **ANALYZE** | `indicator_snapshot_hash` (SHA-256 of snapshot) | DEBUG | `indicator_snapshot` table |
| **CONSENSUS** | `opinion_ids` (list of contributing opinion UUIDs) | INFO | `pred_opinions` table |
| **SIZE** | `kelly_fraction`, `constraints_applied[]` | DEBUG | Position sizing log |
| **EXECUTE** | `order_intent_id`, `kalshi_order_id` | INFO | `data/trade_audit.jsonl` |
| **MONITOR** | `fill_id`, `realized_pnl_cents` | INFO | `pred_resolved` table |
| **PROMOTE** | `elevation_decision`, `brier_score` | INFO | `promotion_log` |
| **PROTECT** | `halt_reason`, `human_override` (if applicable) | CRITICAL | `kill_switch_log` + Telegram |

### 9.3 Trace Verification Checklist

Contractors must verify in code:

- [ ] Every log line with `lifecycle_stage=X` also has `correlation_id`
- [ ] Correlation ID survives from DISCOVER (first news/social hit) to MONITOR (PnL/Brier update)
- [ ] Dashboard can reconstruct full chain: `get_trace_chain(correlation_id)` returns all 8 stages
- [ ] Missing stages in chain trigger `WARNING: Incomplete trace chain for {correlation_id}`

### 9.4 Implementation Template

```python
# Standard trace decorator for all pipeline functions
from functools import wraps
import hashlib
import uuid

def trace_stage(stage: str):
    """Decorator that adds trace logging with correlation ID."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Extract or create correlation ID
            corr_id = kwargs.get('correlation_id') or generate_correlation_id()
            
            # Log entry
            logger.info(f"[TRACE] {stage}_START", 
                       extra={'correlation_id': corr_id, 'stage': stage})
            
            try:
                result = func(*args, correlation_id=corr_id, **kwargs)
                
                # Log success with stage-specific fields
                trace_data = extract_stage_data(stage, result)
                logger.info(f"[TRACE] {stage}_COMPLETE",
                           extra={'correlation_id': corr_id, **trace_data})
                return result
                
            except Exception as e:
                logger.error(f"[TRACE] {stage}_FAILED",
                           extra={'correlation_id': corr_id, 'error': str(e)})
                raise
                
        return wrapper
    return decorator

# Usage example:
@trace_stage("CONSENSUS")
def aggregate_opinions(opinions, correlation_id=None):
    ...
```

---

## 10. Red/Amber/Green Exit Criteria

Each lifecycle stage has numeric gates that decide whether capital can proceed or must fall back to neutral.

### 10.1 Stage-Level Traffic Lights

| Stage | GREEN (Proceed) | AMBER (Caution/Fallback) | RED (Block) |
|-------|-----------------|--------------------------|-------------|
| **DISCOVER** | ≥2 valid sentiment sources with volume > threshold | 1 source only, or low volume (< 30 posts), or **news feed degraded (Finnhub zero-data/stale/no-matches)** | 0 sources, or all sources failed — **news feed issues alone never trigger RED** |
| **ANALYZE** | All indicators computed, chop_gate_ok=True | Some indicators missing, chop_detected=True | Critical indicators failed (e.g., ATR gate), data > 5min stale |
| **CONSENSUS** | ≥3 opinions, total_confidence ≥ 1.5, disagreement_width ≥ 0.03 | 1-2 opinions, or low confidence (< 1.0 total) | 0 opinions, or same-model debate (no diversity) |
| **SIZE** | Kelly > 0, net_edge > 0, drawdown_tier="normal", **news_health_factor=1.0** | Kelly > 0 but drawdown_tier="warning", **or news_health_factor<1.0 (news degraded)** | Kelly ≤ 0, or net_edge ≤ 0, or drawdown_tier in ("tight", "halt") — **news feed issues never block sizing** |
| **EXECUTE** | All pre-trade checks pass, mode=LIVE, not warming_up | Pre-trade check marginal (edge near minimum), degraded mode, **or news_feed warning present** | Any pre-trade check fails, kill switch armed, warming_up not complete — **news_feed warning never blocks execution** |
| **MONITOR** | PnL tracking active, reconciliation OK, Brier < 0.20 | Brier 0.20-0.25, minor reconciliation drift | Brier > 0.25, critical reconciliation failure, data > 10min stale |
| **PROMOTE** | Agent Brier < 0.15, WR > 45%, Sharpe > 0.5 | Agent Brier 0.15-0.20, WR 40-45% | Agent Brier > 0.20, WR < 40%, max_drawdown > 15% |
| **PROTECT** | All kill switches disarmed, drawdown < 5% | Kill switch warning triggered (5% < drawdown < 8%), circuit breaker cooling | Kill switch armed (drawdown ≥ 12%), or manual halt |

### 10.1a News Health Factor Mapping (D6/D7 Implementation)

Per invariants **D6** and **D7**, news feed health affects conviction/sizing but **never blocks execution**. The `news_health_factor` is computed from `get_feed_health()["news"]["status"]` and applied as a multiplicative factor in position sizing.

| News Status | `news_health_factor` | Sizing Impact | R/A/G |
|-------------|----------------------|---------------|-------|
| `healthy` | 1.0 | Full sizing | GREEN |
| `stale` | 0.5 | Reduced sizing | AMBER |
| `zero_data` | 0.5 | Reduced sizing | AMBER |
| `no_matches` | 0.5 | Reduced sizing | AMBER |
| `error` | 0.5 | Reduced sizing | AMBER |
| `not_configured` | 0.5 | Reduced sizing | AMBER |
| `unknown` | 1.0 | Assume healthy | GREEN |

**Implementation Details:**
- **Source**: `merid/signals/live_feeds.py:get_feed_health()["news"]["status"]`
- **Integration**: `merid/prediction/risk/sentiment_vol_service.py:_get_news_health_status()` fetches status; `compute_sizing_multiplier()` applies factor
- **Floor**: `NEWS_HEALTH_FLOOR=0.3` ensures news degradation **never reduces sizing to zero** (per D6/D7)
- **Config**: Environment variables `KALSHI_NEWS_HEALTH_*` control thresholds
- **Formula**: `final_size = base_kelly_size * sentiment_mult * volatility_mult * news_health_mult`

**Logging:**
- TRACE logs include `news_health_status` and `news_health_contribution` in `SizingMultiplier.inputs`
- Reasoning string shows `news_{status}({factor:.2f})` when degraded

### 10.2 Decision Matrix

```python
# Pseudocode for stage gating
def can_proceed_to_next_stage(stage_result, stage_name) -> Tuple[bool, str]:
    criteria = EXIT_CRITERIA[stage_name]
    
    if stage_result.status == "GREEN":
        return True, "Proceed"
    elif stage_result.status == "AMBER":
        # Log warning, apply fallback sizing if SIZE stage
        logger.warning(f"{stage_name}: AMBER - {stage_result.reason}")
        if stage_name == "SIZE":
            stage_result.size *= 0.5  # Conservative fallback
        return True, "Proceed_with_caution"
    else:  # RED
        logger.error(f"{stage_name}: RED - {stage_result.reason}")
        return False, f"Blocked_at_{stage_name}"
```

### 10.3 Aggregate Pipeline Status

| Overall Status | Condition | Action |
|----------------|-----------|--------|
| **GREEN** | All 8 stages GREEN | Full capital deployment, normal sizing |
| **AMBER** | Any stage AMBER, no RED | Reduce sizing 50%, increase monitoring frequency |
| **RED** | Any stage RED | Block new capital, begin position closeout, notify operator |

### 10.4 Contractor Verification Tasks

For each stage, contractors must:

1. **Locate the gate code** in the referenced module
2. **Verify the threshold** matches the documented value
3. **Add a test** that triggers both AMBER and RED conditions
4. **Confirm logging** includes the correlation ID and status

Example test template:

```python
# tests/test_exit_criteria_size.py
def test_size_stage_red_on_halt_tier():
    inputs = PositionSizingInputs(
        bankroll_cents=100000,
        edge=0.05,  # Positive edge
        price_cents=55,
    )
    
    # Apply halt tier constraint
    final, constraints = apply_sizing_constraints(
        raw_contracts=100,
        drawdown_tier="halt"
    )
    
    assert final == 0  # RED: blocked
    assert "HALT_TIER" in constraints[0]
```

---

## 11. Contractor Workplan Template

### Module Checklist Status Format

For each module in Section 3, use this format:

```markdown
#### `merid/sentiment/hashtag_agent.py`
**Status:** ⬜ Not started / 🟡 In progress / ✅ Passed / 🔴 Blocked  
**Owner:** @contractor_name  
**PR:** #123

- [ ] **D3** Invariant validated: sentiment scores in [-1, 1]
- [ ] **Trace hook** added: `correlation_id` in all `HashtagSentiment` outputs
- [ ] **Formula test** added: `test_volume_weighted_sentiment` passes
- [ ] **Exit criteria** implemented: GREEN/AMBER/RED for sentiment volume
```

### Formula Test Mapping

Every formula in Section 5 must have a corresponding test in `test_formulas_source_of_truth.py`:

| Formula | Test Name | Status |
|---------|-----------|--------|
| `volume_weighted_sentiment` | `TestVolumeWeightedSentiment.test_basic_weighted_mean` | ✅ |
| `reddit_confidence` | `TestRedditConfidence.test_formula_match` | ✅ |
| `confidence_weighted_swarm_probability` | `TestConfidenceWeightedSwarmProbability.test_basic_linear_opinion_pool` | ✅ |
| `classify_stance` | `TestClassifyStance.test_symmetry` | ✅ |
| `brier_score` | `TestBrierScore.test_example_from_audit_doc` | ✅ |
| `debate_lift` | `TestDebateLift.test_example_from_audit_doc` | ✅ |
| `kelly_fraction` | `TestKellyFraction.test_example_from_audit_doc` | ✅ |
| `quarter_kelly_size` | `TestQuarterKellySize.test_example_from_audit_doc` | ✅ |
| `drawdown_tier_action` | `TestDrawdownTierAction.test_example_from_audit` | ✅ |
| `fee_aware_edge` | `TestFeeAwareEdge.test_fee_calculation` | ✅ |

### Integration Test

| Test | Description | Status |
|------|-------------|--------|
| `test_full_pipeline_example` | End-to-end DISCOVER→PROTECT golden path | ✅ |

---

## 12. Running the Audit

### Quick Start

```bash
# 1. Run formula tests to verify math
cd /c/Dev/MERID
py -m pytest tests/test_formulas_source_of_truth.py -v

# 2. Run all Kalshi pipeline tests
py -m pytest tests/test_kalshi_market_consensus.py tests/test_crypto_15m_indicators.py tests/test_sprint_bc.py -v

# 3. Generate audit report
py -m pytest tests/ --tb=short -q > audit_report.txt
```

### Expected Test Output

```
tests/test_formulas_source_of_truth.py::TestVolumeWeightedSentiment::test_basic_weighted_mean PASSED
tests/test_formulas_source_of_truth.py::TestConfidenceWeightedSwarmProbability::test_basic_linear_opinion_pool PASSED
tests/test_formulas_source_of_truth.py::TestQuarterKellySize::test_example_from_audit_doc PASSED
tests/test_formulas_source_of_truth.py::TestDrawdownTierAction::test_example_from_audit PASSED
...
47 passed in 2.34s
```

### Sign-Off Checklist

| Role | Checklist Item | Sign-Off |
|------|---------------|----------|
| **Architecture** | All formulas in `merid/formulas.py` match this document | [ ] |
| **Engineering** | All invariants enforced with tests | [ ] |
| **DevOps** | Trace correlation IDs working in production logs | [ ] |
| **Risk** | Exit criteria thresholds approved | [ ] |
| **QA** | Integration test passes (golden path) | [ ] |
| **Ops** | Runbook updated with halt/override procedures | [ ] |

---

## 13. Versioning and Change Control

### Version Constants

The following versions must be tracked and logged:

```python
# merid/formulas.py
FORMULAS_VERSION = "2026-03-K1"      # Formula implementations
AUDIT_SPEC_VERSION = "2026-03-A1"    # This document
```

### When to Bump Versions

**FORMULAS_VERSION** (K-series):
- Any change to formula implementation in `merid/formulas.py`
- New formulas added to the module
- Breaking changes to function signatures
- Bug fixes that change calculated outputs

**AUDIT_SPEC_VERSION** (A-series):
- Changes to invariants D1–P5
- Changes to traceability hook requirements
- Changes to R/A/G exit criteria thresholds
- New lifecycle stages or agents added

### Change Control Process

1. **Propose**: Open PR with version bump and detailed rationale
2. **Review**: Architecture review for formula changes; Risk review for threshold changes
3. **Test**: All tests in `test_formulas_source_of_truth.py` must pass
4. **Sign-off**: Update Section 11 workplan with reviewer names
5. **Merge**: Only after all checks pass
6. **Deploy**: Update running systems with new version

### Version in Correlation IDs

Every correlation ID chain must include version info:

```python
{
    "correlation_id": "20260330_143022_BTC_15m_a1b2c3d4",
    "formulas_version": "2026-03-K1",
    "audit_spec_version": "2026-03-A1",
    "lifecycle_stage": "CONSENSUS",
    ...
}
```

This ensures every trade can be traced back to the governing spec version.

### Backward Compatibility

- **Minor version bumps (K1 → K2)**: Backward compatible, old code continues to work
- **Major version bumps (K1 → L1)**: Breaking changes, all callers must update
- **Spec-only bumps (A1 → A2)**: No code changes required, only documentation/process changes

### Contractor Requirement

Every module in the Kalshi pipeline must import and log version info:

```python
from merid.formulas import get_version_info

version_info = get_version_info()
logger.info("Module initialized", extra={
    "formulas_version": version_info["formulas_version"],
    "audit_spec_version": version_info["audit_spec_version"],
})
```

---

## 14. Anti-Regression Rules

### Hard Checks for Code Review

Reviewers must verify:

1. **No Custom Math**: All Kelly/Brier/sentiment/drawdown calculations import from `merid.formulas.py`
2. **No Untraced Paths**: All decision paths include `correlation_id` in logs
3. **No Missing Invariants**: All invariants D1–P5 are enforced in code
4. **No Undocumented Thresholds**: All R/A/G thresholds match Section 10

### Automated Enforcement

Add to CI pipeline:

```bash
# 1. Verify no duplicate formula implementations
grep -r "kelly_fraction\|brier_score\|volume_weighted" --include="*.py" \
  | grep -v "merid/formulas.py" \
  | grep -v "test_formulas" \
  | grep -v "from merid.formulas import"
# Should return empty

# 2. Run formula tests
pytest tests/test_formulas_source_of_truth.py -v

# 3. Verify version constants are exported
grep -q "FORMULAS_VERSION" merid/formulas.py
```

### Binding Reference

All code review comments referencing this document must use the format:

```
[AGENT_AUDIT: Section X.Y] — Description of requirement
```

Example:
```
[AGENT_AUDIT: Section 8.4] — S3: Kelly fraction must use quarter-Kelly (0.25)
```

**End of Document**
