# Phase 0 Trial Completion Script (PowerShell)
# Use this to complete the 6-week trial and execute decision tree

Write-Host "=========================================="
Write-Host "PHASE 0 TRIAL COMPLETION"
Write-Host "=========================================="
Write-Host "Date: $(Get-Date)"
Write-Host "Week: $((Get-Date).DayOfYear / 7 + 1)"
Write-Host ""

Write-Host "=== COMPLETING TRIAL ==="
Write-Host "Completing 6-week Phase 0 trial..."

try {
    $response = Invoke-RestMethod -Uri "http://localhost:8001/api/v1/phase0/trial/complete" -Method POST -ContentType "application/json"
    
    if ($response.success) {
        Write-Host "✅ Trial completed successfully"
        
        # Extract results
        $results = $response.results
        $successful = $results.success_determination.trial_successful
        $alignment = $results.decision_analysis.alignment_rate
        $compliance = $results.decision_analysis.contract_compliance_rate
        $decisions = $results.decision_analysis.total_decisions
        $recommendations = $results.recommendations
        
        Write-Host ""
        Write-Host "=== TRIAL RESULTS ==="
        Write-Host "Successful: $successful"
        Write-Host "Alignment Rate: $([math]::Round($alignment * 100))%"
        Write-Host "Contract Compliance: $([math]::Round($compliance * 100))%"
        Write-Host "Total Decisions: $decisions"
        
        Write-Host ""
        Write-Host "=== SUCCESS DETERMINATION ==="
        if ($successful) {
            Write-Host "✅ TRIAL SUCCESSFUL"
            Write-Host ""
            Write-Host "PRE-COMMITTED SUCCESS ACTIONS:"
            Write-Host "1. Add third model to Phase 1"
            Write-Host "2. Loosen risk limits (Tier 2 allowed)"
            Write-Host "3. Enable limited auto-promotion"
            Write-Host "4. Continue with Phase 1"
            Write-Host ""
            Write-Host "NEXT PHASE CONFIGURATION:"
            Write-Host "- Phase: phase1"
            Write-Host "- Governance Mode: limited_auto_execution"
            Write-Host "- Scoped Models: crypto_prediction_agent_v1, arbitrage_analyst_v2, third_model_v1"
            Write-Host "- Risk Limits: Tier 2 allowed, $100K per model"
            Write-Host "- Auto-Execution: Limited auto-promotion with human review"
            Write-Host ""
            Write-Host "IMPLEMENTATION:"
            Write-Host "- Update environment variables for Phase 1"
            Write-Host "- Configure Phase 1 risk limits"
            Write-Host "- Enable auto-promotion feature flag"
            Write-Host "- Add third model to scope"
            Write-Host "- Continue monitoring with expanded scope"
            
            # Create Phase 1 configuration
            $phase1Config = @"
# Phase 1 Configuration (copy to environment setup)
export MERID_ENV=local
export MERID_PHASE1_ENABLED=true
export MERID_PHASE1_MODEL_IDS=crypto_prediction_agent_v1,arbitrage_analyst_v2,third_model_v1
export MERID_FEATURE_BRIER_GOVERNANCE=true
export MERID_FEATURE_EXPANDED_SCOPE=true
export MERID_PHASE1_CONTRACT_ENFORCED=true
export GOVERNANCE_ALLOW_AUTO_PROMOTION=true
export GOVERNANCE_ALLOW_AUTO_DEMOTION=false
export GOVERNANCE_RISK_PROFILE=moderate
export MERID_LOG_LEVEL=INFO
"@
            
            Write-Host ""
            Write-Host "=== PHASE 1 CONFIGURATION ==="
            Write-Host $phase1Config
            
            # Save Phase 1 config
            $phase1Config | Out-File -FilePath "phase1_config.env" -Encoding UTF8
            Write-Host "Phase 1 configuration saved to phase1_config.env"
            
        } else {
            Write-Host "❌ TRIAL FAILED"
            Write-Host ""
            Write-Host "PRE-COMMITTED FAILURE ACTIONS:"
            Write-Host "1. No model additions"
            Write-Host "2. Maintain recommendation-only mode"
            Write-Host "3. Adjust thresholds based on evidence"
            Write-Host "4. Run 4-week iteration trial"
            Write-Host "5. Continue until success criteria met"
            Write-Host ""
            Write-Host "POLICY ITERATION NEEDED:"
            Write-Host "- Analyze override patterns and misalignments"
            Write-Host "- Adjust BSS threshold from 0.05 to 0.03"
            Write-Host "- Review model-specific thresholds"
            Write-Host "- Investigate contract test failures"
            Write-Host "- Run shorter 4-week trial with adjusted parameters"
            Write-Host ""
            Write-Host "IMPLEMENTATION:"
            Write-Host "- Keep Phase 0 active with adjusted thresholds"
            Write-Host "- Update governance template based on evidence"
            Write-Host "- Continue weekly governance cadence"
            Write-Host "- Re-evaluate after 4 weeks"
            
            # Create iteration configuration
            $iterationConfig = @"
# Phase 0 Iteration Configuration (copy to environment setup)
export MERID_ENV=local
export MERID_PHASE0_ENABLED=true
export MERID_PHASE0_MODEL_IDS=crypto_prediction_agent_v1,arbitrage_analyst_v2
export MERID_FEATURE_BRIER_GOVERNANCE=true
export MERID_FEATURE_MINIMAL_SCOPE=true
export MERID_PHASE0_CONTRACT_ENFORCED=true
export GOVERNANCE_DRY_RUN=true
export MERID_LOG_LEVEL=DEBUG

# Adjusted thresholds based on trial evidence
export MERID_BSS_THRESHOLD=0.03
export MERID_ALIGNMENT_THRESHOLD=0.65
export MERID_COMPLIANCE_THRESHOLD=0.90
"@
            
            Write-Host ""
            Write-Host "=== ITERATION CONFIGURATION ==="
            Write-Host $iterationConfig
            
            # Save iteration config
            $iterationConfig | Out-File -FilePath "phase0_iteration.env" -Encoding UTF8
            Write-Host "Phase 0 iteration configuration saved to phase0_iteration.env"
        }
        
        Write-Host ""
        Write-Host "=== RECOMMENDATIONS ==="
        foreach ($rec in $recommendations) {
            Write-Host "- $rec"
        }
        
    } else {
        Write-Host "❌ Trial completion failed"
        Write-Host "Response: $($response.error)"
        exit 1
    }
    
} catch {
    Write-Host "❌ Failed to complete trial"
    Write-Host "Error: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "=== TRIAL COMPLETE ==="
Write-Host "Phase 0 trial completed. Next phase determined by evidence-based criteria."

# Generate final report
$report = @"
# Phase 0 Trial Final Report

## Trial Summary
- Start Date: $($response.results.trial_configuration.trial_period.start_date)
- End Date: $(Get-Date)
- Duration: 6 weeks
- Models: crypto_prediction_agent_v1, arbitrage_analyst_v2
- Governance Mode: recommendation_only

## Results
- Successful: $successful
- Alignment Rate: $([math]::Round($alignment * 100))%
- Contract Compliance: $([math]::Round($compliance * 100))%
- Total Decisions: $decisions

## Success Criteria
- Alignment Target: 70% (Actual: $([math]::Round($alignment * 100))%)
- Compliance Target: 95% (Actual: $([math]::Round($compliance * 100))%)
- Decision Target: 12 (Actual: $decisions)

## Next Steps
$($recommendations -join "`n")

## Decision Tree Execution
$(
if ($successful) {
    "SUCCESS PATH: Proceed to Phase 1 with expanded scope and limited auto-promotion"
} else {
    "FAILURE PATH: Policy iteration with adjusted thresholds and shorter retry trial"
}
)
"@

$report | Out-File -FilePath "phase0_final_report.md" -Encoding UTF8
Write-Host "Final report saved to phase0_final_report.md"
