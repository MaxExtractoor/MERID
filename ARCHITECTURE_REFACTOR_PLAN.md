# Kalshi 15-Minute Trading System Architecture Refactor

## Executive Summary

This document outlines the architectural refactor of the MERID Kalshi 15-minute crypto trading system based on peer-reviewed best practices and production requirements.

## Key Findings from Research

### Kalshi 15-Minute Market Structure
- **Single Market Invariant**: There is exactly ONE active 15-minute market per asset at any time
- **Market Identification**: Markets are identified by their expiration time (ET window)
- **Settlement**: Binary contracts settle at expiration (automatic exit)
- **Available Assets**: BTC, ETH, SOL, XRP, DOGE (5 assets total)

### Peer-Reviewed Best Practices
1. **Trade Volatility, Not Direction**: Fade the panic when the book moves hard
2. **Position Sizing**: 
   - Use fractional Kelly sizing (25% of full Kelly in practice)
   - Cap individual contract exposure at 2% of bankroll
3. **Avoid Tight Targets**: Don't run 2-cent price targets with high turnover (fees/slippage)
4. **Regime Awareness**: Strategies are regime-dependent and must adapt
5. **Liquidity Awareness**: Don't trade outside US market hours when liquidity is thinner

## Current Architecture Issues

### 1. Market Selection Flaws
- **Problem**: System was selecting arbitrary first market from catalog instead of exact ET window match
- **Impact**: Could select wrong or duplicate markets, leading to subscription errors
- **Fix**: Use `get_current_15m_market()` which enforces single-market invariant via exact ET window matching

### 2. WebSocket Subscription Issues
- **Problem**: `orderbook_snapshot` messages were not being subscribed to
- **Impact**: Orderbooks never initialized, causing `DELTA-QUEUE-FULL` errors and dropped deltas
- **Fix**: Added `orderbook_snapshot` to subscription channels in `ws.py`

### 3. WS Bridge Starting with No Tickers
- **Problem**: WS bridge would start with empty ticker list if catalog not populated
- **Impact**: No market data received, system cannot trade
- **Fix**: Improved catalog wait loop with better error handling and logging

### 4. Legacy vs Production Stack Contamination
- **Problem**: Multiple code paths using legacy components instead of production ones
- **Impact**: Inconsistent behavior, hard to debug
- **Fix**: Audit and remove legacy code paths, enforce production stack usage

## Refactored Architecture

### Core Principles

1. **Single Source of Truth**
   - Market catalog is the authoritative source for market discovery
   - Market state store is the authoritative source for orderbook data
   - Risk envelope is the authoritative source for position limits

2. **Exact Market Matching**
   - Use `get_current_15m_market()` for all market selection
   - Enforce single-market invariant: exactly 1 market per asset
   - No arbitrary selection or fallback to "first available"

3. **Graceful Degradation**
   - If WS fails, fall back to REST polling
   - If catalog fails, retry with exponential backoff
   - If market state is stale, refresh via REST

4. **Defensive Programming**
   - Validate all inputs
   - Log all state transitions
   - Add recursion guards
   - Implement circuit breakers

### Component Responsibilities

#### KalshiMarketCatalog
- **Purpose**: Discover and cache all Kalshi markets
- **Key Method**: `get_current_15m_market(asset)` - returns exactly ONE active market per asset
- **Refresh Interval**: 60 seconds (configurable)
- **Thread Safety**: Protected by asyncio lock

#### KalshiWebSocketBridge
- **Purpose**: Subscribe to and receive real-time market data from Kalshi WebSocket
- **Subscription Channels**: `["orderbook_delta", "orderbook_snapshot"]`
- **Market Selection**: Uses `get_current_15m_market()` to determine which markets to subscribe to
- **Fallback**: REST polling if WS connection fails

#### KalshiMarketStateStore
- **Purpose**: Maintain orderbook state for all subscribed markets
- **Initialization**: Requires `orderbook_snapshot` before applying deltas
- **Delta Queue**: Maximum 20 pending deltas (configurable)
- **Staleness Threshold**: 10 seconds for 15m markets

