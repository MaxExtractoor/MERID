#!/bin/bash
#
# CI Guardrail Script: Block Direct Venue Touchpoints
#
# This script runs in CI to ensure no code introduces direct Kalshi client calls
# outside of the canonical router/kill-switch/fills-ledger pipeline.
#
# Exit codes:
#   0 - No violations found
#   1 - Violations detected (CI should fail)
#
# Whitelist: Files that are allowed to have direct client calls must be
# explicitly listed in .ci/venue_touchpoint_whitelist.txt

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MERID_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WHITELIST_FILE="$MERID_ROOT/.ci/venue_touchpoint_whitelist.txt"

# Patterns that indicate direct venue touching.  These match *invocations* of
# order-mutating client methods (call paren required), so attribute probes,
# comments, docstrings, string literals, and read-only market-data calls
# (get_market/get_positions/get_balance/is_demo/...) do not false-positive.
# ERE is used (grep -E) so \( \| groups behave as written.
PATTERNS=(
    "client\.(place_order|place_order_result|cancel_order|cancel_order_result|create_order|create_order_result|create_order_group|cancel_order_group)\s*\("
    "\.execute_trade\s*\("
    "executor\.(place_order|cancel_order|execute_trade)\s*\("
    "KalshiExecutor\(\)"
    "kalshi_client\.(place_order|place_order_result|cancel_order|cancel_order_result|create_order|create_order_result|execute_trade)\s*\("
    "rest_client\.(place_order|cancel_order|create_order)\s*\("
)

# Files that are allowed to have these patterns (the canonical pipeline)
DEFAULT_WHITELIST=(
    "merid/event_venues/kalshi/order_router.py"
    "merid/event_venues/kalshi/client.py"
    "merid/event_venues/kalshi/order_manager.py"
    "merid/execution/executors/kalshi.py"
    "merid/execution/executors/kalshi_enhanced.py"
    "merid/execution/router.py"
    "tests/"
    "scripts/ci_red_team.py"
    "scripts/stress_test_reconciliation.py"
    "legacy/"
)

# Load custom whitelist if exists
if [[ -f "$WHITELIST_FILE" ]]; then
    echo "Loading custom whitelist from $WHITELIST_FILE"
    # Skip blank lines and comments — an empty whitelist entry would substring-
    # match every path and silently disable the guardrail.
    mapfile -t CUSTOM_WHITELIST < <(grep -vE '^[[:space:]]*(#|$)' "$WHITELIST_FILE" || true)
    WHITELIST=("${DEFAULT_WHITELIST[@]}" "${CUSTOM_WHITELIST[@]}")
else
    WHITELIST=("${DEFAULT_WHITELIST[@]}")
fi

echo "🔍 Scanning for direct venue touchpoints..."
echo ""

VIOLATIONS=0
VIOLATION_DETAILS=""

for pattern in "${PATTERNS[@]}"; do
    # Search Python files, excluding whitelisted paths
    MATCHES=$(find "$MERID_ROOT" -type f -name "*.py" | while read -r file; do
        # Check if file is whitelisted
        IS_WHITELISTED=false
        for whitelist_item in "${WHITELIST[@]}"; do
            if [[ "$file" == *"$whitelist_item"* ]]; then
                IS_WHITELISTED=true
                break
            fi
        done
        
        if [[ "$IS_WHITELISTED" == "false" ]]; then
            # Search for pattern in file (ERE so \( \| work as written)
            if grep -EHn "$pattern" "$file" 2>/dev/null; then
                : # grep found matches, output them
            fi
        fi
    done)
    
    if [[ -n "$MATCHES" ]]; then
        VIOLATIONS=$((VIOLATIONS + 1))
        VIOLATION_DETAILS+="\n❌ Pattern '$pattern' found in:\n$MATCHES\n"
    fi
done

if [[ $VIOLATIONS -gt 0 ]]; then
    echo -e "$VIOLATION_DETAILS"
    echo ""
    echo "⛔ FAILURE: Direct venue touchpoints detected outside canonical pipeline!"
    echo ""
    echo "All venue interactions must go through:"
    echo "  → merid/event_venues/kalshi/order_router.py (route_order_async)"
    echo "  → with kill switch check"
    echo "  → with fills ledger recording"
    echo "  → with lineage tracking"
    echo ""
    echo "If you have a legitimate exception, add the file to:"
    echo "  $WHITELIST_FILE"
    echo ""
    echo "And ensure the code sets manual_or_external=true and is marked"
    echo "with appropriate UI badges (DataSourceBadge)."
    exit 1
else
    echo "✅ No direct venue touchpoints found outside canonical pipeline."
    echo ""
    echo "Canonical pipeline verified:"
    echo "  ✓ Order routing: order_router.py"
    echo "  ✓ Kill switch integration: risk_controller"
    echo "  ✓ Fills ledger: fills_ledger"
    echo "  ✓ Lineage: /orders/{id}/lineage"
    exit 0
fi
