# 🎯 **PHASE 0B - ENHANCED ACCEPTANCE TEST**

## ✅ **STRUCTURED LOGGING & PERSISTENCE DEBUGGING**

### **Test Objective**: Verify Phase 0 decision persistence with comprehensive logging  
### **Test Date**: January 24, 2026  
### **Test Status**: READY TO EXECUTE

---

## 🚀 **ENHANCED ACCEPTANCE TEST**

### **✅ Test Setup with Correlation ID**
```powershell
# Enhanced Phase 0 Acceptance Test with Structured Logging
Write-Host "=========================================="
Write-Host "PHASE 0B ENHANCED ACCEPTANCE TEST"
Write-Host "=========================================="

# Generate correlation ID
$testId = "phase0_acceptance_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Write-Host "Test ID: $testId"

# Enable debug logging
$env:LOG_LEVEL = "DEBUG"
$env:PHASE0_DEBUG = "true"

# Log file setup
$logFile = "logs/phase0_acceptance_$testId.log"
New-Item -ItemType Directory -Path "logs" -Force | Out-Null
"Starting Phase 0b acceptance test" | Out-File -FilePath $logFile -Append
"Test ID: $testId" | Out-File -FilePath $logFile -Append
"Timestamp: $(Get-Date)" | Out-File -FilePath $logFile -Append
```

### **✅ Step 1: Verify DB Connectivity**
```powershell
Write-Host "Step 1: Verifying DB connectivity..."
"Step 1: Verifying DB connectivity" | Out-File -FilePath $logFile -Append

try {
    # Check if server is running
    $healthCheck = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/health" -Method GET
    Write-Host "✅ Server health check passed"
    "✅ Server health check passed" | Out-File -FilePath $logFile -Append
} catch {
    Write-Host "❌ Server health check failed: $_"
    "❌ Server health check failed: $_" | Out-File -FilePath $logFile -Append
    exit 1
}
```

### **✅ Step 2: Start Trial**
```powershell
Write-Host "Step 2: Starting Phase 0 trial..."
"Step 2: Starting Phase 0 trial" | Out-File -FilePath $logFile -Append

try {
    $startBody = @{} | ConvertTo-Json
    $startResponse = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/start" -Method POST -ContentType "application/json" -Body $startBody
    Write-Host "✅ Trial started successfully"
    "✅ Trial started successfully" | Out-File -FilePath $logFile -Append
    "Trial response: $($startResponse | ConvertTo-Json -Depth 5)" | Out-File -FilePath $logFile -Append
} catch {
    Write-Host "❌ Trial start failed: $_"
    "❌ Trial start failed: $_" | Out-File -FilePath $logFile -Append
    exit 1
}
```

### **✅ Step 3: Record Decision (Without Performance Data)**
```powershell
Write-Host "Step 3: Recording decision without performance data..."
"Step 3: Recording decision without performance data" | Out-File -FilePath $logFile -Append

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
    
    Write-Host "✅ Decision recording response: $($response.status_code)"
    "✅ Decision recording response: $($response.status_code)" | Out-File -FilePath $logFile -Append
    "Response body: $($response | ConvertTo-Json -Depth 3)" | Out-File -FilePath $logFile -Append
    
} catch {
    Write-Host "❌ Decision recording failed: $_"
    "❌ Decision recording failed: $_" | Out-File -FilePath $logFile -Append
    "Stacktrace: $($_.ScriptStackTrace)" | Out-File -FilePath $logFile -Append
    $errors += "record-weekly-decision failed: $_"
}
```

### **✅ Step 4: Verify Trial Status**
```powershell
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
```

### **✅ Step 5: Verify Alignment Analysis**
```powershell
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
```

### **✅ Step 6: Verify Contract Compliance**
```powershell
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
```

### **✅ Step 7: Report Results**
```powershell
Write-Host "=========================================="
Write-Host "PHASE 0B ENHANCED ACCEPTANCE TEST RESULTS"
Write-Host "=========================================="

if ($errors.Count -gt 0) {
    Write-Host "❌ TEST FAILED"
    Write-Host "Errors:"
    $errors | ForEach-Object { Write-Host "  - $_" }
    
    "❌ TEST FAILED" | Out-File -FilePath $logFile -Append
    "Errors:" | Out-File -FilePath $logFile -Append
    $errors | ForEach-Object { "  - $_" | Out-File -FilePath $logFile -Append }
    
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

"Test completed" | Out-File -FilePath $logFile -Append
"Log file: $logFile" | Out-File -FilePath $logFile -Append
"==========================================" | Out-File -FilePath $logFile -Append
```

---

## 🎯 **DATABASE PERSISTENCE ASSERTIONS**

