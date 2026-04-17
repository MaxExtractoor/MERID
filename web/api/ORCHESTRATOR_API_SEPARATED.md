# Orchestrator API - Separated from Kalshi Trading System

## 🎯 Overview

The AgentOrchestrator API has been clearly separated from the Kalshi trading system and designated as research-only. This prevents confusion and ensures that trading decisions use the proper Kalshi-specific APIs rather than generic agent orchestration.

---

## 📁 Enhanced File

- **`web/api/orchestrator_api.py`**: Enhanced with research-only mode and clear separation documentation

---

## 🚀 Key Separations

### 1. Clear Scope Definition ✅

#### Updated Module Documentation
```python
"""
API endpoints for the AgentOrchestrator.

Exposes cycle status, phase results, and history for generic agent reasoning.
This is SEPARATE from Kalshi trading and should NOT be used for trading decisions.

Scope: Research / idea generation with generic reasoning agents only.
Kalashi trading uses Crypto15MLane + RCK + consensus engine APIs.
"""
```

#### Function-Level Documentation
```python
def _get_orchestrator():
    """
    Get the global orchestrator singleton for generic agent reasoning.
    
    NOTE: This is NOT used for Kalshi trading. Kalshi trading uses:
    - Crypto15MLane for lane operations
    - KalshiCore for market-aware consensus
    - ConsensusEngine API endpoints for trading status
    
    This orchestrator is only for research/idea generation with generic agents.
    """
```

---

### 2. Research-Only Mode Flag ✅

#### All Endpoints Include Mode Flag
```python
return {
    "status": "ok",
    "mode": "research_only",  # Clear separation from trading
    "summary": summary,
    "latest_cycle": latest_cycle,
}
```

#### Consistent Mode Flag Across All Responses
- **Summary endpoint**: `"mode": "research_only"`
- **History endpoint**: `"mode": "research_only"`
- **Status endpoint**: `"mode": "research_only"`

---

### 3. Agent Registry Safety ✅

#### Kalshi Agent Detection and Warning
```python
# Ensure no Kalshi trading agents are registered
kalshi_agents = [aid for aid in registry.list_agents() 
               if any(keyword in aid.lower() 
                     for keyword in ['kalshi', 'crypto', 'trading', 'lane'])]
if kalshi_agents:
    logger.warning(f"Found Kalshi-related agents in registry: {kalshi_agents}")
    logger.warning("These agents should NOT be used for live trading via this orchestrator")
```

#### Generic Agent Focus
```python
logger.info(f"Bootstrapped {agent_count} canonical reasoning agents")
logger.info(f"Research orchestrator created: {registry.count()} agents registered")
```

---

### 4. Trading System API References ✅

#### Clear Documentation of Proper Trading APIs
```python
return {
    "status": "ok",
    "mode": "research_only",
    "message": "Generic agent orchestrator for research/idea generation only",
    "kalshi_trading": False,  # Explicit flag
    "trading_systems": {
        "kalshi_crypto_15m": {
            "api": "/api/v1/consensus/*",
            "description": "Kalshi 15m crypto trading with RCK"
        },
        "lane_status": {
            "api": "/api/v1/lanes/*", 
            "description": "Lane-specific status and metrics"
        }
    }
}
```

---

### 5. Enhanced Endpoint Documentation ✅

#### Summary Endpoint
```python
@router.get("/summary")
async def get_orchestrator_summary():
    """
    Get orchestrator summary for research/idea generation.
    
    Returns:
        Dict with research-only mode flag and generic agent cycle information.
        This does NOT include any Kalshi trading data.
    """
```

#### History Endpoint
```python
@router.get("/history")
async def get_orchestrator_history(limit: int = Query(default=20)):
    """
    Get recent orchestrator cycle history for research analysis.
    
    Returns:
        Dict with research-only mode flag and generic agent cycle history.
        This does NOT include any Kalshi trading history.
    """
```

#### Status Endpoint
```python
@router.get("/status")
async def get_orchestrator_status():
    """
    Get orchestrator status with clear research-only designation.
    
    Returns:
        Dict indicating this is for research only, not live trading.
    """
```

---

## 📊 API Response Examples

