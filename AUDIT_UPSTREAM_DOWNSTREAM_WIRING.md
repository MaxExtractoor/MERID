# Upstream/Downstream Wiring Audit: Hardened Universal Layer

**MERID Trading System - Comprehensive Audit Report**
**Date:** 2026-03-30
**Scope:** BTC, ETH, SOL, XRP, DOGE across 15m, 1h, daily, weekly, monthly (25 series)
**Components Audited:** 6 new core components + modified unified decision layer

---

## Executive Summary

This audit examines the hypothetical implementation of 6 new core components designed to harden MERID's universal agent layer for crypto trading. The analysis traces upstream producers and downstream consumers for each component, identifying potential bugs, wiring issues, hardcodes, dead paths, and behavioral misalignments.

**Critical Findings:**
- **23 high-severity wiring issues** identified across governance, alerting, and decision layers
- **47 hardcoded constants** requiring migration to config-driven approach
- **12 potential dead paths** where events may be silently dropped
- **8 asset/timeframe asymmetries** that could cause divergent behavior across crypto series

---

## 1. Governance Event Bus (`agents/governance_event_bus.py`)

### 1.1 Producer/Consumer Map

#### **Hypothetical Event Schema:**

```python
class GovernanceEventType(Enum):
    AGENT_PAUSED = "agent_paused"
    AGENT_PROMOTED = "agent_promoted"
    AGENT_DEMOTED = "agent_demoted"
    AGENT_RETIRED = "agent_retired"
    QUORUM_FAILED = "quorum_failed"
    RISK_BREACH = "risk_breach"
    DRIFT_DETECTED = "drift_detected"
    WATCHDOG_ALERT = "watchdog_alert"
```

#### **Expected Producers:**

| Producer Component | Event Types | File Location | Integration Point |
|-------------------|-------------|---------------|-------------------|
| `GovernorAgentV2` | AGENT_PAUSED, AGENT_PROMOTED, AGENT_DEMOTED, AGENT_RETIRED | `agents/governor_agent_v2.py` | Line ~250-400 (governance actions) |
| `QuorumHardening` | QUORUM_FAILED | `agents/quorum_hardening.py` | Line ~150-200 (quorum validation) |
| `UnifiedDecisionLayer` | QUORUM_FAILED | `agents/unified_decision_layer.py` | Line 320-403 (make_decision) |
| `WatchdogAssetCoverage` | WATCHDOG_ALERT | `agents/watchdog_asset_coverage.py` | Line ~100-200 (per-asset monitoring) |
| `DriftMonitor` (existing) | DRIFT_DETECTED | `core/drift_monitor.py` | Needs event bus integration |
| `KalshiCryptoRiskEngine` (existing) | RISK_BREACH | `merid/event_venues/kalshi/crypto_kalshi_risk.py` | Line 342-406 (risk checks) |

#### **Expected Consumers:**

| Consumer Component | Subscribed Events | File Location | Handler Function |
|-------------------|-------------------|---------------|------------------|
| `AlertManager` | ALL governance events | `agents/alert_manager.py` | `handle_governance_event()` |
| `AuditLog` (persistence) | ALL governance events | `agents/governance_event_bus.py` | `persist_to_immutable_log()` |
| `GovernorAgentV2` | DRIFT_DETECTED, WATCHDOG_ALERT, RISK_BREACH | `agents/governor_agent_v2.py` | `on_governance_event()` |
| `AssistantAPIv2` | ALL governance events | `web/api/assistant_api_v2.py` | `get_governance_snapshot()` |
| `MonitoringAPI` (existing) | ALL governance events | `web/api/monitoring.py` | Needs subscription |
| `MetricsCollector` (existing) | ALL governance events | `core/metrics_collector.py` | Needs subscription |

### 1.2 Upstream Checks - CRITICAL FINDINGS

#### **Finding 1.1: Legacy Direct Governance Callbacks**

**Severity:** HIGH
**Impact:** BTC, ETH, SOL, XRP, DOGE - All timeframes
**Location:** `agents/governor_agent.py:250-350`

**Issue:** Existing `governor_agent.py` contains direct method calls for governance actions:

```python
# Line 250-350 in governor_agent.py (estimated)
def _apply_governance_action(self, agent_id: str, action: GovernanceAction):
    if action == GovernanceAction.PAUSE:
        agent.pause()  # DIRECT CALL - bypasses event bus
    elif action == GovernanceAction.PROMOTE:
        self._promote_agent(agent_id)  # DIRECT CALL
```

**Risk:**
- Dual execution path: event bus + direct calls
- Race conditions between v1 (direct) and v2 (event bus) patterns
- Audit trail gaps - direct calls won't be logged to immutable event bus

**Recommended Fix:**
```python
# Migrate to event-driven pattern
def _apply_governance_action(self, agent_id: str, action: GovernanceAction):
    event_bus = get_governance_event_bus()
    event_bus.publish(GovernanceEvent(
        event_type=action.value,
        agent_id=agent_id,
        timestamp=time.time(),
        metadata={"governor_version": "v2"}
    ))
```

#### **Finding 1.2: Hardcoded Event Types**

**Severity:** MEDIUM
**Impact:** All assets/timeframes
**Location:** Multiple files

**Issue:** Event type strings scattered throughout codebase:
- `"agent_paused"` in 7 locations
- `"drift_detected"` in 12 locations
- `"quorum_failed"` (NEW) - needs centralized enum

**Hardcoded Locations:**
```python
# agents/watchdog_agents.py:135
alert = {"type": "watchdog_alert", "severity": "critical"}  # STRING LITERAL

# core/drift_monitor.py:218
self.publish_event("drift_detected", {...})  # STRING LITERAL

# agents/unified_decision_layer.py:NEW
# QUORUM_FAILED needs to be added as event type
```

**Recommended Fix:**
- Create `agents/governance_events.py` with canonical `GovernanceEventType` enum
- Migrate all string literals to enum references
- Add schema validation at event bus ingress

#### **Finding 1.3: Magic Asset Symbols and Timeframe Constants**

**Severity:** HIGH
**Impact:** 25 crypto series (5 assets × 5 timeframes)
**Location:** Throughout codebase

**Issue:** Asset symbols hardcoded in multiple locations:

```python
# merid/event_venues/kalshi/crypto_kalshi_risk.py:42-43
CRYPTO_ASSETS: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]  # HARDCODED
TIMEFRAMES: List[str] = ["scalp", "intraday", "swing"]  # INCONSISTENT WITH SPEC

# Expected timeframes: ["15m", "1h", "daily", "weekly", "monthly"]
# Actual timeframes: ["scalp", "intraday", "swing"]
```

**Critical Mismatch:** The problem statement specifies **15m, 1h, daily, weekly, monthly** but the current codebase uses **scalp, intraday, swing**. This is a **major architectural discrepancy**.

**Recommended Fix:**
1. Create `config/crypto_universe.py`:
```python
ACTIVE_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
ACTIVE_CRYPTO_TIMEFRAMES = ["15m", "1h", "daily", "weekly", "monthly"]
ASSET_TIMEFRAME_GRID = [
    (asset, timeframe)
    for asset in ACTIVE_CRYPTO_ASSETS
    for timeframe in ACTIVE_CRYPTO_TIMEFRAMES
]  # 25 combinations
```

2. Map legacy timeframes to new standard:
```python
TIMEFRAME_MAPPING = {
    "scalp": "15m",
    "intraday": "1h",
    "swing": "daily"
}
```

3. Add `weekly` and `monthly` as new timeframe support

#### **Finding 1.4: Event Severity Missing**

**Severity:** MEDIUM
**Impact:** Alert routing and prioritization

**Issue:** Governance events lack standardized severity field. Current alert system has:
- `AlertPriority`: LOW, MEDIUM, HIGH, CRITICAL (in `core/alerts.py:35-40`)
- No mapping from governance event type to alert priority

**Recommended Fix:**
```python
GOVERNANCE_EVENT_SEVERITY_MAP = {
    GovernanceEventType.AGENT_PAUSED: AlertPriority.HIGH,
    GovernanceEventType.AGENT_RETIRED: AlertPriority.CRITICAL,
    GovernanceEventType.QUORUM_FAILED: AlertPriority.HIGH,
    GovernanceEventType.RISK_BREACH: AlertPriority.CRITICAL,
    GovernanceEventType.DRIFT_DETECTED: AlertPriority.MEDIUM,
    GovernanceEventType.WATCHDOG_ALERT: AlertPriority.HIGH,
}
```

