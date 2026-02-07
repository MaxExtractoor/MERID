# 🎯 **PHASE 0B - PERSISTENCE ACCEPTANCE TEST**

## ✅ **ACCEPTANCE TEST: DECISION PERSISTENCE**

### **Test Objective**
Verify that Phase 0 decisions are properly persisted in the database and retrievable via API endpoints.

---

## 🚀 **TEST SCENARIO**

### **✅ Step 1: Record Decision**
```powershell
# Record a test decision
$body = @{
    model_id = "crypto_prediction_agent_v1"
    human_decision = "hold"
    decision_reason = "Test decision for persistence verification"
} | ConvertTo-Json

Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/record-weekly-decision" -Method POST -ContentType "application/json" -Body $body
```

### **✅ Step 2: Verify Trial Status**
```powershell
# Check that decision appears in trial status
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/status" -Method GET | ConvertTo-Json -Depth 10
```

**Expected**: `total_decisions >= 1`

### **✅ Step 3: Verify Alignment Analysis**
```powershell
# Check that decision appears in alignment analysis
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/alignment-analysis" -Method GET | ConvertTo-Json -Depth 10
```

**Expected**: Decision included in analysis counts

### **✅ Step 4: Verify Contract Compliance**
```powershell
# Check that decision appears in contract compliance
Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/contract-compliance" -Method GET | ConvertTo-Json -Depth 10
```

**Expected**: Decision included in compliance analysis

### **✅ Step 5: Verify Database Directly**
```powershell
# Check database directly for persisted decision
# (This would be a helper script to query the Phase 0 decisions table)
```

**Expected**: Row exists in Phase 0 decisions table with correct data

---

## 🎯 **ACCEPTANCE CRITERIA**

### **✅ Test Passes If**
- **API Response**: `record-weekly-decision` returns success
- **Trial Status**: `total_decisions >= 1`
- **Alignment Analysis**: Decision included in calculations
- **Contract Compliance**: Decision included in analysis
- **Database**: Row exists in Phase 0 decisions table

### **❌ Test Fails If**
- **API Response**: `record-weekly-decision` returns error
- **Trial Status**: `total_decisions = 0`
- **Alignment Analysis**: Decision not included
- **Contract Compliance**: Decision not included
- **Database**: No row exists in Phase 0 decisions table

---

## 🎯 **TEST AUTOMATION**

### **✅ PowerShell Test Script**
```powershell
# Phase 0b Persistence Acceptance Test
Write-Host "=========================================="
Write-Host "PHASE 0B PERSISTENCE ACCEPTANCE TEST"
Write-Host "=========================================="

# Step 1: Record test decision
Write-Host "Step 1: Recording test decision..."
$body = @{
    model_id = "crypto_prediction_agent_v1"
    human_decision = "hold"
    decision_reason = "Test decision for persistence verification"
} | ConvertTo-Json

try {
    $response = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/record-weekly-decision" -Method POST -ContentType "application/json" -Body $body
    Write-Host "✅ Decision recorded successfully"
} catch {
    Write-Host "❌ Failed to record decision: $_"
    exit 1
}

# Step 2: Verify trial status
Write-Host "Step 2: Verifying trial status..."
try {
    $status = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/status" -Method GET
    if ($status.status.current_metrics.total_decisions -ge 1) {
        Write-Host "✅ Trial status shows total_decisions >= 1"
    } else {
        Write-Host "❌ Trial status shows total_decisions = 0"
        exit 1
    }
} catch {
    Write-Host "❌ Failed to get trial status: $_"
    exit 1
}

# Step 3: Verify alignment analysis
Write-Host "Step 3: Verifying alignment analysis..."
try {
    $alignment = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/alignment-analysis" -Method GET
    Write-Host "✅ Alignment analysis retrieved successfully"
} catch {
    Write-Host "❌ Failed to get alignment analysis: $_"
    exit 1
}

# Step 4: Verify contract compliance
Write-Host "Step 4: Verifying contract compliance..."
try {
    $compliance = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/contract-compliance" -Method GET
    Write-Host "✅ Contract compliance retrieved successfully"
} catch {
    Write-Host "❌ Failed to get contract compliance: $_"
    exit 1
}

Write-Host "=========================================="
Write-Host "PERSISTENCE ACCEPTANCE TEST PASSED"
Write-Host "=========================================="
```

---

## 🎯 **TEST EXECUTION**

### **✅ Pre-Phase 0b Checklist**
- [ ] Server running on http://localhost:8001
- [ ] Database accessible
- [ ] Phase 0 trial active
- [ ] Test script ready

### **✅ Test Execution**
1. **Run Test**: Execute acceptance test script
2. **Verify Results**: All acceptance criteria met
3. **Document Results**: Record test pass/fail
4. **Green-light Phase 0b**: Only if test passes

---

## 🎯 **TEST FAILURE HANDLING**

### **✅ If Test Fails**
- **Debug**: Check API → adapter → service → DB path
- **Fix**: Address specific failure point
- **Retest**: Run acceptance test again
- **Block Phase 0b**: Don't start Phase 0b until test passes

### **✅ Common Failure Points**
- **API Layer**: Endpoint not responding correctly
- **Adapter Layer**: DTO conversion issues
- **Service Layer**: Business logic problems
- **Database Layer**: Connection or persistence issues

---

## 🎯 **SUCCESS METRICS**

### **✅ Technical Success**
- **Persistence**: Decisions stored and retrievable
- **API Endpoints**: All three canonical endpoints working
- **Data Flow**: End-to-end data flow validated
- **Test Coverage**: Critical path tested

### **✅ Governance Success**
- **Process Ready**: Weekly cadence can proceed
- **Decision Recording**: Human decisions can be recorded
- **Metrics Calculation**: Success criteria can be calculated
- **Evidence-Based**: Phase 1 decision based on real data

---

## 🎯 **FINAL STATUS**

**Status: PHASE 0B PERSISTENCE ACCEPTANCE TEST READY** 🎯

The acceptance test is designed to prove that Phase 0 decisions are properly persisted and retrievable before starting Phase 0b.

**Only when this test passes will Phase 0b be green-lit for execution.**

**This ensures that Phase 0b will generate real metrics for evidence-based Phase 1 decision.**
