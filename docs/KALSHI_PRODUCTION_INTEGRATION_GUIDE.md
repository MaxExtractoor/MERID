# Kalshi Wiring & Safety Stack - Production Integration Guide

## 🎯 **Complete Production-Grade Stack**

You now have a comprehensive, production-ready Kalshi wiring and safety stack that provides:

- **Complete market coverage** with zero dark markets
- **Explicit symbol mappings** with manual override support
- **Multi-layer safety enforcement** with context freshness and per-market caps
- **Segment-based CQI gating** for different risk profiles
- **Operational visibility** with comprehensive dashboards

## 📋 **Integration Checklist**

### **✅ 1. Enhanced Kalshi Generator Integration**

#### **Required Imports**
```python
from merid.event_venues.kalshi.market_context_resolver import get_market_context_resolver
from merid.event_venues.kalshi.market_wiring.safety import get_kalshi_safety_layer
```

#### **Signal Generation Workflow**
```python
def generate_all_signals(self):
    # Get resolvers
    context_resolver = get_market_context_resolver()
    safety_layer = get_kalshi_safety_layer()
    
    # Get all safe contexts
    safe_contexts = context_resolver.get_safe_contexts()
    
    for context in safe_contexts:
        # Generate signal with proposed notional
        signal = self._generate_signal_for_context(context)
        proposed_notional = signal.get("notional", 100.0)
        
        # Safety layer check
        safety_result = safety_layer.perform_safety_check(
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
            emit_tradable_signal(signal)
        else:
            # Mark as suppressed for analytics
            signal["suppressed"] = True
            signal["suppressed_reason"] = safety_result.block_reasons
            signal["notional"] = 0.0
            store_for_analytics(signal)
```

### **✅ 2. Execution Bridge Integration**

#### **Required Imports**
```python
from merid.event_venues.kalshi.market_wiring.safety import get_kalshi_safety_layer
```

#### **Order Execution Workflow**
```python
def execute_kalshi_order(self, signal):
    # Get safety layer
    safety_layer = get_kalshi_safety_layer()
    
    # Resolve market ticker from signal
    market_ticker = signal.get("market_ticker")
    if not market_ticker:
        reject_order("Missing market_ticker")
        return
    
    # Get intended notional
    intended_notional = signal.get("notional", 100.0)
    
    # Final safety check
    safety_result = safety_layer.perform_safety_check(
        market_ticker=market_ticker,
        signal=signal,
        proposed_notional=intended_notional
    )
    
    if not safety_result.safe_to_trade:
        reject_order(f"Safety check failed: {safety_result.block_reasons}")
        return
    
    # Clamp notional by effective limits
    final_notional = min(intended_notional, safety_result.effective_max_notional)
    
    # Check daily and open risk limits
    if not self._check_daily_limits(market_ticker, final_notional, safety_result.effective_daily_notional):
        reject_order("Daily limit would be exceeded")
        return
    
    if not self._check_open_risk_limits(market_ticker, final_notional, safety_result.effective_open_risk):
        reject_order("Open risk limit would be exceeded")
        return
    
    # Execute order
    execute_order(signal, final_notional)
```

### **✅ 3. Dashboard Integration**

#### **Coverage Metrics**
```python
GET /api/v1/kalshi/dashboard/coverage-stats
{
  "mapping_stats": {
    "total_markets": 150,
    "mapped_markets": 145,
    "enabled_markets": 120,
    "coverage_percentage": 96.7,
    "enablement_percentage": 80.0
  },
  "validation_stats": {
    "total_enabled": 120,
    "safe_to_trade": 95,
    "unsafe": 25
  }
}
```

#### **Safety Statistics**
```python
GET /api/v1/kalshi/dashboard/safety-stats
{
  "total_markets_checked": 120,
  "safe_to_trade": 95,
  "blocked_by_reason": {
    "missing_context": 5,
    "stale_context": 8,
    "cqi_suppression": 7,
    "risk_limit_breach": 3,
    "market_disabled": 2
  },
  "safe_percentage": 79.2
}
```

