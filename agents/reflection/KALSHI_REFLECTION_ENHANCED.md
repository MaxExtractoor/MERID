# Kalshi Reflection Orchestrator - Enhanced for 15m Crypto Operations

## 🎯 Overview

The reflection orchestrator has been enhanced with Kalshi 15m crypto-specific trigger types, evidence types, metrics, and experience key generation. It now carries explicit market, risk, and performance context into reflection events, making it useful for trading system analysis and improvement.

---

## 📁 Enhanced File

- **`agents/reflection/orchestrator.py`**: Enhanced with Kalshi-specific components and logging

---

## 🚀 Key Enhancements

### 1. Kalshi-Specific Trigger Types ✅

#### Standardized Trigger Types
```python
class KalshiTriggerType(str, Enum):
    TRADE_OUTCOME_MISMATCH = "kalshi_trade_outcome_mismatch"
    RCK_DRAWDOWN_BREACH = "kalshi_rck_drawdown_breach"
    P_TRUE_MISCALIBRATION = "kalshi_p_true_miscalibration"
    EDGE_DECAY = "kalshi_edge_decay"
    POSITION_LIMIT_BREACH = "kalshi_position_limit_breach"
    KELLY_FRACTION_BREACH = "kalshi_kelly_fraction_breach"
```

#### Trigger Creation with Kalshi Context
```python
trigger = ReflectionTrigger(
    type="kalshi_trade_outcome_mismatch",
    source_ref=market_id,  # "KXBTC15M-20260306-0130"
    severity=ReflectionSeverity.MAJOR,
    metrics={
        "lane_id": lane_id,
        "symbol": symbol,
        "p_true": p_true,
        "p_implied": p_implied,
        "direction": direction,       # "YES"/"NO"
        "outcome_yes": outcome_yes,   # 0/1 from settlement
        "pnl_contracts": pnl,
        "f_used": f_used,
        "target_dd": target_dd,
    },
)
```

---

### 2. Kalshi-Specific Evidence Types ✅

#### Standardized Evidence Types
```python
class KalshiEvidenceType(str, Enum):
    KALSHI_MARKET = "kalshi_market"
    RCK_DECISION = "rck_decision"
    CONSENSUS_BLOCK = "consensus_block"
    BACKTEST_RUN = "backtest_run"
    SETTLEMENT_DATA = "settlement_data"
    PERFORMANCE_METRICS = "performance_metrics"
```

#### Evidence Creation Helper
```python
evidence = ReflectionEvidence(
    ref_type="kalshi_market",
    reference=market_id,
    notes="Market terms and settlement data"
)
```

---

### 3. Enhanced ProducerArtifact with Kalshi + RCK Context ✅

#### Complete Market and Risk Context
```python
artifact = ProducerArtifact(
    artifact_id=f"kalshi_decision::{market_id}",
    content={
        "lane_id": lane_id,
        "market_id": market_id,
        "symbol": symbol,
        "direction": direction,
        "size_contracts": size_contracts,
    },
    metadata={
        "p_true": p_true,
        "p_implied": p_implied,
        "edge_bps": edge_bps,
        "kelly_fraction_full": f_full,
        "kelly_fraction_rck": f_rck,
        "kelly_fraction_used": f_used,
        "target_drawdown": target_dd,
        "drawdown_probability": dd_prob,
        "bankroll_before": bankroll_before,
        "bankroll_after": bankroll_after,
        "consensus_block_id": consensus_block_id,
    },
)
```

#### Fingerprinting Capability
```python
# content_hash() includes both content and metadata
# This lets you fingerprint an entire Kalshi decision for later comparison
artifact_hash = artifact.content_hash()
```

---

### 4. KalshiRCKMetric - Trading-Specific Metrics ✅

#### Dedicated Trading Metrics Dataclass
```python
@dataclass(frozen=True)
class KalshiRCKMetric:
    lane_id: str
    symbol: str
    period_start: str
    period_end: str
    trades: int
    hit_rate: float
    brier_score: float
    avg_edge_bps: float
    realized_dd: float
    target_dd: float
    avg_f_used: float
    pnl_per_contract: float
    avg_p_true: float
    avg_p_implied: float
    calibration_bucket: str = "medium"
```

#### Separate Logging
```python
def log_kalshi_rck_metrics(self, metric: KalshiRCKMetric) -> None:
    """Log Kalshi RCK-specific trading metrics."""
    # Creates separate log file: kalshi_rck_metrics.jsonl
    kalshi_metrics_path = self._experience_log_path.parent / "kalshi_rck_metrics.jsonl"
    with kalshi_metrics_path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
```

---

### 5. Enhanced Experience Keys ✅

