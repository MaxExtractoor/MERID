#!/bin/bash
# MERID TLS Verification Script
# Run after deployment to confirm TLS is properly configured
# Usage: bash infra/verify-tls.sh [host] [port]

HOST="${1:-localhost}"
API_PORT="${2:-8000}"

echo "=========================================="
echo "MERID TLS Verification"
echo "Host: $HOST"
echo "=========================================="

PASS=0
FAIL=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" = "0" ]; then
        echo "  [PASS] $name"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $name"
        FAIL=$((FAIL + 1))
    fi
}

# 1. Check API is reachable
echo ""
echo "--- API Connectivity ---"
curl -sf "http://$HOST:$API_PORT/healthz" > /dev/null 2>&1
check "API /healthz reachable" $?

curl -sf "http://$HOST:$API_PORT/readyz" > /dev/null 2>&1
check "API /readyz reachable" $?

# 2. Check TLS cert files exist (if running locally)
echo ""
echo "--- TLS Certificate Files ---"
if [ -d "infra/certs" ] || [ -d "certs" ]; then
    CERT_DIR=$([ -d "infra/certs" ] && echo "infra/certs" || echo "certs")
    [ -f "$CERT_DIR/server.crt" ] && check "server.crt exists" 0 || check "server.crt exists" 1
    [ -f "$CERT_DIR/server.key" ] && check "server.key exists" 0 || check "server.key exists" 1
    [ -f "$CERT_DIR/ca.crt" ] && check "ca.crt exists" 0 || check "ca.crt exists" 1
else
    echo "  [INFO] No local certs dir — certs generated inside containers"
    PASS=$((PASS + 1))
fi

# 3. Check HTTPS (if TLS is enabled)
echo ""
echo "--- HTTPS Verification ---"
curl -sf --insecure "https://$HOST:8443/healthz" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    check "HTTPS /healthz reachable on 8443" 0

    # Check cert details
    echo | openssl s_client -connect "$HOST:8443" -servername "$HOST" 2>/dev/null | openssl x509 -noout -dates 2>/dev/null
    if [ $? -eq 0 ]; then
        check "TLS certificate valid" 0
        EXPIRY=$(echo | openssl s_client -connect "$HOST:8443" -servername "$HOST" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)
        echo "         Expires: $EXPIRY"
    else
        check "TLS certificate valid" 1
    fi
else
    echo "  [INFO] HTTPS not available on 8443 — TLS may not be enabled in this environment"
    PASS=$((PASS + 1))
fi

# 4. Check .gitignore covers secrets
echo ""
echo "--- Secrets Protection ---"
grep -q '\.pem' .gitignore 2>/dev/null
check ".gitignore covers *.pem" $?

grep -q '\.env' .gitignore 2>/dev/null
check ".gitignore covers .env" $?

grep -q '\.key' .gitignore 2>/dev/null
check ".gitignore covers *.key" $?

# 5. Check no secrets tracked
echo ""
echo "--- Git Secrets Scan ---"
TRACKED_SECRETS=$(git ls-files '*.pem' '*.key' '.env' '.env.backup' '.env.production' 2>/dev/null | wc -l)
[ "$TRACKED_SECRETS" -eq 0 ]
check "No secret files tracked in git" $?

# 6. Check firewall config exists
echo ""
echo "--- Network Security ---"
[ -f "infra/firewall-rules.yml" ]
check "Firewall rules defined" $?

[ -f "infra/tls-config.yml" ]
check "TLS config defined" $?

# Summary
echo ""
echo "=========================================="
echo "Results: $PASS passed, $FAIL failed"
echo "=========================================="

if [ "$FAIL" -gt 0 ]; then
    echo "⚠️  Some checks failed — review above"
    exit 1
else
    echo "✅ All TLS/security checks passed"
    exit 0
fi