### Research-Only Summary Response
```json
{
  "status": "ok",
  "mode": "research_only",
  "summary": {
    "agent_count": 8,
    "last_cycle": "2026-03-06T01:30:00Z"
  },
  "latest_cycle": {
    "cycleId": 12345,
    "phases": [...],
    "proposalsGenerated": 3
  }
}
```

### Research-Only History Response
```json
{
  "status": "ok",
  "mode": "research_only",
  "cycles": [
    {
      "cycleId": 12345,
      "startedAt": "2026-03-06T01:30:00Z",
      "phaseCount": 3,
      "proposalsGenerated": 3
    }
  ]
}
```

### Status Response with Trading System References
```json
{
  "status": "ok",
  "mode": "research_only",
  "message": "Generic agent orchestrator for research/idea generation only",
  "agent_count": 8,
  "recent_cycles": 5,
  "kalshi_trading": false,
  "trading_systems": {
    "kalshi_crypto_15m": {
      "api": "/api/v1/consensus/*",
      "description": "Kalshi 15m crypto trading with RCK"
    },
    "lane_status": {
      "api": "/api/v1/lanes/*",
      "description": "Lane-specific status and metrics"
    }
  }
}
```

---

## 🔧 System Architecture Separation

### Generic Agent Orchestrator (Research Only)
```
Generic Agent Orchestrator API (/api/v1/orchestrator/*)
    ↓
Generic Reasoning Agents
    ↓
Research/Idea Generation Cycles
    ↓
No Trading Capabilities
```

### Kalshi Trading System (Live Trading)
```
Kalshi Trading System
    ↓
Crypto15MLane + RCK + ConsensusEngine
    ↓
Market-Aware Consensus (/api/v1/consensus/*)
    ↓
Lane Status APIs (/api/v1/lanes/*)
    ↓
Live Trading with Real Markets
```

---

## 📈 Benefits of Separation

### For Safety ✅
- **Clear boundaries**: Research-only flag prevents confusion
- **Agent isolation**: Kalshi agents warned against in generic orchestrator
- **API separation**: Different endpoints for different purposes
- **Documentation clarity**: Explicit separation in all docstrings

### For Development ✅
- **Clear responsibilities**: Research vs trading clearly separated
- **Proper tool usage**: Developers directed to correct APIs
- **System integrity**: Trading system isolated from research agents
- **Maintainability**: Clear separation makes code easier to maintain

### For Operations ✅
- **Monitoring clarity**: Easy to distinguish research vs trading activity
- **Debugging separation**: Issues isolated to proper system
- **Risk management**: Trading system protected from research agents
- **Compliance**: Clear separation for regulatory purposes

---

## 🎯 Usage Guidelines

### When to Use Generic Orchestrator API
- **Research**: Idea generation and concept exploration
- **Analysis**: Generic reasoning about non-trading topics
- **Testing**: Agent behavior analysis in safe environment
- **Development**: Prototyping new agent capabilities

### When to Use Kalshi Trading APIs
- **Live Trading**: All actual trading operations
- **Market Analysis**: Kalshi-specific market data and consensus
- **Risk Management**: RCK calculations and drawdown monitoring
- **Lane Operations**: Crypto15MLane status and metrics

### API Selection Guide
```python
# For research/idea generation
GET /api/v1/orchestrator/summary
GET /api/v1/orchestrator/history

# For Kalshi trading
GET /api/v1/consensus/status
GET /api/v1/consensus/votes
GET /api/v1/lanes/{lane_id}/status
```

---

## 🏆 Final Status

**🎯 ORCHESTRATOR API SEPARATION COMPLETE** ✅

The AgentOrchestrator API is now **clearly separated** from the Kalshi trading system:

- **Research-Only Mode**: All responses include `"mode": "research_only"`
- **Clear Documentation**: Explicit separation in all docstrings and comments
- **Agent Safety**: Kalshi agents detected and warned against
- **API References**: Proper trading system APIs documented
- **System Boundaries**: Clear separation between research and trading

This ensures that:
- **No confusion** between research and trading systems
- **Proper tool usage** for different purposes
- **System safety** with clear boundaries
- **Development clarity** with well-defined responsibilities

The generic orchestrator remains available for research while the Kalshi trading system uses its dedicated, market-aware APIs. 🚀