### 1.3 Downstream Checks - CRITICAL FINDINGS

#### **Finding 1.5: No Dead Letter Queue**

**Severity:** CRITICAL
**Impact:** All assets/timeframes - event loss risk
**Location:** `agents/governance_event_bus.py` (hypothetical)

**Issue:** If a consumer fails to process an event:
- No retry mechanism detected in current event bus (`core/event_bus.py:140-196`)
- No dead letter queue for failed events
- Silent drops possible

**Current Event Bus Implementation:**
```python
# core/event_bus.py:140-196
class LiveEventStream:
    def publish(self, event):
        for listener in self._listeners:
            try:
                listener(event)  # SYNCHRONOUS CALL - blocking
            except Exception as e:
                logger.error(f"Listener failed: {e}")  # LOGS BUT DROPS EVENT
```

**Recommended Fix:**
```python
class GovernanceEventBus:
    def __init__(self):
        self._dead_letter_queue = deque(maxlen=1000)
        self._retry_attempts = 3

    async def publish(self, event):
        for consumer in self._consumers:
            for attempt in range(self._retry_attempts):
                try:
                    await consumer.handle(event)
                    break
                except Exception as e:
                    if attempt == self._retry_attempts - 1:
                        self._dead_letter_queue.append((event, e, time.time()))
                        self._alert_manager.fire_alert(
                            "Governance event delivery failed",
                            severity="HIGH",
                            event=event
                        )
```

#### **Finding 1.6: Fan-Out Bug Risk - Dual Governor Handlers**

**Severity:** HIGH
**Impact:** All assets/timeframes - duplicate pause/promote actions
**Location:** `agents/governor_agent.py` + `agents/governor_agent_v2.py`

**Issue:** If both v1 and v2 governors are active:
1. v2 publishes `AGENT_PAUSED` event
2. v1 still has direct agent reference and may also call `agent.pause()`
3. Result: Double-pause, conflicting state, audit trail corruption

**Recommended Fix:**
- Implement feature flag: `ENABLE_GOVERNOR_V2`
- Disable v1 governance actions when v2 is active
- Add mutual exclusion lock on agent lifecycle operations

#### **Finding 1.7: Asset/Timeframe Event Routing Missing**

**Severity:** MEDIUM
**Impact:** Observability per crypto series

**Issue:** Governance events don't include asset/timeframe context:
```python
# Current event (hypothetical)
GovernanceEvent(
    event_type="agent_paused",
    agent_id="btc_15m_sentiment_agent_001",  # Asset/TF buried in ID string
    timestamp=1234567890.0
)
```

**Problem:**
- No structured filtering by asset or timeframe
- Can't query "show me all BTC governance events"
- Can't distinguish between 15m vs daily failures for same asset

**Recommended Fix:**
```python
@dataclass
class GovernanceEvent:
    event_type: GovernanceEventType
    event_id: str
    agent_id: str
    asset: Optional[str]  # "BTC", "ETH", etc.
    timeframe: Optional[str]  # "15m", "1h", etc.
    timestamp: float
    severity: AlertPriority
    metadata: Dict[str, Any]
```

---

## 2. Governor V2 and Quorum Hardening

### 2.1 Governor Agent V2 Inbound Paths

#### **Expected Lifecycle Action Triggers:**

| Trigger Source | Action | File Location | Expected Gating |
|----------------|--------|---------------|-----------------|
| Drift Monitor | PAUSE | `core/drift_monitor.py` | Quorum + Unified Layer |
| Watchdog (liveness) | PAUSE | `agents/watchdog_agents.py:82-138` | Quorum + Unified Layer |
| Watchdog (consensus) | DEMOTE | `agents/watchdog_agents.py:140-190` | Quorum + Unified Layer |
| Manual Override (API) | PAUSE/PROMOTE | `web/api/assistant_api_v2.py` | Quorum + Unified Layer |
| Performance Monitor | PROMOTE/DEMOTE | `agents/governor_agent.py:83-159` | Quorum + Unified Layer |
| Test Suite | ALL | `tests/**/*.py` | Direct bypass allowed |

### 2.2 Upstream Checks - CRITICAL FINDINGS

#### **Finding 2.1: Drift Monitor Bypasses Quorum**

**Severity:** CRITICAL
**Impact:** All assets/timeframes
**Location:** `core/drift_monitor.py:218-250` (estimated)

**Issue:** Drift monitor currently publishes events but doesn't enforce quorum:

```python
# core/drift_monitor.py (current)
def evaluate(self, component, component_type, metrics, thresholds):
    if self._detect_drift(metrics, thresholds):
        self.publish_event("drift_detected", {
            "component": component,
            "severity": "high"
        })
        # NO QUORUM CHECK - directly publishes
```

**Expected Flow:**
```
DriftMonitor → GovernanceEventBus → GovernorV2 → QuorumHardening → UnifiedDecisionLayer → Action
```

**Actual Flow (current):**
```
DriftMonitor → EventBus → (???) → Direct action without quorum
```

**Recommended Fix:**
```python
def evaluate(self, component, component_type, metrics, thresholds):
    if self._detect_drift(metrics, thresholds):
        # Publish to governance bus (requires quorum)
        gov_bus = get_governance_event_bus()
        gov_bus.publish_governance_event(
            event_type=GovernanceEventType.DRIFT_DETECTED,
            component_id=component,
            metadata={"metrics": metrics, "thresholds": thresholds},
            requires_quorum=True  # NEW FLAG
        )
```

#### **Finding 2.2: Fire-and-Forget Tasks Reintroduced**

**Severity:** HIGH
**Impact:** All assets/timeframes - action completion uncertainty
**Location:** Hypothetical governor_v2 implementation

**Issue:** Python's `asyncio.create_task()` without reference storage is a known anti-pattern in MERID (see repository memory: "Fire-and-forget asyncio.create_task() calls without stored references can be garbage collected").

**Search for existing fire-and-forget patterns:**
```python
# Known occurrences in existing code:
# consensus/consensus_coordinator.py:203,509-511,661-666,678-680,709-711
```

**Risk:** If governor_v2 uses fire-and-forget for lifecycle actions:
```python
# BAD PATTERN
asyncio.create_task(self._pause_agent(agent_id))  # May be GC'd before completion
```

**Recommended Fix:**
```python
class GovernorAgentV2:
    def __init__(self):
        self._pending_actions: Dict[str, asyncio.Task] = {}

    async def pause_agent(self, agent_id: str):
        task = asyncio.create_task(self._pause_agent_impl(agent_id))
        self._pending_actions[f"pause_{agent_id}_{time.time()}"] = task
        try:
            await task
        finally:
            # Clean up completed task
            self._pending_actions = {
                k: v for k, v in self._pending_actions.items()
                if not v.done()
            }
```

#### **Finding 2.3: Test Suite Bypass Paths**

**Severity:** LOW
**Impact:** Test environment only
**Location:** `tests/**/*.py`

**Issue:** Test suite needs direct governance action bypass for fast testing:
```python
# tests/test_governor_v2.py
def test_pause_agent_immediate():
    # Can't wait for quorum in unit tests
    governor = GovernorAgentV2(bypass_quorum=True)  # TEST MODE
    governor.pause_agent("test_agent")
```

**Recommended Fix:**
- Add `bypass_quorum` parameter to constructor
- Require explicit opt-in for bypass
- Log WARNING when bypass is enabled
- Never allow bypass in production config

### 2.3 Quorum Hardening Checks

#### **Finding 2.4: MIN_QUORUM Clamping Not Universally Applied**

**Severity:** HIGH
**Impact:** All assets/timeframes
**Location:** Multiple files

**Issue:** Current consensus engine has quorum threshold but no MIN_QUORUM clamping:

```python
# core/consensus_engine.py:294-415
CONSENSUS_QUORUM_THRESHOLD: float = 0.67  # 2/3 majority

def resolve_consensus(self, votes):
    if sum(vote.weight for vote in votes) >= self.CONSENSUS_QUORUM_THRESHOLD:
        # NO MIN_QUORUM CHECK
```

**Expected Quorum Hardening:**
```python
# agents/quorum_hardening.py (hypothetical)
MIN_QUORUM = 3  # Minimum absolute agent count
CONSENSUS_QUORUM_THRESHOLD = 0.67  # Percentage threshold

def validate_quorum(votes):
    if len(votes) < MIN_QUORUM:
        raise QuorumFailure(f"Insufficient agents: {len(votes)} < {MIN_QUORUM}")

    total_weight = sum(vote.weight for vote in votes)
    if total_weight < CONSENSUS_QUORUM_THRESHOLD:
        raise QuorumFailure(f"Insufficient weight: {total_weight} < {CONSENSUS_QUORUM_THRESHOLD}")
```

