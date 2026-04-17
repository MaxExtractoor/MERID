#!/bin/bash
# Anti-Regression CI Script for MERID Kalshi Pipeline
# 
# This script enforces the "No Custom Math" rule from AGENT_AUDIT_KALSHI_SENTIMENT.md
# Section 14. It fails the build if any Kelly, Brier, sentiment aggregation, or
# drawdown logic is found outside of merid/formulas.py.
#
# Usage: ./scripts/ci_check_formulas.sh
# Exit: 0 if clean, 1 if violations found

set -euo pipefail

echo "=== MERID Formula Anti-Regression Check ==="
echo "Checking for duplicate formula implementations outside merid/formulas.py..."
echo ""

# Patterns that should ONLY appear in merid/formulas.py or its tests
FORBIDDEN_PATTERNS=(
    # Kelly criterion patterns
    "kelly_fraction\s*="
    "kelly_criterion"
    "fractional.*kelly"
    
    # Brier score patterns
    "brier_score\s*="
    "\(forecast.*-\s*outcome\)\s*\*\*\s*2"
    "\(prob.*-\s*actual\)\s*\*\*\s*2"
    
    # Sentiment aggregation patterns
    "volume_weighted_sentiment"
    "weighted.*sentiment"
    "sentiment.*aggregate"
    
    # Drawdown tier patterns  
    "drawdown_tier"
    "downsize_at\s*="
    "halt_at\s*="
)

VIOLATIONS=0
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

check_pattern() {
    local pattern="$1"
    local description="$2"
    
    # Search for pattern, excluding merid/formulas.py and test files
    local matches
    matches=$(grep -r "${pattern}" \
        --include="*.py" \
        "${PROJECT_ROOT}/merid" \
        "${PROJECT_ROOT}/core" \
        "${PROJECT_ROOT}/streams" 2>/dev/null \
        | grep -v "merid/formulas.py" \
        | grep -v "test_formulas" \
        | grep -v "from merid.formulas import" \
        | grep -v "merid/formulas import" \
        || true)
    
    if [ -n "$matches" ]; then
        echo "❌ VIOLATION: ${description}"
        echo "   Pattern: ${pattern}"
        echo "   Found in:"
        echo "$matches" | head -5 | sed 's/^/     /'
        if [ $(echo "$matches" | wc -l) -gt 5 ]; then
            echo "     ... ($(echo "$matches" | wc -l) total matches)"
        fi
        echo ""
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
}

echo "Checking forbidden patterns..."
echo ""

check_pattern "kelly_fraction\s*=" "Kelly fraction implementation outside formulas.py"
check_pattern "brier_score\s*=" "Brier score implementation outside formulas.py"
check_pattern "\(p.*-\s*o\)\s*\*\*\s*2" "Brier formula (prob - outcome)**2 outside formulas.py"
check_pattern "volume_weighted_sentiment" "Volume-weighted sentiment outside formulas.py"
check_pattern "drawdown_tier_action" "Drawdown tier logic outside formulas.py"

echo ""
echo "Checking for proper imports..."
echo ""

# Verify merid/formulas.py exports the expected symbols
REQUIRED_EXPORTS=(
    "FORMULAS_VERSION"
    "AUDIT_SPEC_VERSION"
    "get_version_info"
    "generate_correlation_id"
    "kelly_fraction"
    "quarter_kelly_size"
    "brier_score"
    "debate_lift"
    "volume_weighted_sentiment"
    "drawdown_tier_action"
)

for export in "${REQUIRED_EXPORTS[@]}"; do
    if grep -q "^${export}\s*=" "${PROJECT_ROOT}/merid/formulas.py" || \
       grep -q "^def ${export}" "${PROJECT_ROOT}/merid/formulas.py" || \
       grep -q "^class ${export}" "${PROJECT_ROOT}/merid/formulas.py"; then
        echo "  ✅ ${export} found in merid/formulas.py"
    else
        echo "  ❌ ${export} NOT FOUND in merid/formulas.py"
        VIOLATIONS=$((VIOLATIONS + 1))
    fi
done

echo ""

# Check that __all__ includes versioning
if grep -q "FORMULAS_VERSION" "${PROJECT_ROOT}/merid/formulas.py" && \
   grep -A 20 "^__all__" "${PROJECT_ROOT}/merid/formulas.py" | grep -q "FORMULAS_VERSION"; then
    echo "  ✅ FORMULAS_VERSION exported in __all__"
else
    echo "  ❌ FORMULAS_VERSION not exported in __all__"
    VIOLATIONS=$((VIOLATIONS + 1))
fi

# Check that __all__ includes correlation ID
if grep -A 20 "^__all__" "${PROJECT_ROOT}/merid/formulas.py" | grep -q "generate_correlation_id"; then
    echo "  ✅ generate_correlation_id exported in __all__"
else
    echo "  ❌ generate_correlation_id not exported in __all__"
    VIOLATIONS=$((VIOLATIONS + 1))
fi

echo ""

if [ $VIOLATIONS -eq 0 ]; then
    echo "✅ All checks passed! No formula regressions detected."
    echo ""
    echo "Remember: All Kelly/Brier/sentiment/drawdown logic must import from merid.formulas"
    exit 0
else
    echo "❌ ${VIOLATIONS} violation(s) found!"
    echo ""
    echo "Fixes required:"
    echo "1. Remove duplicate implementations"
    echo "2. Import from merid.formulas instead"
    echo "3. Reference: AGENT_AUDIT_KALSHI_SENTIMENT.md Section 14"
    exit 1
fi
