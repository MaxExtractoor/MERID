# MERID Production Stack Logging Audit Report

**Generated:** 2026-07-07  
**Scope:** Production 15M Kalshi Crypto Trading Stack  
**Auditor:** Cascade AI Assistant

---

## Executive Summary

This audit analyzed the production stack's logging infrastructure to identify flaws, inconsistencies, and areas requiring improvement for better observability, debugging, and operational excellence.

**Key Findings:**
- **Inconsistent logging patterns** across modules (mix of `get_logger()`, `logging.getLogger()`, and `print()`)
- **Diagnostic noise** polluting production logs with CRITICAL DIAGNOSTIC markers
- **Missing context** in risk-critical logs (window tracking, exposure, halt events)
- **Poor explainability** in error messages (lacking causal context)
- **Silent failures** with minimal or no logging
- **Lack of structured logging** (key-value pairs, correlation IDs)
- **No correlation IDs** for transaction tracing across components

---

## Critical Issues Requiring Immediate Attention

### 1. Print Statement Pollution in Production Code

**Location:** `web/main_15m_lean.py` (lines 6-10, 42, 47, 53, 62, 73, 91, etc.)

**Issue:** Extensive use of `print()` statements for diagnostic output instead of proper logging.

**Example:**
```python
print("[MODULE-IMPORT] main_15m_lean.py imported", file=sys.stderr, flush=True)
print("[SINGLETON-RESET] Resetting singletons for clean startup", file=sys.stderr, flush=True)
```

**Impact:**
- Bypasses log management infrastructure
- No log level control (always outputs)
- Cannot be filtered or aggregated
- Pollutes stderr with diagnostic noise
- Inconsistent with production logging standards

**Recommendation:**
Replace all `print()` statements with `logger.debug()` for diagnostics and `logger.info()` for operational events:
```python
logger.debug("[MODULE-IMPORT] main_15m_lean.py imported")
logger.info("[SINGLETON-RESET] Resetting singletons for clean startup")
```

---

### 2. Diagnostic Noise in Production Logs

**Location:** `web/main_15m_lean.py` (lines 6, 26, 27, 30, 36, 42, 46, 56, etc.)

**Issue:** CRITICAL DIAGNOSTIC markers polluting production logs.

**Example:**
```python
# CRITICAL DIAGNOSTIC: Write to file to verify execution
try:
    import time
    Path("c:\\Dev\\MERID\\main_15m_execution_marker.txt").write_text(f"EXECUTED: {time.time()}")
except:
    pass

# CRITICAL DIAGNOSTIC: Immediate log to verify this code runs
logger.info("[MAIN-15M-LEAN] FIRST LINE OF FILE - EXECUTING")
```

**Impact:**
- Unnecessary noise in production logs
- File I/O blocking during startup
- No cleanup of diagnostic files
- Confuses operational monitoring

**Recommendation:**
- Remove diagnostic file writes
- Use dedicated debug log level for diagnostics
- Implement feature flags to enable diagnostics only in dev/test
- Clean up all CRITICAL DIAGNOSTIC comments

---

### 3. Missing Context in Risk-Critical Logs

**Location:** `merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py`

**Issue:** Window tracking and risk limit logs lack sufficient context for debugging.

**Example:**
```python
logger.warning(
    f"[WINDOW-TRACKING] FORCE RESET at ts={current_ts:.0f} - stale exposure cleared"
)
```

**Missing Context:**
- Which agent triggered the reset
- What was the stale exposure value
- Why it became stale
- What positions were affected

**Recommendation:**
Add comprehensive context to risk-critical logs:
```python
logger.warning(
    f"[WINDOW-TRACKING] FORCE RESET at ts={current_ts:.0f} - "
    f"agent={agent_id} stale_exposure=${stale_exposure:.2f} "
    f"current_positions={position_count} reason={reset_reason}"
)
```

---

### 4. Poor Error Explainability

**Location:** Multiple files across the stack

**Issue:** Error logs lack causal context, making root cause analysis difficult.

**Examples:**
```python
# merid/risk/profiles/crypto_15m_profile.py
logger.warning(f"[UNIFIED-SIZING] Failed to read fractional_contract_override_threshold: {s}")

# merid/event_venues/kalshi/ws_bridge.py
logger.error("[WS-AUTO-RECONNECT] Catalog API error: %s", ae)
```

**Missing Context:**
- Why the operation failed
- What was being attempted
- What recovery actions were taken
- Impact on system state

**Recommendation:**
Add causal context to all error logs:
```python
logger.error(
    "[WS-AUTO-RECONNECT] Catalog API error during reconnection attempt %d/%d: %s. "
    "Recovery: falling back to cached subscriptions. Impact: %d tickers may be stale.",
    attempt, max_attempts, ae, len(saved_subscriptions)
)
```

