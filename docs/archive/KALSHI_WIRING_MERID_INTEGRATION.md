# Kalshi Wiring Orchestrator - MERID Integration Guide

## 🎯 **Complete Integration Architecture**

You now have three main layers that work together seamlessly:

- **Signals/Orchestrator** (crypto/debate/sentiment/enhanced Kalshi, CQI, unified signals)
- **Execution** (SignalExecutionBridge + execution daemon)
- **Kalshi Wiring** (orchestrator + sync + mapping + safety + coverage)

## 🚀 **1. Application Startup Integration**

### **Start Wiring Services**
```python
# In your main application startup (e.g., main.py or app.py)
async def start_kalshi_wiring():
    """Initialize and start all Kalshi wiring services"""
    try:
        # Get wiring orchestrator
        wiring = await get_kalshi_wiring_orchestrator()
        
        # Start all background services
        await wiring.start_wiring_services()
        
        logger.info("Kalshi wiring services started successfully")
        return wiring
        
    except Exception as e:
        logger.error(f"Failed to start Kalshi wiring services: {e}")
        raise

# In your startup sequence
async def main():
    # Start other services...
    await start_unified_signal_manager()
    await start_execution_daemon()
    
    # Start Kalshi wiring
    kalshi_wiring = await start_kalshi_wiring()
    
    # Start web API, etc.
    await start_web_server()
    
    # Keep running
    await keep_alive()
```

### **Graceful Shutdown**
```python
async def shutdown_kalshi_wiring():
    """Gracefully shutdown Kalshi wiring services"""
    try:
        wiring = await get_kalshi_wiring_orchestrator()
        await wiring.stop_wiring_services()
        logger.info("Kalshi wiring services stopped successfully")
    except Exception as e:
        logger.error(f"Error stopping Kalshi wiring services: {e}")
```

## 🔄 **2. Enhanced Kalshi Generator Integration**

### **Signal Generation Workflow**
```python
from merid.event_venues.kalshi.market_wiring.orchestrator import get_kalshi_wiring_orchestrator

class EnhancedKalshiSignalGenerator:
    def __init__(self):
        self._wiring_orchestrator = None  # Will be initialized lazily
    
    async def _get_wiring_orchestrator(self):
        if self._wiring_orchestrator is None:
            self._wiring_orchestrator = await get_kalshi_wiring_orchestrator()
        return self._wiring_orchestrator
    
    async def generate_all_signals(self):
        """Generate signals using complete wiring integration"""
        wiring = await self._get_wiring_orchestrator()
        
        # Get all safe contexts
        safe_contexts = wiring.get_safe_contexts()
        logger.info(f"Found {len(safe_contexts)} safe market contexts")
        
        signals = []
        suppressed_count = 0
        
        for context in safe_contexts:
            try:
                # Generate signal for this market
                signal = self._generate_signal_for_context(context)
                
                if signal:
                    # Safety check before marking as tradable
                    proposed_notional = signal.get("notional", 100.0)
                    safety_result = wiring.check_market_safety(
                        market_ticker=context.market_mapping.market_ticker,
                        signal=signal,
                        proposed_notional=proposed_notional
                    )
                    
                    if safety_result.safe_to_trade:
                        # Use effective limits for sizing
                        final_notional = min(proposed_notional, safety_result.effective_max_notional)
                        signal["notional"] = final_notional
                        signal["meta"]["safety_check"] = {
                            "safe_to_trade": True,
                            "effective_limits": {
                                "max_notional": safety_result.effective_max_notional,
                                "max_daily": safety_result.effective_daily_notional,
                                "max_open_risk": safety_result.effective_open_risk,
                            }
                        }
                        signals.append(signal)
                    else:
                        # Mark as suppressed for analytics
                        signal["suppressed"] = True
                        signal["suppressed_reason"] = safety_result.block_reasons
                        signal["notional"] = 0.0
                        signals.append(signal)  # Store for analytics
                        suppressed_count += 1
                        
            except Exception as e:
                logger.warning(f"Failed to generate signal for {context.market_mapping.market_ticker}: {e}")
                suppressed_count += 1
        
        # Store signals (including suppressed ones for analytics)
        tradable_signals = [s for s in signals if not s.get("suppressed", False)]
        stored_count = await self._store_signals(signals)
        
        return {
            "generated": len(tradable_signals),
            "stored": stored_count,
            "suppressed": suppressed_count,
            "signals": tradable_signals,
        }
    
    def _generate_signal_for_context(self, context):
        """Generate signal using market context"""
        mapping = context.market_mapping
        market = context.kalshi_market
        
        # Gather features using explicit mappings (no string heuristics)
        features = self._gather_features_from_context(context)
        if not features:
            return None
        
        # Calculate signal components
        signal_components = self._calculate_signal_components(features, mapping.risk_profile)
        
        # Calculate proposed notional from edge
        proposed_notional = self._calculate_notional_from_edge(signal_components["edge_bps"])
        
        # Build signal with complete metadata
        signal = {
            "signal_id": f"kalshi_edge_{market.market_ticker}_{int(time.time())}",
            "symbol": mapping.merid_symbol,
            "domain": "prediction",
            "signal_type": "kalshi_edge",
            "source": "enhanced_kalshi_generator",
            "generated_at": time.time(),
            "market_ticker": market.market_ticker,
            "underlying_symbol": mapping.underlying_symbol,
            "risk_profile": mapping.risk_profile.value,
            "confidence": signal_components["confidence"],
            "strength": signal_components["strength"],
            "edge_bps": signal_components["edge_bps"],
            "direction": signal_components["direction"],
            "notional": proposed_notional,
            "features": features,
            "meta": {
                "market_ticker": market.market_ticker,
                "underlying_symbol": mapping.underlying_symbol,
                "risk_profile": mapping.risk_profile.value,
                "context_complete": context.context_complete,
                # Full market record for execution bridge
                "market_record": {
                    "max_notional_per_trade": market.max_notional_per_trade,
                    "max_daily_notional": market.max_daily_notional,
                    "max_open_risk": market.max_open_risk,
                    "enabled_for_merid": market.enabled_for_merid,
                    "status": market.status.value,
                },
                # Full mapping for execution bridge
                "mapping": {
                    "requires_crypto_context": mapping.requires_crypto_context,
                    "requires_debate_context": mapping.requires_debate_context,
                    "requires_sentiment_context": mapping.requires_sentiment_context,
                    "sentiment_symbols": mapping.sentiment_symbols,
                    "debate_symbol": mapping.debate_symbol,
                    "enabled": mapping.enabled,
                }
            }
        }
        
        return signal
```

