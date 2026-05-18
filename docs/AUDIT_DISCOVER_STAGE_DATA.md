# MERID Pipeline Audit — Discover Stage Data Collection

**Date:** 2026-03-26
**Focus:** Energy, News, and Sentiment Ingestion for Swarm Decisions
**Scope:** Discover, Analyze, Consensus, Size, Execute, Monitor, Promote, Protect stages

---

## Executive Summary

This audit evaluates MERID's data ingestion pipeline across eight decision stages, identifying gaps in energy market integration, sentiment processing, and cross-venue arbitrage. The pipeline integrates Kalshi prediction markets with multi-platform social sentiment (Reddit, X, Telegram) to fuel swarm-based trading decisions.

**Key Findings:**
- ✅ Market discovery infrastructure is robust (62/62 items complete per KALSHI_SWARM_GAP_ANALYSIS.md)
- ⚠️ Energy-specific ticker filtering missing (no ERCOT, oil, carbon markets)
- ⚠️ Sentiment processing overweights headlines vs content
- 🔴 No cross-venue arbitrage between Kalshi and onchain energy futures (Pyth integration needed)

---

## Pipeline Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│ MERID 8-STAGE PIPELINE                                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  1. DISCOVER  → Scan Kalshi markets + social buzz                   │
│                 - REST: KalshiMarketCatalog (5min refresh)           │
│                 - WebSocket: Real-time orderbook/trades              │
│                 - Social: Twitter/Reddit/Telegram scrapers            │
│                                                                       │
│  2. ANALYZE   → Process feeds into signals                           │
│                 - Sentiment: FinBERT + VADER scoring                 │
│                 - Order book: Microstructure forecaster              │
│                 - Quality: CQI computation (Brier-weighted)          │
│                                                                       │
│  3. CONSENSUS → Swarm voting with weighted aggregation               │
│                 - Weighted: trust × confidence × calibration         │
│                 - Auction: Conflict resolution via bidding           │
│                 - Diversity: ≥2 agent archetypes required            │
│                                                                       │
│  4. SIZE      → Kelly criterion with risk caps                       │
│                 - Fractional Kelly with fees                         │
│                 - Position caps per asset/category                   │
│                 - Correlation-aware exposure reduction               │
│                                                                       │
│  5. EXECUTE   → Order routing with maker/taker policy                │
│                 - MakerTakerPolicyEngine (3 modes)                   │
│                 - Execution intelligence (5-factor scoring)          │
│                 - Order groups for multi-leg trades                  │
│                                                                       │
│  6. MONITOR   → PnL, volume, sentiment drift tracking                │
│                 - Paper/shadow/live performance tracking             │
│                 - Drawdown governance (tiered stops)                 │
│                 - Volume anomaly detection (Kalman + z-score)        │
│                                                                       │
│  7. PROMOTE   → Auto-promotion: paper → shadow → live                │
│                 - Quantitative gates: PF, expectancy, drawdown       │
│                 - Automatic rollback on degradation                  │
│                 - Deployment controller with health checks           │
│                                                                       │
│  8. PROTECT   → Kill switches + circuit breakers                     │
│                 - Global + per-domain kill switches                  │
│                 - Liquidity thresholds (min $1000)                   │
│                 - Sentiment shock detection (>50% flip)              │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Stage 1: Discover — Market & Sentiment Discovery

### 1.1 Kalshi Market Discovery

**Status:** ✅ **Implemented**
**Files:**
- `merid/event_venues/kalshi/market_catalog.py` (primary)
- `merid/event_venues/kalshi/collector.py` (historical data)
- `merid/event_venues/kalshi/ws.py` (real-time streaming)

**Current Implementation:**
- **REST API Polling**: `KalshiMarketCatalog.refresh()` every 300 seconds
- **Category Detection**: Regex-based ticker patterns for 9 categories
  - Crypto: `KXBTC`, `KXETH`, `KXSOL`, `KXDOGE`, `KXXRP`
  - Economics: `KXCPI`, `KXGDP`, `KXJOBS`, `KXFED`
  - Financials: `KXSPX`, `KXNDX`, `KXDJI`
  - Politics: `KXELECTION`, `KXTRUMP`, `KXSENATE`
  - Sports, Climate, Culture, Tech, Science
- **Filters**: `seriesTicker`, `status=open`, quality gates (volume, spread, price)
- **WebSocket**: Real-time orderbook/trade/ticker subscriptions with sequence tracking

**Energy Market Gap — SEVERITY: MEDIUM**

❌ **Missing Energy Category Ticker Patterns**

Current catalog has no explicit energy market detection:
- No regex for ERCOT markets (Texas grid electricity)
- No oil/gas ticker patterns (WTI, Brent crude)
- No carbon credit market detection
- No renewable energy market patterns

**Example Energy Markets (from Kalshi):**
- ERCOT zero-carbon electricity share markets
- Natural gas price thresholds
- Oil production volume predictions
- Carbon offset futures

**Recommendation:**
```python
# Add to market_catalog.py category detection
ENERGY_PATTERNS = [
    r"KXERCOT",           # ERCOT electricity markets
    r"KXOIL",             # Oil price markets
    r"KXGAS",             # Natural gas markets
    r"KXCARBON",          # Carbon credit markets
    r"KXRENEW",           # Renewable energy
    r".*ENERGY.*",        # Catch-all for energy keyword
]
```

**Priority:** P1 (Medium) — Enables energy market discovery

---

