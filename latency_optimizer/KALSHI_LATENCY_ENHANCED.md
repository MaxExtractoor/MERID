# Kalshi Latency Optimization - Enhanced for 15m Crypto Operations

## 🎯 Overview

The latency optimizer has been enhanced with Kalshi-specific usage patterns for Crypto15MLane operations. This provides detailed latency tracking and optimization suggestions for the full tick → consensus → order pipeline.

---

## 📁 Enhanced File

- **`latency_optimizer/orchestrator_hooks.py`**: Enhanced with Kalshi-specific documentation and examples

---

## 🚀 Kalshi-Specific Usage

### 1. Trading Tick Context Manager ✅

#### Enhanced `record_trading_tick` Function
```python
def record_trading_tick(metadata: Dict[str, str], *, decision_key: Optional[str] = None) -> LatencyProbe:
    """
    Record trading tick latency with Kalshi-specific metadata.
    
    For Kalshi 15m crypto lanes, include venue, lane_id, symbol, and optional market details:
    
    Args:
        metadata: Trading tick metadata. For Kalshi, include:
            - venue: "kalshi"
            - lane_id: "BTC_15M", "ETH_15M", etc.
            - symbol: "BTC", "ETH", "SOL", "XRP"
            - market_id: Optional Kalshi market ID (e.g., "KXBTC15M-20260306-0115")
            - series_ticker: Optional series ticker (e.g., "KXBTC15M")
        decision_key: Optional decision key for latency policy decisions
    """
```

---

### 2. Crypto15MLane Integration Pattern ✅

#### Complete Pipeline Latency Tracking
```python
from latency_optimizer.orchestrator_hooks import record_trading_tick

async def process_tick(self):
    """Process a single trading tick with full latency tracking."""
    
    # Create Kalshi-specific metadata
    metadata = {
        "venue": "kalshi",
        "lane_id": self.lane_id,
        "symbol": self.cfg.symbol,
        "series_ticker": f"KX{self.cfg.symbol}15M",
    }
    
    # Add market ID if available
    if self.current_market:
        metadata["market_id"] = self.current_market["market_id"]
    
    # Track full tick-to-order pipeline
    with record_trading_tick(
        metadata,
        decision_key=f"kalshi::{self.lane_id}",
    ):
        # 1. Fetch orderbook and market data
        await self._fetch_market_data()
        
        # 2. Compute consensus and p_true
        consensus_result = await self._compute_consensus()
        
        # 3. Run RCK risk evaluation
        risk_decision = await self._evaluate_risk(consensus_result)
        
        # 4. Send order if approved
        if risk_decision["direction"] != "FLAT":
            await self._send_order(risk_decision)
```

---

### 3. Granular Component Tracking ✅

#### Individual Component Latency
```python
async def _compute_consensus(self) -> Dict[str, Any]:
    """Compute consensus with latency tracking."""
    
    metadata = {
        "venue": "kalshi",
        "lane_id": self.lane_id,
        "symbol": self.cfg.symbol,
        "component": "consensus",
    }
    
    with record_trading_tick(
        metadata,
        decision_key=f"kalshi::{self.lane_id}::consensus",
    ):
        # Agent voting and consensus calculation
        votes = await self._gather_agent_votes()
        consensus = await self._calculate_consensus(votes)
        return consensus

async def _evaluate_risk(self, consensus_result: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate RCK risk with latency tracking."""
    
    metadata = {
        "venue": "kalshi",
        "lane_id": self.lane_id,
        "symbol": self.cfg.symbol,
        "component": "rck",
    }
    
    with record_trading_tick(
        metadata,
        decision_key=f"kalshi::{self.lane_id}::rck",
    ):
        # Risk-constrained Kelly calculation
        rck_result = await self._run_rck_solver(consensus_result)
        return rck_result
```

---

### 4. Latency Metrics Emitted ✅

#### Automatic Metrics Collection
```python
# Emits these metrics automatically:
trading.tick_to_order.duration_ms    # Full pipeline duration
trading.tick_to_order.count          # Number of ticks processed
trading.tick_to_order.status.{status}  # Latency policy status
trading.tick_to_order.fallback       # Fallback suggestions

# Tags included:
# - venue: "kalshi"
# - lane_id: "BTC_15M"
# - symbol: "BTC"
# - market_id: "KXBTC15M-20260306-0115"
# - series_ticker: "KXBTC15M"
```

#### Component-Level Metrics
```python
# For granular tracking:
trading.tick_to_order.duration_ms    # Full pipeline
trading.consensus.duration_ms        # Consensus component
trading.rck.duration_ms              # RCK component
trading.order.duration_ms            # Order submission

# Tags include component type:
# - component: "consensus"
# - component: "rck"
# - component: "order"
```

---

### 5. Latency Policy Integration ✅