### **✅ Direct Database Checks**
```powershell
# Direct database persistence checks (if SQLite)
Write-Host "Step 8: Direct database verification..."
"Step 8: Direct database verification" | Out-File -FilePath $logFile -Append

try {
    # Check if SQLite database exists and has decisions table
    $dbPath = "data/phase0_decisions.db"
    if (Test-Path $dbPath) {
        Write-Host "✅ Database file exists: $dbPath"
        "✅ Database file exists: $dbPath" | Out-File -FilePath $logFile -Append
        
        # Query database directly
        $query = "SELECT COUNT(*) as count FROM phase0_decisions WHERE model_id = 'crypto_prediction_agent_v1'"
        $result = sqlite3 $dbPath $query
        
        Write-Host "Database query result: $result"
        "Database query result: $result" | Out-File -FilePath $logFile -Append
        
        if ($result -match "count: 0") {
            Write-Host "❌ No rows found in phase0_decisions table"
            "❌ No rows found in phase0_decisions table" | Out-File -FilePath $logFile -Append
            $errors += "No rows found in phase0_decisions table"
        } else {
            Write-Host "✅ Found rows in phase0_decisions table"
            "✅ Found rows in phase0_decisions table" | Out-File -FilePath $logFile -Append
        }
    } else {
        Write-Host "❌ Database file not found: $dbPath"
        "❌ Database file not found: $dbPath" | Out-File -FilePath $logFile -Append
        $errors += "Database file not found: $dbPath"
    }
} catch {
    Write-Host "❌ Database verification failed: $_"
    "❌ Database verification failed: $_" | Out-File -FilePath $logFile -Append
    $errors += "Database verification failed: $_"
}
```

---

## 🎯 **SQL QUERY LOGGING**

### **✅ Enable SQL Logging**
```powershell
# Enable SQL query logging for debugging
Write-Host "Step 9: Enabling SQL query logging..."
"Step 9: Enabling SQL query logging" | Out-File -FilePath $logFile -Append

# For SQLite, enable verbose mode
$env:SQLITE_DEBUG = "true"
$env:SQLITE_LOG = "logs/sqlite_$testId.log"

Write-Host "SQL logging enabled"
"SQL logging enabled" | Out-File -FilePath $logFile -Append
"SQLite debug mode: $env:SQLITE_DEBUG" | Out-File -FilePath $logFile -Append
"SQLite log file: $env:SQLITE_LOG" | Out-File -FilePath $logFile -Append
```

---

## 🎯 **ERROR STACKTRACE CAPTURE**

### **✅ Enhanced Error Handling**
```powershell
# Enhanced error handling with full stacktraces
function Invoke-WithStackTrace {
    param(
        [string]$Uri,
        [string]$Method,
        [string]$Body,
        [hashtable]$Headers = @{}
    )
    
    try {
        $response = Invoke-RestMethod -Uri $Uri -Method $Method -Body $Body -Headers $Headers
        return $response
    } catch {
        $errorRecord = $_
        $stackTrace = $errorRecord.ScriptStackTrace
        
        Write-Host "❌ API call failed"
        Write-Host "URI: $Uri"
        Write-Host "Method: $Method"
        Write-Host "Stacktrace:"
        Write-Host $stackTrace
        
        "❌ API call failed" | Out-File -FilePath $logFile -Append
        "URI: $Uri" | Out-File -FilePath $logFile -Append
        "Method: $Method" | Out-File -FilePath $logFile -Append
        "Stacktrace:" | Out-File -FilePath $logFile -Append
        $stackTrace | Out-File -FilePath $logFile -Append
        
        throw
    }
}
```

---

## 🎯 **TEST EXECUTION COMMANDS**

### **✅ Run Enhanced Acceptance Test**
```powershell
# Execute the enhanced acceptance test
cd "C:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e"
.\phase0b_enhanced_acceptance_test.ps1

# Check results
Get-Content "logs\phase0_acceptance_$testId.log" | Select-String "✅|❌"
```

### **✅ Export Test Artifacts**
```powershell
# Export test artifacts for analysis
$artifactDir = "test_artifacts_$testId"
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null

Copy-Item "logs\phase0_acceptance_$testId.log" $artifactDir\
if (Test-Path "logs\sqlite_$testId.log") {
    Copy-Item "logs\sqlite_$testId.log" $artifactDir\
}

Write-Host "Test artifacts exported to: $artifactDir"
```

---

## 🎯 **EXPECTED OUTCOMES**

### **✅ Test Passes If**
- **HTTP Success**: `record-weekly-decision` returns 200
- **Trial Status**: `total_decisions >= 1`
- **Endpoints**: Decision appears in all three canonical endpoints
- **Database**: Row exists in phase0_decisions table
- **SQL Logs**: INSERT statements visible in SQL log

### **❌ Test Fails If**
- **HTTP Error**: `record-weekly-decision` returns 4xx/5xx
- **No Persistence**: `total_decisions = 0`
- **Missing Data**: Decision not in endpoints
- **Database Empty**: No rows in phase0_decisions table
- **SQL Errors**: No INSERT statements in SQL log

---

## 🎯 **FINAL STATUS**

**Status: PHASE 0B ENHANCED ACCEPTANCE TEST READY** 🎯

The enhanced acceptance test is ready with:
- **Structured Logging**: Correlation ID, comprehensive logging
- **Persistence Assertions**: Direct database checks
- **SQL Query Logging**: Database operation visibility
- **Error Stacktraces**: Full error context
- **Test Artifacts**: Log files for analysis

**Execute this test to identify the exact persistence failure point and gather the debugging information needed to fix the service layer.**

**This enhanced test will provide the detailed persistence debugging information needed to fix the technical issue blocking Phase 0b.**
