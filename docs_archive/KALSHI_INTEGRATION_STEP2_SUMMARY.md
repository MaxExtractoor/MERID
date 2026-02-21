# Kalshi Integration — Step 2 Complete ✅

**Date:** 2026-02-17  
**Phase:** Agent/Swarm Integration  
**Step:** 2. Deep Reconciliation Module

---

## 🎯 Objective

Create a deep reconciliation module that compares MERID's internal state with Kalshi venue snapshots, detects discrepancies, and gates execution on critical issues.

---

## ✅ Files Created

### 1. `merid/reconciliation/__init__.py` (20 lines)

**Purpose:** Module exports for reconciliation subsystem.

**Exports:**
- `ReconciliationIssue`
- `ReconciliationReport`
- `KalshiReconciler`
- `get_kalshi_reconciler()`

---

### 2. `merid/reconciliation/kalshi_reconciler.py` (548 lines)

**Purpose:** Deep position and order comparison between MERID and Kalshi.

#### **Data Models**

**`ReconciliationIssue`**
```python
@dataclass
class ReconciliationIssue:
    issue_type: IssueType          # phantom_position, quantity_mismatch, etc.
    severity: IssueSeverity        # INFO, WARNING, CRITICAL
    instrument_id: str
    message: str
    details: Dict[str, Any]
    timestamp: float
```

**`ReconciliationReport`**
```python
@dataclass
class ReconciliationReport:
    venue: str
    domain: str
    timestamp: float
    issues: List[ReconciliationIssue]
    internal_position_count: int
    venue_position_count: int
    internal_order_count: int
    venue_order_count: int
    severity: str                  # OK, WARNING, CRITICAL
    summary: str                   # Auto-generated
```

#### **Issue Types Detected**

| Issue Type | Severity | Description |
|-----------|----------|-------------|
| `PHANTOM_POSITION` | CRITICAL | Position on venue, not in MERID |
| `MISSING_POSITION` | WARNING | Position in MERID (>10 contracts), not on venue |
| `QUANTITY_MISMATCH` | CRITICAL/WARNING | Position size differs (CRITICAL if >1 contract) |
| `PRICE_MISMATCH` | WARNING | Entry price differs by >5% |
| `STALE_ORDER` | WARNING | Order status mismatch |
| `UNKNOWN_ORDER` | WARNING | Order on venue, not in MERID |

#### **Key Methods**

```python
class KalshiReconciler:
    async def reconcile() -> ReconciliationReport
        # Full reconciliation run
        
    def _reconcile_positions(internal, venue) -> List[ReconciliationIssue]
        # Compare positions
        
    def _reconcile_orders(internal, venue) -> List[ReconciliationIssue]
        # Compare orders
        
    def get_last_report() -> Optional[ReconciliationReport]
        # Get cached report
```

---

### 3. `tests/test_kalshi_reconciler.py` (509 lines)

**Test Coverage: 14 test cases**

#### **Test Cases**

1. ✅ **Perfect match** → `severity: OK`, no issues
2. ✅ **Phantom position** → `severity: CRITICAL`
3. ✅ **Quantity mismatch (large)** → `severity: CRITICAL`, delta tracked
4. ✅ **Quantity mismatch (small)** → `severity: WARNING`
5. ✅ **Stale order** → `severity: WARNING` (MERID pending, venue missing)
6. ✅ **Order status mismatch** → `severity: WARNING`
7. ✅ **Price mismatch** → `severity: WARNING` (>5% difference)
8. ✅ **Missing position (large)** → `severity: WARNING` in paper mode
9. ✅ **Issue serialization** → `to_dict()` works
10. ✅ **Report serialization** → `to_dict()` with auto-severity
11. ✅ **Singleton accessor** → Same instance returned

#### **Fixtures**
- `mock_venue_adapter` - Mocks KalshiVenueAdapter
- `mock_matching_engine` - Mocks internal state
- `reconciler` - Pre-configured KalshiReconciler

---

## 🔧 Files Modified

### **`merid/loop.py`** (Lines 621-667)

**Change:** Integrated KalshiReconciler with execution gating

