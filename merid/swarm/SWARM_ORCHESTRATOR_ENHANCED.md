# Kalshi Swarm Orchestrator - Enhanced for 15m Crypto Operations

## 🎯 Overview

The SwarmOrchestrator has been enhanced with Kalshi 15m crypto-specific intent validation, guardrails, and lane state-based overrides. It now serves as a low-latency safety + coordination layer that sits cleanly on top of the RCK / lane logic.

---

## 📁 Enhanced File

- **`merid/swarm/orchestrator.py`**: Enhanced with Kalshi 15m crypto-specific validation and overrides

---

## 🚀 Key Enhancements

### 1. Explicit Kalshi 15m Intent Schema ✅

#### Complete Intent Specification
```python
"""
Expected intent keys for Kalshi 15m crypto:
  - venue: "kalshi"
  - lane_id: "BTC_15M" | "ETH_15M" | "SOL_15M" | "XRP_15M"
  - symbol: "BTC" | "ETH" | "SOL" | "XRP"
  - market_id: Kalshi market identifier
  - series_ticker: e.g. "KXBTC15M"
  - timeframe: "15m"
  - direction: "YES" | "NO" | "FLAT"
  - p_true: float
  - p_implied: float
  - edge_bps: float
  - kelly_fraction_full: float
  - kelly_fraction_rck: float
  - kelly_fraction_used: float
  - size_contracts: int
  - agent_id: str
"""
```

#### Field Validation
```python
# Validate required fields
if not all([agent_id, venue, lane_id, symbol]):
    logger.warning("SwarmOrchestrator: missing required fields in intent: %s", intent)
    return {"approved": False, "reason": "missing_required_fields", "intent": intent}

# Check if this is a Kalshi 15m crypto lane
is_kalshi_15m = (
    venue == "kalshi" and
    lane_id.endswith("_15M") and
    symbol in SYMBOL_LIMITS and
    agent_id in self.kalshi_agents
)
```

---

### 2. Basic Kalshi-Aware Guardrails ✅

#### Guardrail Constants
```python
# Kalshi 15m guardrail constants
MIN_EDGE_BPS = 10.0
MAX_F_USED = 0.35
MAX_SIZE_CONTRACTS = 100

# Symbol-specific limits
SYMBOL_LIMITS = {
    "BTC": {"max_f_used": 0.35, "max_size_contracts": 100},
    "ETH": {"max_f_used": 0.30, "max_size_contracts": 150},
    "SOL": {"max_f_used": 0.25, "max_size_contracts": 200},
    "XRP": {"max_f_used": 0.25, "max_size_contracts": 250},
}
```

#### Guardrail Enforcement
```python
# Extract key fields with defaults
edge_bps = float(intent.get("edge_bps", 0.0) or 0.0)
f_used = float(intent.get("kelly_fraction_used", 0.0) or 0.0)
size_contracts = int(intent.get("size_contracts", 0) or 0)

# Get symbol-specific limits
symbol_limits = SYMBOL_LIMITS.get(symbol, {"max_f_used": MAX_F_USED, "max_size_contracts": MAX_SIZE_CONTRACTS})

# Apply guardrails
if edge_bps < MIN_EDGE_BPS:
    return {
        "approved": False, 
        "reason": "edge_too_small", 
        "details": f"edge_bps={edge_bps:.1f}, min_edge_bps={MIN_EDGE_BPS}",
        "intent": intent
    }

if f_used > max_f_used:
    return {
        "approved": False, 
        "reason": "kelly_fraction_exceeds_cap", 
        "details": f"kelly_fraction_used={f_used:.3f}, max_f_used={max_f_used:.3f}",
        "intent": intent
    }

if size_contracts > max_size_contracts:
    return {
        "approved": False, 
        "reason": "position_limit_exceeded", 
        "details": f"size_contracts={size_contracts}, max_size_contracts={max_size_contracts}",
        "intent": intent
    }
```