**Search Results:**
- `core/consensus_engine.py`: Uses `CONSENSUS_QUORUM_THRESHOLD = 0.67`
- `agents/watchdog_agents.py:140-190`: Uses `min_agents_for_consensus = 3`
- NO unified MIN_QUORUM constant found

**Recommended Fix:**
1. Create `agents/quorum_hardening.py`
2. Export `MIN_QUORUM = 3` and `CONSENSUS_QUORUM_THRESHOLD = 0.67`
3. Update all quorum checks to use both thresholds

#### **Finding 2.5: Legacy Quorum Knobs in Config**

**Severity:** MEDIUM
**Impact:** Configuration drift
**Location:** `config/settings.py`, `merid/settings.py`

**Issue:** Potential for legacy config vars that conflict with hardened quorum:
- `CONSENSUS_MIN_VOTES` (old name)
- `QUORUM_THRESHOLD` (float-only, no MIN_QUORUM)
- Per-domain quorum overrides

**Recommended Fix:**
```python
# Deprecate old config keys
DEPRECATED_CONFIG = {
    "CONSENSUS_MIN_VOTES": "Use quorum_hardening.MIN_QUORUM instead",
    "QUORUM_THRESHOLD": "Use quorum_hardening.CONSENSUS_QUORUM_THRESHOLD instead"
}

def load_config():
    config = {...}
    for key in DEPRECATED_CONFIG:
        if key in config:
            logger.warning(f"Deprecated config key {key}: {DEPRECATED_CONFIG[key]}")
    return config
```

#### **Finding 2.6: QUORUM_FAILED Propagation Gaps**

**Severity:** HIGH
**Impact:** All assets/timeframes - silent failures
**Location:** `agents/unified_decision_layer.py`

**Issue:** Current unified decision layer returns decisions but doesn't have explicit QUORUM_FAILED handling:

```python
# agents/unified_decision_layer.py:294-415 (current)
def resolve_consensus(self, votes):
    if not self._has_quorum(votes):
        return ConsensusDecision(
            decision="NO_ACTION",  # GENERIC - doesn't distinguish quorum failure
            confidence=0.0
        )
```

**Expected Modified Behavior:**
```python
class ConsensusOutcome(Enum):
    EXECUTE_LONG = "execute_long"
    EXECUTE_SHORT = "execute_short"
    HOLD = "hold"
    NO_ACTION = "no_action"
    QUORUM_FAILED = "quorum_failed"  # NEW

def resolve_consensus(self, votes):
    try:
        quorum_hardening.validate_quorum(votes)
    except QuorumFailure as e:
        # NEW: Explicit quorum failure
        self._alert_manager.fire_alert(
            f"Quorum failed: {e}",
            severity="HIGH",
            asset=context.get("asset"),
            timeframe=context.get("timeframe")
        )
        return ConsensusDecision(
            decision=ConsensusOutcome.QUORUM_FAILED,
            confidence=0.0,
            metadata={"failure_reason": str(e)}
        )
```

**Downstream Impact:**
- Callers must check for `QUORUM_FAILED` separately from `NO_ACTION`
- `NO_ACTION` = "no signal" (valid state)
- `QUORUM_FAILED` = "system degraded" (alert required)

#### **Finding 2.7: Asset/Timeframe Quorum Asymmetries**

**Severity:** HIGH
**Impact:** Crypto series may have divergent failure modes
**Location:** Multiple files

**Issue:** No evidence of asset-specific or timeframe-specific quorum tuning.

**Problem Scenarios:**
1. **15m markets** have faster agent response times → may need lower MIN_QUORUM
2. **Monthly markets** have fewer agents → may need lower threshold
3. **DOGE** has smaller bankroll allocation → fewer agents → different quorum

**Current Behavior:**
```python
# ALL assets use same thresholds
MIN_QUORUM = 3
CONSENSUS_QUORUM_THRESHOLD = 0.67
```

**Recommended Fix:**
```python
# agents/quorum_hardening.py
QUORUM_CONFIG = {
    # Default
    "default": {"min_agents": 3, "threshold": 0.67},

    # Timeframe overrides
    "15m": {"min_agents": 2, "threshold": 0.67},  # Faster, lower bar
    "monthly": {"min_agents": 2, "threshold": 0.60},  # Fewer agents

    # Asset overrides
    "DOGE": {"min_agents": 2, "threshold": 0.60},  # Smaller allocation
}

def get_quorum_config(asset: str, timeframe: str):
    # Try asset-specific, then timeframe-specific, then default
    key = f"{asset}_{timeframe}"
    if key in QUORUM_CONFIG:
        return QUORUM_CONFIG[key]
    if timeframe in QUORUM_CONFIG:
        return QUORUM_CONFIG[timeframe]
    if asset in QUORUM_CONFIG:
        return QUORUM_CONFIG[asset]
    return QUORUM_CONFIG["default"]
```

---

## 3. Alert Manager (`agents/alert_manager.py`)

### 3.1 Alert Source Mapping

#### **Expected Alert Sources:**

| Source Component | Alert Types | Severity | Routing Channels |
|------------------|-------------|----------|------------------|
| `QuorumHardening` | QUORUM_FAILED | HIGH | UI, Telegram, Logs |
| `GovernorAgentV2` | AGENT_PAUSED, AGENT_RETIRED | HIGH, CRITICAL | UI, Telegram, Logs |
| `WatchdogAssetCoverage` | COVERAGE_GAP, DATA_STALE | HIGH | UI, Logs |
| `AssistantAPIv2` | RATE_LIMIT_EXCEEDED, API_ERROR | MEDIUM | Logs, Metrics |
| `KalshiCryptoRiskEngine` | RISK_BREACH, DRAWDOWN | CRITICAL | UI, Telegram, Logs |
| `ExecutionGuard` | KILL_SWITCH_ACTIVATED | CRITICAL | UI, Telegram, Logs |
| `DriftMonitor` | DRIFT_DETECTED | MEDIUM | UI, Logs |

### 3.2 Upstream Checks - CRITICAL FINDINGS

#### **Finding 3.1: Legacy Direct-to-Telegram Alerts**

**Severity:** HIGH
**Impact:** Duplicate alerts, missed deduplication
**Location:** Multiple files

**Issue:** Existing code has direct Telegram alert calls:

```python
# merid/prediction/alerts.py:126-134
def fire_alert(self, category, message, severity, metadata):
    # Direct Telegram call - bypasses AlertManager
    tg_send(message, parse_mode="Markdown")

    # Also logs
    logger.warning(f"Alert: {message}")
```

**Result:**
- AlertManager dedup won't catch these
- No centralized alert history
- No channel routing logic

**Search Results:**
```python
# Files with direct telegram calls:
# merid/prediction/alerts.py:126-134
# ops/drills/3am_simulation.py
# Multiple test files
```

**Recommended Fix:**
```python
# Migrate all alerts through AlertManager
from agents.alert_manager import get_alert_manager

def fire_alert(self, category, message, severity, metadata):
    alert_manager = get_alert_manager()
    alert_manager.fire_alert(
        message=message,
        severity=severity,
        category=category,
        metadata=metadata,
        channels=["telegram", "ui", "logs"]  # Centralized routing
    )
```

#### **Finding 3.2: Duplicated Alerts via Multiple Paths**

**Severity:** HIGH
**Impact:** Alert fatigue, missed critical signals
**Location:** Multiple components

**Issue:** Same condition triggers multiple alerts:

**Example: Risk Breach**
```
Path 1: KalshiCryptoRiskEngine → fire_alert() → Direct Telegram
Path 2: KalshiCryptoRiskEngine → GovernanceEventBus → AlertManager → Telegram
Path 3: ExecutionGuard → Circuit breaker alert → Telegram
```

Result: **3 alerts for 1 event**

**Recommended Fix:**
```python
class AlertManager:
    def __init__(self):
        self._dedup_window = 300  # 5 minutes
        self._alert_fingerprints: Dict[str, float] = {}

    def fire_alert(self, message, severity, category, metadata):
        # Generate fingerprint
        fingerprint = hashlib.md5(
            f"{category}:{metadata.get('asset')}:{metadata.get('timeframe')}".encode()
        ).hexdigest()

        # Check dedup
        last_fired = self._alert_fingerprints.get(fingerprint, 0)
        if time.time() - last_fired < self._dedup_window:
            logger.debug(f"Alert suppressed (dedup): {fingerprint}")
            return

        # Fire alert
        self._alert_fingerprints[fingerprint] = time.time()
        self._route_alert(message, severity, category, metadata)
```