## ⚡ **3. Execution Bridge Integration**

### **Order Execution Workflow**
```python
from merid.event_venues.kalshi.market_wiring.orchestrator import get_kalshi_wiring_orchestrator

class SignalExecutionBridge:
    def __init__(self):
        self._wiring_orchestrator = None  # Will be initialized lazily
    
    async def _get_wiring_orchestrator(self):
        if self._wiring_orchestrator is None:
            self._wiring_orchestrator = await get_kalshi_wiring_orchestrator()
        return self._wiring_orchestrator
    
    async def execute_kalshi_signal(self, signal):
        """Execute Kalshi signal with final safety validation"""
        wiring = await self._get_wiring_orchestrator()
        
        # Resolve market ticker from signal
        market_ticker = signal.get("market_ticker")
        if not market_ticker:
            self._reject_order(signal, "Missing market_ticker")
            return
        
        # Get intended notional from signal
        intended_notional = signal.get("notional", 100.0)
        
        # Final safety check
        safety_result = wiring.check_market_safety(
            market_ticker=market_ticker,
            signal=signal,
            proposed_notional=intended_notional
        )
        
        if not safety_result.safe_to_trade:
            self._reject_order(signal, f"Safety check failed: {safety_result.block_reasons}")
            return
        
        # Clamp notional by effective limits
        final_notional = min(intended_notional, safety_result.effective_max_notional)
        
        # Check position limits
        if not await self._check_daily_limits(market_ticker, final_notional, safety_result.effective_daily_notional):
            self._reject_order(signal, "Daily limit would be exceeded")
            return
        
        if not await self._check_open_risk_limits(market_ticker, final_notional, safety_result.effective_open_risk):
            self._reject_order(signal, "Open risk limit would be exceeded")
            return
        
        # Execute order
        await self._execute_order(signal, final_notional)
        logger.info(f"Executed Kalshi order: {market_ticker}, notional={final_notional}")
    
    async def _check_daily_limits(self, market_ticker, notional, max_daily):
        """Check if daily limit would be exceeded"""
        current_daily = await self._get_current_daily_exposure(market_ticker)
        return (current_daily + notional) <= max_daily
    
    async def _check_open_risk_limits(self, market_ticker, notional, max_open_risk):
        """Check if open risk limit would be exceeded"""
        current_open = await self._get_current_open_risk(market_ticker)
        return (current_open + notional) <= max_open_risk
    
    def _reject_order(self, signal, reason):
        """Reject order with reason"""
        logger.warning(f"Order rejected: {signal.get('signal_id')} - {reason}")
        # Store rejection for analytics
        self._store_rejection(signal, reason)
```

## 📊 **4. Health and Status Integration**

### **Health Endpoint Integration**
```python
from merid.event_venues.kalshi.market_wiring.orchestrator import get_kalshi_wiring_orchestrator

@router.get("/health/kalshi-wiring")
async def kalshi_wiring_health():
    """Kalshi wiring health check"""
    try:
        wiring = await get_kalshi_wiring_orchestrator()
        health = await wiring.health_check()
        
        return {
            "status": health["overall"],
            "components": health["components"],
            "issues": health["issues"],
            "timestamp": time.time()
        }
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": time.time()
        }

@router.get("/status/kalshi-wiring")
async def kalshi_wiring_status():
    """Kalshi wiring detailed status"""
    try:
        wiring = await get_kalshi_wiring_orchestrator()
        status = wiring.get_wiring_status()
        
        return {
            "success": True,
            "data": status,
            "timestamp": time.time()
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "timestamp": time.time()
        }
```