#### Enhanced Logging
```python
logger.info(
    "SwarmOrchestrator: approved Kalshi 15m intent from %s | %s %s @ %.1f bps edge, %.3f Kelly, %d contracts",
    agent_id, symbol, intent.get("direction", "UNKNOWN"), edge_bps, f_used, size_contracts
)
```

---

### 3. Lane State-Based Overrides ✅

#### Expected State Schema
```python
"""
Expected state keys:
  - lanes: { lane_id: { symbol, recent_dd, recent_win_rate, recent_edge_bps, cooldown_until, ... } }
"""
```

#### Override Logic
```python
async def propose_overrides(self, state: Dict[str, Any]) -> Dict[str, Any]:
    lanes = state.get("lanes", {})
    overrides = {}
    
    for lane_id, lane_state in lanes.items():
        symbol = lane_state.get("symbol")
        recent_dd = lane_state.get("recent_dd", 0.0)
        recent_win_rate = lane_state.get("recent_win_rate", 0.5)
        cooldown_until = lane_state.get("cooldown_until", 0.0)
        
        # Check for drawdown breach
        target_dd = 0.10 if symbol == "BTC" else 0.08 if symbol == "ETH" else 0.05
        if recent_dd > target_dd:
            overrides[lane_id] = {
                "suspend_trading": True,
                "reason": f"drawdown_breach: {recent_dd:.2%} > {target_dd:.2%}"
            }
            continue
        
        # Check for cooldown period
        if cooldown_until > time.time():
            overrides[lane_id] = {
                "suspend_trading": True,
                "reason": f"cooldown_active: until {cooldown_until}"
            }
            continue
        
        # Check for low win rate
        if recent_win_rate < 0.3:  # Less than 30% win rate
            overrides[lane_id] = {
                "reduce_size": 0.5,  # Reduce position size by 50%
                "reason": f"low_win_rate: {recent_win_rate:.2%}"
            }
```

---

## 📊 Enhanced Data Flow

### Intent Validation Flow
```
Lane Intent (KalshiEnergy)
    ↓ (validate)
SwarmOrchestrator.review_intent()
    ↓ (check)
Required Fields + Lane ID + Symbol
    ↓ (apply)
Guardrails (edge, Kelly, size)
    ↓ (return)
Approved/Rejected with Details
```

### Override Proposal Flow
```
Lane State (performance metrics)
    ↓ (analyze)
SwarmOrchestrator.propose_overrides()
    ↓ (check)
Drawdown + Cooldown + Win Rate
    ↓ (propose)
Lane Overrides (suspend/reduce)
    ↓ (apply)
Lane Adjustments
```

---

## 🔧 Integration Pattern

### Lane Integration
```python
# In Crypto15MLane
from merid.swarm.orchestrator import get_swarm_orchestrator

async def _execute_trade(self, risk_decision):
    # Create intent with complete Kalshi context
    intent = {
        "venue": "kalshi",
        "lane_id": self.lane_id,
        "symbol": self.cfg.symbol,
        "market_id": market_data["market_id"],
        "series_ticker": market_data["series_ticker"],
        "direction": risk_decision["direction"],
        "p_true": consensus_result["p_true"],
        "p_implied": consensus_result["p_implied"],
        "edge_bps": consensus_result["edge_bps"],
        "kelly_fraction_used": risk_decision["kelly_fraction_used"],
        "size_contracts": int(risk_decision["position_size"] * 100),
        "agent_id": "crypto_15m_lane",
    }
    
    # Review intent with swarm orchestrator
    swarm_orchestrator = get_swarm_orchestrator()
    review_result = await swarm_orchestrator.review_intent(intent)
    
    if not review_result["approved"]:
        logger.warning("Trade rejected by SwarmOrchestrator: %s", review_result["reason"])
        return
    
    # Execute trade
    await self._execute_order(risk_decision)
```