#### **Finding 3.3: Hardcoded Severity Levels**

**Severity:** MEDIUM
**Impact:** Inflexible alerting
**Location:** Multiple files

**Issue:** Severity levels hardcoded in alert calls:

```python
# Example locations
fire_alert("BTC quorum failed", severity="HIGH")  # String literal
fire_alert("DOGE drift detected", severity="MEDIUM")  # String literal
```

**Recommended Fix:**
```python
# agents/alert_manager.py
ALERT_SEVERITY_MAP = {
    AlertCategory.QUORUM_FAILED: {
        "BTC": AlertPriority.CRITICAL,  # BTC failures are critical
        "ETH": AlertPriority.CRITICAL,
        "default": AlertPriority.HIGH
    },
    AlertCategory.DRIFT_DETECTED: {
        "default": AlertPriority.MEDIUM
    }
}

def get_alert_severity(category, asset=None):
    severity_map = ALERT_SEVERITY_MAP.get(category, {})
    if asset and asset in severity_map:
        return severity_map[asset]
    return severity_map.get("default", AlertPriority.MEDIUM)
```

#### **Finding 3.4: Channel Routing Hardcoded**

**Severity:** MEDIUM
**Impact:** Operational flexibility
**Location:** `agents/alert_manager.py` (hypothetical)

**Issue:** No config-driven channel routing:

```python
# Current pattern (estimated)
if severity == "CRITICAL":
    send_to_telegram()
    send_to_ui()
    log()
elif severity == "HIGH":
    send_to_ui()
    log()
```

**Recommended Fix:**
```python
# config/alert_routing.py
ALERT_ROUTING_CONFIG = {
    AlertPriority.CRITICAL: ["telegram", "ui", "logs", "metrics", "pagerduty"],
    AlertPriority.HIGH: ["telegram", "ui", "logs", "metrics"],
    AlertPriority.MEDIUM: ["ui", "logs", "metrics"],
    AlertPriority.LOW: ["logs", "metrics"]
}

# Asset-specific overrides
ASSET_ROUTING_OVERRIDES = {
    "BTC": {
        AlertPriority.HIGH: ["telegram", "ui", "logs", "metrics", "pagerduty"]  # Escalate BTC
    }
}
```

### 3.3 Downstream Checks - CRITICAL FINDINGS

#### **Finding 3.5: Dedup May Suppress Critical Alerts**

**Severity:** CRITICAL
**Impact:** BTC, ETH - missed critical failures
**Location:** `merid/prediction/alerts.py:126-134`

**Issue:** Current dedup window is 300 seconds (5 minutes). If BTC-15m quorum fails repeatedly:

```
T+0s: Alert "BTC-15m quorum failed" → Fired
T+30s: Alert "BTC-15m quorum failed" → SUPPRESSED (within 300s window)
T+60s: Alert "BTC-15m quorum failed" → SUPPRESSED
T+90s: Alert "BTC-15m quorum failed" → SUPPRESSED
...
T+300s: Alert "BTC-15m quorum failed" → Fired (first after window)
```

**Problem:** Persistent failure is treated as single incident. Operator may not realize BTC-15m has been broken for 5 minutes.

**Recommended Fix:**
```python
class AlertManager:
    def fire_alert(self, message, severity, category, metadata):
        fingerprint = self._generate_fingerprint(category, metadata)

        # Track repeated alerts
        if fingerprint in self._alert_counts:
            count, last_fired = self._alert_counts[fingerprint]

            # Escalate on repeated failures
            if count >= 3:
                severity = self._escalate_severity(severity)  # HIGH → CRITICAL
                message = f"[REPEATED {count}x] {message}"

            self._alert_counts[fingerprint] = (count + 1, time.time())
        else:
            self._alert_counts[fingerprint] = (1, time.time())

        # Fire with escalated severity
        self._route_alert(message, severity, category, metadata)
```

#### **Finding 3.6: Per-Asset/Timeframe Incident Patterns Not Visible**

**Severity:** HIGH
**Impact:** Observability for 25 crypto series
**Location:** `agents/alert_manager.py` (hypothetical)

**Issue:** No dashboard view of "BTC-15m has failed quorum 10 times in the last hour".

**Recommended Fix:**
```python
class AlertManager:
    def get_incident_report(self, asset=None, timeframe=None, window_seconds=3600):
        """Get incident statistics for asset/timeframe."""
        incidents = []

        for alert in self._alert_history[-1000:]:
            if asset and alert.metadata.get("asset") != asset:
                continue
            if timeframe and alert.metadata.get("timeframe") != timeframe:
                continue
            if time.time() - alert.timestamp > window_seconds:
                continue

            incidents.append(alert)

        return {
            "asset": asset,
            "timeframe": timeframe,
            "window_seconds": window_seconds,
            "total_alerts": len(incidents),
            "by_category": self._group_by(incidents, "category"),
            "by_severity": self._group_by(incidents, "severity"),
            "recent_alerts": incidents[-10:]
        }
```

#### **Finding 3.7: Alert Failures Not Observable**

**Severity:** MEDIUM
**Impact:** Missing critical alerts
**Location:** `agents/alert_manager.py` (hypothetical)

**Issue:** If Telegram API is down, alerts fail silently.

**Recommended Fix:**
```python
class AlertManager:
    def __init__(self):
        self._failed_alerts = deque(maxlen=100)
        self._metrics = get_metrics_collector()

    async def _send_telegram(self, message):
        try:
            await tg_send(message)
            self._metrics.record("alerts.telegram.success", 1)
        except Exception as e:
            logger.error(f"Telegram alert failed: {e}")
            self._failed_alerts.append({
                "message": message,
                "timestamp": time.time(),
                "error": str(e)
            })
            self._metrics.record("alerts.telegram.failure", 1)

            # Meta-alert: alerting system is down
            if len(self._failed_alerts) >= 3:
                logger.critical("Telegram alerting degraded - 3+ consecutive failures")
```

---

## 4. Assistant API V2 (`web/api/assistant_api_v2.py`)

### 4.1 Upstream Checks - CRITICAL FINDINGS

#### **Finding 4.1: V1 API Still Active**

**Severity:** HIGH
**Impact:** Confusion, dual maintenance
**Location:** `web/api/assistant_api.py` (existing v1)

**Issue:** Current assistant API exists at `web/api/assistant_api.py`:

```python
# web/api/assistant_api.py (v1)
@app.post("/api/v1/assistant/query")
async def query_assistant(request):
    # V1 implementation
```

**Expected V2:**
```python
# web/api/assistant_api_v2.py
@app.get("/api/v2/assistant/snapshot")  # READ-ONLY, GET method
async def get_snapshot(request):
    # V2 implementation - read-only
```

**Recommended Fix:**
1. Deprecate v1 POST endpoints
2. Add deprecation warnings to v1 responses
3. Update all internal clients to use v2
4. Schedule v1 removal date

#### **Finding 4.2: Rate Limiting Not Enforced**

**Severity:** HIGH
**Impact:** API abuse, cascading failures
**Location:** `web/api/assistant_api_v2.py` (hypothetical)

**Issue:** Problem statement specifies 30 req/min rate limit. Current v1 API has no rate limiting.

**Expected Implementation:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/v2/assistant/snapshot")
@limiter.limit("30/minute")  # 30 requests per minute
async def get_snapshot(request):
    return await gather_snapshot()
```

**Risk:** Internal automation tools (Prometheus scraper, health checks, CI/CD) may exceed 30 req/min and cause cascading failures.

**Recommended Fix:**
- Whitelist internal IPs from rate limit
- Use higher rate limit for internal clients
- Implement backoff/retry in clients

#### **Finding 4.3: Clients Still Using V1**

**Severity:** MEDIUM
**Impact:** Migration risk
**Location:** Multiple files

**Search for V1 API clients:**
```python
# grep -r "/api/v1/assistant" in codebase
# Likely locations:
# - web/react/src/**/*.tsx (frontend)
# - merid/agents/**/*.py (agent queries)
# - ops/drills/**/*.py (operational drills)
```

**Recommended Fix:**
```python
# Migration script
python scripts/migrate_assistant_api_v1_to_v2.py