### 1.2 Social Sentiment Discovery

**Status:** ✅ **Implemented** with gaps
**Files:**
- `merid/sentiment/twitter_fetcher.py` (Twitter polling)
- `merid/sentiment/reddit_scraper.py` (Reddit subreddit monitoring)
- `agents/telegram_agent.py` (Telegram channel monitoring)
- `merid/sentiment/hashtag_agent.py` (event-aware sentiment bridge)

**Current Implementation:**
- **Twitter**: Queries for BTC, ETH, SOL, XRP, DOGE, FED, CPI, SPX keywords
- **Reddit**: Monitors r/Bitcoin, r/CryptoCurrency, r/Kalshi, r/wallstreetbets, etc.
- **Telegram**: System alerts and market updates (posting only, not scraping)
- **Sentiment Scoring**: VADER compound scores (-1 to +1)
- **Volume Spike Detection**: current_volume > 2.5× rolling_avg
- **Engagement Weighting**: Likes, retweets, upvotes weighted into sentiment aggregate

**Energy Social Discovery Gap — SEVERITY: HIGH**

❌ **Missing Energy-Specific Social Channels**

Current implementation focuses on crypto keywords. Energy markets require:

**Missing Subreddits:**
- r/energytrading
- r/oil
- r/renewableenergy
- r/ERCOT
- r/commodities

**Missing Twitter Keywords:**
- "ERCOT outage", "Texas grid"
- "oil prices", "WTI crude", "Brent crude"
- "natural gas", "LNG"
- "carbon credits", "emissions"
- "wind power", "solar capacity"

**Missing Telegram Channels:**
- Energy trading groups
- Commodity futures channels
- Grid operator alert channels

**Recommendation:**
```python
# Add to twitter_fetcher.py and reddit_scraper.py
ENERGY_KEYWORDS = [
    "ERCOT", "Texas grid", "electricity prices",
    "oil prices", "WTI", "Brent crude", "OPEC",
    "natural gas", "LNG", "gas storage",
    "carbon credits", "emissions trading",
    "wind power", "solar capacity", "renewable energy"
]

ENERGY_SUBREDDITS = [
    "energytrading", "oil", "renewableenergy",
    "ERCOT", "commodities", "energy"
]
```

**High-Volume Post Threshold:**
- Reddit: >100 upvotes
- Twitter: >500 engagements
- Telegram: >50 mentions in 1h window

**Priority:** P0 (High) — Required for energy market sentiment signals

---

### 1.3 Volume & Liquidity Discovery

**Status:** ✅ **Implemented**
**Files:**
- `merid/event_venues/kalshi/volume_monitor.py`
- `merid/event_venues/kalshi/liquidity_monitor.py`
- `merid/event_venues/kalshi/market_filter.py`

**Current Implementation:**
- **Volume Monitor**: Polls catalog every 60s, Kalman filtering, z-score anomaly detection (threshold: 3σ)
- **Liquidity Monitor**: Spread/depth alerting when below thresholds
- **Market Filter**: Quality gates with configurable thresholds
  - `min_volume: 50` contracts
  - `min_open_interest: 10` contracts
  - `max_spread_cents: 12` (12¢ spread)
  - Price range: 10¢ to 90¢

**Gap:** Energy markets may have different liquidity profiles than crypto markets. ERCOT markets may have wider spreads or lower volume due to specialized nature.

**Recommendation:**
- Add category-specific quality thresholds
- Energy markets: `max_spread_cents: 20`, `min_volume: 25`
- Track energy market liquidity separately in observability

**Priority:** P2 (Low) — Nice to have but not critical

---

## Stage 2: Analyze — Signal Processing & Quality Scoring

### 2.1 Sentiment Analysis Processing

**Status:** 🟡 **Partial Gap**
**Files:**
- `core/sentiment_nlp.py` (FinBERT + VADER)
- `merid/sentiment/news_sentiment.py` (news headlines)

**Current Implementation:**
- **FinBERT**: ProsusAI/finbert model, 512-token truncation, GPU support
- **VADER**: Keyword-based scoring with financial sentiment dictionary
- **Blending**: 60% VADER + 40% FinBERT when both available
- **News Processing**: Headlines scored via FinBERT, confidence filtering (min 0.6)

**Sentiment Processing Gap — SEVERITY: HIGH**

⚠️ **Headline Overweighting vs Content**

From `news_sentiment.py`:
```python
def score_headline(self, headline: str) -> NewsSentimentResult:
    # Only processes headlines, not article content
    result = self.finbert_analyzer.analyze(headline)
```

**Research Findings** (from problem statement):
> "Sentiment overweighted on headlines vs. content; energy news shows content superior for stock preds. Fix: Parallel FinBERT pipelines, threshold >0.3 abs(sentiment) for swarm input."

**Issue:**
- Current code scores headlines only, not full article content
- Energy news often has misleading headlines (clickbait) vs substantive content
- Financial studies show article content has higher predictive value for energy stocks

**Recommendation:**
1. Add parallel pipelines: `score_headline()` + `score_content()`
2. Weight: 30% headline + 70% content for final sentiment
3. Filter signals: only pass to swarm if `|sentiment| > 0.3`
4. Chunk long articles (>512 tokens) and aggregate sentiment per chunk

**Priority:** P0 (High) — Critical for energy market prediction quality

---

### 2.2 Order Book & Microstructure Analysis

