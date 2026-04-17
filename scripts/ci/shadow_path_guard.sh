#!/bin/bash
#
# CI Shadow-Path Guard
# ====================
#
# Detects direct venue client usage that bypasses the canonical order router.
# This prevents "shadow paths" that can leak synthetic orders or bypass risk checks.
#
# Usage:
#   ./scripts/ci/shadow_path_guard.sh
#
# Exit codes:
#   0 - No shadow paths detected
#   1 - Shadow path detected (CI should fail)
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
WHITELIST_FILE=".ci/shadow_path_whitelist.txt"
SCAN_DIRS="merid execution trading"

# Patterns that indicate direct venue client usage
# These bypass the order_router and risk checks
SHADOW_PATTERNS=(
    # Direct Kalshi client instantiation
    "KalshiClient(" 
    "KalshiApiClient("
    "kalshi_client\s*="
    
    # Direct venue API calls (not through router)
    "\.create_order\(" 
    "\.submit_order\("
    "\.place_order\("
    
    # Direct HTTP calls to venue APIs
    "requests\.(post|put).*kalshi"
    "httpx\.(post|put).*kalshi"
    "aiohttp\.ClientSession.*kalshi"
    
    # Legacy direct execution patterns
    "direct_execution"
    "_submit_fast\("  # The bug from incident INC-2026-0320-001
    "bypass_router"
)

# Patterns that are allowed (router, test mocks, etc.)
ALLOWED_PATTERNS=(
    "order_router\.py"           # The canonical router itself
    "test_"                      # Test files
    "_test\.py$"                  # Test files
    "mock_"                      # Mock implementations
    "fake_"                      # Fake implementations
    "paper_session"              # Paper trading (expected bypass)
    "#.*shadow"                  # Comments about shadow paths
    "SHADOW_PATH_GUARD"          # This guard script itself
)

echo "🔍 Shadow-Path Guard: Scanning for direct venue client usage..."
echo ""

# Build grep pattern
GREP_PATTERN=$(IFS='|'; echo "${SHADOW_PATTERNS[*]}")
ALLOWED_GREP=$(IFS='|'; echo "${ALLOWED_PATTERNS[*]}")

# Track violations
VIOLATIONS=0
VIOLATION_FILES=""

# Scan each directory
for dir in $SCAN_DIRS; do
    if [[ ! -d "$dir" ]]; then
        continue
    fi
    
    while IFS= read -r file; do
        # Skip files matching allowed patterns
        skip=false
        for pattern in "${ALLOWED_PATTERNS[@]}"; do
            if [[ "$file" =~ $pattern ]]; then
                skip=true
                break
            fi
        done
        
        if [[ "$skip" == true ]]; then
            continue
        fi
        
        # Check whitelist
        if [[ -f "$WHITELIST_FILE" ]]; then
            if grep -q "^$file$" "$WHITELIST_FILE" 2>/dev/null; then
                echo -e "${YELLOW}WHITELISTED${NC}: $file"
                continue
            fi
        fi
        
        # Check for shadow patterns
        for pattern in "${SHADOW_PATTERNS[@]}"; do
            if grep -n "$pattern" "$file" 2>/dev/null | head -1 >/dev/null; then
                line=$(grep -n "$pattern" "$file" | head -1)
                echo -e "${RED}VIOLATION${NC}: $file"
                echo "  Pattern: $pattern"
                echo "  Line: $line"
                echo ""
                
                VIOLATIONS=$((VIOLATIONS + 1))
                VIOLATION_FILES="$VIOLATION_FILES\n  - $file"
                break
            fi
        done
        
    done < <(find "$dir" -name "*.py" -type f 2>/dev/null || true)
done

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [[ $VIOLATIONS -eq 0 ]]; then
    echo -e "${GREEN}✓ No shadow paths detected${NC}"
    echo ""
    echo "All venue client usage goes through the canonical order_router."
    exit 0
else
    echo -e "${RED}✗ Shadow paths detected: $VIOLATIONS${NC}"
    echo ""
    echo "Files with direct venue client usage:"
    echo -e "$VIOLATION_FILES"
    echo ""
    echo "To fix:"
    echo "  1. Route orders through order_router.py instead of direct client calls"
    echo "  2. If intentional (e.g., special case), add to whitelist:"
    echo "     echo '$file' >> $WHITELIST_FILE"
    echo ""
    echo "Reference: docs/incident_examples/synthetic_leak_2026-03-20.md"
    echo "  (Shows why direct client calls are dangerous)"
    exit 1
fi
