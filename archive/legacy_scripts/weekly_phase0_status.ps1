# Phase 0 Weekly Status Script (PowerShell)
# Use this for weekly governance meetings

Write-Host "=========================================="
Write-Host "PHASE 0 WEEKLY STATUS REPORT"
Write-Host "=========================================="
Write-Host "Date: $(Get-Date)"
Write-Host "Week: $((Get-Date).DayOfYear / 7 + 1)"
Write-Host ""

Write-Host "=== TRIAL STATUS ==="
try {
    $status = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/status" -Method GET
    Write-Host "Status: $($status.status)"
    Write-Host "Governance Mode: $($status.governance_mode)"
    Write-Host "Total Decisions: $($status.current_metrics.total_decisions)"
    Write-Host "Alignment Rate: $($status.current_metrics.alignment_rate)"
    Write-Host "Contract Compliance: $($status.current_metrics.contract_compliance_rate)"
} catch {
    Write-Host "Error getting trial status: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== ALIGNMENT ANALYSIS ==="
try {
    $alignment = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/alignment-analysis" -Method GET
    Write-Host "Total Decisions: $($alignment.total_decisions)"
    Write-Host "Alignment Rate: $($alignment.alignment_rate)"
    Write-Host "Message: $($alignment.message)"
} catch {
    Write-Host "Error getting alignment analysis: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== CONTRACT COMPLIANCE ==="
try {
    $compliance = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/contract-compliance" -Method GET
    Write-Host "Total Decisions: $($compliance.total_decisions)"
    Write-Host "Compliance Rate: $($compliance.compliance_rate)"
    Write-Host "Message: $($compliance.message)"
} catch {
    Write-Host "Error getting contract compliance: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== SUCCESS INDICATORS ==="
try {
    $status = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/status" -Method GET
    $alignment = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/alignment-analysis" -Method GET
    $compliance = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/contract-compliance" -Method GET
    
    $weekNum = (Get-Date).DayOfYear / 7 + 1
    $expectedDecisions = $weekNum * 2
    
    Write-Host "Expected Decisions: $expectedDecisions"
    Write-Host "Actual Decisions: $($status.current_metrics.total_decisions)"
    Write-Host "Alignment Target: 0.7, Current: $($alignment.alignment_rate)"
    Write-Host "Compliance Target: 0.95, Current: $($compliance.compliance_rate)"
    
    # Success indicators
    if ($alignment.alignment_rate -ge 0.7 -and $compliance.compliance_rate -ge 0.95 -and $status.current_metrics.total_decisions -ge $expectedDecisions) {
        Write-Host "🟢 ON TRACK"
    } elseif ($alignment.alignment_rate -lt 0.6 -or $compliance.compliance_rate -lt 0.9 -or $status.current_metrics.total_decisions -lt ($expectedDecisions - 2)) {
        Write-Host "🟡 NEEDS ATTENTION"
    } else {
        Write-Host "🟡 MONITORING"
    }
} catch {
    Write-Host "Error calculating success indicators: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== NEXT STEPS ==="
Write-Host "1. Review metrics above"
Write-Host "2. Prepare for weekly governance meeting"
Write-Host "3. Record decisions for both models"
Write-Host "4. Continue weekly cadence until trial completion"
Write-Host ""
Write-Host "=== WEEKLY DECISION RECORDING ==="
Write-Host "Use these commands to record decisions:"
Write-Host ""
Write-Host "Model 1 (crypto_prediction_agent_v1):"
Write-Host '$body1 = ''{"model_id": "crypto_prediction_agent_v1", "human_decision": "hold", "decision_reason": "Your reason here"}'''
Write-Host "Invoke-RestMethod -Uri `"http://localhost:8001/api/v1/phase0/trial/record-weekly-decision`" -Method POST -ContentType `"application/json`" -Body `$body1"
Write-Host ""
Write-Host "Model 2 (arbitrage_analyst_v2):"
Write-Host '$body2 = ''{"model_id": "arbitrage_analyst_v2", "human_decision": "hold", "decision_reason": "Your reason here"}'''
Write-Host "Invoke-RestMethod -Uri `"http://localhost:8001/api/v1/phase0/trial/record-weekly-decision`" -Method POST -ContentType `"application/json`" -Body `$body2"
