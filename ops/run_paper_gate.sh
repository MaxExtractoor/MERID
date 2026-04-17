#!/bin/bash
# MERID Paper Gate Ops Wrapper
# Production/VPS helper for running validation gates
#
# Usage:
#   ./ops/run_paper_gate.sh --duration 1800 --gate-id pre_live_check
#   ./ops/run_paper_gate.sh --dry-run
#
# This wrapper ensures proper environment setup and artifact storage.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERID_ROOT="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="${MERID_ROOT}/validation_results"

# Ensure results directory exists
mkdir -p "$RESULTS_DIR"

# Safety: ensure paper mode
echo "🔒 Enforcing paper mode..."
export MERID_TRADE_MODE=paper
export MERID_ALLOW_LIVE_TRADES=false

# Parse arguments
DURATION="1800"
GATE_ID=""
DRY_RUN=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --duration)
      DURATION="$2"
      shift 2
      ;;
    --gate-id)
      GATE_ID="$2"
      shift 2
      ;;
    --dry-run)
      DRY_RUN="--dry-run"
      shift
      ;;
    --help|-h)
      cat << 'EOF'
MERID Paper Gate Ops Wrapper

Usage: ./ops/run_paper_gate.sh [OPTIONS]

Options:
  --duration SECONDS   Gate duration (default: 1800 = 30 min)
  --gate-id ID         Unique gate identifier
  --dry-run            Quick 2-minute wiring check
  --help, -h           Show this help

Examples:
  # Quick wiring check
  ./ops/run_paper_gate.sh --dry-run

  # Standard 30-minute gate
  ./ops/run_paper_gate.sh --duration 1800 --gate-id pre_live_$(date +%Y%m%d)

  # 1-hour extended gate
  ./ops/run_paper_gate.sh --duration 3600 --gate-id extended_check

Results are saved to: ./validation_results/
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Auto-generate gate ID if not provided
if [[ -z "$GATE_ID" ]]; then
  GATE_ID="ops_$(date +%Y%m%d_%H%M%S)"
fi

echo "🚀 Starting MERID Paper Gate"
echo "   Gate ID: $GATE_ID"
echo "   Duration: $DURATION seconds"
echo "   Results: $RESULTS_DIR"
echo ""

# Run the gate
cd "$MERID_ROOT"
python scripts/run_paper_gate.py \
  --duration "$DURATION" \
  --gate-id "$GATE_ID" \
  --output-dir "$RESULTS_DIR" \
  $DRY_RUN

EXIT_CODE=$?

echo ""
if [[ $EXIT_CODE -eq 0 ]]; then
  echo "✅ Gate PASSED - Results in $RESULTS_DIR"
  echo ""
  echo "Next steps:"
  echo "  1. Review the JSON report"
  echo "  2. Copy gate summary to fix_history.md:"
  echo "     cat $RESULTS_DIR/gate_summary_$GATE_ID.md"
else
  echo "❌ Gate FAILED (exit code $EXIT_CODE)"
  echo "   Review logs and report in $RESULTS_DIR"
  echo "   Open ANOMALY entry in fix_history.md"
fi

exit $EXIT_CODE