**Status:** ✅ **Implemented**
**Files:**
- `merid/event_venues/kalshi/orderbook.py` (local orderbook tracking)
- `merid/prediction/forecasters/orderbook.py` (microstructure forecaster)

**Current Implementation:**
- **LocalOrderbook**: Maintains YES/NO level dictionaries, bid/ask spread computation
- **OrderbookForecaster**: 4 signals
  1. Bid/ask imbalance (depth ratio)
  2. Spread compression (narrowing spread signal)
  3. Depth-weighted fair value (bias detection)
  4. Trade flow imbalance (buy vs sell aggressor)
- **DataFrame Processing**: Kalshi order books converted to pandas DataFrames

**No gaps identified.** Implementation is comprehensive.

---

### 2.3 CQI (Consensus Quality Index) Computation

**Status:** ✅ **Implemented**
**Files:**
- `merid/signals/drift.py`
- `merid/signals/store.py`

**Current Implementation:**
- **CQI Formula**: `0.30×brier + 0.25×pnl + 0.20×drift + 0.25×decay`
- **Band Classification**: good (>0.65), neutral (0.35-0.65), poor (<0.35)
- **Risk Adjustments**: Position sizing multipliers (0.5x-1.0x) based on CQI band
- **Tracking**: Per-domain drift metrics over rolling windows (default 24h)

**No gaps identified.** CQI system is production-ready.

---

## Stage 3: Consensus — Swarm Decision Making

### 3.1 Weighted Voting & Aggregation

**Status:** ✅ **Implemented**
**Files:**
- `merid/swarm/consensus_aggregator.py`
- `consensus/consensus_coordinator.py`
- `core/consensus_engine.py`

**Current Implementation:**
- **Vote Weighting**: `trust_score × agent_reliability × confidence`
- **Probability Blend**: Social platforms weighted (Reddit 40%, X 30%, Telegram 20%, News 10%)
- **Quorum**: 60% of registered agents required
- **Auction Consensus**: Conflict resolution via escalation-based bidding

**Energy Calibration Gap — SEVERITY: HIGH**

🔴 **Missing Energy-Specific Calibration**

From problem statement:
> "Past integrations handle prediction markets fully, but energy-specific calibration missing (e.g., ERCOT volatility)."

**Issue:**
- Current calibration uses generic Brier scores across all categories
- Energy markets (ERCOT electricity, oil prices) have different:
  - Volatility profiles (spiky vs smooth)
  - Seasonality patterns (weather-dependent)
  - News sensitivity (geopolitical events, weather shocks)
  - Time-to-expiry behavior (hourly markets vs daily)

**Recommendation:**
1. Track Brier scores per category: `crypto`, `economics`, `financials`, `energy`
2. Energy-specific CQI component weights:
   - Increase drift weight (0.30 vs 0.20) for weather/supply shocks
   - Decrease decay weight (0.15 vs 0.25) for event-driven moves
3. Add volatility regime detection for energy markets
4. Separate calibration window: 7 days for energy vs 24h for crypto

**Priority:** P0 (High) — Required for energy market accuracy

---

### 3.2 Cross-Venue Arbitrage Detection

**Status:** 🔴 **Critical Gap**
**Files:**
- `merid/signals/arbitrage.py` (existing arb scanner)
- `oracles/pyth.py` (existing Pyth oracle)

**Current Implementation:**
- **VenuePrice**: Tracks bid/ask/spread/liquidity per venue
- **DislocationSignal**: Detects gross edge, computes net edge after fees
- **Supported Venues**: Kalshi only (no cross-venue comparison implemented)
- **Pyth Oracle**: Fetches BTC/ETH/SOL/XRP/DOGE price feeds, but not integrated into arbitrage scanner

**Cross-Venue Arbitrage Gap — SEVERITY: HIGH**

🔴 **No Kalshi vs Onchain Energy Futures Arbitrage**

From problem statement:
> "High-severity gap: No cross-venue arb (Kalshi vs. crypto energy futures). Enhance with Pyth-Kalshi onchain feeds for prob distributions."

**Issue:**
- Pyth Network announced partnership with Kalshi to deliver real-time prediction market data onchain
- Energy markets exist on both Kalshi (binary contracts) and crypto prediction markets
- No scanner comparing Kalshi energy market probabilities vs onchain energy futures

**Example Arbitrage Opportunity:**
- **Kalshi**: ERCOT zero-carbon share >30% (implied prob: 65%)
- **Onchain Prediction Market**: Same event (implied prob: 58%)
- **Gross Edge**: 7% probability difference = potential arbitrage

**Recommendation:**
1. Extend `arbitrage.py` DislocationScanner to support Pyth feed comparison
2. Add `detect_kalshi_pyth_arb()` method:
   - Fetch Kalshi market probability (from orderbook mid)
   - Fetch Pyth probability feed for same event
   - Compute gross edge in probability space
   - Convert to dollar edge: `edge_usd = size × (p_kalshi - p_pyth) × $1_payout`
3. Add energy event matching logic (map Kalshi ticker → Pyth feed ID)
4. Implement multi-leg execution: short Kalshi + long onchain (or vice versa)

