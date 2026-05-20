# Sentiment Isolation Audit — Specification Document

## Objective

Conduct a hostile audit to ensure sentiment signals are **descriptive context only** and **never directly influence execution decisions** for Kalshi 15m crypto markets (BTC, ETH, SOL, XRP, DOGE).

Sentiment may inform diagnostics, research, and future model training, but cannot directly flip side, size, or entry for live 15m trades.

## Invariants

### Invariant #1: Sentiment is Descriptive, Not Actionable
- Sentiment is a model feature and telemetry signal, not an execution lever.
- Sentiment may be logged, analyzed, and used for research.
- Sentiment **must not** determine: side (YES/NO), quantity/size, price/contract selection, or whether to trade.
- Execution must depend only on: Kalshi market state, orderbook/candle pipeline, and 15m mean-reversion edge logic (distance, window, TP/SL, bankroll).

### Invariant #2: Structural Separation in Data Model
- Sentiment fields live in a dedicated `sentiment` envelope, never mixed into generic "edge" or "confidence" fields.
- Execution envelope (objects passed to Kalshi router) **must not** include sentiment fields.
- Clear separation: `ExecutionContext` (price/time/edge/TP/SL/bankroll only) vs `AnalysisContext` (can carry sentiment).

### Invariant #3: No Sentiment in Execution Path
- No sentiment-only strategies in the same execution path as live 15m Kalshi trading.
- Any pure sentiment strategies must go through separate research/sandbox environment.
- Functions that place orders **must not** read or depend on sentiment fields.

### Invariant #4: Agent-Level Invariant
- For each 15m agent (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M):
  - Sentiment can affect internal scoring only through the edge interface, or not at all.
  - No branches depend directly on sentiment outside internal model.
  - No custom "panic mode" logic wired to sentiment.

### Invariant #5: Consensus Layer Invariant
- Consensus aggregator treats sentiment as a tag/annotation only.
- Consensus formula **must not** read `sentiment_*` fields.
- Feature flag `MERID_ALLOW_SENTIMENT_IN_CONSENSUS` must be false in production.

### Invariant #6: Risk/Bankroll Invariant
- Sentiment **must not** touch bankroll sizing logic.
- Production bankroll logic is purely function of system-level risk settings and recent PnL.
- No dynamic sizing based on "market mood" in production.

## Data Flow Requirements

### Sentiment Data Flow
```
[Sentiment Sources] → [Sentiment Envelope] → [Telemetry/Research] → [Offline Analysis]
                                           ↓
                                   [Never reaches Execution]
```

### Execution Data Flow
```
[Kalshi Market State] → [Orderbook/Candle Pipeline] → [Edge Logic] → [Execution Context] → [Kalshi Router]
```

### Forbidden Data Flow
```
[Sentiment Sources] → [Execution Context] → [Kalshi Router]  ← FORBIDDEN
```

## Sentiment Envelope Specification

### Sentiment Data Structure
```python
@dataclass
class SentimentEnvelope:
    """Dedicated envelope for sentiment signals - never used for execution decisions."""
    sentiment_score: float  # Numeric, e.g., -1 to +1 or 0-100
    sentiment_source: str  # news, x/twitter, orderflow_proxy, etc.
    sentiment_confidence: float  # How reliable the signal is
    sentiment_version: str  # Model or feed version
    timestamp: datetime
```

### Allowed Locations
- `AnalysisContext.sentiment` - For research and diagnostics
- Forensic logs (telemetry section only)
- Offline analysis scripts

### Forbidden Locations
- `ExecutionContext` - Execution envelope
- Kalshi router and order constructors
- Risk/bankroll sizing logic
- Consensus aggregation formula
- Any function that directly determines side, size, or entry

## Execution Context Specification

### Execution Context (Sentiment-Free)
```python
@dataclass
class ExecutionContext:
    """Execution context - MUST NOT contain sentiment fields."""
    asset: str
    timeframe: str
    market_state: KalshiMarketState
    edge: float
    edge_confidence: float
    tp: Optional[float]  # Take profit
    sl: Optional[float]  # Stop loss
    bankroll: float
    # NO SENTIMENT FIELDS ALLOWED
```