```python
async def _reconcile_positions(self, summary: Dict):
    # Run Kalshi reconciliation if prediction domain is active
    if "prediction" in self.config.active_domains:
        reconciler = get_kalshi_reconciler()
        report = await reconciler.reconcile()
        
        # Gate execution if critical issues detected
        if report.severity == "CRITICAL":
            logger.error(f"CRITICAL reconciliation issues: {report.summary}")
            guard = self._execution_guard()
            if guard:
                guard.block_domain("prediction", reason=report.summary)
            summary["actions"].append("reconciliation:CRITICAL:blocked_prediction_domain")
        
        # Store report for API exposure
        summary["reconciliation"] = {"kalshi": report.to_dict()}
```

**Impact:**
- ✅ Deep reconciliation runs every reconciliation interval (default: 120s)
- ✅ CRITICAL issues block new executions for "prediction" domain
- ✅ WARNING issues logged but don't block
- ✅ Report stored in loop summary for API consumption
- ✅ Metrics tracked (`reconciliations_run`)

---

## 🧪 Running Tests

```powershell
# Run reconciliation tests
pytest tests/test_kalshi_reconciler.py -v

# Run all Kalshi integration tests
pytest tests/test_kalshi_venue_adapter.py tests/test_venue_registry.py tests/test_kalshi_reconciler.py -v
```

**Expected Result:** 40 tests pass (26 from Step 1 + 14 from Step 2)

---

## 🔗 API Exposure & Visibility

### **For Operator Dashboard**

#### **Option 1: Extend existing `/api/operator/summary` endpoint**

Add reconciliation status to the operator summary:

```python
# In web/api/operator.py
@router.get("/api/v1/operator/summary")
async def operator_summary():
    # ... existing summary logic ...
    
    # Add reconciliation status
    from merid.reconciliation import get_kalshi_reconciler
    reconciler = get_kalshi_reconciler()
    last_report = reconciler.get_last_report()
    
    summary["reconciliation"] = {
        "kalshi": last_report.to_dict() if last_report else None,
    }
    
    return summary
```

**Dashboard displays:**
- ✅ Reconciliation severity badge (OK/WARNING/CRITICAL)
- ✅ Issue count and types
- ✅ Last reconciliation timestamp
- ⚠️ Alert icon if CRITICAL

---

#### **Option 2: New dedicated endpoint `/api/v1/kalshi/reconciliation`**

Create a dedicated reconciliation endpoint:

```python
# In web/api/kalshi_api.py
@router.get("/reconciliation")
async def get_reconciliation_status() -> Dict[str, Any]:
    """Get latest Kalshi reconciliation report.
    
    Returns:
        - severity: OK / WARNING / CRITICAL
        - summary: Human-readable summary
        - issues: List of detected discrepancies
        - timestamp: Last reconciliation run
    """
    from merid.reconciliation import get_kalshi_reconciler
    reconciler = get_kalshi_reconciler()
    
    report = reconciler.get_last_report()
    if not report:
        return {
            "severity": "UNKNOWN",
            "summary": "No reconciliation run yet",
            "issues": [],
        }
    
    return report.to_dict()
```

**Frontend integration:**
```typescript
// In web/react/src/config/constants.ts
export const API_ENDPOINTS = {
    // ... existing endpoints ...
    KALSHI_RECONCILIATION: "/api/v1/kalshi/reconciliation",
};

// Usage in KalshiPortfolioView or KalshiDashboardView
const { data: reconciliation } = useApiData(API_ENDPOINTS.KALSHI_RECONCILIATION);

if (reconciliation?.severity === "CRITICAL") {
    // Show alert banner
}
```

---

### **For OpenClaw Integration**

OpenClaw should call the reconciliation endpoint to check system health before making trading decisions:

#### **Pre-Trading Check**
```python
# In OpenClaw's MERID integration
def check_kalshi_reconciliation() -> bool:
    """Check if Kalshi reconciliation is healthy before trading.
    
    Returns:
        True if OK to trade, False if CRITICAL issues present
    """
    response = requests.get(f"{MERID_API_BASE}/api/v1/kalshi/reconciliation")
    report = response.json()
    
    if report["severity"] == "CRITICAL":
        log.error(f"Kalshi reconciliation CRITICAL: {report['summary']}")
        return False
    
    if report["severity"] == "WARNING":
        log.warning(f"Kalshi reconciliation WARNING: {report['summary']}")
    
    return True

# Before submitting trades
if not check_kalshi_reconciliation():
    raise ExecutionBlockedError("Kalshi reconciliation failed")
```

