# Kalshi Core Orchestrator - Specialized for 15m Crypto Lane Operations

## 🎯 Overview

The core orchestrator has been specialized for Kalshi 15m crypto lane operations, replacing generic energy processing with market-aware consensus, validation, and audit trails specifically designed for prediction market trading.

---

## 📁 Enhanced Files

### Core Components
- **`core/kalshi_energy.py`**: Specialized energy dataclasses for Kalshi operations
- **`core/kalshi_orchestrator.py`**: Specialized core for Kalshi lane operations
- **`agents/trading_registry.py`**: Trading-specific agent loader

### Integration Points
- **`core/consensus_engine.py`**: Enhanced with Kalshi + RCK context
- **`web/api/consensus.py`**: Enhanced API endpoints with market context

---

## 🚀 Key Enhancements

### 1. Specialized Energy Schema ✅

#### KalshiEnergy Dataclass
```python
@dataclass
class KalshiEnergy:
    # Energy identification
    energy_id: str
    source: str = "lane"
    
    # Lane identification
    lane_id: str                    # "BTC_15M", "ETH_15M"
    symbol: str                    # "BTC", "ETH", "SOL", "XRP"
    
    # Market identification
    market_id: str                  # "KXBTC15M-20260306-0115"
    series_ticker: str              # "KXBTC15M"
    
    # Market pricing (cents)
    yes_price_cents: int
    no_price_cents: int
    yes_bid_cents: Optional[int]
    yes_ask_cents: Optional[int]
    
    # Probabilities and edge
    p_true: float                   # Bayesian estimated probability
    p_implied: float                # De-vigged market probability
    edge_bps: float                 # Edge in basis points
    direction: str                  # "YES", "NO", "FLAT"
    
    # RCK sizing
    kelly_fraction_full: float      # Full Kelly fraction
    kelly_fraction_rck: float        # RCK solver result
    kelly_fraction_used: float      # Final fraction after safety
    target_drawdown: float          # RCK target drawdown
    size_contracts: int             # Position size in contracts
```

#### Factory Functions
```python
def create_kalshi_energy_from_lane(
    lane_id: str,
    market_data: Dict[str, Any],
    consensus_result: Dict[str, Any],
    risk_decision: Dict[str, Any]
) -> KalshiEnergy
```

---

### 2. Market-Aware Consensus Engine ✅

#### Replace Blind Voting with Kalshi Consensus
```python
# OLD: Generic blind voting
vote_result = blind_vote(list(zip(responses, self.agents)), threshold=CONSENSUS_THRESHOLD)

# NEW: Kalshi-specific consensus
consensus_result = await self._run_kalshi_consensus(kalshi_energy, responses)
```

#### Enhanced Consensus Block
```python
consensus_block = ConsensusResult(
    decision="APPROVE",
    signal="bullish",
    votes=votes,
    
    # Kalshi + RCK context
    lane_id=kalshi_energy.lane_id,
    market_id=kalshi_energy.market_id,
    symbol=kalshi_energy.symbol,
    p_true=kalshi_energy.p_true,
    edge_bps=kalshi_energy.edge_bps,
    kelly_fraction_used=kalshi_energy.kelly_fraction_used,
    direction=kalshi_energy.direction,
    size_contracts=kalshi_energy.size_contracts,
)
```

---

### 3. Specialized Logging and Audit ✅

#### Enhanced Logging with Market Context
```python
# OLD: Generic energy logging
self.logger.info("Processing energy %s | %s", energy_id, payload_preview)

# NEW: Kalshi-specific logging
self.logger.info(
    "Processing Kalshi energy %s | lane=%s market=%s | %s",
    energy_id, lane_id, market_id, kalshi_energy.get_summary()
)
```

#### Structured Event Publishing
```python
await event_stream.publish(
    "kalshi:energy_received",
    {
        "energy_id": energy_id,
        "lane_id": lane_id,
        "market_id": market_id,
        "symbol": kalshi_energy.symbol,
        "direction": kalshi_energy.direction,
        "edge_bps": kalshi_energy.edge_bps,
    },
)
```

---

### 4. Trading-Specific Agent Loading ✅

#### Load Trading Agents Instead of Generic Chat Agents
```python
def load_trading_agents() -> List:
    """Load trading-specific agents for Kalshi 15m crypto operations."""
    
    trading_agents = [
        SentimentAgent(
            agent_id="sentiment_agent",
            focus="crypto_15m",
            data_sources=["kalshi", "rti", "fear_greed"]
        ),
        MarketAnalystAgent(
            agent_id="market_analyst",
            focus="crypto_markets",
            timeframes=["15m", "1h", "4h"]
        ),
        RiskAgent(
            agent_id="risk_agent",
            focus="kalshi_risk",
            risk_model="rck_constrained"
        ),
        SkepticAgent(
            agent_id="skeptic_agent",
            focus="crypto_validation",
            challenge_threshold=0.7
        ),
    ]
```

#### Agent Validation
```python
def validate_trading_agents(agents: List) -> bool:
    """Validate that loaded agents are suitable for trading operations."""
    essential_types = ['SentimentAgent', 'RiskAgent']
    has_essential = any(essential in agent_type for essential_type in essential_types 
                       for agent_type in agent_types)
```

---

### 5. Market-Specific Validation ✅

#### KalshiValidationResult Dataclass
```python
@dataclass
class KalshiValidationResult:
    status: str                     # "confirmed", "wrong_side", "size_error"
    validated: bool                 # Overall validation success
    score: float                    # Validation score (0-1)
    reality_gap: float              # Difference between p_true and empirical
    realized_edge: Optional[float]  # Actual edge realized
    settlement_correct: bool        # Whether settlement matched direction
    rck_constraints_met: bool       # Whether RCK constraints were respected
```