#### LeanAgent15m
- **Purpose**: Generate trading signals and candidates for 15-minute markets
- **Signal Type**: Velocity-based (fade the panic)
- **Position Sizing**: Fractional Kelly (25% of full Kelly)
- **Risk Limits**: 2% of bankroll per position

#### CandidateOptimizer
- **Purpose**: Filter and rank trading candidates
- **Pipeline**:
  1. Parallel market data collection
  2. Quality filtering
  3. Edge threshold filtering
  4. Final ranking and selection
- **Recursion Guard**: Prevent infinite recursion

### Data Flow

```
1. Market Discovery (KalshiMarketCatalog)
   └─> get_current_15m_market(asset) → 1 market per asset

2. WebSocket Subscription (KalshiWebSocketBridge)
   └─> Subscribe to ["orderbook_delta", "orderbook_snapshot"]
   └─> Receive real-time market data

3. Market State Update (KalshiMarketStateStore)
   └─> Apply snapshot to initialize orderbook
   └─> Apply deltas to update orderbook
   └─> Maintain best_bid/best_ask

4. Signal Generation (LeanAgent15m)
   └─> Read market state
   └─> Generate velocity-based signals
   └─> Create trading candidates

5. Candidate Optimization (CandidateOptimizer)
   └─> Filter by quality
   └─> Filter by edge threshold
   └─> Rank and select final candidates

6. Order Submission (OrderRouter)
   └─> Submit orders to Kalshi
   └─> Track fills and positions
```

### Error Handling Strategy

1. **Catalog Errors**
   - Retry with exponential backoff
   - Log all failures
   - Alert if catalog remains empty after 15 seconds

2. **WebSocket Errors**
   - Attempt reconnection (max 3 attempts)
   - Fall back to REST polling if WS fails
   - Log all connection errors

3. **Market State Errors**
   - Refresh via REST if stale
   - Log all state transitions
   - Alert if orderbook remains uninitialized

4. **Candidate Generation Errors**
   - Skip market if state is invalid
   - Log all validation failures
   - Continue with other markets

## Implementation Status

### Completed
- ✅ Fixed market selection to use exact ET window matching
- ✅ Added `orderbook_snapshot` to WebSocket subscription channels
- ✅ Improved catalog wait loop with better error handling
- ✅ Fixed WS bridge starting with no tickers

### In Progress
- 🔄 Architecture refactor based on peer-reviewed patterns
- 🔄 Remove legacy code paths
- 🔄 Implement graceful degradation
- 🔄 Add comprehensive diagnostics

### Pending
- ⏳ Implement velocity-based signal generation
- ⏳ Implement fractional Kelly position sizing
- ⏳ Add regime detection
- ⏳ Implement liquidity-aware trading hours

## Next Steps

1. **Complete Architecture Refactor**
   - Remove all legacy code paths
   - Enforce production stack usage
   - Add comprehensive validation

2. **Implement Peer-Reviewed Strategies**
   - Velocity-based signal generation (fade the panic)
   - Fractional Kelly position sizing
   - Regime detection and adaptation

3. **Add Comprehensive Diagnostics**
   - Market selection logging
   - WebSocket subscription logging
   - Market state transition logging
   - Candidate generation pipeline logging

4. **Implement Graceful Degradation**
   - WebSocket → REST fallback
   - Catalog retry with exponential backoff
   - Market state refresh via REST

5. **Add Risk Controls**
   - Position size limits (2% of bankroll)
   - Exposure tracking per asset
   - Circuit breakers for extreme volatility

## References

- Turbine Blog: "How to Trade Kalshi 15-Minute Crypto Contracts and Perpetual Futures"
- Turbine Blog: "We backtested 5,000 strategies on Kalshi BTC 15M. Only 2% made money."
- Kalshi View: "How to Find the Most Active Kalshi Markets Before You Trade"
- The Lines: "Kalshi 15 Minute Markets Guide & Trading Tips For 2026"