#### **Segment CQI Monitoring**
```python
GET /api/v1/kalshi/dashboard/segment-cqi
{
  "segment_cqi": {
    "prediction_crypto_linked": {"value": 0.75, "band": "good"},
    "prediction_macro_election": {"value": 0.45, "band": "poor"},
    "prediction_equity_linked": {"value": 0.60, "band": "neutral"},
    "prediction_other": {"value": 0.50, "band": "neutral"}
  }
}
```

## 🔄 **Complete Data Flow**

### **Signal Generation Pipeline**
```python
# 1. Universe Sync (background)
markets = kalshi_client.get_markets(status="open")
for market in markets:
    market_record = parse_market_data(market)  # KalshiMarketRecord
    store.upsert_market(market_record)

# 2. Mapping Builder (background)
for market in open_markets:
    mapping = mapping_registry.auto_build_mapping(market)  # MarketMapping
    store.upsert_mapping(mapping)

# 3. Context Resolution (signal generation)
context = context_resolver.get_market_context_config(market_ticker)
# Returns MarketContextConfig with safety validation

# 4. Safety Check (signal generation)
safety_result = safety_layer.perform_safety_check(
    market_ticker, signal, proposed_notional
)
# Returns SafetyCheckResult with safe_to_trade decision

# 5. Signal Emission
if safety_result.safe_to_trade:
    final_notional = min(proposed_notional, safety_result.effective_max_notional)
    emit_tradable_signal(signal_with_final_notional)
else:
    emit_suppressed_signal(signal_with_block_reasons)
```

### **Execution Pipeline**
```python
# 1. Signal Selection
signal = get_tradable_signal()  # Already passed safety check

# 2. Final Safety Validation
safety_result = safety_layer.perform_safety_check(
    signal["market_ticker"], signal, signal["notional"]
)

# 3. Order Sizing
if safety_result.safe_to_trade:
    final_notional = min(signal["notional"], safety_result.effective_max_notional)
    
    # Check position limits
    if check_position_limits(signal["market_ticker"], final_notional, safety_result):
        execute_order(signal, final_notional)
    else:
        reject_order("Position limits exceeded")
else:
    reject_order("Safety check failed")
```

## 🛡️ **Safety Layer Features**

### **Multi-Layer Validation**
```python
class SafetyCheckResult:
    safe_to_trade: bool
    context_check: ContextCheckResult      # Freshness validation
    risk_check: RiskCheckResult            # Per-market caps
    cqi_decision: GatingDecision          # Segment CQI gating
    block_reasons: List[str]               # Detailed block reasons
    effective_max_notional: float         # CQI-adjusted sizing
    effective_daily_notional: float
    effective_open_risk: float
```

### **Context Freshness Enforcement**
- **Crypto context**: 5 minutes maximum staleness
- **Sentiment context**: 10 minutes maximum staleness  
- **Debate context**: 15 minutes maximum staleness
- **Automatic suppression**: Markets blocked when context is stale

### **Per-Market Risk Caps**
- **Hard caps**: Raw market limits for blocking decisions
- **Effective limits**: CQI-adjusted limits for sizing
- **Position tracking**: Daily and open risk limit enforcement
- **Risk profile scaling**: Different caps per risk profile

### **Segment CQI Gating**
- **Crypto-linked**: CQI threshold 0.3 (more lenient)
- **Macro/Election**: CQI threshold 0.5 (stricter)
- **Equity-linked**: CQI threshold 0.4 (moderate)
- **Idiosyncratic**: CQI threshold 0.6 (strictest)

## 📊 **Operational Monitoring**