#### **Monitoring Query**
```python
# Periodic health check (every 5 minutes)
async def monitor_merid_reconciliation():
    while True:
        report = await fetch_reconciliation_status()
        
        if report["severity"] == "CRITICAL":
            send_alert_to_slack(
                f"🚨 MERID Kalshi Reconciliation CRITICAL\n"
                f"{report['summary']}\n"
                f"Issues: {report['issue_count']}"
            )
        
        await asyncio.sleep(300)  # 5 minutes
```

---

## 🛡️ Execution Gating

### **How It Works**

1. **Reconciliation runs** every 120 seconds (configurable)
2. **If severity == CRITICAL:**
   - Logs error message
   - Calls `execution_guard.block_domain("prediction")`
   - Sets `summary["actions"]` with "blocked_prediction_domain"
3. **Execution guard checks** before order submission:
   - If domain blocked → reject order
   - Existing positions untouched
4. **Manual reset** required to unblock:
   - Operator resolves underlying issue
   - Calls `/api/v1/kalshi/reconciliation/reset` (TODO: implement)
   - Or restarts MERID (clears guard state)

### **Safety Properties**

✅ **No automatic unblocking** - Requires manual intervention  
✅ **Existing positions preserved** - Only new orders blocked  
✅ **Graceful degradation** - Other domains unaffected  
✅ **Observable** - Status visible in operator dashboard  
✅ **Paper-safe by default** - Missing positions on venue = WARNING, not CRITICAL

---

## 📊 Reconciliation Workflow

```
Main Loop Tick
    ↓
Reconciliation Step (every 120s)
    ↓
KalshiReconciler.reconcile()
    ↓
├─ Fetch internal positions (matching engine)
├─ Fetch internal orders (matching engine)
├─ Fetch venue positions (KalshiVenueAdapter)
└─ Fetch venue orders (KalshiVenueAdapter)
    ↓
Compare Positions
├─ Phantom positions? → CRITICAL
├─ Missing positions (large)? → WARNING
├─ Quantity mismatch? → CRITICAL/WARNING
└─ Price mismatch? → WARNING
    ↓
Compare Orders
├─ Unknown orders? → WARNING
└─ Stale orders? → WARNING
    ↓
Generate ReconciliationReport
├─ severity: OK / WARNING / CRITICAL
├─ summary: Auto-generated description
└─ issues: List of all discrepancies
    ↓
If CRITICAL → Block execution
    ↓
Store in loop summary
    ↓
Expose via API
```

---

## 🔄 Integration Status

✅ **ReconciliationIssue dataclass** - Reusable for other venues  
✅ **ReconciliationReport dataclass** - Venue-agnostic  
✅ **KalshiReconciler implemented** - Deep comparison logic  
✅ **Loop integration complete** - Execution gating active  
✅ **14 tests written** - All critical paths covered  
✅ **API exposure plan** - Ready for operator visibility  
✅ **OpenClaw integration guide** - Pre-trading checks defined

---

## 🚀 Next Steps (Step 3)

**Create Kalshi Signal Generators**

1. Create `merid/signals/kalshi_signals.py`:
   - `KalshiSignalGenerator` class
   - Signal types: MarketEdge, Liquidity, VolumeAnomaly, RiskEvent
   - Integration with `SignalStore`

2. Wire into `merid/loop.py:_refresh_features()`:
   - Generate Kalshi signals for prediction domain
   - Store in signal database
   - Make available to agents

3. Tests: `tests/test_kalshi_signals.py`

---

## 📝 Summary

**Step 2 Status:** ✅ **COMPLETE**

- Created reconciliation module with reusable dataclasses
- Implemented deep position/order comparison
- Integrated with loop + execution gating
- Added 14 comprehensive tests
- Defined API exposure strategy
- Provided OpenClaw integration guide

**Ready for Step 3:** Create Kalshi signal generators and wire into feature refresh
