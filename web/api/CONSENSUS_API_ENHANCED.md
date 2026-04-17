# Enhanced Consensus API with Kalshi + RCK Context

## 🎯 Overview

The consensus API endpoints have been enhanced to expose **complete Kalshi + RCK context** for the 15m crypto trading system. This provides the UI with real-time access to actual market decisions, risk calculations, and consensus voting.

---

## 📁 Enhanced Files

### Core Engine Enhancements
- **`core/consensus_engine.py`**: Enhanced `Vote` and `ConsensusResult` classes with Kalshi + RCK context
- **`merid/lanes/consensus_engine_integration.py`**: Integration helpers for Crypto15MLane

### API Endpoint Enhancements  
- **`web/api/consensus.py`**: All endpoints now include Kalshi + RCK context

---

## 🚀 Enhanced Endpoints

### 1. Status Endpoint - `/api/v1/consensus/status`

**NEW**: Includes active lanes with complete Kalshi + RCK context

```json
{
  "running": true,
  "lanes": [
    {
      "lane_id": "BTC_15M",
      "symbol": "BTC", 
      "timeframe": "15m",
      "market_id": "KXBTC15M-20260306-0115",
      "series_ticker": "KXBTC15M",
      "yes_bid_cents": 48,
      "yes_ask_cents": 52,
      "no_bid_cents": 48,
      "no_ask_cents": 52,
      "p_yes_implied": 0.52,
      "p_yes_devig": 0.50,
      "direction": "YES",
      "edge_bps": 170,
      "kelly_fraction_used": 0.28,
      "size_contracts": 2800,
      "p_true": 0.537,
      "target_drawdown": 0.10,
      "drawdown_probability": 0.10,
      "safety_factor": 0.8
    }
  ]
}
```

**Key Features:**
- **Active lanes**: Real-time lane status with market context
- **Kalshi market data**: Actual market IDs, tickers, prices
- **RCK decisions**: Complete risk-constrained Kelly calculations
- **Probability analysis**: p_true, p_implied, edge calculations

---

### 2. Votes Endpoint - `/api/v1/consensus/votes`

**NEW**: Each vote includes Kalshi + RCK context

```json
{
  "votes": [
    {
      "agent_id": "sentiment_agent",
      "proposal": "trade_KXBTC15M-20260306-0115",
      "signal": "bullish",
      "confidence": 0.8,
      "weight": 0.72,
      "lane_id": "BTC_15M",
      "market_id": "KXBTC15M-20260306-0115",
      "symbol": "BTC",
      "side": "YES",
      "p_true": 0.537,
      "p_implied": 0.50,
      "edge_bps": 170,
      "kelly_fraction_used": 0.28,
      "size_contracts": 2800
    }
  ]
}
```

**Key Features:**
- **Market context**: Each vote tied to specific Kalshi market
- **RCK details**: Position sizing and Kelly fractions
- **Lane attribution**: Clear association with specific lanes

---

### 3. History Endpoint - `/api/v1/consensus/history`

**ENHANCED**: Returns enriched ConsensusBlock data with Kalshi + RCK context

```json
{
  "decisions": [
    {
      "block_id": "cb_1234567890abcdef",
      "kalshi": {
        "market_id": "KXBTC15M-20260306-0115",
        "symbol": "BTC",
        "p_yes_devig": 0.50
      },
      "risk_decision": {
        "p_true": 0.537,
        "edge_bps": 170,
        "kelly_fraction_used": 0.28,
        "direction": "YES",
        "size_contracts": 2800
      }
    }
  ]
}
```

**Key Features:**
- **Complete audit trail**: Full decision replay capability
- **Kalshi context**: Market identifiers and prices
- **RCK context**: Risk calculations and position sizing

---

### 4. Metrics Endpoint - `/api/v1/consensus/metrics`

**NEW**: Per-symbol and per-lane performance statistics

