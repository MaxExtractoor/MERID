#!/bin/bash
# complete_trial.sh
# Complete Phase 0 trial and execute pre-committed decision tree

echo "=========================================="
echo "PHASE 0 TRIAL COMPLETION"
echo "=========================================="
echo "Date: $(date)"
echo "Week: $(date +%U)"
echo ""

echo "=== COMPLETING TRIAL ==="
echo "Completing 6-week Phase 0 trial..."
RESPONSE=$(curl -s -X POST http://localhost:8000/api/v1/phase0/trial/complete)

# Extract results
SUCCESSFUL=$(echo "$RESPONSE" | jq -r '.success')
if [ "$SUCCESSFUL" != "true" ]; then
    echo "❌ Trial completion failed"
    echo "Response: $RESPONSE"
    exit 1
fi

echo "✅ Trial completed successfully"

# Get trial results
ALIGNMENT=$(echo "$RESPONSE" | jq -r '.results.decision_analysis.alignment_rate')
COMPLIANCE=$(echo "$RESPONSE" | jq -r '.results.decision_analysis.contract_compliance_rate')
DECISIONS=$(echo "$RESPONSE" | jq -r '.results.decision_analysis.total_decisions')
SUCCESSFUL=$(echo "$RESPONSE" | jq -r '.results.success_determination.trial_successful')
RECOMMENDATIONS=$(echo "$RESPONSE" | jq -r '.results.recommendations[]')

echo ""
echo "=== TRIAL RESULTS ==="
echo "Successful: $SUCCESSFUL"
echo "Alignment Rate: \($ALIGNMENT * 100 | floor)%"
echo "Contract Compliance: \($COMPLIANCE * 100 | floor)%"
echo "Total Decisions: $DECISIONS"

echo ""
echo "=== SUCCESS DETERMINATION ==="
if [ "$SUCCESSFUL" = "true" ]; then
    echo "✅ TRIAL SUCCESSFUL"
    echo ""
    echo "PRE-COMMITTED SUCCESS ACTIONS:"
    echo "1. Add third model to Phase 1"
    echo "2. Loosen risk limits (Tier 2 allowed)"
    echo "3. Enable limited auto-promotion"
    echo "4. Continue with Phase 1"
    echo ""
    echo "NEXT PHASE CONFIGURATION:"
    echo "- Phase: phase1"
    echo "- Governance Mode: limited_auto_execution"
    echo "- Scoped Models: crypto_prediction_agent_v1, arbitrage_analyst_v2, third_model_v1"
    echo "- Risk Limits: Tier 2 allowed, $100K per model"
    echo "- Auto-Execution: Limited auto-promotion with human review"
    echo ""
    echo "IMPLEMENTATION:"
    echo "- Update environment variables for Phase 1"
    echo "- Configure Phase 1 risk limits"
    echo "- Enable auto-promotion feature flag"
    echo "- Add third model to scope"
    echo "- Continue monitoring with expanded scope"
    
else
    echo "❌ TRIAL FAILED"
    echo ""
    echo "PRE-COMMITTED FAILURE ACTIONS:"
    echo "1. No model additions"
    echo "2. Maintain recommendation-only mode"
    echo "3. Adjust thresholds based on evidence"
    echo "4. Run 4-week iteration trial"
    echo "5. Continue until success criteria met"
    echo ""
    echo "POLICY ITERATION NEEDED:"
    echo "- Analyze override patterns and misalignments"
    echo "- Adjust BSS threshold from 0.05 to 0.03"
    echo "- Review model-specific thresholds"
    echo "- Investigate contract test failures"
    echo "- Run shorter 4-week trial with adjusted parameters"
    echo ""
    echo "IMPLEMENTATION:"
    echo "- Keep Phase 0 active with adjusted thresholds"
    echo "- Update governance template based on evidence"
    echo "- Continue weekly governance cadence"
    echo "- Re-evaluate after 4 weeks"
fi

echo ""
echo "=== RECOMMENDATIONS ==="
echo "$RECOMMENDATIONS" | while read -r line; do echo "  - $line"; done

echo ""
echo "=== TRIAL COMPLETE ==="
echo "Phase 0 trial completed. Next phase determined by evidence-based criteria."