**Technical Details:**
```python
# Pseudocode for implementation
class PythKalshiArbScanner:
    def detect_energy_arb(self, kalshi_ticker: str) -> Optional[ArbSignal]:
        # 1. Get Kalshi market probability
        kalshi_prob = self._get_kalshi_mid(kalshi_ticker)

        # 2. Map to Pyth feed ID (e.g., ERCOT markets)
        pyth_feed_id = self._map_ticker_to_pyth_feed(kalshi_ticker)
        if not pyth_feed_id:
            return None

        # 3. Fetch Pyth probability feed
        pyth_prob = await self._fetch_pyth_probability(pyth_feed_id)

        # 4. Compute edge
        gross_edge = abs(kalshi_prob - pyth_prob)
        if gross_edge < 0.05:  # 5% threshold
            return None

        # 5. Account for fees and execution costs
        kalshi_fees = compute_kalshi_fees(kalshi_prob, size=100)
        onchain_gas = estimate_gas_cost()
        net_edge = gross_edge - kalshi_fees - onchain_gas

        if net_edge > 0.02:  # 2% net edge threshold
            return ArbSignal(
                venue_buy="pyth" if kalshi_prob > pyth_prob else "kalshi",
                venue_sell="kalshi" if kalshi_prob > pyth_prob else "pyth",
                gross_edge_bps=int(gross_edge * 10000),
                net_edge_bps=int(net_edge * 10000),
                ttl_seconds=120
            )
```

**Priority:** P0 (High) — High-value arbitrage opportunity

---

### 1.4 Social Volume & Buzz Tracking

**Status:** ✅ **Implemented**
**Files:**
- `merid/sentiment/twitter_fetcher.py`
- `merid/sentiment/reddit_scraper.py`
- `merid/sentiment/hashtag_agent.py`

**Current Implementation:**
- **Volume Spike Detection**: `current > 2.5× rolling_avg`
- **High-Volume Posts**: Reddit >100 upvotes tracked
- **Engagement Weighting**: Likes, retweets, comments weighted into aggregate
- **Asset Tagging**: Regex extraction of asset mentions per post

**Gap:** No explicit energy keyword tracking (see 1.2 above).

**Recommendation:** Add energy keywords to existing infrastructure (see Section 1.2).

**Priority:** P0 (High) — Bundled with energy social discovery

---

## Stage 4: Size & Execute — Position Sizing & Order Routing

### 4.1 Kelly Criterion Position Sizing

**Status:** ✅ **Implemented**
**Files:**
- `merid/event_venues/kalshi/kalshi_risk.py`
- `merid/event_venues/kalshi/position_sizer.py`

**Current Implementation:**
- **Fee-Aware Kelly**: Accounts for Kalshi parabolic fee schedule
  - Taker: `ceil(0.07 × C × P × (1-P))` dollars
  - Maker: `ceil(0.0175 × C × P × (1-P))` dollars
- **Fractional Kelly**: `kelly_frac = 0.25` (quarter-Kelly for safety)
- **Position Caps**: Per-asset notional limits, per-category caps
- **Open Interest Cap**: Limited by `open_interest_fp` from Kalshi market data

**Batching Gap — SEVERITY: MEDIUM**

⚠️ **No Batching for Multi-Market Energy Series**

From problem statement:
> "Audit flags: No batching for multi-market energy series; PyKalshi supports retries/backoff."

**Issue:**
- When multiple energy markets in same series (e.g., ERCOT hourly series), orders placed individually
- No batch order submission to reduce API calls and improve atomicity
- Kalshi REST API supports batch operations but not currently used

**Recommendation:**
```python
# Add to order_router.py
def submit_batch_orders(self, orders: List[OrderIntent]) -> List[OrderResult]:
    # Group by series/asset
    by_series = defaultdict(list)
    for order in orders:
        series = self._extract_series(order.ticker)
        by_series[series].append(order)

    # Submit batches
    results = []
    for series, series_orders in by_series.items():
        batch_result = await self.client.submit_batch(series_orders)
        results.extend(batch_result)

    return results
```

**Priority:** P1 (Medium) — Performance optimization, not critical

---

### 4.2 CQI Gating for Telegram Sentiment Spikes

**Status:** ❌ **Missing**
**Files:**
- `merid/sentiment/telegram_agent.py` (currently posting only)
- `merid/signals/drift.py` (CQI computation exists)

**CQI Gate Gap — SEVERITY: MEDIUM**

⚠️ **Telegram Hype Spikes Un-Sized for Volatility**

From problem statement:
> "Telegram hype spikes un-sized for volatility—add CQI gate (>0.7)."

**Issue:**
- Telegram sentiment spikes can cause outsized position sizing
- No quality filter on Telegram signals before consensus
- High risk of following pump-and-dump schemes or manipulation

**Recommendation:**
```python
# Add to consensus_aggregator.py
def _filter_telegram_signals(self, signals: List[SentimentSignal]) -> List[SentimentSignal]:
    filtered = []
    for signal in signals:
        if signal.source == "telegram":
            # Require high CQI for Telegram signals
            cqi = self._get_domain_cqi("social_telegram")
            if cqi.quality_index < 0.7:
                logger.warning(f"Telegram signal filtered: CQI {cqi.quality_index:.2f} < 0.7")
                continue

            # Additional spike detection filter
            if signal.volume_spike and signal.confidence < 0.6:
                logger.warning("Telegram volume spike with low confidence, filtering")
                continue

        filtered.append(signal)

    return filtered
```

**Priority:** P0 (High) — Risk management for social manipulation

---

### 2.4 Sentiment Decay Tuning

**Status:** 🟡 **Needs Tuning**
**Files:**
- `merid/sentiment/sentiment_bus.py`
- `merid/swarm/consensus_aggregator.py`

