# Phase 0 Decision Recording Script (PowerShell)
# Use this to record weekly governance decisions

Write-Host "=========================================="
Write-Host "PHASE 0 WEEKLY DECISION RECORDING"
Write-Host "=========================================="
Write-Host "Date: $(Get-Date)"
Write-Host "Week: $((Get-Date).DayOfYear / 7 + 1)"
Write-Host ""

# Get current trial status first
try {
    $status = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/status" -Method GET
    Write-Host "Trial Status: $($status.status)"
    Write-Host "Current Decisions: $($status.current_metrics.total_decisions)"
    Write-Host ""
} catch {
    Write-Host "Error getting trial status: $($_.Exception.Message)"
    Write-Host "Please ensure the trial is active and server is running on port 8001"
    exit 1
}

Write-Host "=== RECORDING DECISIONS ==="
Write-Host ""

# Model 1 decision
Write-Host "crypto_prediction_agent_v1:"
Write-Host "Options: promote, demote, hold, suspend, retire"
$decision1 = Read-Host "Enter decision for crypto_prediction_agent_v1"

while ($decision1 -notin @("promote", "demote", "hold", "suspend", "retire")) {
    Write-Host "Invalid decision. Please enter: promote, demote, hold, suspend, or retire"
    $decision1 = Read-Host "Enter decision for crypto_prediction_agent_v1"
}

$reason1 = Read-Host "Enter reason for crypto_prediction_agent_v1"

# Model 2 decision
Write-Host ""
Write-Host "arbitrage_analyst_v2:"
Write-Host "Options: promote, demote, hold, suspend, retire"
$decision2 = Read-Host "Enter decision for arbitrage_analyst_v2"

while ($decision2 -notin @("promote", "demote", "hold", "suspend", "retire")) {
    Write-Host "Invalid decision. Please enter: promote, demote, hold, suspend, or retire"
    $decision2 = Read-Host "Enter decision for arbitrage_analyst_v2"
}

$reason2 = Read-Host "Enter reason for arbitrage_analyst_v2"

Write-Host ""
Write-Host "=== RECORDING DECISIONS ==="

# Record decision 1
try {
    $body1 = @{
        model_id = "crypto_prediction_agent_v1"
        human_decision = $decision1
        decision_reason = $reason1
    } | ConvertTo-Json
    
    $response1 = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/record-weekly-decision" -Method POST -ContentType "application/json" -Body $body1
    
    if ($response1.success) {
        Write-Host "✅ crypto_prediction_agent_v1 decision recorded: $decision1"
        Write-Host "   Reason: $reason1"
    } else {
        Write-Host "❌ Failed to record crypto_prediction_agent_v1 decision"
        Write-Host "   Response: $($response1.error)"
        exit 1
    }
} catch {
    Write-Host "❌ Failed to record crypto_prediction_agent_v1 decision"
    Write-Host "   Error: $($_.Exception.Message)"
    exit 1
}

# Record decision 2
try {
    $body2 = @{
        model_id = "arbitrage_analyst_v2"
        human_decision = $decision2
        decision_reason = $reason2
    } | ConvertTo-Json
    
    $response2 = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/record-weekly-decision" -Method POST -ContentType "application/json" -Body $body2
    
    if ($response2.success) {
        Write-Host "✅ arbitrage_analyst_v2 decision recorded: $decision2"
        Write-Host "   Reason: $reason2"
    } else {
        Write-Host "❌ Failed to record arbitrage_analyst_v2 decision"
        Write-Host "   Response: $($response2.error)"
        exit 1
    }
} catch {
    Write-Host "❌ Failed to record arbitrage_analyst_v2 decision"
    Write-Host "   Error: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "=== DECISIONS RECORDED ==="
Write-Host "crypto_prediction_agent_v1: $decision1"
Write-Host "  Reason: $reason1"
Write-Host ""
Write-Host "arbitrage_analyst_v2: $decision2"
Write-Host "  Reason: $reason2"

Write-Host ""
Write-Host "=== VERIFICATION ==="
Write-Host "Verifying decisions were recorded..."

try {
    $verification = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/weekly-decisions" -Method GET
    Write-Host "Total decisions in trial: $($verification.total_decisions)"
    Write-Host "Latest decisions:"
    
    # Show last 2 decisions
    $latestDecisions = $verification.decisions | Select-Object -Last 2
    foreach ($decision in $latestDecisions) {
        Write-Host "Week $($decision.week_number): $($decision.model_id)"
        Write-Host "  System: $($decision.system_recommendation)"
        Write-Host "  Human: $($decision.human_decision)"
        Write-Host "  Alignment: $(if ($decision.alignment) { '✅' } else { '❌' })"
        Write-Host "  Contracts: $(if ($decision.contract_tests_passed) { '✅' } else { '❌' })"
        Write-Host "  Reason: $($decision.decision_reason)"
        Write-Host ""
    }
} catch {
    Write-Host "Error verifying decisions: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "=== WEEKLY DECISION COMPLETE ==="
Write-Host "Proceed with weekly status check: .\weekly_phase0_status.ps1"