---

## High Severity Issues

### 5. Inconsistent Logger Initialization

**Locations:** 
- `web/main_15m_lean.py`: Uses `get_logger("web.main_15m_lean")`
- `merid/risk/profiles/crypto_15m_profile.py`: Uses `logging.getLogger(__name__)`
- `merid/prediction/unified_sizing.py`: Uses `get_logger("merid.prediction.unified_sizing")`

**Issue:** Mix of `get_logger()` and `logging.getLogger()` creates inconsistent log configuration.

**Impact:**
- Some logs bypass custom log formatting
- Inconsistent log levels across modules
- Difficult to configure logging centrally
- Potential for missing logs in production

**Recommendation:**
Standardize on `get_logger()` from `utils.logger` across all production modules:
```python
from utils.logger import get_logger
logger = get_logger("module.path.here")
```

---

### 6. Lack of Structured Logging

**Location:** All modules

**Issue:** Most logs use string formatting instead of structured key-value pairs.

**Example:**
```python
logger.info(f"[WINDOW-TRACKING] Recorded execution: agent={agent_id} notional=${order_notional_usd:.2f}")
```

**Impact:**
- Difficult to parse logs programmatically
- Cannot query logs by specific fields
- No log aggregation benefits
- Limited observability tooling support

**Recommendation:**
Implement structured logging with key-value pairs:
```python
logger.info(
    "[WINDOW-TRACKING] Recorded execution",
    extra={
        "agent_id": agent_id,
        "order_notional_usd": order_notional_usd,
        "window_start_ts": window_start_ts,
        "total_exposure_usd": total_exposure_usd
    }
)
```

---

### 7. Missing Correlation IDs

**Location:** All modules

**Issue:** No correlation IDs for tracing transactions across components.

**Impact:**
- Cannot trace a single order through the system
- Difficult to debug distributed issues
- No way to correlate logs across services
- Limited root cause analysis capability

**Recommendation:**
Implement correlation ID propagation:
```python
import uuid

# Generate at entry point
correlation_id = str(uuid.uuid4())

# Pass through call stack
logger.info("Processing order", extra={"correlation_id": correlation_id, "order_id": order_id})

# Include in all related logs
logger.info("Order executed", extra={"correlation_id": correlation_id, "status": "filled"})
```

---

## Medium Severity Issues

### 8. Inconsistent Log Level Usage

**Location:** Multiple files

**Issue:** Inappropriate log level usage (e.g., using INFO for errors, DEBUG for operational events).

**Examples:**
```python
# Using WARNING for operational info
logger.warning("[UNIFIED-SIZING] Profile adapter not available, using hardcoded values")

# Using INFO for what should be DEBUG
logger.debug("[WS-DEBUG-LOCK] Creating new asyncio.Lock for start_lock")
```

**Recommendation:**
Define and enforce log level policy:
- **DEBUG**: Detailed diagnostics for development
- **INFO**: Operational events (startup, shutdown, normal operations)
- **WARNING:** Degraded but functional (fallbacks, retries)
- **ERROR:** Failures requiring attention (API errors, validation failures)
- **CRITICAL:** System-impacting failures (halt, circuit breaker, data loss)

---

### 9. Missing Business Context

**Location:** Trading and risk modules

**Issue:** Logs lack business impact information.

**Example:**
```python
logger.info("[WINDOW-TRACKING] Recorded execution: agent={agent_id} notional=${order_notional_usd:.2f}")
```

**Missing Context:**
- What % of bankroll this represents
- How close to risk limits
- Expected PnL impact
- Market conditions at time of execution

**Recommendation:**
Add business context to trading logs:
```python
logger.info(
    "[WINDOW-TRACKING] Recorded execution",
    extra={
        "agent_id": agent_id,
        "order_notional_usd": order_notional_usd,
        "bankroll_pct": (order_notional_usd / bankroll_usd) * 100,
        "distance_to_limit_pct": ((limit_usd - current_exposure_usd) / limit_usd) * 100,
        "market_regime": current_regime,
        "volatility_percentile": volatility_percentile
    }
)
```

---

### 10. Silent Exception Handling

**Location:** Multiple files (e.g., `web/main_15m_lean.py` lines 9, 55, 65, 76)

**Issue:** Exception handlers with `pass` or minimal logging.

**Example:**
```python
try:
    import time
    Path("c:\\Dev\\MERID\\main_15m_execution_marker.txt").write_text(f"EXECUTED: {time.time()}")
except:
    pass
```

**Impact:**
- Failures go undetected
- No debugging information
- Cannot monitor system health
- Silent data corruption possible

**Recommendation:**
Always log exceptions:
```python
try:
    import time
    Path("c:\\Dev\\MERID\\main_15m_execution_marker.txt").write_text(f"EXECUTED: {time.time()}")
except Exception as e:
    logger.warning("Failed to write execution marker: %s", e)
```