**Current Implementation:**
- Generic 2h half-life for social sentiment decay
- No platform-specific decay rates

**Decay Tuning Gap — SEVERITY: MEDIUM**

⚠️ **Decay Not Tuned Per Platform**

From problem statement (Risk Table):
> "Sentiment | Medium | Decay not tuned | Half-life per platform"

**Issue:**
- Twitter has faster signal decay (news cycle: 2-4 hours)
- Reddit discussions have longer half-life (12-24 hours)
- Telegram hype can persist for days or fade in minutes
- Energy markets: fundamental news has multi-day impact (supply disruptions)

**Recommendation:**
```python
# Platform-specific decay half-lives
SENTIMENT_DECAY_HALFLIFE = {
    "twitter": 2 * 3600,      # 2 hours
    "reddit": 12 * 3600,      # 12 hours
    "telegram": 4 * 3600,     # 4 hours
    "news": 24 * 3600,        # 24 hours (energy fundamentals)
}

def compute_decayed_sentiment(signal, age_seconds):
    halflife = SENTIMENT_DECAY_HALFLIFE[signal.platform]
    decay_factor = 2 ** (-age_seconds / halflife)
    return signal.sentiment_score * decay_factor
```

**Priority:** P1 (Medium) — Improves signal quality over time

---

## Stage 6: Monitor — Performance & Risk Tracking

### 6.1 PnL & Volume Monitoring

**Status:** ✅ **Implemented**
**Files:**
- `merid/trading/paper_session.py`
- `merid/event_venues/kalshi/volume_monitor.py`
- `merid/swarm/performance.py`

**Current Implementation:**
- **Paper Session**: Tracks per-cell, per-cluster PnL with daily/weekly rollups
- **Volume Monitor**: Kalman filtering + z-score anomaly detection
- **Performance Comparator**: Backtest vs paper vs live comparison
- **Drawdown Governance**: Tiered stops (warning 5%, downsize 8%, halt 12%)

**Real-Time Social Volume Alerts Gap — SEVERITY: MEDIUM**

⚠️ **No Real-Time Social Volume Alerts**

From problem statement:
> "Gaps: No real-time social volume alerts; integrate Octobot-style Reddit evaluator."

**Issue:**
- Volume monitor only tracks Kalshi market volume
- No real-time alerting for social media volume spikes
- Reddit/Twitter polling is periodic (2-5 min intervals), not real-time streaming

**Current Polling Intervals:**
- Twitter: Every 2 minutes (rate limit: 20 calls/min)
- Reddit: Every 5 minutes (rate limit: 10 calls/min)
- Telegram: Posting only, no scraping

**Recommendation:**
```python
# Add to sentiment monitoring
class SocialVolumeMonitor:
    def __init__(self):
        self.baseline_volume = {}  # asset → rolling avg
        self.alert_threshold = 3.0  # 3× baseline

    async def check_volume_spike(self, asset: str) -> Optional[VolumeAlert]:
        current = self._get_current_volume(asset)
        baseline = self.baseline_volume.get(asset, current)

        if current > baseline * self.alert_threshold:
            return VolumeAlert(
                asset=asset,
                current_volume=current,
                baseline_volume=baseline,
                spike_ratio=current / baseline,
                platform="reddit",  # or twitter/telegram
                timestamp=datetime.now(timezone.utc)
            )

        # Update rolling average
        self.baseline_volume[asset] = 0.9 * baseline + 0.1 * current
        return None
```

**Integration:** Wire to Telegram/Discord alerting system for manual review.

**Priority:** P1 (Medium) — Useful for catching early momentum shifts

---

## Stage 8: Protect — Kill Switches & Circuit Breakers

### 8.1 Liquidity Kill Switches

**Status:** ✅ **Implemented**
**Files:**
- `merid/trading/execution_guard.py`
- `merid/event_venues/kalshi/kalshi_risk.py`

**Current Implementation:**
- **Global Kill Switch**: Halts all trading when triggered
- **Per-Domain Kill Switch**: Halts trading for specific domains (crypto, prediction, sports)
- **Liquidity Threshold**: Minimum `liquidity_dollars` check before order submission
- **Circuit Breaker**: Exponential backoff on API failures

**Energy Early Close Gap — SEVERITY: LOW**

🟡 **Missing Energy Early Close Condition Handling**

From problem statement:
> "Past P0 fixes addressed Kalshi fees/settlement; extend to energy early_close_condition."

**Issue:**
- Kalshi energy markets can settle early based on real-world events
- Example: ERCOT outage market resolves early if grid fails
- Current code handles standard expiry but not early close events

**Recommendation:**
```python
# Add to market_catalog.py
@dataclass
class CatalogMarket:
    # ... existing fields ...
    early_close_condition: Optional[str] = None  # e.g., "ERCOT outage reported"
    can_close_early: bool = False

# Add to order_manager.py
def _check_early_close(self, ticker: str) -> bool:
    market = self.catalog.get_market(ticker)
    if market.can_close_early:
        # Check API for early resolution
        status = await self.client.get_market_status(ticker)
        if status.get("result") is not None:
            logger.warning(f"Market {ticker} closed early: {status['result']}")
            return True
    return False
```

**Priority:** P2 (Low) — Edge case, not critical for initial deployment

---

### 8.2 Sentiment Shock Circuit Breakers

**Status:** ✅ **Implemented**
**Files:**
- `merid/signals/drift.py`
- `merid/swarm/consensus_aggregator.py`

