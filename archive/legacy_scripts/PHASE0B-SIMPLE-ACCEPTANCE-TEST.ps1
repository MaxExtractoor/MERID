# 🎯 **PHASE 0B - SIMPLE ACCEPTANCE TEST**

## ✅ **SIMPLIFIED ACCEPTANCE TEST**

### **Purpose**: Execute acceptance test with basic logging  
### **Status**: READY TO EXECUTE

---

## 🚀 **SIMPLIFIED TEST EXECUTION**

```powershell
# Phase 0b Simple Acceptance Test
Write-Host "=========================================="
Write-Host "PHASE 0B ACCEPTANCE TEST"
Write-Host "=========================================="

# Generate test ID
$testId = "phase0_acceptance_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Write-Host "Test ID: $testId"

# Create logs directory
New-Item -ItemType Directory -Path "logs" -Force | Out-Null
New-Item -ItemType Directory -Path "test_artifacts" -Force | Out-Null

# Log file setup
$logFile = "logs/phase0_acceptance_$testId.log"
"Starting Phase 0b acceptance test" | Out-File -FilePath $logFile -Append
"Test ID: $testId" | Out-File -FilePath $logFile -Append
"Timestamp: $(Get-Date)" | Out-File -FilePath $logFile -Append

# Step 1: Verify DB connectivity
Write-Host "Step 1: Verifying DB connectivity..."
"Step 1: Verifying DB connectivity" | Out-File -FilePath $logFile -Append

try {
    $healthCheck = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/health" -Method GET
    Write-Host "✅ Server health check passed"
    "✅ Server health check passed" | Out-File -FilePath $logFile -Append
} catch {
    Write-Host "❌ Server health check failed: $_"
    "❌ Server health check failed: $_" | Out-File -FilePath $logFile -Append
    exit 1
}

# Step 2: Start trial
Write-Host "Step 2: Starting Phase 0 trial..."
"Step 2: Starting Phase 0 trial" | Out-File -FilePath $logFile -Append

try {
    $startBody = @{} | ConvertTo-Json
    $startResponse = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/start" -Method POST -ContentType "application/json" -Body $startBody
    Write-Host "✅ Trial started successfully"
    "✅ Trial started successfully" | Out-File -FilePath $logFile -Append
} catch {
    Write-Host "❌ Trial start failed: $_"
    "❌ Trial start failed: $_" | Out-File -FilePath $logFile -Append
    exit 1
}

# Step 3: Record decision
Write-Host "Step 3: Recording decision..."
"Step 3: Recording decision" | Out-File -FilePath $logFile -Append

$decisionPayload = @{
    model_id = "crypto_prediction_agent_v1"
    human_decision = "hold"
    decision_reason = "Acceptance test decision without performance data"
} | ConvertTo-Json

"Decision payload: $decisionPayload" | Out-File -FilePath $logFile -Append

try {
    $headers = @{
        "Content-Type" = "application/json"
        "X-Test-Id" = $testId
    }
    
    $response = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/record-weekly-decision" -Method POST -ContentType "application/json" -Body $decisionPayload -Headers $headers
    
    Write-Host "Decision recording response: $($response.status_code)"
    "Decision recording response: $($response.status_code)" | Out-File -FilePath $logFile -Append
    "Response body: $($response | ConvertTo-Json -Depth 3)" | Out-File -FilePath $logFile -Append
    
} catch {
    Write-Host "❌ Decision recording failed: $_"
    "❌ Decision recording failed: $_" | Out-File -FilePath $logFile -Append
    $errors += "record-weekly-decision failed: $_"
}

# Step 4: Verify trial status
Write-Host "Step 4: Verifying trial status..."
"Step 4: Verifying trial status" | Out-File -FilePath $logFile -Append

try {
    $status = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/status" -Method GET
    Write-Host "Trial status: $($status.status.current_metrics.total_decisions) total decisions"
    "Trial status: $($status.status.current_metrics.total_decisions) total decisions" | Out-File -FilePath $logFile -Append
    
    if ($status.status.current_metrics.total_decisions -eq 0) {
        Write-Host "❌ total_decisions is 0 after recording decision"
        "❌ total_decisions is 0 after recording decision" | Out-File -FilePath $logFile -Append
        $errors += "total_decisions is 0 after recording decision"
    } else {
        Write-Host "✅ total_decisions incremented to $($status.status.current_metrics.total_decisions)"
        "✅ total_decisions incremented to $($status.status.current_metrics.total_decisions)" | Out-File -FilePath $logFile -Append
    }
} catch {
    Write-Host "❌ Failed to get trial status: $_"
    "❌ Failed to get trial status: $_" | Out-File -FilePath $logFile -Append
    $errors += "Failed to get trial status: $_"
}

# Step 5: Verify alignment analysis
Write-Host "Step 5: Verifying alignment analysis..."
"Step 5: Verifying alignment analysis" | Out-File -FilePath $logFile -Append

try {
    $alignment = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/alignment-analysis" -Method GET
    Write-Host "Alignment analysis retrieved successfully"
    "Alignment analysis retrieved successfully" | Out-File -FilePath $logFile -Append
    
    if ($alignment.total_decisions -eq 0) {
        Write-Host "❌ alignment-analysis shows 0 decisions"
        "❌ alignment-analysis shows 0 decisions" | Out-File -FilePath $logFile -Append
        $errors += "alignment-analysis shows 0 decisions"
    } else {
        Write-Host "✅ alignment-analysis shows $($alignment.total_decisions) decisions"
        "✅ alignment-analysis shows $($alignment.total_decisions) decisions" | Out-File -FilePath $logFile -Append
    }
} catch {
    Write-Host "❌ Failed to get alignment analysis: $_"
    "❌ Failed to get alignment analysis: $_" | Out-File -FilePath $logFile -Append
    $errors += "Failed to get alignment analysis: $_"
}

# Step 6: Verify contract compliance
Write-Host "Step 6: Verifying contract compliance..."
"Step 6: Verifying contract compliance" | Out-File -FilePath $logFile -Append

try {
    $compliance = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/contract-compliance" -Method GET
    Write-Host "Contract compliance retrieved successfully"
    "Contract compliance retrieved successfully" | Out-File -FilePath $logFile -Append
    
    if ($compliance.total_decisions -eq 0) {
        Write-Host "❌ contract-compliance shows 0 decisions"
        "❌ contract-compliance shows 0 decisions" | Out-File -FilePath $logFile -Append
        $errors += "contract-compliance shows 0 decisions"
    } else {
        Write-Host "✅ contract-compliance shows $($compliance.total_decisions) decisions"
        "✅ contract-compliance shows $($compliance.total_decisions) decisions" | Out-File -FilePath $logFile -Append
    }
} catch {
    Write-Host "❌ Failed to get contract compliance: $_"
    "❌ Failed to get contract compliance: $_" | Out-File -FilePath $logFile -Append
    $errors += "Failed to get contract compliance: $_"
}

# Step 7: Report results
Write-Host "=========================================="
Write-Host "PHASE 0B ACCEPTANCE TEST RESULTS"
Write-Host "=========================================="

if ($errors.Count -gt 0) {
    Write-Host "❌ TEST FAILED"
    Write-Host "Errors:"
    $errors | ForEach-Object { Write-Host "  - $_" }
    
    "❌ TEST FAILED" | Out-File -FilePath $logFile -Append
    "Errors:" | Out-File -FilePath $logFile -Append
    $errors | ForEach-Object { "  - $_" | Out-File -FilePath $logFile -Append
    
    exit 1
} else {
    Write-Host "✅ TEST PASSED"
    Write-Host "All persistence assertions passed"
    
    "✅ TEST PASSED" | Out-File -FilePath $logFile -Append
    "All persistence assertions passed" | Out-File -FilePath $logFile -Append
}

Write-Host "Log file: $logFile"
Write-Host "Test ID: $testId"
Write-Host "=========================================="

# Copy test artifacts
$artifactDir = "test_artifacts/$testId"
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null

if (Test-Path $logFile) {
    Copy-Item $logFile "$artifactDir/phase0_acceptance.log"
}

Write-Host "Test artifacts exported to: $artifactDir"
Write-Host "=========================================="

# Show key log entries
if (Test-Path $logFile) {
    Write-Host ""
    Write-Host "Key Log Entries:"
    Get-Content $logFile | Select-String "✅|❌" | Select-Object -First 10
}
```

---

## 🎯 **EXECUTION COMMAND**

### **✅ Run Simple Test**
```powershell
# Execute simple acceptance test
cd "C:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e"
.\phase0b_simple_acceptance_test.ps1

# View results
Get-Content "logs/phase0_acceptance_*.log" | Select-String "✅|❌"
```

---

## 🎯 **FINAL STATUS**

**Status: PHASE 0B SIMPLE ACCEPTANCE TEST READY** 🎯

The simplified acceptance test is ready with:
- **Basic Logging**: Structured logging with correlation ID
- **Core Testing**: All essential persistence assertions
- **Error Capture**: HTTP errors and exceptions
- **Artifact Generation**: Log files for analysis

**Execute this simplified test to gather the debugging information needed to fix the persistence issue.**

**This simplified approach will provide the core debugging information needed while avoiding PowerShell syntax errors.**