#### Lane/Market-Aware Experience Keys
```python
# Enhanced experience key generation for Kalshi
if experience_key is None:
    # For Kalshi, encode lane and symbol in the key if present
    lane_id = trigger.metrics.get("lane_id")
    symbol = trigger.metrics.get("symbol")
    market_id = trigger.metrics.get("market_id")
    
    if lane_id and symbol:
        experience_key = f"{trigger.type}::{symbol}::{lane_id}"
    elif market_id and symbol:
        experience_key = f"{trigger.type}::{symbol}::{market_id}"
    else:
        experience_key = f"{trigger.type}::{producer_id}"
```

#### Example Experience Keys
- `"kalshi_trade_outcome_mismatch::BTC::BTC_15M"`
- `"kalshi_rck_drawdown_breach::ETH::KXETH15M-20260306-0130"`
- `"kalshi_p_true_miscalibration::SOL::SOL_15M"`

---

### 6. Guardrail Integration for Risk Violations ✅

#### CriticResult for Risk Violations
```python
critic_result = CriticResult(
    passed=False,
    guardrail_status=GuardrailStatus.DENY,
    findings=[
        CriticFinding(
            issue="kalshi_rck_drawdown_breach",
            severity=ReflectionSeverity.MAJOR,
            details=f"Realized drawdown {realized_dd:.2%} exceeded target {target_dd:.2%}",
        )
    ],
    evidence_refs=[
        ReflectionEvidence(ref_type="kalshi_market", reference=market_id),
        ReflectionEvidence(ref_type="rck_decision", reference=consensus_block_id),
    ],
)
```

#### MetaDecision Integration
- **DENY** → `MetaDecision.ESCALATE` → `ReflectionGuardrailViolation`
- **WARN** → `MetaDecision.RETRY` or `MetaDecision.DEFER`
- **ALLOW** → `MetaDecision.NONE`

---

## 🔧 Integration Pattern

### Creating Kalshi Reflection Events
```python
from agents.reflection.orchestrator import get_reflection_orchestrator

# Get the orchestrator
orchestrator = get_reflection_orchestrator()

# Create trigger for trade outcome mismatch
trigger = orchestrator.create_kalshi_trigger(
    trigger_type=KalshiTriggerType.TRADE_OUTCOME_MISMATCH,
    source_ref="KXBTC15M-20260306-0115",
    severity=ReflectionSeverity.MAJOR,
    metrics={
        "lane_id": "BTC_15M",
        "symbol": "BTC",
        "p_true": 0.537,
        "p_implied": 0.50,
        "direction": "YES",
        "outcome_yes": False,  # Wrong side
        "pnl_contracts": -100,
        "f_used": 0.28,
        "target_dd": 0.10,
    },
)

# Create artifact with RCK context
artifact = orchestrator.create_kalshi_artifact(
    market_id="KXBTC15M-20260306-0115",
    lane_id="BTC_15M",
    symbol="BTC",
    decision_data={"direction": "YES", "size_contracts": 2800},
    rck_data={
        "p_true": 0.537,
        "edge_bps": 170,
        "kelly_fraction_used": 0.28,
        "target_drawdown": 0.10,
        "consensus_block_id": "cb_123456",
    },
)

# Create critic result
critic_result = CriticResult(
    passed=False,
    guardrail_status=GuardrailStatus.DENY,
    findings=[
        CriticFinding(
            issue="kalshi_trade_outcome_mismatch",
            severity=ReflectionSeverity.MAJOR,
            details="Trade took wrong side vs settlement"
        )
    ],
    evidence_refs=[
        orchestrator.create_kalshi_evidence(
            KalshiEvidenceType.KALSHI_MARKET,
            "KXBTC15M-20260306-0115",
            "Market settlement data"
        ),
        orchestrator.create_kalshi_evidence(
            KalshiEvidenceType.RCK_DECISION,
            "cb_123456",
            "RCK decision block"
        )
    ]
)

# Record the event
event = orchestrator._record_event(
    loop_type=ReflectionLoopType.POST_TASK,
    producer_id="kalshi_lane",
    critic_id="risk_critic",
    meta_id="meta_decision",
    trigger=trigger,
    artifact=artifact,
    critic_result=critic_result,
    meta_decision=MetaDecision.ESCALATE,
    loop_iteration=1,
    experience_key=None,  # Will be auto-generated as "kalshi_trade_outcome_mismatch::BTC::BTC_15M"
    resolved=False,
)
```