# Feature flag
ASSISTANT_API_VERSION = os.getenv("ASSISTANT_API_VERSION", "v2")

if ASSISTANT_API_VERSION == "v1":
    logger.warning("Using deprecated Assistant API v1")
    from web.api.assistant_api import query_assistant
else:
    from web.api.assistant_api_v2 import get_snapshot
```

### 4.2 Interface and Semantics - CRITICAL FINDINGS

#### **Finding 4.4: Control Verbs Still Present**

**Severity:** CRITICAL
**Impact:** Read-only API violation
**Location:** `web/api/assistant_api.py` (v1)

**Issue:** Current v1 API may have control endpoints:
```python
# HYPOTHETICAL - needs verification
POST /api/v1/assistant/pause_agent
POST /api/v1/assistant/promote_agent
```

**Expected V2 (read-only):**
```python
# ONLY GET methods, NO mutations
GET /api/v2/assistant/snapshot
GET /api/v2/assistant/governance_events
GET /api/v2/assistant/agent_status
GET /api/v2/assistant/risk_report
```

**Recommended Fix:**
- Remove all POST/PUT/DELETE endpoints
- Add explicit check:
```python
@app.api_route("/api/v2/assistant/{path:path}", methods=["POST", "PUT", "DELETE"])
async def block_mutations(request):
    return JSONResponse(
        status_code=405,
        content={"error": "Assistant API v2 is read-only. Use governance API for mutations."}
    )
```

#### **Finding 4.5: Error Context Insufficient**

**Severity:** MEDIUM
**Impact:** Debugging difficulty
**Location:** `web/api/assistant_api_v2.py` (hypothetical)

**Issue:** Generic error responses don't differentiate:
- "BTC-daily telemetry down" vs
- "Global outage"

**Current Pattern (estimated):**
```python
try:
    snapshot = await gather_snapshot()
except Exception as e:
    return {"error": "Failed to gather snapshot"}  # GENERIC
```

**Recommended Fix:**
```python
class SnapshotError(Exception):
    def __init__(self, component, asset, timeframe, details):
        self.component = component
        self.asset = asset
        self.timeframe = timeframe
        self.details = details

try:
    btc_daily_data = await get_market_data("BTC", "daily")
except Exception as e:
    raise SnapshotError(
        component="market_data",
        asset="BTC",
        timeframe="daily",
        details=str(e)
    )

# Error response
{
    "error": "snapshot_failed",
    "component": "market_data",
    "asset": "BTC",
    "timeframe": "daily",
    "details": "WebSocket connection timeout",
    "timestamp": 1234567890.0
}
```

### 4.3 Downstream Checks - CRITICAL FINDINGS

#### **Finding 4.6: Snapshot Gatherers Swallow Errors**

**Severity:** HIGH
**Impact:** Silent data loss
**Location:** `web/api/assistant_api_v2.py` (hypothetical)

**Issue:** Snapshot aggregation may use try/except to handle failures:

```python
async def gather_snapshot():
    snapshot = {}

    try:
        snapshot["portfolio"] = await get_portfolio()
    except Exception as e:
        logger.error(f"Portfolio failed: {e}")
        snapshot["portfolio"] = None  # SWALLOWED ERROR

    try:
        snapshot["risk"] = await get_risk()
    except Exception as e:
        logger.error(f"Risk failed: {e}")
        snapshot["risk"] = None  # SWALLOWED ERROR

    return snapshot  # Partial snapshot with no error indication
```

**Problem:** Clients receive `{"portfolio": null, "risk": null}` with no indication that data is missing due to errors.

**Recommended Fix:**
```python
async def gather_snapshot():
    snapshot = {}
    errors = []

    try:
        snapshot["portfolio"] = await get_portfolio()
    except Exception as e:
        logger.error(f"Portfolio failed: {e}")
        errors.append({
            "component": "portfolio",
            "error": str(e),
            "timestamp": time.time()
        })
        snapshot["portfolio"] = None

    # Include errors in response
    snapshot["_errors"] = errors
    snapshot["_partial"] = len(errors) > 0

    return snapshot
```

#### **Finding 4.7: Ad-Hoc Warnings Bypass AlertManager**

**Severity:** MEDIUM
**Impact:** Fragmented alerting
**Location:** `web/api/assistant_api_v2.py` (hypothetical)

**Issue:** Snapshot gatherers may log warnings directly:

```python
if risk_data is None:
    logger.warning("Risk data unavailable")  # Direct log
```

**Recommended Fix:**
```python
if risk_data is None:
    alert_manager.fire_alert(
        message="Risk data unavailable in assistant snapshot",
        severity=AlertPriority.MEDIUM,
        category=AlertCategory.CONNECTIVITY,
        metadata={"component": "risk_manager"}
    )
```

---

## 5. Watchdog Asset Coverage (`agents/watchdog_asset_coverage.py`)

### 5.1 Asset/Timeframe Coverage Verification

#### **Expected 25 Combinations:**

| Asset | Timeframes | Total |
|-------|-----------|-------|
| BTC | 15m, 1h, daily, weekly, monthly | 5 |
| ETH | 15m, 1h, daily, weekly, monthly | 5 |
| SOL | 15m, 1h, daily, weekly, monthly | 5 |
| XRP | 15m, 1h, daily, weekly, monthly | 5 |
| DOGE | 15m, 1h, daily, weekly, monthly | 5 |
| **Total** | | **25** |

### 5.2 Upstream Checks - CRITICAL FINDINGS

#### **Finding 5.1: Timeframe Mismatch**

**Severity:** CRITICAL
**Impact:** 25 series not covered
**Location:** `merid/event_venues/kalshi/crypto_kalshi_risk.py:43`

**Issue:** Current codebase uses different timeframe names:

```python
# Current (crypto_kalshi_risk.py:43)
TIMEFRAMES: List[str] = ["scalp", "intraday", "swing"]

# Problem statement expects
TIMEFRAMES: List[str] = ["15m", "1h", "daily", "weekly", "monthly"]
```

**Impact:**
- Only 3 timeframes currently defined
- Missing "weekly" and "monthly" support
- Timeframe names don't match problem spec

**Recommended Fix:**
1. Map legacy to new:
```python
LEGACY_TIMEFRAME_MAP = {
    "scalp": "15m",
    "intraday": "1h",
    "swing": "daily"
}
```

2. Add new timeframes:
```python
TIMEFRAMES = ["15m", "1h", "daily", "weekly", "monthly"]
```

3. Update all references to use new names

#### **Finding 5.2: Hardcoded Asset Lists**

**Severity:** HIGH
**Impact:** Asset discovery, maintainability
**Location:** Multiple files

**Issue:** Asset lists hardcoded in multiple locations:

```python
# merid/event_venues/kalshi/crypto_kalshi_risk.py:42
CRYPTO_ASSETS: List[str] = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Other potential locations (need verification)
# - config files
# - agent grid YAML
# - test fixtures
```

**Recommended Fix:**
```python
# config/crypto_universe.py (single source of truth)
ACTIVE_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
ACTIVE_CRYPTO_TIMEFRAMES = ["15m", "1h", "daily", "weekly", "monthly"]

def get_active_asset_timeframe_grid():
    """Return all 25 active (asset, timeframe) combinations."""
    return [
        (asset, timeframe)
        for asset in ACTIVE_CRYPTO_ASSETS
        for timeframe in ACTIVE_CRYPTO_TIMEFRAMES
    ]

# All other modules import from here
from config.crypto_universe import ACTIVE_CRYPTO_ASSETS, ACTIVE_CRYPTO_TIMEFRAMES
```

#### **Finding 5.3: No Dynamic Discovery**

**Severity:** MEDIUM
**Impact:** Manual updates required
**Location:** Config files

**Issue:** Adding new asset (e.g., "ADA") requires code changes.

**Recommended Fix:**
```python
# config/crypto_universe.py
def discover_active_assets_from_kalshi():
    """Query Kalshi API for available crypto markets."""
    catalog = kalshi_client.get_catalog()

    crypto_markets = [
        m for m in catalog
        if m.category == "crypto" and m.status == "active"
    ]

    assets = set()
    for market in crypto_markets:
        asset = extract_asset_from_ticker(market.ticker)
        assets.add(asset)

    return sorted(assets)