### Analysis Context (Can Contain Sentiment)
```python
@dataclass
class AnalysisContext:
    """Analysis context - may contain sentiment for research/diagnostics."""
    sentiment: Optional[SentimentEnvelope] = None
    # Other analysis-only fields
```

## Search Patterns for Sentiment Leakage

### Identifiers to Search
- `sentiment`
- `fear_greed`
- `twitter`
- `social_`
- `nlp_`
- `news_score`
- `emotion`
- `mood`
- `finbert`

### File Classification
- **OK**: Research/ETL, feature engineering/model inputs (upstream only)
- **SUSPECT**: Live agents, consensus aggregator, risk modules, order routing, Kalshi API calls

### Execution Adjacency Check
For each sentiment usage in a live path, check if it's upstream of or inside:
- Kalshi 15m trading agents
- Consensus/confidence aggregator
- Risk/bankroll modules
- Order routing and Kalshi API calls

## Guardrails

### Agent-Level Guardrails
- Assert sentiment does not directly determine side, size, or entry
- Add explicit comments in agent files making invariant explicit
- No custom panic mode logic wired to sentiment

### Consensus Layer Guardrails
- Treat sentiment as tag/annotation only
- Do not branch on sentiment fields in consensus formula
- Feature flag `MERID_ALLOW_SENTIMENT_IN_CONSENSUS` = false in production
- CI fails if sentiment branches exist when flag is false

### Risk/Bankroll Guardrails
- Explicitly prohibit sentiment from bankroll sizing logic
- Production bankroll logic = function(system risk settings, recent PnL) only
- No dynamic sizing based on "market mood"

## Test Requirements

### Static Code Guard Test
- Test file: `tests/test_sentiment_quarantine.py`
- Parse/grep production packages (excluding tests/, research/, experiments/)
- Fail if:
  - Sentiment identifier appears in router, Kalshi API client, or risk modules
  - Execution-critical function signature includes sentiment parameters

### Behavioral "No-Effect" Test
- Build harness around 15m agent + consensus + router path
- Feed identical data streams differing only in sentiment values
- Assert decisions are identical: same trade/no-trade, side, size, TP/SL

### CI Enforcement
- Tag tests with `sentiment_audit` marker
- Add to CI gate (production_audit, consensus_audit, sentiment_audit)

## Forensics Requirements

### Forensic Log Schema
```json
{
  "execution_decision": {
    "asset": "BTC",
    "timeframe": "15m",
    "side": "yes",
    "size": 10,
    "edge": 0.05,
    "confidence": 0.65,
    "tp": 0.60,
    "sl": 0.45
  },
  "telemetry": {
    "sentiment_score": 0.5,
    "sentiment_source": "news",
    "sentiment_confidence": 0.7,
    "sentiment_version": "v1.0"
  }
}
```

### Offline Analysis Scripts
- Answer questions like:
  - "Does top edge perform differently under extreme fear vs extreme greed?"
  - "Should we eventually consider position throttling during certain sentiment regimes?"
- All analysis stays in research/analytics land until explicitly designed and test-gated

## Implementation Priority

### P0 (High Priority)
1. Define strict sentiment role and invariants (spec document)
2. Isolate sentiment in data model (sentiment envelope, execution context split)
3. Hunt and kill sentiment leaks into execution (search patterns, execution adjacency)
4. Add guardrails in agents and consensus (agent-level, consensus, risk invariants)

### P1 (Medium Priority)
5. Add sentiment quarantine test suite (static code guard, behavioral no-effect test)
6. Wire sentiment into forensics/research-only (telemetry, offline analysis)

## Success Criteria

- ✅ No sentiment fields in execution context or Kalshi router
- ✅ No sentiment usage in functions that determine side, size, or entry
- ✅ Static code guard test passes (no sentiment in execution modules)
- ✅ Behavioral no-effect test passes (sentiment changes don't affect decisions)
- ✅ Forensic logs separate execution_decision from telemetry (sentiment)
- ✅ All invariants enforced via code guards and CI