### Logging Kalshi RCK Metrics
```python
# Create trading metrics
metric = KalshiRCKMetric(
    lane_id="BTC_15M",
    symbol="BTC",
    period_start="2026-03-06T00:00:00Z",
    period_end="2026-03-06T23:59:59Z",
    trades=25,
    hit_rate=0.68,
    brier_score=0.142,
    avg_edge_bps=145.2,
    realized_dd=0.08,
    target_dd=0.10,
    avg_f_used=0.26,
    pnl_per_contract=12.5,
    avg_p_true=0.542,
    avg_p_implied=0.498,
)

# Log metrics
orchestrator.log_kalshi_rck_metrics(metric)
```

---

## 📊 Enhanced Data Flow

### Reflection Event with Kalshi Context
```
Kalshi Trade Settlement
    ↓ (analyze)
Trigger (kalshi_trade_outcome_mismatch)
    ↓ (create)
Artifact (market + RCK context)
    ↓ (evaluate)
CriticResult (DENY for risk violation)
    ↓ (record)
ReflectionEvent (experience_key: "kalshi_trade_outcome_mismatch::BTC::BTC_15M")
    ↓ (log)
JSONL Logs + Kalshi Metrics
```

### Experience Key Generation
```
Trigger: "kalshi_rck_drawdown_breach"
Metrics: {"lane_id": "BTC_15M", "symbol": "BTC"}
    ↓
Experience Key: "kalshi_rck_drawdown_breach::BTC::BTC_15M"
```

---

## 📈 Benefits Achieved

### For Trading Analysis ✅
- **Market context**: Every reflection event includes complete market and risk data
- **Replay capability**: Artifacts include all RCK context for decision replay
- **Performance tracking**: Dedicated metrics for trading performance analysis
- **Lane grouping**: Experience keys group events by lane and symbol

### For Risk Management ✅
- **Risk violation tracking**: Specific trigger types for drawdown breaches
- **Guardrail integration**: DENY status triggers escalation for hard violations
- **Evidence tracking**: Links to market data and RCK decisions
- **Audit trail**: Complete chain from trigger → artifact → critic → decision

### For System Improvement ✅
- **Calibration analysis**: Track p_true miscalibration over time
- **Edge decay monitoring**: Detect when realized edges fall below estimates
- **Position limit tracking**: Monitor and enforce position size limits
- **Kelly fraction monitoring**: Track RCK constraint compliance

---

## 🎯 Usage Examples

### Trade Outcome Mismatch Reflection
```python
# Wrong side trade detected
trigger = orchestrator.create_kalshi_trigger(
    KalshiTriggerType.TRADE_OUTCOME_MISMATCH,
    "KXBTC15M-20260306-0115",
    ReflectionSeverity.MAJOR,
    {
        "lane_id": "BTC_15M",
        "symbol": "BTC",
        "direction": "YES",
        "outcome_yes": False,
        "pnl_contracts": -100,
        "edge_bps": 170,
    }
)

# Experience key: "kalshi_trade_outcome_mismatch::BTC::BTC_15M"
```

### RCK Drawdown Breach Reflection
```python
# Drawdown exceeded target
trigger = orchestrator.create_kalshi_trigger(
    KalshiTriggerType.RCK_DRAWDOWN_BREACH,
    "BTC_15M",
    ReflectionSeverity.MAJOR,
    {
        "lane_id": "BTC_15M",
        "symbol": "BTC",
        "realized_dd": 0.12,
        "target_dd": 0.10,
        "f_used": 0.28,
    }
)

# Experience key: "kalshi_rck_drawdown_breach::BTC::BTC_15M"
```

### P True Miscalibration Reflection
```python
# Brier score degradation
trigger = orchestrator.create_kalshi_trigger(
    KalshiTriggerType.P_TRUE_MISCALIBRATION,
    "BTC_15M",
    ReflectionSeverity.MINOR,
    {
        "lane_id": "BTC_15M",
        "symbol": "BTC",
        "brier_score": 0.185,
        "avg_p_true": 0.542,
        "avg_p_implied": 0.498,
        "calibration_bucket": "poor",
    }
)

# Experience key: "kalshi_p_true_miscalibration::BTC::BTC_15M"
```

---

## 🏆 Final Status

**🎯 KALSHI REFLECTION ORCHESTRATOR COMPLETE** ✅

The reflection orchestrator is now **specialized for Kalshi 15m crypto operations** with:

- **Kalshi-Specific Triggers**: Standardized trigger types for trading events
- **Market Context**: Complete Kalshi market and RCK context in artifacts
- **Trading Metrics**: Dedicated `KalshiRCKMetric` dataclass for performance tracking
- **Lane-Aware Experience Keys**: Grouping by symbol and lane for analysis
- **Guardrail Integration**: Risk violation detection and escalation
- **Evidence Tracking**: Links to market data, RCK decisions, and settlement data

This provides a **comprehensive reflection system** that captures the full context of Kalshi trading decisions, enabling systematic analysis, improvement, and risk management for the 15m crypto trading system. 🚀