### **Dashboard Integration**
```python
@router.get("/dashboard/kalshi-metrics")
async def kalshi_dashboard_metrics():
    """Kalshi metrics for dashboard"""
    try:
        wiring = await get_kalshi_wiring_orchestrator()
        
        # Get comprehensive metrics
        status = wiring.get_wiring_status()
        health = await wiring.health_check()
        
        # Extract key metrics
        metrics = {
            "sync_status": status.get("sync_timestamps", {}),
            "coverage_metrics": {
                "total_open_markets": status.get("total_open_markets", 0),
                "enabled_mappings": status.get("enabled_mappings", 0),
                "coverage_percentage": status.get("coverage_report", {}).get("coverage_percentage", 0),
                "enablement_percentage": status.get("coverage_report", {}).get("enablement_percentage", 0),
            },
            "health_status": health["overall"],
            "services": status.get("services", {}),
        }
        
        return {
            "success": True,
            "data": metrics,
            "timestamp": time.time()
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "timestamp": time.time()
        }
```

## 🔄 **5. Complete Data Flow Summary**

### **Signal Generation → Execution Pipeline**
```python
# 1. Background Services (startup)
wiring = await get_kalshi_wiring_orchestrator()
await wiring.start_wiring_services()
# Starts: universe sync, mapping updates, coverage checks

# 2. Signal Generation
safe_contexts = wiring.get_safe_contexts()
for context in safe_contexts:
    # Generate signal with explicit mappings
    signal = generate_signal_for_context(context)
    
    # Safety check
    safety_result = wiring.check_market_safety(market_ticker, signal, proposed_notional)
    
    if safety_result.safe_to_trade:
        # Size using effective limits
        final_notional = min(proposed_notional, safety_result.effective_max_notional)
        emit_tradable_signal(signal_with_final_notional)
    else:
        emit_suppressed_signal(signal_with_block_reasons)

# 3. Execution
safety_result = wiring.check_market_safety(market_ticker, signal, intended_notional)
if safety_result.safe_to_trade:
    final_notional = min(intended_notional, safety_result.effective_max_notional)
    execute_order(signal, final_notional)
```

### **Monitoring and Alerting**
```python
# Health monitoring
health = await wiring.health_check()
if health["overall"] != "healthy":
    alert(f"Kalshi wiring health degraded: {health['issues']}")

# Coverage monitoring
status = wiring.get_wiring_status()
coverage = status.get("coverage_report", {})
if coverage.get("coverage_percentage", 0) < 95.0:
    alert(f"Low Kalshi coverage: {coverage['coverage_percentage']:.1f}%")

# Sync freshness monitoring
sync_timestamps = status.get("sync_timestamps", {})
current_time = time.time()
universe_age = current_time - sync_timestamps.get("kalshi", 0)
if universe_age > 1800:  # 30 minutes
    alert(f"Kalshi universe sync is stale: {universe_age/60:.0f} minutes")
```

## 🎯 **6. Production Benefits**

### **✅ Complete Safety Guarantee**
- **Zero dark markets**: Every market explicitly enabled or disabled
- **Multi-layer validation**: Context, risk, and CQI checks at generation and execution
- **Dual enforcement**: Both layers agree on safety decisions
- **Complete audit trail**: All decisions logged and tracked

### **✅ Operational Excellence**
- **Single orchestrator**: Clean coordination of all wiring services
- **Health monitoring**: Component-level health checks and metrics
- **Dashboard integration**: Complete operational visibility
- **Graceful lifecycle**: Proper startup and shutdown handling

### **✅ Straightforward Integration**
- **Simple API**: `get_market_context_config()` and `check_market_safety()`
- **Clear separation**: Blocking vs sizing logic
- **Complete metadata**: All necessary data passed through pipeline
- **Error handling**: Comprehensive exception management

## 🚀 **Ready for Production**

The Kalshi Wiring Orchestrator provides a **clean, production-ready interface** for integrating Kalshi prediction markets with the rest of MERID:

✅ **Simple startup**: `await wiring.start_wiring_services()`  
✅ **Easy integration**: `wiring.get_market_context_config()` and `wiring.check_market_safety()`  
✅ **Complete monitoring**: Health checks and status endpoints  
✅ **Production safety**: Multi-layer validation with clear separation of concerns  
✅ **Operational excellence**: Comprehensive dashboards and alerting  

Every Kalshi market is now either **fully discovered, mapped, safety-checked, and CQI-gated before execution**, or **explicitly disabled and visible in coverage reports and health checks**! 🚀
