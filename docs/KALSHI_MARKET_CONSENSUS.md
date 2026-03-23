# Kalshi Market Consensus Architecture

## Overview

This document describes the refactored consensus logic for MERID's Kalshi trading platform. The system has been redesigned so that **Kalshi markets** are the primary object of consensus, with news as a supporting feature.

## Philosophy

### OLD Design (News-Centric)
```
News → Simulation → Consensus (Approve/Reject News) → Post/Don't Post
```
- Agents voted on: "Should we post this news?"
- Logs showed: "Consensus: REJECTED (28.6%)"
- Problem: Trading decisions conflated with news posting decisions

### NEW Design (Market-Centric)
```
Market Data + Features (News/OnChain/Technicals) → MarketConsensusSnapshot
→ Agent Opinions → Consensus Engine → Trading Action (LONG/SHORT/FLAT/NO_EDGE)
```
- Agents vote on: "What position (if any) should we take in this Kalshi market?"
- Logs show: "KalshiConsensus: KXBTCD-26MAR2300 LONG (72.4%) edge=+3.1%"
- News becomes ONE INPUT among many features

## Architecture

### 1. Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    MARKET CONSENSUS DATA FLOW                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  NEWS FEEDS                      KALSHI API           ON-CHAIN DATA │
│     ↓                                ↓                      ↓       │
│  NewsMonitor    ────────→   MarketAggregator   ←────   Other Sources│
│  (Features)                        ↓                                │
│                        MarketConsensusSnapshot                      │
│                              (contains)                              │
│                        ┌─────────────────────┐                      │
│                        │ • Market data       │                      │
│                        │ • Best bid/ask      │                      │
│                        │ • Liquidity/spread  │                      │
│                        │ • Features:         │                      │
│                        │   - News sentiment  │                      │
│                        │   - On-chain flows  │                      │
│                        │   - Technicals      │                      │
│                        └─────────────────────┘                      │
│                                ↓                                     │
│                         Agent Opinions                               │
│                      (LONG/SHORT/FLAT/NO_EDGE)                      │
│                                ↓                                     │
│                      MarketConsensusEngine                           │
│                     (aggregates + risk filters)                      │
│                                ↓                                     │
│                        Consensus Decision                            │
│                    (action + confidence + edge)                      │
│                                ↓                                     │
│                          Risk Gates                                  │
│                  (liquidity, position limits, fees)                  │
│                                ↓                                     │
│                    KalshiTradingAgent                                │
│                     (executes if allowed)                            │
│                                ↓                                     │
│                        Order Placement                               │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### 2. Core Components

#### 2.1 MarketConsensusSnapshot (merid/signals/market_consensus.py)

Central data structure that agents vote on:

```python
@dataclass
class MarketConsensusSnapshot:
    # Market identification
    contract_id: str              # e.g., "KXBTCD-26MAR2300-T"
    asset: str                     # BTC, ETH, SOL
    timeframe: str                 # 15m, 1h, 24h

    # Market data
    market_data: MarketData        # Prices, liquidity, volume

    # Features (news is here)
    features: MarketFeatures       # Sentiment, on-chain, technicals

    # Agent opinions
    agent_opinions: List[AgentOpinion]

    # Consensus outcome
    consensus_action: TradingAction   # LONG/SHORT/FLAT/NO_EDGE
    consensus_confidence: float
    consensus_edge_pct: float
```

#### 2.2 KalshiMarketAggregator (merid/signals/market_aggregator.py)

Fetches and assembles market data + features:

```python
class KalshiMarketAggregator:
    async def create_snapshot(ticker: str) -> MarketConsensusSnapshot:
        """Fetch market data from Kalshi + features from various sources."""

    def update_news_features(asset: str, sentiment: float):
        """Called by NewsMonitorAgent to update sentiment cache."""
```

#### 2.3 NewsMonitorAgent (agents/news_monitor_agent.py) - REFACTORED

**OLD ROLE**: Consensus-driven news poster
**NEW ROLE**: Feature generator