**Current Implementation:**
- **Sentiment Drift Detection**: Tracks sentiment changes over time windows
- **Consensus Confidence Degradation**: Low agreement triggers reduced sizing
- **Veto System**: Risk agents can veto trades with score ≤ -0.5

**Enhancement Recommendation:**
Add explicit sentiment shock detection:
```python
def detect_sentiment_shock(self, asset: str) -> bool:
    current = self._get_current_sentiment(asset)
    previous = self._get_previous_sentiment(asset, lookback_minutes=60)

    flip_magnitude = abs(current - previous)
    if flip_magnitude > 0.5:  # 50% sentiment flip
        logger.error(f"Sentiment shock detected for {asset}: {previous:.2f} → {current:.2f}")
        return True

    return False
```

**Priority:** P1 (Medium) — Enhances existing protection

---

## Stage 2 & 5: WebSocket Streaming Enhancement

### WebSocket Streaming for Live Discovery

**Status:** ✅ **Implemented** (already robust)
**Files:**
- `merid/event_venues/kalshi/ws.py`
- `merid/event_venues/kalshi/ws_bridge.py`

**Current Implementation:**
- **Kalshi WebSocket Client**: Real-time orderbook/trade/ticker subscriptions
- **Reconnection**: Exponential backoff with jitter
- **Sequence Tracking**: Gap detection per market
- **Message Queue**: Async queue with 4096 max size
- **Error Handling**: Fatal error codes (auth_failed, invalid_token, rate_limited)

**Recommendation from problem statement:**
> "Implement WebSocket streaming via PyKalshi for live market discovery."

**Assessment:** Already implemented and production-ready. No changes needed.

---

## Priority Matrix — P0 Fixes for Develop Branch Merge

From problem statement:
> "Prioritize 6 P0 fixes (energy filters, decay tuning, arb scanner) for develop branch merge."

### P0 (High Priority — Must Fix)

| Priority | Fix | Severity | File(s) | Effort |
|----------|-----|----------|---------|--------|
| **P0-1** | Add energy ticker filtering regex | High | `market_catalog.py` | 1h |
| **P0-2** | Add energy keywords to social scrapers | High | `twitter_fetcher.py`, `reddit_scraper.py` | 2h |
| **P0-3** | Implement parallel FinBERT pipelines (headline + content) | High | `news_sentiment.py` | 4h |
| **P0-4** | Add Pyth-Kalshi arbitrage scanner | High | `arbitrage.py`, new file | 6h |
| **P0-5** | Add CQI gate for Telegram signals | High | `consensus_aggregator.py` | 2h |
| **P0-6** | Add energy-specific calibration | High | `drift.py`, `calibration.py` | 3h |

**Total Estimated Effort:** 18 hours

---

### P1 (Medium Priority — Should Fix)

| Priority | Fix | Severity | File(s) | Effort |
|----------|-----|----------|---------|--------|
| **P1-1** | Platform-specific sentiment decay tuning | Medium | `sentiment_bus.py` | 2h |
| **P1-2** | Social volume alerting system | Medium | New file + integration | 4h |
| **P1-3** | Batch order submission for series | Medium | `order_router.py` | 3h |
| **P1-4** | Sentiment shock circuit breaker | Medium | `drift.py` | 2h |

---

### P2 (Low Priority — Nice to Have)

| Priority | Fix | Severity | File(s) | Effort |
|----------|-----|----------|---------|--------|
| **P2-1** | Category-specific quality thresholds | Low | `market_filter.py` | 1h |
| **P2-2** | Energy early close condition handling | Low | `market_catalog.py`, `order_manager.py` | 2h |

---

## Implementation Roadmap

### Phase 1: Energy Discovery (P0-1, P0-2)
1. Add energy ticker patterns to market catalog
2. Add energy keywords to Twitter/Reddit scrapers
3. Test discovery with Kalshi demo energy markets

**Estimated:** 3 hours

---

### Phase 2: Sentiment Processing (P0-3, P1-1)
1. Implement parallel FinBERT: headline + content pipelines
2. Add sentiment threshold filter (|score| > 0.3)
3. Implement platform-specific decay rates
4. Test with historical news articles

**Estimated:** 6 hours

---

### Phase 3: Arbitrage Detection (P0-4)
1. Create `PythKalshiArbScanner` class
2. Implement energy event matching (Kalshi ticker → Pyth feed ID)
3. Add cross-venue probability comparison
4. Wire into consensus aggregator
5. Add monitoring/alerting for arbitrage opportunities

**Estimated:** 6 hours

---

### Phase 4: Risk Gating (P0-5, P0-6)
1. Add CQI gate for Telegram signals
2. Implement energy-specific Brier calibration buckets
3. Add volatility regime detection for energy
4. Test with historical energy market data

**Estimated:** 5 hours

---

### Phase 5: Monitoring Enhancements (P1-2, P1-3, P1-4)
1. Build social volume monitoring system
2. Add batch order submission
3. Implement sentiment shock detection
4. Wire to alerting infrastructure

**Estimated:** 9 hours

---

## Testing Strategy

### Unit Tests
- Energy ticker regex matching (new patterns)
- FinBERT content processing (chunking, aggregation)
- Pyth-Kalshi arbitrage signal generation
- CQI gating logic for Telegram
- Decay rate calculations per platform

### Integration Tests
- End-to-end energy market discovery
- Social sentiment with energy keywords
- Cross-venue arbitrage detection with mock Pyth feeds
- Consensus aggregation with filtered Telegram signals