```json
{
  "per_symbol": {
    "BTC": {
      "active_lanes": 1,
      "avg_edge_bps": 170.0,
      "avg_kelly_used": 0.28,
      "total_contracts": 2800,
      "directions": {"YES": 1, "NO": 0, "FLAT": 0}
    },
    "ETH": {
      "active_lanes": 1,
      "avg_edge_bps": 120.0,
      "avg_kelly_used": 0.22,
      "total_contracts": 2200,
      "directions": {"YES": 0, "NO": 1, "FLAT": 0}
    }
  },
  "per_lane": {
    "BTC_15M": {
      "symbol": "BTC",
      "edge_bps": 170,
      "kelly_fraction_used": 0.28,
      "size_contracts": 2800,
      "direction": "YES",
      "p_true": 0.537,
      "target_drawdown": 0.10
    }
  },
  "active_lanes": 4
}
```

**Key Features:**
- **Symbol aggregation**: Performance by crypto asset
- **Lane breakdown**: Individual lane statistics
- **RCK metrics**: Kelly usage and edge tracking

---

### 5. Start/Stop Endpoints - Kalshi-Specific

**ENHANCED**: Includes lane information and consensus type

```json
{
  "status": "started",
  "lanes": ["BTC_15M", "ETH_15M", "SOL_15M", "XRP_15M"],
  "interval": 10.0,
  "consensus_type": "kalshi_15m_crypto"
}
```

---

## 🔧 Integration Pattern

### Core Engine Enhancements

#### Enhanced Vote Class
```python
@dataclass
class Vote:
    # Existing fields...
    agent_id: str
    proposal: str
    signal: str
    
    # NEW: Kalshi + RCK context
    lane_id: Optional[str] = None           # "BTC_15M"
    market_id: Optional[str] = None          # "KXBTC15M-20260306-0115"
    symbol: Optional[str] = None             # "BTC"
    side: Optional[str] = None               # "YES", "NO", "FLAT"
    p_true: Optional[float] = None           # Bayesian probability
    edge_bps: Optional[float] = None         # Edge in basis points
    kelly_fraction_used: Optional[float] = None  # RCK Kelly fraction
    size_contracts: Optional[int] = None     # Position size
```

#### Enhanced ConsensusResult Class
```python
@dataclass
class ConsensusResult:
    # Existing fields...
    decision: str
    signal: str
    votes: List[Vote]
    
    # NEW: Kalshi + RCK context
    lane_id: Optional[str] = None
    market_id: Optional[str] = None
    symbol: Optional[str] = None
    p_true: Optional[float] = None
    edge_bps: Optional[float] = None
    kelly_fraction_used: Optional[float] = None
    # ... complete RCK details
```

#### Lane Intent Tracking
```python
class ConsensusEngine:
    def __init__(self):
        # NEW: Current intents for active lanes
        self.current_intents: Dict[str, Any] = {}  # lane_id -> intent data
    
    def update_lane_intent(self, lane_id: str, intent_data: Dict[str, Any]):
        """Update intent data for a specific lane."""
        self.current_intents[lane_id] = intent_data
```

---

### Crypto15MLane Integration

#### Usage Pattern
```python
from merid.lanes.consensus_engine_integration import (
    update_consensus_engine_with_lane_data,
    create_vote_from_lane_decision,
    submit_lane_votes_to_consensus
)

async def _run_cycle(self):
    # ... consensus and risk evaluation ...
    
    # Create Kalshi and RCK contexts
    kalshi_context = KalshiContext(
        market_id=best_market["market_id"],
        symbol=self.cfg.symbol,
        yes_bid_cents=best_market.get("yes_bid"),
        # ... complete market data
    )
    
    risk_context = RiskDecisionContext(
        p_true=consensus_result["p_true"],
        edge_bps=consensus_result["edge_bps"],
        kelly_fraction_used=risk_decision["kelly_fraction_used"],
        # ... complete RCK data
    )
    
    # Update consensus engine with current lane data
    update_consensus_engine_with_lane_data(
        self.lane_id, kalshi_context, risk_context
    )
    
    # Submit votes to consensus engine
    submit_lane_votes_to_consensus(
        self.lane_id, kalshi_context, risk_context
    )
```

---

## 📊 API Response Examples

### Real-Time Lane Status
```bash
GET /api/v1/consensus/status
```