### **Coverage Monitoring**
```python
# Coverage Report
coverage_report = coverage_checker.get_latest_report()

# Key metrics
coverage_percentage = coverage_report.coverage_percentage
enablement_percentage = coverage_report.enablement_percentage
unmapped_markets = coverage_report.unmapped_markets
disabled_markets = coverage_report.disabled_markets

# Alerts
if coverage_percentage < 95.0:
    alert("Low market coverage")
if enablement_percentage < 80.0:
    alert("Low enablement percentage")
```

### **Safety Monitoring**
```python
# Safety Statistics
safety_stats = safety_layer.get_safety_statistics()

# Key metrics
safe_percentage = safety_stats["safe_percentage"]
blocked_by_reason = safety_stats["blocked_by_reason"]

# Alerts
if safe_percentage < 75.0:
    alert("Low safety percentage")
if blocked_by_reason["stale_context"] > 10:
    alert("High stale context count")
```

### **Segment Health Monitoring**
```python
# Segment CQI
segment_cqi = get_segment_cqi()

# Health checks
for segment, cqi_data in segment_cqi.items():
    if cqi_data["value"] < 0.4:
        alert(f"Poor CQI in segment: {segment}")
```

## 🚀 **Production Deployment**

### **Service Startup**
```python
# Initialize all components
context_resolver = get_market_context_resolver()
safety_layer = get_kalshi_safety_layer()
coverage_checker = get_coverage_checker()

# Start background services
await coverage_checker.start_coverage_loop()
await safety_layer.start_cqi_monitoring()
```

### **Health Checks**
```python
def health_check():
    health = {
        "coverage": coverage_checker.health_status(),
        "safety": safety_layer.health_status(),
        "context": context_resolver.health_status(),
    }
    
    overall_health = "healthy"
    if any(status != "healthy" for status in health.values()):
        overall_health = "degraded"
    
    return {"overall": overall_health, "components": health}
```

### **Configuration**
```bash
# Safety thresholds
KALSHI_CRYPTO_STALENESS_SECONDS=300
KALSHI_SENTIMENT_STALENESS_SECONDS=600
KALSHI_DEBATE_STALENESS_SECONDS=900

# CQI thresholds
KALSHI_CQI_CRYPTO_THRESHOLD=0.3
KALSHI_CQI_MACRO_THRESHOLD=0.5
KALSHI_CQI_EQUITY_THRESHOLD=0.4
KALSHI_CQI_IDIOSYNCRATIC_THRESHOLD=0.6

# Coverage thresholds
KALSHI_COVERAGE_THRESHOLD=95.0
KALSHI_ENABLEMENT_THRESHOLD=80.0
```

## 🎯 **Production Benefits**

### **✅ Complete Safety Guarantee**
- **Zero dark markets**: Every market either explicitly enabled or disabled
- **Multi-layer validation**: Context, risk, and CQI checks
- **Dual enforcement**: Both generation and execution layers validate safety
- **Complete audit trail**: All decisions logged and tracked

### **✅ Operational Excellence**
- **Real-time monitoring**: Coverage, safety, and segment health
- **Proactive alerting**: Automatic alerts for degradation
- **Comprehensive dashboards**: Complete operational visibility
- **Analytics support**: Suppressed signals stored for analysis

### **✅ Risk Management**
- **Per-market enforcement**: Individual caps automatically respected
- **Segment-based gating**: Different thresholds per risk profile
- **Context validation**: Fresh data requirements enforced
- **Effective sizing**: Automatic sizing based on market conditions

## 🎯 **Final Result**

You now have a **complete, production-grade Kalshi wiring and safety stack** that provides:

✅ **Complete market coverage** with explicit mappings and zero dark markets  
✅ **Multi-layer safety enforcement** with context freshness and per-market caps  
✅ **Segment-based CQI gating** for different risk profiles  
✅ **Operational visibility** with comprehensive dashboards and alerting  
✅ **Straightforward integration** with existing orchestrator and execution bridge  

The stack is **production-ready** and provides comprehensive protection against market-specific risks while enabling optimal trading based on real-time market conditions and segment health! 🚀
