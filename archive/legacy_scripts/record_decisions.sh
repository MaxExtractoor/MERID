#!/bin/bash
# record_decisions.sh
# Record weekly Phase 0 decisions - change approval board

echo "=========================================="
echo "PHASE 0 WEEKLY DECISION RECORDING"
echo "=========================================="
echo "Date: $(date)"
echo "Week: $(date +%U)"
echo ""

# Get current system recommendations
echo "=== CURRENT SYSTEM RECOMMENDATIONS ==="
echo "Fetching current scorecards..."
RECOMMENDATIONS=$(curl -s http://localhost:8000/api/v1/minimal/scorecards | jq -r '.scorecards[] | {model_id, governance} | "\(.model_id): \(.governance.suggested_action)"')

if [ -n "$RECOMMENDATIONS" ]; then
    echo "$RECOMMENDATIONS"
else
    echo "No recommendations available"
fi

echo ""
echo "=== DECISION INPUT ==="

# Model 1 decision
echo "crypto_prediction_agent_v1:"
echo "Current recommendation: $(echo "$RECOMMENDATIONS" | grep "crypto_prediction_agent_v1" | cut -d: -f2)"
echo "Options: promote, demote, hold, suspend, retire"
echo "Enter decision for crypto_prediction_agent_v1:"
read DECISION1

while [[ "$DECISION1" != "promote" && "$DECISION1" != "demote" && "$DECISION1" != "hold" && "$DECISION1" != "suspend" && "$DECISION1" != "retire" ]]; do
    echo "Invalid decision. Please enter: promote, demote, hold, suspend, or retire"
    echo "Enter decision for crypto_prediction_agent_v1:"
    read DECISION1
done

echo "Enter reason for crypto_prediction_agent_v1:"
read REASON1

# Model 2 decision
echo ""
echo "arbitrage_analyst_v2:"
echo "Current recommendation: $(echo "$RECOMMENDATIONS" | grep "arbitrage_analyst_v2" | cut -d: -f2)"
echo "Options: promote, demote, hold, suspend, retire"
echo "Enter decision for arbitrage_analyst_v2:"
read DECISION2

while [[ "$DECISION2" != "promote" && "$DECISION2" != "demote" && "$DECISION2" != "hold" && "$DECISION2" != "suspend" && "$DECISION2" != "retire" ]]; do
    echo "Invalid decision. Please enter: promote, demote, hold, suspend, or retire"
    echo "Enter decision for arbitrage_analyst_v2:"
    read DECISION2
done

echo "Enter reason for arbitrage_analyst_v2:"
read REASON2

# Record decisions
echo ""
echo "=== RECORDING DECISIONS ==="

echo "Recording decision for crypto_prediction_agent_v1..."
RESPONSE1=$(curl -s -X POST http://localhost:8000/api/v1/phase0/trial/record-weekly-decision \
  -H "Content-Type: application/json" \
  -d "{\"model_id\": \"crypto_prediction_agent_v1\", \"human_decision\": \"$DECISION1\", \"decision_reason\": \"$REASON1\"}")

if echo "$RESPONSE1" | jq -r '.success' | grep -q true; then
    echo "✅ crypto_prediction_agent_v1 decision recorded: $DECISION1"
    echo "   Reason: $REASON1"
else
    echo "❌ Failed to record crypto_prediction_agent_v1 decision"
    echo "   Response: $RESPONSE1"
    exit 1
fi

echo ""
echo "Recording decision for arbitrage_analyst_v2..."
RESPONSE2=$(curl -s -X POST http://localhost:8000/api/v1/phase0/trial/record-weekly-decision \
  -H "Content-Type: application/json" \
  -d "{\"model_id\": \"arbitrage_analyst_v2\", \"human_decision\": \"$DECISION2\", \"decision_reason\": \"$REASON2\"}")

if echo "$RESPONSE2" | jq -r '.success' | grep -q true; then
    echo "✅ arbitrage_analyst_v2 decision recorded: $DECISION2"
    echo "   Reason: $REASON2"
else
    echo "❌ Failed to record arbitrage_analyst_v2 decision"
    echo "   Response: $RESPONSE2"
    exit 1
fi

echo ""
echo "=== DECISIONS RECORDED ==="
echo "crypto_prediction_agent_v1: $DECISION1"
echo "  Reason: $REASON1"
echo ""
echo "arbitrage_analyst_v2: $DECISION2"
echo "  Reason: $REASON2"

echo ""
echo "=== VERIFICATION ==="
echo "Verifying decisions were recorded..."

# Verify decisions were recorded
VERIFICATION=$(curl -s http://localhost:8000/api/v1/phase0/trial/weekly-decisions | jq -r '.decisions | length')
echo "Total decisions in trial: $VERIFICATION"

# Get latest decisions for verification
echo ""
echo "Latest decisions:"
curl -s http://localhost:8000/api/v1/phase0/trial/weekly-decisions | jq -r '.decisions[-2] | {
  week_number,
  model_id,
  system_recommendation,
  human_decision,
  decision_reason,
  alignment,
  contract_tests_passed
} |
  {
    "Week \(week_number\): \(model_id\)",
    "System: \(system_recommendation)",
    "Human: \(human_decision)",
    "Alignment: \(if .alignment then "✅" else "❌"\)",
    "Contracts: \(if .contract_tests_passed then "✅" else "❌"\)",
    "Reason: \(decision_reason)"
  }
'

echo ""
echo "=== WEEKLY DECISION COMPLETE ==="
echo "Proceed with weekly status check: ./weekly_phase0_status.sh"
