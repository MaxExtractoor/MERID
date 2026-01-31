# 🎯 **PHASE 0B - ACCEPTANCE TEST EXECUTOR**

## ✅ **TEST EXECUTION AUTOMATION**

### **Purpose**: Execute enhanced acceptance test and generate debugging artifacts  
### **Status**: READY TO EXECUTE

---

## 🚀 **EXECUTION SCRIPT**

### **✅ Run Enhanced Acceptance Test**
```powershell
# Phase 0b Acceptance Test Executor
Write-Host "=========================================="
Write-Host "PHASE 0B ACCEPTANCE TEST EXECUTOR"
Write-Host "=========================================="

# Set up environment
$env:LOG_LEVEL = "DEBUG"
$env:PHASE0_DEBUG = "true"

# Create logs directory
New-Item -ItemType Directory -Path "logs" -Force | Out-Null
New-Item -ItemType Directory -Path "test_artifacts" -Force | Out-Null

# Generate test ID
$testId = "phase0_acceptance_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
Write-Host "Test ID: $testId"
Write-Host "Log file: logs/phase0_acceptance_$testId.log"
Write-Host "Artifacts: test_artifacts/$testId/"

# Execute enhanced acceptance test
Write-Host "Executing enhanced acceptance test..."
try {
    & .\PHASE0B-ENHANCED-ACCEPTANCE-TEST.ps1
    $testExitCode = $LASTEXITCODE
} catch {
    Write-Host "❌ Test execution failed: $_"
    $testExitCode = 1
}

# Generate test report
$reportFile = "test_artifacts/$testId/test_report.md"
"Phase 0b Acceptance Test Report" | Out-File -FilePath $reportFile
"Test ID: $testId" | Out-File -FilePath $reportFile
"Timestamp: $(Get-Date)" | Out-File -FilePath $reportFile
"Exit Code: $testExitCode" | Out-File -FilePath $reportFile
"" | Out-File -FilePath $reportFile

# Copy test artifacts
$artifactDir = "test_artifacts/$testId"
New-Item -ItemType Directory -Path $artifactDir -Force | Out-Null

if (Test-Path "logs/phase0_acceptance_$testId.log") {
    Copy-Item "logs/phase0_acceptance_$testId.log" "$artifactDir/phase0_acceptance.log"
}

if (Test-Path "logs/sqlite_$testId.log") {
    Copy-Item "logs/sqlite_$testId.log" "$artifactDir/sqlite_queries.log"
}

# Show results
Write-Host "=========================================="
Write-Host "PHASE 0B ACCEPTANCE TEST RESULTS"
Write-Host "=========================================="

if ($testExitCode -eq 0) {
    Write-Host "✅ TEST PASSED"
    Write-Host "All persistence assertions passed"
    "✅ TEST PASSED" | Out-File -FilePath $reportFile -Append
    "All persistence assertions passed" | Out-File -FilePath $reportFile -Append
} else {
    Write-Host "❌ TEST FAILED"
    Write-Host "Check log file for details: logs/phase0_acceptance_$testId.log"
    Write-Host "Check artifacts: $artifactDir"
    "❌ TEST FAILED" | Out-File -FilePath $reportFile -Append
    "Check log file for details: logs/phase0_acceptance_$testId.log" | Out-File -FilePath $reportFile -Append
    "Check artifacts: $artifactDir" | Out-File -FilePath $reportFile -Append
}

Write-Host "Test report: $reportFile"
Write-Host "Artifacts: $artifactDir"
Write-Host "=========================================="

# Show key log entries
if (Test-Path "logs/phase0_acceptance_$testId.log") {
    Write-Host ""
    Write-Host "Key Log Entries:"
    Get-Content "logs/phase0_acceptance_$testId.log" | Select-String "✅|❌" | Select-Object -First 10
}
```

### **✅ Quick Test Execution**
```powershell
# Quick test execution (one-liner)
cd "C:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e"
$testId = "phase0_acceptance_$(Get-Date -Format 'yyyyMMdd_HHmmss')"
& .\PHASE0B-ENHANCED-ACCEPTANCE-TEST.ps1
Get-Content "logs/phase0_acceptance_$testId.log" | Select-String "✅|❌" | Select-Object -First 5
```

---

## 🎯 **ANALYSIS COMMANDS**

### **✅ View Test Results**
```powershell
# View test report
Get-Content "test_artifacts/phase0_acceptance_*/test_report.md"

# View full log
Get-Content "logs/phase0_acceptance_*.log"

# View SQL queries
Get-Content "logs/sqlite_*.log"
```

### **✅ Debug Persistence Issues**
```powershell
# Check for decision recording errors
Get-Content "logs/phase0_acceptance_*.log" | Select-String "record-weekly-decision failed"

# Check for database errors
Get-Content "logs/phase0_acceptance_*.log" | Select-String "Database"

# Check for SQL INSERT statements
Get-Content "logs/sqlite_*.log" | Select-String "INSERT"

# Check for stacktraces
Get-Content "logs/phase0_acceptance_*.log" | Select-String -A 10 "Stacktrace"
```

---

## 🎯 **EXPECTED DEBUGGING OUTPUT**

### **✅ Success Indicators**
- **HTTP 200**: Decision recording succeeds
- **total_decisions >= 1**: Decision persisted
- **SQL INSERT**: Database write visible
- **All ✅ marks**: All assertions passed

### **❌ Failure Indicators**
- **HTTP 4xx/5xx**: Decision recording failed
- **total_decisions = 0**: No persistence
- **No SQL INSERT**: Database write failed
- **Stacktrace visible**: Service layer error

---

## 🎯 **TROUBLESHOOTING GUIDE**

### **✅ If Test Fails**
1. **Check HTTP Response**: Look for `record-weekly-decision failed`
2. **Check Database**: Verify `phase0_decisions` table exists
3. **Check SQL Log**: Look for INSERT statements
4. **Check Stacktrace**: Identify service layer error
5. **Check Connectivity**: Verify database connection

### **✅ Common Issues**
- **Service Validation**: "No performance data available"
- **Database Connection**: Connection refused or wrong credentials
- **Transaction Rollback**: INSERT succeeded but rolled back
- **Missing Table**: `phase0_decisions` table doesn't exist

---

## 🎯 **FINAL STATUS**

**Status: PHASE 0B ACCEPTANCE TEST EXECUTOR READY** 🎯

The enhanced acceptance test executor is ready with:
- **Automated Execution**: Runs test and generates artifacts
- **Comprehensive Logging**: Structured logging with correlation ID
- **Debugging Support**: SQL queries, stacktraces, error details
- **Artifact Generation**: Test reports and log files

**Execute this script to run the enhanced acceptance test and gather the detailed debugging information needed to fix the persistence issue.**

**This enhanced testing approach will provide the comprehensive debugging information needed to identify and fix the exact technical issue blocking Phase 0b.**