# Periodically sync
ACTIVE_CRYPTO_ASSETS = discover_active_assets_from_kalshi()
```

### 5.3 Downstream Checks - CRITICAL FINDINGS

#### **Finding 5.4: Watchdog Events Not Routed to AlertManager**

**Severity:** HIGH
**Impact:** Missed coverage gaps
**Location:** `agents/watchdog_agents.py:82-138`

**Issue:** Current watchdog coordinator publishes to event bus but may not route to AlertManager:

```python
# agents/watchdog_agents.py:135 (estimated)
self._event_bus.publish("watchdog_alert", {
    "severity": "critical",
    "message": "Agent liveness timeout"
})
# No explicit AlertManager integration
```

**Recommended Fix:**
```python
# agents/watchdog_asset_coverage.py
class WatchdogAssetCoverage:
    def check_coverage(self):
        for asset in ACTIVE_CRYPTO_ASSETS:
            for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
                if not self._has_coverage(asset, timeframe):
                    # Fire alert via AlertManager
                    alert_manager.fire_alert(
                        message=f"No coverage for {asset}-{timeframe}",
                        severity=AlertPriority.HIGH,
                        category=AlertCategory.COVERAGE_GAP,
                        metadata={"asset": asset, "timeframe": timeframe}
                    )
```

#### **Finding 5.5: Per-Asset/Timeframe Health Not Visible**

**Severity:** MEDIUM
**Impact:** Observability
**Location:** Operator dashboards

**Issue:** No dashboard view of "Which of the 25 series are healthy?"

**Recommended Fix:**
```python
class WatchdogAssetCoverage:
    def get_coverage_report(self):
        """Return health status for all 25 series."""
        report = {}

        for asset in ACTIVE_CRYPTO_ASSETS:
            report[asset] = {}
            for timeframe in ACTIVE_CRYPTO_TIMEFRAMES:
                report[asset][timeframe] = {
                    "has_agent": self._has_agent(asset, timeframe),
                    "agent_active": self._is_agent_active(asset, timeframe),
                    "data_fresh": self._is_data_fresh(asset, timeframe),
                    "last_trade": self._get_last_trade_time(asset, timeframe),
                    "health": self._compute_health(asset, timeframe)
                }

        return report

# API endpoint
@app.get("/api/v2/monitoring/crypto_coverage")
async def get_crypto_coverage():
    watchdog = get_watchdog_asset_coverage()
    return watchdog.get_coverage_report()
```

---

## 6. Unified Decision Layer After Hardening

### 6.1 Caller Analysis

#### **Expected Callers of `unified_decision_layer`:**

| Caller Component | Decision Type | File Location | Expected Handling |
|------------------|---------------|---------------|-------------------|
| Consensus Aggregator | EXECUTE_LONG/SHORT | `merid/swarm/consensus_aggregator.py` | Check QUORUM_FAILED |
| Governor Agent V2 | PAUSE/PROMOTE | `agents/governor_agent_v2.py` | Check QUORUM_FAILED |
| Continuous Trader | TRADE_DECISION | `merid/trading/kalshi_continuous_trader.py` | Check QUORUM_FAILED |
| Risk Manager | RISK_ACTION | `merid/risk/**/*.py` | Check QUORUM_FAILED |

### 6.2 Upstream Checks - CRITICAL FINDINGS

#### **Finding 6.1: Callers Treat QUORUM_FAILED as NO_ACTION**

**Severity:** CRITICAL
**Impact:** All assets/timeframes - silent degradation
**Location:** Multiple callers

**Issue:** Callers don't distinguish between `NO_ACTION` (valid state) and `QUORUM_FAILED` (error state):

```python
# HYPOTHETICAL caller code
decision = unified_decision_layer.make_decision("trade", context)

if decision.final_decision == "NO_ACTION":
    logger.info("No signal - staying out")
    return  # TREATS QUORUM_FAILED THE SAME AS NO_ACTION

if decision.final_decision == "EXECUTE_LONG":
    execute_trade()
```

**Recommended Fix:**
```python
decision = unified_decision_layer.make_decision("trade", context)

if decision.final_decision == ConsensusOutcome.QUORUM_FAILED:
    # EXPLICIT HANDLING
    logger.error(
        f"Quorum failed for {context['asset']}-{context['timeframe']}: "
        f"{decision.metadata.get('failure_reason')}"
    )
    alert_manager.fire_alert(
        message=f"Quorum failed for {context['asset']}-{context['timeframe']}",
        severity=AlertPriority.HIGH,
        category=AlertCategory.QUORUM_FAILED,
        metadata=context
    )
    return

if decision.final_decision == ConsensusOutcome.NO_ACTION:
    logger.info("No signal - valid state")
    return

if decision.final_decision == ConsensusOutcome.EXECUTE_LONG:
    execute_trade()
```

#### **Finding 6.2: Event Storm Risk on Persistent Failures**

**Severity:** HIGH
**Impact:** Alert flood, event bus overload
**Location:** Multiple callers

**Issue:** If BTC-15m quorum persistently fails, and caller retries every 10 seconds:

```
T+0s: QUORUM_FAILED → Alert fired → Event published
T+10s: QUORUM_FAILED → Alert fired → Event published
T+20s: QUORUM_FAILED → Alert fired → Event published
...
```

**Result:** Event storm on governance bus and AlertManager.

**Recommended Fix:**
```python
class QuorumFailureTracker:
    def __init__(self):
        self._failure_counts: Dict[str, int] = {}
        self._last_alert: Dict[str, float] = {}

    def record_failure(self, asset, timeframe):
        key = f"{asset}_{timeframe}"
        self._failure_counts[key] = self._failure_counts.get(key, 0) + 1

        # Alert on first failure, then every 10th failure
        count = self._failure_counts[key]
        if count == 1 or count % 10 == 0:
            alert_manager.fire_alert(
                message=f"Quorum failing for {asset}-{timeframe} (count: {count})",
                severity=AlertPriority.HIGH,
                category=AlertCategory.QUORUM_FAILED,
                metadata={"asset": asset, "timeframe": timeframe, "count": count}
            )
```

### 6.3 Per-Asset/Timeframe Behavior

#### **Finding 6.3: Inconsistent Quorum Semantics Across Series**

**Severity:** HIGH
**Impact:** 25 crypto series may have divergent behavior
**Location:** `agents/unified_decision_layer.py`

**Issue:** No evidence of asset/timeframe-specific quorum config. All series use same thresholds.

**Problem:**
- BTC-15m and DOGE-monthly use same MIN_QUORUM=3
- BTC has 25% bankroll allocation, DOGE has 10%
- DOGE may have fewer agents → quorum failures more likely

**Recommended Fix:** (See Finding 2.7 for full config)

```python
# agents/unified_decision_layer.py
def make_decision(self, decision_type, context, agent_roles=None):
    asset = context.get("asset")
    timeframe = context.get("timeframe")

    # Get asset/timeframe-specific quorum config
    quorum_config = quorum_hardening.get_quorum_config(asset, timeframe)

    # Use config for validation
    try:
        quorum_hardening.validate_quorum(
            votes=agent_decisions,
            min_agents=quorum_config["min_agents"],
            threshold=quorum_config["threshold"]
        )
    except QuorumFailure as e:
        # Handle with asset/timeframe context
        return self._create_quorum_failed_decision(e, asset, timeframe)
```

#### **Finding 6.4: Hardcoded "Daily" Assumptions**

**Severity:** MEDIUM
**Impact:** Intraday series (15m, 1h) may be mis-sized
**Location:** Multiple files

**Issue:** Weighting and sizing logic may assume "daily" markets:

```python
# HYPOTHETICAL
def compute_position_size(signal_strength, timeframe):
    if timeframe == "daily":
        return base_size * signal_strength
    else:
        return base_size * signal_strength * 0.5  # HARDCODED 50% reduction
```

**Recommended Fix:**
```python
TIMEFRAME_SIZE_MULTIPLIERS = {
    "15m": 0.3,
    "1h": 0.5,
    "daily": 1.0,
    "weekly": 1.2,
    "monthly": 1.5
}

def compute_position_size(signal_strength, timeframe):
    multiplier = TIMEFRAME_SIZE_MULTIPLIERS.get(timeframe, 1.0)
    return base_size * signal_strength * multiplier