**Response:**
```json
{
  "running": true,
  "lanes": [
    {
      "lane_id": "BTC_15M",
      "symbol": "BTC",
      "market_id": "KXBTC15M-20260306-0115",
      "direction": "YES",
      "edge_bps": 170,
      "kelly_fraction_used": 0.28,
      "size_contracts": 2800,
      "p_true": 0.537,
      "p_implied": 0.50,
      "target_drawdown": 0.10,
      "safety_factor": 0.8
    }
  ]
}
```

### Agent Voting with Market Context
```bash
GET /api/v1/consensus/votes
```

**Response:**
```json
{
  "votes": [
    {
      "agent_id": "sentiment_agent",
      "lane_id": "BTC_15M",
      "market_id": "KXBTC15M-20260306-0115",
      "symbol": "BTC",
      "side": "YES",
      "p_true": 0.537,
      "edge_bps": 170,
      "kelly_fraction_used": 0.28,
      "size_contracts": 2800,
      "confidence": 0.8,
      "weight": 0.72
    }
  ]
}
```

### Performance Metrics by Symbol
```bash
GET /api/v1/consensus/metrics
```

**Response:**
```json
{
  "per_symbol": {
    "BTC": {
      "active_lanes": 1,
      "avg_edge_bps": 170.0,
      "avg_kelly_used": 0.28,
      "total_contracts": 2800,
      "directions": {"YES": 1, "NO": 0, "FLAT": 0}
    }
  },
  "per_lane": {
    "BTC_15M": {
      "symbol": "BTC",
      "edge_bps": 170,
      "kelly_fraction_used": 0.28,
      "p_true": 0.537,
      "target_drawdown": 0.10
    }
  }
}
```

---

## 🎯 Benefits

### For UI Development
- **Real-time market context**: Actual Kalshi market IDs and prices
- **Complete decision visibility**: Full RCK calculations and risk metrics
- **Lane-level granularity**: Per-lane status and performance tracking
- **Audit capability**: Complete decision replay with ConsensusBlock

### For Monitoring
- **Per-symbol performance**: Track performance by crypto asset
- **Risk metrics visibility**: Monitor Kelly usage and edge calculations
- **Lane health**: Active lane status and decision quality
- **Agent transparency**: See what each agent is voting on

### For Debugging
- **Complete context**: Every decision includes full market and risk data
- **Replay capability**: Historical decisions can be fully reconstructed
- **Traceability**: From market data → consensus → risk → execution
- **Performance analysis**: Detailed metrics for optimization

---

## 🚀 Production Readiness

### ✅ Complete Implementation
- [x] Enhanced core classes with Kalshi + RCK context
- [x] All API endpoints include market context
- [x] Lane intent tracking and updates
- [x] Integration helpers for Crypto15MLane
- [x] Per-symbol and per-lane metrics
- [x] Complete audit trail with ConsensusBlock

### ✅ API Features
- **Real-time status**: Active lanes with market context
- **Voting transparency**: Votes tied to specific markets
- **Historical audit**: Complete decision replay
- **Performance metrics**: Symbol and lane breakdowns
- **Kalshi-specific**: Market IDs, tickers, prices

### ✅ Integration Support
- **Drop-in helpers**: Easy integration with Crypto15MLane
- **Dataclass conversion**: Seamless data flow between systems
- **Type safety**: Full type annotations and validation
- **Documentation**: Complete usage examples

---

## 🏆 Final Status

**🎯 KALSHI + RCK CONSENSUS API COMPLETE** ✅

The consensus API now provides **complete visibility** into the Kalshi 15m crypto trading system with:

- **Real-time market context**: Actual Kalshi markets and prices
- **Complete RCK visibility**: Risk-constrained Kelly calculations
- **Lane-level granularity**: Per-lane status and performance
- **Audit capability**: Full decision replay with ConsensusBlock
- **Performance metrics**: Symbol and lane breakdowns

This enables the UI to display **exactly what the system is deciding** about actual Kalshi contracts, with complete transparency into the Bayesian p_true estimation, RCK calculations, and consensus voting process. 🚀