Changes:
- `post_breaking_news()` → `process_news_as_features()`
- No longer calls `form_consensus()` on news items
- Extracts sentiment, affected assets, regime signals
- Updates `KalshiMarketAggregator` feature cache
- Optionally posts to social media (decoupled from trading)

```python
async def process_news_as_features(news_item):
    sentiment, assets, regime = extract_news_features(news_item)

    for asset in assets:
        update_sentiment_cache(asset, sentiment)
        market_aggregator.update_news_features(asset, sentiment)

    # Optional: post to social if high importance
    if importance >= 0.8 and abs(sentiment) >= 0.5:
        post_to_social_media(news_item)
```

#### 2.4 MarketConsensusEngine (merid/consensus/market_engine.py)

Aggregates agent votes on markets:

```python
class MarketConsensusEngine:
    async def form_consensus(
        snapshot: MarketConsensusSnapshot,
        agent_opinions: List[AgentOpinion],
    ) -> MarketConsensusSnapshot:
        """
        1. Count votes by action (LONG/SHORT/FLAT/NO_EDGE)
        2. Determine consensus action (requires 60% agreement)
        3. Calculate weighted confidence and edge
        4. Apply risk filters (liquidity, fees, position limits)
        5. Set execution parameters if tradeable
        6. Log market decision
        """
```

Consensus rules:
- Min quorum: 60% of agents must vote
- Min agreement: 60% on same action for directional trades
- Edge threshold: Must exceed fees + spread (default 2%)
- Liquidity filter: Spread < 5% of mid
- No trade default: If unclear → NO_EDGE

### 3. Logging Changes

#### OLD Logs (News-Centric)
```
Consensus formed: REJECTED (28.6%)
News rejected by consensus: Michael Saylor signals BTC buy...
Simulation: ✅ APPROVED (89%)
Consensus: ❌ REJECTED (29%)
```

#### NEW Logs (Market-Centric)
```
KalshiConsensus: KXBTCD-26MAR2300 LONG (72.4%) edge=+3.1% (spread=2.1%, depth=150)
  Dominant features: news_bullish, onchain_whales, vol_regime
  → Execute: YES 20 contracts @ ≤54¢

KalshiConsensus: KXBTCD-26MAR2300 FLAT (81.0%) – no tradable edge

KalshiConsensus: KXBTCD-26MAR2300 LONG (65.0%) edge=+2.8%
  → Blocked by: liquidity (spread too wide)

News feature update: BTC sentiment -0.15 → +0.35 (headline: Saylor MicroStrategy...)
```

### 4. Execution Integration

The consensus engine output feeds directly into trading execution:

```python
# In KalshiTradingAgent or similar
snapshot = await market_aggregator.create_snapshot(ticker)
opinions = await collect_agent_opinions(snapshot)
consensus = await market_consensus_engine.form_consensus(snapshot, opinions)

if consensus.is_tradeable():
    # Execute trade
    await kalshi_trader.place_order(
        ticker=consensus.contract_id,
        side=consensus.recommended_side,
        size=consensus.recommended_size,
        max_price=consensus.max_price_cents,
    )
```

### 5. Reflection & Persistence

Track outcomes for learning:

```python
@dataclass
class MarketConsensusDecision:
    snapshot: MarketConsensusSnapshot
    executed: bool
    execution_price: Decimal
    settlement_price: Decimal  # 0 or 100 at resolution
    pnl_usd: float
    decision_correct: bool     # Did we pick right side?
    edge_realized_pct: float   # Actual vs estimated edge
```

Stored in database for:
- Agent performance evaluation
- Edge estimation calibration
- Kelly sizing adjustments
- Feature importance ranking

### 6. Agent Opinion Structure

Each agent provides:

```python
@dataclass
class AgentOpinion:
    agent_id: str
    agent_role: str               # "price_feed", "news_monitor", "risk"
    action: TradingAction         # LONG/SHORT/FLAT/NO_EDGE
    confidence: float             # 0-1
    edge_estimate_pct: float      # vs market price
    reasoning: List[str]
    primary_factors: List[str]    # Which features drove this opinion
```