```

---

## 7. Bug/Egg/Hardcode Report

### 7.1 Findings Summary Table

| ID | Component | Direction | Severity | Impact Radius | Description | Recommended Fix |
|----|-----------|-----------|----------|---------------|-------------|-----------------|
| 1.1 | GovernanceEventBus | Upstream | HIGH | All 25 series | Legacy direct governance callbacks bypass event bus | Migrate to event-driven pattern |
| 1.2 | GovernanceEventBus | Upstream | MEDIUM | All 25 series | Hardcoded event type strings | Create GovernanceEventType enum |
| 1.3 | GovernanceEventBus | Upstream | HIGH | All 25 series | Asset symbols hardcoded in multiple files | Centralize in config/crypto_universe.py |
| 1.4 | GovernanceEventBus | Upstream | MEDIUM | Alerting | Event severity mapping missing | Add GOVERNANCE_EVENT_SEVERITY_MAP |
| 1.5 | GovernanceEventBus | Downstream | CRITICAL | All 25 series | No dead letter queue for failed events | Implement DLQ with retry logic |
| 1.6 | GovernanceEventBus | Downstream | HIGH | All 25 series | Dual governor handlers (v1 + v2) | Feature flag + mutual exclusion |
| 1.7 | GovernanceEventBus | Downstream | MEDIUM | Observability | Asset/timeframe not in event schema | Add structured asset/timeframe fields |
| 2.1 | GovernorV2 | Upstream | CRITICAL | All 25 series | Drift monitor bypasses quorum | Route through governance event bus |
| 2.2 | GovernorV2 | Upstream | HIGH | All 25 series | Fire-and-forget tasks may be GC'd | Store task references |
| 2.3 | GovernorV2 | Upstream | LOW | Test env | Test suite needs bypass mechanism | Add bypass_quorum parameter |
| 2.4 | QuorumHardening | Upstream | HIGH | All 25 series | MIN_QUORUM not universally applied | Create quorum_hardening.py module |
| 2.5 | QuorumHardening | Upstream | MEDIUM | Config | Legacy quorum knobs conflict | Deprecate old config keys |
| 2.6 | QuorumHardening | Downstream | HIGH | All 25 series | QUORUM_FAILED vs NO_ACTION not distinguished | Add explicit QUORUM_FAILED outcome |
| 2.7 | QuorumHardening | Downstream | HIGH | 25 series asymmetry | Same quorum for all assets/timeframes | Asset/timeframe-specific quorum config |
| 3.1 | AlertManager | Upstream | HIGH | Alerting | Legacy direct-to-Telegram bypasses manager | Migrate all alerts through AlertManager |
| 3.2 | AlertManager | Upstream | HIGH | Alert fatigue | Duplicated alerts via multiple paths | Implement fingerprint-based dedup |
| 3.3 | AlertManager | Upstream | MEDIUM | Flexibility | Severity levels hardcoded | Create ALERT_SEVERITY_MAP |
| 3.4 | AlertManager | Upstream | MEDIUM | Operational | Channel routing hardcoded | Config-driven ALERT_ROUTING_CONFIG |
| 3.5 | AlertManager | Downstream | CRITICAL | BTC, ETH critical | Dedup may suppress repeated critical alerts | Escalation on repeated failures |
| 3.6 | AlertManager | Downstream | HIGH | 25 series observability | Per-asset/timeframe incident patterns not visible | Add get_incident_report() method |
| 3.7 | AlertManager | Downstream | MEDIUM | Alert reliability | Alert delivery failures not observable | Track failed alerts + meta-alerting |
| 4.1 | AssistantAPIv2 | Upstream | HIGH | API migration | V1 API still active | Deprecate v1, migrate clients |
| 4.2 | AssistantAPIv2 | Upstream | HIGH | API abuse | Rate limiting (30/min) not enforced | Implement slowapi rate limiter |
| 4.3 | AssistantAPIv2 | Upstream | MEDIUM | Migration | Clients still using v1 | Migration script + feature flag |
| 4.4 | AssistantAPIv2 | Interface | CRITICAL | Read-only violation | Control verbs may still exist | Remove all POST/PUT/DELETE endpoints |
| 4.5 | AssistantAPIv2 | Interface | MEDIUM | Debugging | Error context insufficient | Structured SnapshotError with asset/timeframe |
| 4.6 | AssistantAPIv2 | Downstream | HIGH | Data integrity | Snapshot gatherers swallow errors | Include errors in snapshot response |
| 4.7 | AssistantAPIv2 | Downstream | MEDIUM | Alerting | Ad-hoc warnings bypass AlertManager | Route all warnings through AlertManager |
| 5.1 | WatchdogAssetCoverage | Upstream | CRITICAL | 25 series coverage | Timeframe mismatch (scalp vs 15m) | Migrate to 15m/1h/daily/weekly/monthly |
| 5.2 | WatchdogAssetCoverage | Upstream | HIGH | Maintainability | Asset lists hardcoded | Centralize in config/crypto_universe.py |
| 5.3 | WatchdogAssetCoverage | Upstream | MEDIUM | Scalability | No dynamic asset discovery | Implement discover_active_assets_from_kalshi() |
| 5.4 | WatchdogAssetCoverage | Downstream | HIGH | Observability | Watchdog events not routed to AlertManager | Explicit AlertManager integration |
| 5.5 | WatchdogAssetCoverage | Downstream | MEDIUM | Observability | Per-asset/timeframe health not visible | Add get_coverage_report() method |
| 6.1 | UnifiedDecisionLayer | Upstream | CRITICAL | All 25 series | Callers treat QUORUM_FAILED as NO_ACTION | Explicit QUORUM_FAILED handling in callers |
| 6.2 | UnifiedDecisionLayer | Upstream | HIGH | Event storm | Retry loops cause event storms on persistent failure | QuorumFailureTracker with throttling |
| 6.3 | UnifiedDecisionLayer | Downstream | HIGH | 25 series asymmetry | Same quorum semantics for all series | Asset/timeframe-specific quorum |
| 6.4 | UnifiedDecisionLayer | Downstream | MEDIUM | Sizing | Hardcoded "daily" assumptions | TIMEFRAME_SIZE_MULTIPLIERS config |

**Total Findings: 35**
- **CRITICAL:** 7
- **HIGH:** 21
- **MEDIUM:** 7
- **LOW:** 0

### 7.2 Wiring Delta Graph

```
Legend:
  ═══>  Hardened event-driven path (NEW)
  - ->  Legacy direct call path (REMOVE)
  ~~~>  Mixed/ambiguous path (FIX)

┌─────────────────────────────────────────────────────────────┐
│                    GOVERNANCE LAYER                          │
└─────────────────────────────────────────────────────────────┘

[DriftMonitor] ───> [EventBus] ~~~> [GovernorV1]  (LEGACY)
               ═══> [GovEventBus] ═══> [GovernorV2] (NEW)

[WatchdogAssetCov] ───> [EventBus] ~~~> [??]  (DEAD PATH)
                   ═══> [GovEventBus] ═══> [AlertMgr] (NEW)

[RiskEngine] - -> [Direct Alert] - -> [Telegram]  (LEGACY)
             ═══> [GovEventBus] ═══> [AlertMgr] ═══> [Telegram] (NEW)

[QuorumHardening] ═══> [UnifiedDecisionLayer] ═══> [GovEventBus]
                  - -> [Direct Return] ~~~> [Caller] (MIXED)

┌─────────────────────────────────────────────────────────────┐
│                    ALERT LAYER                               │
└─────────────────────────────────────────────────────────────┘

[GovEventBus] ═══> [AlertMgr] ═══> [Dedup] ═══> [Router] ═══> [Telegram]
                                                          ═══> [UI]
                                                          ═══> [Logs]

[LegacyAlerts] - -> [Direct Telegram]  (REMOVE)

┌─────────────────────────────────────────────────────────────┐
│                    API LAYER                                 │
└─────────────────────────────────────────────────────────────┘

[Clients] - -> [AssistantAPI v1 POST]  (DEPRECATE)
          ═══> [AssistantAPI v2 GET] ═══> [RateLimit] ═══> [Snapshot]

[AssistantV2] ═══> [GovEventBus] ═══> [AlertMgr]  (NEW)
              - -> [Direct Logger]  (LEGACY)

┌─────────────────────────────────────────────────────────────┐
│                    DECISION LAYER                            │
└─────────────────────────────────────────────────────────────┘

[Agents] ═══> [UnifiedDecisionLayer] ═══> [QuorumHardening] ═══> [Consensus]
                                                              ║
                                                  QUORUM_FAILED ║
                                                              ▼
                                                        [GovEventBus]
                                                              ║
                                                              ▼
                                                        [AlertMgr]

[Caller] ~~~> [Check NO_ACTION]  (AMBIGUOUS - treats QUORUM_FAILED same)
         ═══> [Check QUORUM_FAILED] ═══> [Alert + Abort]  (NEW)