### Regression Tests
- Existing crypto market discovery still works
- Calibration weights unchanged for non-energy assets
- No impact on existing forecaster performance

### Manual Verification
- Deploy to demo environment with Kalshi demo credentials
- Monitor logs for energy market discovery
- Verify sentiment processing with test news articles
- Check arbitrage scanner output with mock scenarios

---

## Configuration Requirements

### Environment Variables

```bash
# Energy Market Discovery
MERID_ENERGY_DISCOVERY_ENABLED=true
MERID_ENERGY_TICKER_PATTERNS=KXERCOT,KXOIL,KXGAS,KXCARBON

# Social Sentiment
MERID_ENERGY_REDDIT_SUBREDDITS=energytrading,oil,renewableenergy,ERCOT
MERID_ENERGY_TWITTER_KEYWORDS=ERCOT,oil prices,natural gas,carbon credits

# Sentiment Processing
MERID_FINBERT_PROCESS_CONTENT=true
MERID_FINBERT_CONTENT_MAX_TOKENS=2048
MERID_SENTIMENT_THRESHOLD=0.3

# Pyth Integration
MERID_PYTH_ARB_ENABLED=true
MERID_PYTH_ENERGY_FEEDS=ercot_carbon_share,wti_crude,natural_gas

# CQI Gating
MERID_TELEGRAM_CQI_THRESHOLD=0.7
MERID_SOCIAL_VOLUME_ALERT_ENABLED=true

# Platform Decay Rates (seconds)
MERID_DECAY_TWITTER=7200
MERID_DECAY_REDDIT=43200
MERID_DECAY_TELEGRAM=14400
MERID_DECAY_NEWS=86400
```

---

## Risk Assessment

### High-Severity Gaps (P0)
1. **Energy ticker filtering** — Without this, energy markets won't be discovered
2. **Telegram CQI gating** — Risk of manipulation without quality filter
3. **Pyth-Kalshi arbitrage** — Missing high-value trading opportunity
4. **FinBERT content processing** — Headline-only sentiment reduces prediction quality

### Medium-Severity Gaps (P1)
1. **Sentiment decay tuning** — Suboptimal signal weighting over time
2. **Social volume alerts** — Delayed reaction to momentum shifts
3. **Batch order submission** — Performance bottleneck for series trades

### Low-Severity Gaps (P2)
1. **Category-specific quality thresholds** — Minor optimization
2. **Early close handling** — Edge case, rare occurrence

---

## Dependencies & External APIs

### Kalshi API
- **Endpoint**: `https://trading-api.kalshi.com/trade-api/v2`
- **Rate Limits**: 120 req/min per IP
- **Features Used**: `/markets`, `/events`, `/orderbook`, WebSocket
- **Status**: ✅ Production-ready

### NewsAPI
- **Endpoint**: `https://newsapi.ai/api/v1`
- **Rate Limits**: 100 req/day (free tier), 1000 req/day (paid)
- **Features Used**: `/articles` with crypto/energy keywords
- **Status**: ✅ Implemented in `news_sentiment.py`

### Pyth Network
- **Endpoint**: `https://hermes.pyth.network/api`
- **Rate Limits**: No published limits (generous)
- **Features Used**: Price feeds for BTC/ETH/SOL/XRP/DOGE
- **Status**: 🟡 Oracle implemented, arbitrage scanner missing

### Twitter API v2
- **Rate Limits**: 20 calls/min
- **Features Used**: Tweet search with keyword filters
- **Status**: ✅ Implemented in `twitter_fetcher.py`

### Reddit API
- **Rate Limits**: 10 calls/min
- **Features Used**: Subreddit post scraping
- **Status**: ✅ Implemented in `reddit_scraper.py`

### Telegram Bot API
- **Rate Limits**: 30 messages/sec per bot
- **Features Used**: Message posting (not scraping)
- **Status**: ✅ Implemented in `telegram_agent.py`

---

## Self-Healing & Reliability

### WebSocket Disconnection Recovery

**Status:** ✅ **Implemented**
**File:** `merid/event_venues/kalshi/ws.py`

**Features:**
- Exponential backoff: `min(300s, 2^retry × (1 + jitter))`
- Sequence gap detection and orderbook resync
- Fatal error handling (auth failures, rate limits)
- Bounded message queue with backpressure

**Recommendation from problem statement:**
> "Self-healing on WebSocket disconnects, 100% test coverage via CI."

**Assessment:**
- Self-healing: ✅ Already implemented
- Test coverage: Check current coverage

---

## Test Coverage Analysis

**Current Test Files:**
- `tests/event_venues/kalshi/test_kalshi_regression.py`
- `tests/trading/test_kalshi_continuous_trader.py`
- `tests/test_bugfix_regressions.py`

**Coverage Gaps:**
- Energy ticker filtering: No tests yet (new feature)
- Pyth arbitrage scanner: No tests yet (new feature)
- FinBERT content processing: No tests yet (new feature)
- CQI gating: No tests yet (new feature)

**Recommendation:**
Achieve 100% test coverage for P0 fixes:
- Unit tests for all new functions
- Integration tests for end-to-end flows
- Regression tests to prevent breakage

---

## Master Prompt for LLM Auditor

Use this prompt to prioritize fixes in your LLM-powered auditor:

