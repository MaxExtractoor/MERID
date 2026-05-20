# Sentiment Isolation Contract for Kalshi 15m Crypto Path

## Target Contract (Law)

This document defines the invariant contract for the BTC/ETH/SOL/XRP/DOGE 15m Kalshi crypto trading path. Any violation of this contract is a bug.

### Scope
- **Only assets**: BTC, ETH, SOL, XRP, DOGE
- **Only timeframe**: 15m Kalshi crypto markets, restricted via AllowedMarketPolicy / canonical 15m config
- **Execution decisions** (enter/size/side/exit) are driven purely by:
  - EV/edge from band/edge stack
  - Volatility regime
  - Risk config
  - Live Kalshi data only
- **No sentiment, no "mood"** in the execution path

### Allowed Sentiment Usage
Sentiment/marketmood are allowed **only** as:
1. Logged telemetry fields on signals/trades
2. Optional features inside the modeling layer used to compute edge, but never as a direct gate, override, or synchronous dependency for the trading loop

### Forbidden Patterns
Any of the following patterns in production code is a bug:
- `if sentiment < X: skip trade`
- `if mood == "bearish": reduce size by 50%`
- `edge = base_edge + sentiment_weight * sentiment_score`
- Awaiting sentiment/mood services in the hot path
- Blocking on sentiment warmup during agent startup
- Bubbling sentiment errors that stop the agent loop

### Required Invariant
> "Kalshi 15m crypto agents must be able to start, tick, and place orders with sentiment completely off, failing, or returning null."

### Startup Requirements
Agents should only require:
1. Kalshi catalog/market universe ready
2. Spot/basis alignment ready
3. Live bankroll / portfolio fetched

Sentiment is NOT a startup dependency.

### Architecture Principle
Sentiment may be a feature inside a model that outputs edge/probability, but the output is just a number. No separate branch looks at sentiment in the execution path. No test or production code asserts anything about sentiment to allow an order to go through; only risk, EV, and market constraints matter.