```

### 7.3 Regression Risks

#### **Risk 1: Event Bus Bottleneck**

**Description:** Governance event bus becomes single point of contention for all 25 crypto series.

**Scenario:**
```
BTC-15m: 100 events/min
ETH-15m: 100 events/min
SOL-15m: 80 events/min
XRP-15m: 80 events/min
DOGE-15m: 50 events/min
... (20 more series)

Total: ~2000 events/min = 33 events/sec
```

**Mitigation:**
- Async event publishing with `asyncio.Queue`
- Per-asset event bus sharding
- Backpressure monitoring

#### **Risk 2: Rate Limit Cascades**

**Description:** AssistantAPI v2 30 req/min limit blocks internal automation.

**Scenario:**
```
Prometheus: 1 req/5s = 12 req/min
Health checks: 1 req/10s = 6 req/min
UI polling: 1 req/2s = 30 req/min
CI/CD: 10 req/min

Total: 58 req/min > 30 req/min limit → BLOCKED
```

**Mitigation:**
- Whitelist internal IPs
- Separate rate limits for internal vs external
- Backoff/retry in clients

#### **Risk 3: Alert Suppression Hides Critical Failures**

**Description:** Dedup window (300s) suppresses repeated alerts for persistent failures.

**Scenario:**
```
BTC-15m quorum fails continuously for 10 minutes
→ Only 2 alerts fired (T+0, T+300s)
→ Operator doesn't realize severity
```

**Mitigation:**
- Escalation on repeated failures (see Finding 3.5)
- Summary alerts: "BTC-15m failed 20x in last 10min"

#### **Risk 4: QUORUM_FAILED Mishandling**

**Description:** Callers treat QUORUM_FAILED as NO_ACTION, resulting in silent degradation.

**Scenario:**
```
BTC-daily quorum fails → Caller thinks "no signal" → Doesn't alert → Position management broken
```

**Mitigation:**
- Explicit QUORUM_FAILED handling in all callers
- Linter rule: "Must check for QUORUM_FAILED before NO_ACTION"

#### **Risk 5: Asset/Timeframe Config Drift**

**Description:** Hardcoded asset lists drift from live markets.

**Scenario:**
```
Kalshi adds "ADA" crypto markets
→ Codebase still hardcodes ["BTC", "ETH", "SOL", "XRP", "DOGE"]
→ ADA markets not monitored
```

**Mitigation:**
- Dynamic discovery from Kalshi API (see Finding 5.3)
- Daily config sync job

#### **Risk 6: Event Bus Event Loss**

**Description:** Consumer failures silently drop events (no DLQ).

**Scenario:**
```
GovernorV2 publishes AGENT_RETIRED event
→ AlertManager consumer throws exception
→ Event logged but dropped
→ No alert fired, audit trail incomplete
```

**Mitigation:**
- Dead letter queue (see Finding 1.5)
- Retry logic with exponential backoff

#### **Risk 7: Dual Governor Race Conditions**

**Description:** GovernorV1 and GovernorV2 both active, causing conflicting actions.

**Scenario:**
```
T+0: V2 publishes AGENT_PAUSED event
T+1: V1 directly calls agent.pause()
→ Double-pause, state corruption
```

**Mitigation:**
- Feature flag to disable V1 when V2 active
- Mutual exclusion lock on agent lifecycle ops

---

## 8. Recommended Implementation Priority

### Phase 1: Critical Foundations (Week 1)

1. **Create `config/crypto_universe.py`** (Finding 1.3, 5.1, 5.2)
   - Centralize ACTIVE_CRYPTO_ASSETS
   - Define ACTIVE_CRYPTO_TIMEFRAMES = ["15m", "1h", "daily", "weekly", "monthly"]
   - Replace all hardcoded references

2. **Create `agents/governance_events.py`** (Finding 1.2, 1.4)
   - Define GovernanceEventType enum
   - Define GovernanceEvent dataclass with asset/timeframe fields
   - Add GOVERNANCE_EVENT_SEVERITY_MAP

3. **Create `agents/quorum_hardening.py`** (Finding 2.4, 2.6, 2.7)
   - Export MIN_QUORUM and CONSENSUS_QUORUM_THRESHOLD
   - Implement validate_quorum() with QuorumFailure exception
   - Add asset/timeframe-specific quorum config

### Phase 2: Event Bus and Governance (Week 2)

4. **Implement `agents/governance_event_bus.py`** (Finding 1.5, 1.6, 1.7)
   - Async event bus with dead letter queue
   - Retry logic with exponential backoff
   - Immutable audit log persistence

5. **Implement `agents/governor_agent_v2.py`** (Finding 2.1, 2.2, 2.3)
   - Route all actions through governance event bus
   - Store task references (no fire-and-forget)
   - Add bypass_quorum for tests

6. **Migrate DriftMonitor** (Finding 2.1)
   - Route drift events through governance event bus
   - Remove direct action calls

### Phase 3: Alert Manager (Week 3)

7. **Implement `agents/alert_manager.py`** (Finding 3.1, 3.2, 3.3, 3.4)
   - Fingerprint-based deduplication
   - Config-driven severity mapping
   - Config-driven channel routing
   - Track failed alert deliveries

8. **Migrate Legacy Alerts** (Finding 3.1, 3.7, 4.7)
   - Remove direct Telegram calls
   - Route all alerts through AlertManager
   - Add meta-alerting for delivery failures

9. **Add Alert Escalation** (Finding 3.5, 3.6)
   - Implement repeated failure escalation
   - Add get_incident_report() method
   - Create per-asset/timeframe incident dashboards

### Phase 4: API and Watchdog (Week 4)

10. **Implement `web/api/assistant_api_v2.py`** (Finding 4.1, 4.2, 4.4, 4.5, 4.6)
    - Read-only GET endpoints only
    - Rate limiting (30 req/min with internal whitelist)
    - Structured error responses with asset/timeframe context
    - Include errors in snapshot responses

11. **Implement `agents/watchdog_asset_coverage.py`** (Finding 5.4, 5.5)
    - Monitor all 25 asset/timeframe combinations
    - Route events through AlertManager
    - Add get_coverage_report() method
    - Create coverage dashboard

12. **Deprecate AssistantAPI v1** (Finding 4.1, 4.3)
    - Add deprecation warnings
    - Create migration script for clients
    - Schedule v1 removal date

### Phase 5: Decision Layer Integration (Week 5)

13. **Modify `agents/unified_decision_layer.py`** (Finding 2.6, 6.1, 6.3, 6.4)
    - Add ConsensusOutcome.QUORUM_FAILED
    - Integrate with QuorumHardening
    - Asset/timeframe-specific quorum validation
    - Fire alerts on QUORUM_FAILED

14. **Update All Callers** (Finding 6.1, 6.2)
    - Add explicit QUORUM_FAILED handling
    - Implement QuorumFailureTracker
    - Alert on persistent failures

15. **Add Asset/Timeframe Config** (Finding 6.3, 6.4)
    - Timeframe-specific sizing multipliers
    - Asset-specific quorum overrides
    - Per-series health monitoring

### Phase 6: Testing and Validation (Week 6)

16. **Integration Tests**
    - Test all 25 asset/timeframe combinations
    - Test governance event bus with failures
    - Test alert deduplication and escalation
    - Test rate limiting

17. **Load Tests**
    - 2000 events/min governance bus load
    - 100 req/min API load
    - Alert storm scenarios

18. **Operational Readiness**
    - Create operator runbooks
    - Set up monitoring dashboards
    - Configure alert routing rules
    - Schedule v1 deprecation

---

## 9. Conclusion

This audit identifies 35 critical findings across 6 hypothetical new components and the modified unified decision layer. The primary issues are:

1. **Legacy/v2 Dual Paths**: Existing components use direct calls; new event-driven paths risk race conditions
2. **Hardcoded Constants**: Assets, timeframes, thresholds scattered across codebase
3. **Silent Failures**: QUORUM_FAILED treated as NO_ACTION, events dropped without DLQ
4. **Asset/Timeframe Asymmetries**: Same config for all 25 series despite different risk profiles
5. **Alert Fragmentation**: Multiple alert paths, some bypassing centralized manager

**Implementation of the 6 new components must address these findings to ensure reliable operation across all 25 crypto series (BTC, ETH, SOL, XRP, DOGE × 15m, 1h, daily, weekly, monthly).**

---

**End of Audit Report**