```
MERID Pipeline Audit — P0 Priority Fixes

Context: MERID integrates Kalshi prediction markets with social sentiment across 8 stages.
Goal: Implement 6 P0 fixes for energy market support.

Priority 1: Energy Market Discovery
- Add energy ticker regex patterns (KXERCOT, KXOIL, KXGAS, KXCARBON) to market_catalog.py
- Add energy keywords to twitter_fetcher.py and reddit_scraper.py
- Verify discovery with test energy markets

Priority 2: Sentiment Processing
- Implement parallel FinBERT pipelines for headline + content in news_sentiment.py
- Add sentiment threshold filter (|score| > 0.3)
- Add platform-specific decay rates (Twitter 2h, Reddit 12h, Telegram 4h, News 24h)

Priority 3: Cross-Venue Arbitrage
- Create PythKalshiArbScanner class in arbitrage.py
- Map Kalshi energy tickers to Pyth feed IDs
- Compare Kalshi probabilities vs Pyth onchain feeds
- Alert on net edge > 2% after fees

Priority 4: Risk Gating
- Add CQI gate (threshold 0.7) for Telegram signals in consensus_aggregator.py
- Implement energy-specific Brier calibration buckets in calibration.py
- Track per-category calibration: crypto, economics, financials, energy

Priority 5: Monitoring
- Add SocialVolumeMonitor for real-time volume spike detection
- Wire to Telegram/Discord alerting
- Set alert threshold: 3× baseline volume

Priority 6: Protection
- Extend kill switches for energy early close conditions
- Add sentiment shock circuit breaker (>50% flip in 1h)

Testing:
- Unit test all new functions
- Integration test end-to-end energy discovery → sentiment → consensus → execution
- Regression test to ensure crypto markets unchanged
- Achieve 100% test coverage for new code

Output:
- Implementation code for all 6 P0 fixes
- Test suite with full coverage
- Documentation updates
- Configuration guide with environment variables
```

---

## Next Steps

1. **Immediate (P0 Fixes):**
   - Implement energy ticker filtering
   - Add energy social keywords
   - Build FinBERT content pipeline
   - Create Pyth-Kalshi arbitrage scanner
   - Add CQI gate for Telegram
   - Implement energy calibration buckets

2. **Short-Term (P1 Fixes):**
   - Tune sentiment decay per platform
   - Add social volume alerting
   - Implement batch order submission

3. **Long-Term (P2 Enhancements):**
   - Category-specific quality thresholds
   - Energy early close handling
   - Advanced volatility regime detection

4. **Validation:**
   - Run full test suite with new tests
   - Deploy to staging environment
   - Monitor energy market discovery for 1 week
   - Validate arbitrage scanner with demo accounts

---

## Appendix: File Location Reference

### Discover Stage
- Market catalog: `merid/event_venues/kalshi/market_catalog.py`
- WebSocket client: `merid/event_venues/kalshi/ws.py`
- WebSocket bridge: `merid/event_venues/kalshi/ws_bridge.py`
- Twitter scraper: `merid/sentiment/twitter_fetcher.py`
- Reddit scraper: `merid/sentiment/reddit_scraper.py`
- Telegram agent: `agents/telegram_agent.py`
- Hashtag agent: `merid/sentiment/hashtag_agent.py`

### Analyze Stage
- Sentiment NLP: `core/sentiment_nlp.py`
- News sentiment: `merid/sentiment/news_sentiment.py`
- Order book: `merid/event_venues/kalshi/orderbook.py`
- Microstructure: `merid/prediction/forecasters/orderbook.py`
- Drift/CQI: `merid/signals/drift.py`
- Calibration: `merid/metrics/calibration.py`

### Consensus Stage
- Consensus aggregator: `merid/swarm/consensus_aggregator.py`
- Consensus coordinator: `consensus/consensus_coordinator.py`
- Consensus engine: `core/consensus_engine.py`
- Auction consensus: `merid/swarm/auction_consensus.py`
- Arbitrage scanner: `merid/signals/arbitrage.py`

### Execute Stage
- Order router: `merid/event_venues/kalshi/order_router.py`
- Maker/taker policy: `merid/event_venues/kalshi/maker_taker_policy.py`
- Execution guard: `merid/trading/execution_guard.py`

### Monitor Stage
- Paper session: `merid/trading/paper_session.py`
- Volume monitor: `merid/event_venues/kalshi/volume_monitor.py`
- Performance: `merid/swarm/performance.py`

### Protect Stage
- Risk manager: `merid/risk/global_risk_manager.py`
- Kill switches: `merid/trading/execution_guard.py`
- Drawdown governor: `merid/risk/drawdown_governor.py`

---

## Conclusion

MERID's pipeline foundation is **production-ready** (62/62 complete per existing gap analysis), but **energy market integration requires 6 P0 fixes** before production deployment:

1. Energy ticker filtering
2. Energy social keywords
3. FinBERT content pipelines
4. Pyth-Kalshi arbitrage
5. Telegram CQI gating
6. Energy calibration

These fixes enable MERID to:
- Discover ERCOT, oil, gas, and carbon markets
- Process energy news with content-based sentiment
- Capture cross-venue arbitrage between Kalshi and onchain markets
- Filter low-quality Telegram hype with CQI gates
- Calibrate energy market predictions separately from crypto

**Target Merge:** After P0 implementation + full test coverage + 1-week staging validation

---

**Document Version:** 1.0
**Last Updated:** 2026-03-26
**Author:** Claude Sonnet 4.5 (MERID Pipeline Audit Agent)