### State-Based Overrides
```python
# In lane monitoring
async def _update_swarm_overrides(self):
    lane_state = {
        "symbol": self.cfg.symbol,
        "recent_dd": self.get_recent_drawdown(),
        "recent_win_rate": self.get_recent_win_rate(),
        "cooldown_until": self.cooldown_until,
    }
    
    swarm_orchestrator = get_swarm_orchestrator()
    override_result = await swarm_orchestrator.propose_overrides({"lanes": {self.lane_id: lane_state}})
    
    # Apply overrides
    overrides = override_result["overrides"].get(self.lane_id, {})
    if overrides.get("suspend_trading"):
        self.trading_suspended = True
        logger.warning("Trading suspended: %s", overrides["reason"])
    elif "reduce_size" in overrides:
        self.size_multiplier = overrides["reduce_size"]
        logger.info("Position size reduced to %.1f%%", overrides["reduce_size"] * 100)
```

---

## 📈 Benefits Achieved

### For Safety ✅
- **Multi-layer validation**: Required fields, lane validation, guardrails
- **Symbol-specific limits**: Different caps per crypto asset
- **Real-time enforcement**: Low-latency checks before execution
- **Detailed logging**: Complete audit trail with reasons

### For Coordination ✅
- **Lane state awareness**: Overrides based on performance metrics
- **Dynamic adjustments**: Suspend/reduce based on drawdown and win rate
- **Cooldown management**: Prevent overtrading after losses
- **Scalable design**: Easy to add new override rules

### For Operations ✅
- **Clear error messages**: Detailed reasons for rejections
- **Configurable limits**: Easy to adjust guardrails per symbol
- **Monitoring ready**: Structured output for alerting systems
- **Graceful degradation**: Pass-through for non-Kalshi intents

---

## 🎯 Usage Examples

### Intent Review
```python
# Example intent
intent = {
    "venue": "kalshi",
    "lane_id": "BTC_15M",
    "symbol": "BTC",
    "market_id": "KXBTC15M-20260306-0115",
    "direction": "YES",
    "p_true": 0.537,
    "p_implied": 0.50,
    "edge_bps": 170,
    "kelly_fraction_used": 0.28,
    "size_contracts": 2800,
    "agent_id": "crypto_15m_lane",
}

# Review intent
swarm_orchestrator = get_swarm_orchestrator()
result = await swarm_orchestrator.review_intent(intent)

print(f"Approved: {result['approved']}")
print(f"Reason: {result['reason']}")
print(f"Details: {result.get('details', '')}")
```

### Override Proposal
```python
# Example lane state
state = {
    "lanes": {
        "BTC_15M": {
            "symbol": "BTC",
            "recent_dd": 0.12,  # 12% drawdown (exceeds 10% target)
            "recent_win_rate": 0.25,  # 25% win rate (below 30% threshold)
            "cooldown_until": 0,
        }
    }
}

# Propose overrides
result = await swarm_orchestrator.propose_overrides(state)

print(f"Overrides: {result['overrides']}")
print(f"Reason: {result['reason']}")
print(f"Analyzed lanes: {result['analyzed_lanes']}")
```

---

## 🏆 Final Status

**🎯 KALSHI SWARM ORCHESTRATOR ENHANCED** ✅

The SwarmOrchestrator is now **specialized for Kalshi 15m crypto operations** with:

- **Explicit Intent Schema**: Complete specification for Kalshi 15m crypto intents
- **Guardrails Enforcement**: Edge, Kelly fraction, and position size limits
- **Symbol-Specific Limits**: Different caps per crypto asset (BTC, ETH, SOL, XRP)
- **Lane State Overrides**: Dynamic adjustments based on performance metrics
- **Detailed Logging**: Complete audit trail with structured reasons

This provides a **low-latency safety layer** that complements the RCK/risk engine without interfering with its core logic, while adding valuable coordination capabilities based on lane performance. 🚀