### 7. Consensus Rules

Implemented in `MarketConsensusEngine`:

```python
# Quorum
if total_votes < (total_agents * 0.6):
    return NO_ACTION

# Agreement for directional trades
if action in (LONG, SHORT):
    if agreement_pct < 60%:
        return NO_EDGE

# Edge after costs
net_edge = consensus_edge - (spread/2 + kalshi_fee)
if net_edge < 2%:
    return NO_EDGE

# Liquidity
if spread_pct > 5%:
    return NO_EDGE
```

## Benefits

1. **Separation of Concerns**
   - News → Features (not decisions)
   - Markets → Trading actions
   - Social posting → Decoupled from trading

2. **Explicit Risk Management**
   - Liquidity filters on every market
   - Fees explicitly considered in edge calculation
   - Position limits enforced before execution

3. **Transparent Logs**
   - Clear what market we're trading
   - Why (features, edge, confidence)
   - Whether we executed or were blocked

4. **Measurable Performance**
   - Track realized PnL per consensus decision
   - Calibrate edge estimates over time
   - Adjust agent weights based on market outcomes

5. **Extensible Features**
   - Easy to add new feature sources (on-chain, volume, correlation)
   - Each feature has clear ownership (news → sentiment, etc.)
   - Features don't directly trigger trades (only inform consensus)

## Migration Notes

### Backwards Compatibility

The OLD `agent_orchestrator.form_consensus()` method for general proposals is preserved. The NEW market consensus runs in parallel:

- Old path: `form_consensus(proposal)` → returns `ConsensusResult` (approve/reject)
- New path: `market_consensus_engine.form_consensus(snapshot, opinions)` → returns `MarketConsensusSnapshot`

### Code Paths to Update

1. ✅ `NewsMonitorAgent`: Refactored to feature generator
2. ✅ New schemas: `MarketConsensusSnapshot`, `MarketData`, `MarketFeatures`
3. ✅ New components: `KalshiMarketAggregator`, `MarketConsensusEngine`
4. ⏳ Wire to `KalshiTradingAgent` execution
5. ⏳ Add persistence for `MarketConsensusDecision`
6. ⏳ Update frontend to show market consensus (not news consensus)

## Example End-to-End Flow

```python
# 1. News comes in
news_item = NewsItem(title="MicroStrategy buys 10,000 BTC", ...)
await news_monitor.process_news_as_features(news_item)
# → Updates: BTC sentiment = +0.45

# 2. Create market snapshot
snapshot = await market_aggregator.create_snapshot(
    ticker="KXBTCD-26MAR2300-T",
    asset="BTC",
    timeframe="24h",
)
# → Snapshot includes:
#    - Market: mid=52¢, spread=2.1%, depth=150
#    - Features: news_bullish=+0.45, onchain_signal=+0.3

# 3. Collect agent opinions
opinions = []
for agent in agents:
    opinion = await agent.evaluate_market(snapshot)
    opinions.append(opinion)
# → [LONG(0.8), LONG(0.7), FLAT(0.5), LONG(0.75), ...]

# 4. Form consensus
consensus = await market_consensus_engine.form_consensus(snapshot, opinions)
# → Action: LONG, Confidence: 72%, Edge: +3.1%

# 5. Execute if tradeable
if consensus.is_tradeable():
    await kalshi_trader.place_order(
        ticker=consensus.contract_id,
        side="yes",
        size=20,
        max_price=54,
    )

# 6. Track outcome
decision = MarketConsensusDecision(snapshot=consensus, executed=True, ...)
await decision_store.save(decision)
```

## Glossary

- **MarketConsensusSnapshot**: The central object agents vote on (replaces "news item")
- **TradingAction**: LONG, SHORT, FLAT, NO_EDGE (replaces APPROVED/REJECTED)
- **AgentOpinion**: Single agent's vote on a market
- **MarketFeatures**: All feature inputs (news, on-chain, technicals)
- **Edge**: Expected value vs market price after fees
- **Consensus**: Aggregated agent opinion with risk filters applied