---

## Low Severity Issues

### 11. Inconsistent Log Message Formatting

**Location:** All modules

**Issue:** Mix of formats: `[PREFIX] message`, `PREFIX: message`, `message`, f-strings, % formatting.

**Examples:**
```python
logger.info("[MAIN-15M-LEAN] FIRST LINE OF FILE - EXECUTING")
logger.info(f"[WINDOW-TRACKING] Recorded execution: agent={agent_id}")
logger.warning("[UNIFIED-SIZING] Profile adapter not available, using hardcoded values")
logger.error("[WS-AUTO-RECONNECT] Catalog API error: %s", ae)
```

**Recommendation:**
Standardize log message format:
```python
logger.info("[COMPONENT] Action description", extra={"key": "value"})
```

---

### 12. Verbose Startup Logging

**Location:** `web/main_15m_lean.py`

**Issue:** Excessive logging during startup makes it difficult to identify real issues.

**Example:** 50+ log statements during startup sequence

**Recommendation:**
- Group related startup phases into single log entries
- Use DEBUG level for detailed startup steps
- Use INFO level only for major milestones
- Implement startup progress tracking

---

## Recommendations for Robust Logging

### 1. Implement Centralized Logging Configuration

Create `utils/logging_config.py`:
```python
import logging
import sys
from pathlib import Path

def setup_logging(log_level: str = "INFO", log_file: Path = None):
    """Configure centralized logging for MERID."""
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [%(correlation_id)s] - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        handlers=handlers,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
```

### 2. Create Logging Utilities

Create `utils/structured_logger.py`:
```python
import logging
from contextvars import ContextVar
from typing import Dict, Any

correlation_id_var: ContextVar[str] = ContextVar('correlation_id', default='')

class StructuredLogger:
    """Logger with structured logging support."""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
    
    def info(self, message: str, **kwargs):
        """Log with structured context."""
        extra = kwargs.copy()
        extra['correlation_id'] = correlation_id_var.get('')
        self.logger.info(message, extra=extra)
    
    # Similar methods for debug, warning, error, critical
```

### 3. Define Logging Standards Document

Create `docs/LOGGING_STANDARDS.md`:
```markdown
# MERID Logging Standards

## Log Level Policy
- DEBUG: Development diagnostics
- INFO: Operational events
- WARNING: Degraded but functional
- ERROR: Failures requiring attention
- CRITICAL: System-impacting failures

## Required Context
- All trading logs: asset, order_id, notional, timestamp
- All risk logs: exposure, limits, distance_to_limit
- All error logs: cause, impact, recovery_action

## Structured Logging
- Use key-value pairs for all contextual data
- Include correlation IDs for transaction tracing
- Use consistent field names across modules
```

### 4. Implement Log Aggregation

- Centralize log collection (ELK stack, CloudWatch, etc.)
- Implement log search and filtering
- Add alerting on critical patterns
- Create dashboards for operational monitoring

### 5. Add Log Testing

Create `tests/test_logging.py`:
```python
def test_risk_critical_logs_have_context():
    """Ensure all risk-critical logs include required context."""
    # Scan code for risk-critical log calls
    # Verify they include: asset, exposure, limits, reason
    pass

def test_error_logs_have_causal_context():
    """Ensure all error logs explain why the error occurred."""
    # Scan for error log calls
    # Verify they include causal context
    pass
```

---

## Implementation Priority

### Phase 1 (Immediate - This Week)
1. Remove all `print()` statements from production code
2. Remove CRITICAL DIAGNOSTIC markers and file writes
3. Add context to all risk-critical logs
4. Standardize on `get_logger()` across all modules

### Phase 2 (Short-term - Next 2 Weeks)
1. Implement correlation ID propagation
2. Add causal context to all error logs
3. Create logging standards document
4. Implement centralized logging configuration

### Phase 3 (Medium-term - Next Month)
1. Implement structured logging with key-value pairs
2. Add business context to trading logs
3. Implement log aggregation infrastructure
4. Create logging tests

### Phase 4 (Long-term - Next Quarter)
1. Implement log-based alerting
2. Create operational dashboards
3. Implement log-based metrics
4. Add ML-based anomaly detection on logs

---

## Conclusion

The MERID production stack has a solid foundation with logging present throughout the codebase. However, inconsistencies, missing context, and poor explainability limit its effectiveness for debugging and operational monitoring.

By implementing the recommendations in this report, the system will achieve:
- **Better observability** through structured, contextual logs
- **Faster debugging** through correlation IDs and causal context
- **Improved operational excellence** through centralized log management
- **Enhanced reliability** through better error detection and alerting

The audit script (`scripts/logging_audit.py`) can be run periodically to ensure logging standards are maintained as the codebase evolves.
