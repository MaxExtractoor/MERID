#!/usr/bin/env bash
# Pre-commit hook: reject commits that add secret files or patterns.
# Install: cp scripts/pre-commit-secrets-check.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

set -euo pipefail

RED='\033[0;31m'
NC='\033[0m'

BLOCKED_PATTERNS=(
    '*.pem'
    '*.key'
    '*.p12'
    '*.pfx'
    '*.jks'
    '*.keystore'
    '.env'
    '.env.*'
    '.env.backup'
    'vault-token'
    '.vault-token'
)

BLOCKED_CONTENT_PATTERNS=(
    'PRIVATE KEY'
    'BEGIN RSA'
    'BEGIN EC PRIVATE'
    'BEGIN DSA PRIVATE'
    'sk-[a-zA-Z0-9]{20,}'
    'AKIA[0-9A-Z]{16}'
)

EXIT_CODE=0

# Check staged files against blocked filename patterns
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)

for file in $STAGED_FILES; do
    for pattern in "${BLOCKED_PATTERNS[@]}"; do
        case "$file" in
            $pattern)
                echo -e "${RED}BLOCKED:${NC} Staged file '$file' matches secret pattern '$pattern'"
                EXIT_CODE=1
                ;;
        esac
    done
done

# Check staged file contents for secret patterns
for file in $STAGED_FILES; do
    if [ -f "$file" ]; then
        for pattern in "${BLOCKED_CONTENT_PATTERNS[@]}"; do
            if git diff --cached -- "$file" | grep -qE "$pattern" 2>/dev/null; then
                echo -e "${RED}BLOCKED:${NC} File '$file' contains secret pattern '$pattern'"
                EXIT_CODE=1
            fi
        done
    fi
done

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "Commit rejected: secret files or patterns detected."
    echo "If this is intentional, use: git commit --no-verify"
    exit 1
fi

exit 0