#### Settlement-Based Validation
```python
def create_validation_result_from_settlement(
    energy: KalshiEnergy,
    settlement_data: Dict[str, Any]
) -> KalshiValidationResult:
    """Create validation result from settlement data."""
    
    outcome_yes = settlement_data.get("outcome_yes", False)
    settlement_correct = (
        (energy.direction == "YES" and outcome_yes) or
        (energy.direction == "NO" and not outcome_yes)
    )
    
    # Calculate realized edge and validation status
    if settlement_correct:
        status = "confirmed"
        validated = True
        score = 1.0
    else:
        status = "wrong_side"
        validated = False
        score = 0.0
```

---

## 🔧 Integration Pattern

### Lane to Core Communication
```python
from core.kalshi_orchestrator import get_kalshi_core
from core.kalshi_energy import create_kalshi_energy_from_lane

# In Crypto15MLane
async def _run_cycle(self):
    # ... consensus and risk evaluation ...
    
    # Create structured Kalshi energy
    kalshi_energy = create_kalshi_energy_from_lane(
        lane_id=self.lane_id,
        market_data=best_market,
        consensus_result=consensus_result,
        risk_decision=risk_decision
    )
    
    # Process with Kalshi core
    kalshi_core = get_kalshi_core()
    consensus_result = await kalshi_core.run_cycle(kalshi_energy.to_dict())
```

### Type-Safe Energy Processing
```python
# In KalshiCore
async def run_cycle(self, energy: Dict[str, Any]) -> Dict[str, Any]:
    # Convert to KalshiEnergy
    kalshi_energy = KalshiEnergy.from_dict(energy)
    
    # Process with full market context
    self.logger.info(
        "Processing Kalshi energy %s | lane=%s market=%s | %s",
        kalshi_energy.energy_id,
        kalshi_energy.lane_id,
        kalshi_energy.market_id,
        kalshi_energy.get_summary()
    )
```

---

## 📊 Enhanced Data Flow

### Energy Processing Flow
```
Crypto15MLane
    ↓ (creates)
KalshiEnergy (structured data)
    ↓ (processes)
KalshiCore (market-aware orchestrator)
    ↓ (delegates to)
ConsensusEngine (with Kalshi + RCK context)
    ↓ (produces)
ConsensusBlock (complete audit trail)
    ↓ (validates)
KalshiValidationResult (market-specific validation)
```

### Data Context Preservation
```
Lane Decision → KalshiEnergy → ConsensusBlock → ValidationResult
     ↓                ↓              ↓              ↓
  Lane Context    Market Context   Audit Trail    Settlement Analysis
```

---

## 📈 Benefits Achieved

### For Trading Operations ✅
- **Type Safety**: Structured dataclasses prevent field errors
- **Market Context**: Every decision includes complete market information
- **Audit Trail**: Complete replay capability with ConsensusBlock
- **Performance Tracking**: Per-symbol and per-lane metrics

### For Development ✅
- **Clear Interfaces**: Well-defined data structures
- **Easy Debugging**: Structured logging with market context
- **Validation**: Market-specific validation logic
- **Extensibility**: Easy to add new market types

### For Operations ✅
- **Real-time Monitoring**: Market-aware event publishing
- **Risk Management**: Complete RCK constraint tracking
- **Compliance**: Full audit trail for regulatory requirements
- **Performance Analysis**: Detailed metrics and validation

---

## 🎯 Usage Examples

### Creating Kalshi Energy
```python
kalshi_energy = KalshiEnergy(
    energy_id="kalshi_BTC_15M_1678086400",
    lane_id="BTC_15M",
    symbol="BTC",
    market_id="KXBTC15M-20260306-0115",
    yes_price_cents=52,
    no_price_cents=48,
    p_true=0.537,
    p_implied=0.50,
    edge_bps=170,
    direction="YES",
    kelly_fraction_used=0.28,
    size_contracts=2800,
    target_drawdown=0.10,
)
```

### Processing with Kalshi Core
```python
from core.kalshi_orchestrator import get_kalshi_core

kalshi_core = get_kalshi_core()
result = await kalshi_core.run_cycle(kalshi_energy.to_dict())

print(f"Trade approved: {result['approved']}")
print(f"Consensus: {result['consensus']:.2%}")
print(f"Block ID: {result['block_id']}")
```

### Validation with Settlement
```python
settlement_data = {
    "outcome_yes": True,
    "settlement_price": 43250.0,
}

validation_result = create_validation_result_from_settlement(
    kalshi_energy, settlement_data
)

print(f"Status: {validation_result.status}")
print(f"Validated: {validation_result.validated}")
print(f"Score: {validation_result.score:.2f}")
```

---

## 🏆 Final Status

**🎯 KALSHI CORE ORCHESTRATOR COMPLETE** ✅

The core orchestrator is now **specialized for Kalshi 15m crypto operations** with:

- **Structured Energy**: Type-safe KalshiEnergy dataclasses
- **Market-Aware Consensus**: Integration with Kalshi + RCK consensus engine
- **Trading Agents**: Specialized agents for market analysis and risk management
- **Enhanced Logging**: Market context in all logs and events
- **Validation**: Settlement-based validation with market-specific metrics
- **Audit Trail**: Complete ConsensusBlock with full market context

This provides a **production-ready foundation** for Kalshi trading operations with proper type safety, complete audit trails, and market-specific validation. 🚀
