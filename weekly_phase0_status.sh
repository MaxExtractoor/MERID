#!/bin/bash
# weekly_phase0_status.sh
# Weekly Phase 0 status report - single source of truth

echo "=========================================="
echo "PHASE 0 WEEKLY STATUS REPORT"
echo "=========================================="
echo "Date: $(date)"
echo "Week: $(date +%U)"
echo ""

echo "=== TRIAL STATUS ==="
curl -s http://localhost:8000/api/v1/phase0/trial/status | jq -r '
  {
    status,
    trial_period,
    progress,
    current_metrics
  } |
  {
    "Status": .status,
    "Progress": "\(.progress.progress_pct * 100 | floor)%",
    "Elapsed Days": .progress.elapsed_days,
    "Total Days": .progress.total_days,
    "Total Decisions": .current_metrics.total_decisions,
    "Alignment Rate": "\(.current_metrics.alignment_rate * 100 | floor)%",
    "Contract Compliance": "\(.current_metrics.contract_compliance_rate * 100 | floor)%"
  }
'

echo ""
echo "=== ALIGNMENT ANALYSIS ==="
curl -s http://localhost:8000/api/v1/phase0/trial/alignment-analysis | jq -r '
  {
    overall_alignment,
    model_alignment
  } |
  {
    "Overall Alignment": "\(.overall_alignment.alignment_rate * 100 | floor)%",
    "Total Decisions": .overall_alignment.total_decisions,
    "Aligned Decisions": .overall_alignment.aligned_decisions,
    "Model Alignment": [
      {
        model: .model_alignment[].model_id,
        "Alignment": "\(.model_alignment[].alignment_rate * 100 | floor)%",
        "Total": .model_alignment[].total_decisions,
        "Aligned": .model_alignment[].aligned_decisions
      }
    ]
  }
'

echo ""
echo "=== CONTRACT COMPLIANCE ==="
curl -s http://localhost:8000/api/v1/phase0/trial/contract-compliance | jq -r '
  {
    overall_compliance,
    model_compliance
  } |
  {
    "Overall Compliance": "\(.overall_compliance.compliance_rate * 100 | floor)%",
    "Total Decisions": .overall_compliance.total_decisions,
    "Compliant Decisions": .overall_compliance.compliant_decisions,
    "Model Compliance": [
      {
        model: .model_compliance[].model_id,
        "Compliance": "\(.model_compliance[].compliance_rate * 100 | floor)%",
        "Total": .model_compliance[].total_decisions,
        "Compliant": .model_compliance[].compliant_decisions
      }
    ]
  }
'

echo ""
echo "=== SUCCESS PROBABILITY ==="
curl -s http://localhost:8000/api/v1/phase0/trial/trial_summary | jq -r '
  {
    summary
  } |
  {
    "Success Probability": "\(.summary.success_probability * 100 | floor)%",
    "Status": .summary.status,
    "Recommendations": .summary.recommendations
  }
'

echo ""
echo "=== NEXT STEPS ==="
if [ "$(curl -s http://localhost:8000/api/v1/phase0/trial/status | jq -r '.status')" = "active" ]; then
    echo "1. Review metrics above"
    echo "2. Prepare for weekly governance meeting"
    echo "3. Record decisions using record_decisions.sh"
    echo "4. Continue weekly cadence until trial completion"
else
    echo "1. Trial is not active"
    echo "2. Start trial with: curl -X POST /api/v1/phase0/trial/start"
    echo "3. Verify setup with: curl /api/v1/phase0/trial/status"
fi