#### Automatic Optimization Suggestions
```python
# Latency policy evaluates durations and suggests fallbacks:
{
    "status": "slow",
    "threshold_ms": 100.0,
    "actual_ms": 145.2,
    "fallback": {
        "strategy_id": "skip_consensus",
        "reason": "Consensus too slow for 15m timeframe"
    }
}

# Emits fallback counter:
trading.tick_to_order.fallback
# Tags: venue=kalshi, lane_id=BTC_15M, symbol=BTC
```

#### Decision Key Tracking
```python
# Decision keys allow per-lane optimization:
decision_key = f"kalshi::{lane_id}"

# Examples:
# - "kalshi::BTC_15M"
# - "kalshi::ETH_15M"
# - "kalshi::SOL_15M"
# - "kalshi::BTC_15M::consensus"
# - "kalshi::BTC_15M::rck"
```

---

## 🔧 Integration Examples

### Basic Crypto15MLane Integration
```python
class Crypto15MLane:
    def __init__(self, cfg):
        self.lane_id = f"{cfg.symbol}_15M"
        self.cfg = cfg
        
    async def run_cycle(self):
        """Main lane cycle with latency tracking."""
        
        metadata = {
            "venue": "kalshi",
            "lane_id": self.lane_id,
            "symbol": self.cfg.symbol,
            "series_ticker": f"KX{self.cfg.symbol}15M",
        }
        
        with record_trading_tick(
            metadata,
            decision_key=f"kalshi::{self.lane_id}",
        ):
            # Complete tick processing
            market_data = await self._fetch_markets()
            best_market = self._select_best_market(market_data)
            
            if best_market:
                consensus = await self._compute_consensus(best_market)
                risk = await self._evaluate_risk(consensus)
                
                if risk["direction"] != "FLAT":
                    await self._execute_trade(risk)
```

### Advanced Component Tracking
```python
async def _execute_trade(self, risk_decision: Dict[str, Any]):
    """Execute trade with detailed component tracking."""
    
    # Order submission tracking
    metadata = {
        "venue": "kalshi",
        "lane_id": self.lane_id,
        "symbol": self.cfg.symbol,
        "component": "order",
        "direction": risk_decision["direction"],
        "size_contracts": risk_decision["size_contracts"],
    }
    
    with record_trading_tick(
        metadata,
        decision_key=f"kalshi::{self.lane_id}::order",
    ):
        # Submit order to Kalshi
        order_result = await self.kalshi_client.submit_order({
            "market_id": risk_decision["market_id"],
            "side": risk_decision["direction"],
            "size": risk_decision["size_contracts"],
        })
        
        return order_result
```

---

## 📊 Benefits Achieved

### For Performance Monitoring ✅
- **Complete pipeline tracking**: From tick to order submission
- **Component granularity**: Individual latency for consensus, RCK, order submission
- **Lane-specific metrics**: Per-lane performance analysis
- **Market context**: Full market and decision context in metrics

### For Optimization ✅
- **Automatic fallback suggestions**: Latency policy suggests optimizations
- **Per-lane decision keys**: Independent optimization per lane
- **Threshold monitoring**: Automatic detection of slow operations
- **Performance alerts**: Fallback suggestions for slow components

### For Operations ✅
- **Real-time monitoring**: Live latency metrics with Kalshi context
- **Historical analysis**: Lane-specific performance trends
- **Troubleshooting**: Component-level performance breakdown
- **Capacity planning**: Latency trends and scaling decisions

---

## 🎯 Latency Metrics Examples

### Full Pipeline Metrics
```json
{
  "metric": "trading.tick_to_order.duration_ms",
  "value": 145.2,
  "tags": {
    "venue": "kalshi",
    "lane_id": "BTC_15M",
    "symbol": "BTC",
    "market_id": "KXBTC15M-20260306-0115",
    "series_ticker": "KXBTC15M"
  }
}
```

### Component Metrics
```json
{
  "metric": "trading.consensus.duration_ms",
  "value": 89.7,
  "tags": {
    "venue": "kalshi",
    "lane_id": "BTC_15M",
    "symbol": "BTC",
    "component": "consensus"
  }
}
```

### Fallback Metrics
```json
{
  "metric": "trading.tick_to_order.fallback",
  "tags": {
    "venue": "kalshi",
    "lane_id": "BTC_15M",
    "symbol": "BTC",
    "fallback_strategy": "skip_consensus"
  }
}
```

---

## 🏆 Final Status

**🎯 KALSHI LATENCY OPTIMIZATION COMPLETE** ✅

The latency optimizer is now **enhanced for Kalshi 15m crypto operations** with:

- **Kalshi-specific metadata**: venue, lane_id, symbol, market_id, series_ticker
- **Complete pipeline tracking**: From tick to consensus to order submission
- **Component granularity**: Individual tracking for consensus, RCK, order components
- **Automatic optimization**: Latency policy suggestions and fallback strategies
- **Per-lane decision keys**: Independent optimization per lane
- **Rich telemetry**: Detailed metrics with full Kalshi context

This provides **comprehensive latency visibility** for the Kalshi trading system with automatic optimization suggestions and detailed performance breakdown by component and lane. 🚀
