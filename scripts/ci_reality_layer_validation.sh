#!/bin/bash
# CI/CD Integration Script for Domain Priority System and SIGHTED_DEGRADED Mode

# This script runs as part of the "reality layer" job in CI/CD pipeline
# It must pass before any deployment is allowed

set -e  # Exit on any failure

echo "🔍 Starting Reality Layer CI/CD Validation"
echo "=========================================="

# Configuration
PYTHON_VERSION="3.11"
COVERAGE_THRESHOLD=90
SAFETY_CHECK_TIMEOUT=300

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Helper functions
log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_info() {
    echo "ℹ️  $1"
}

# Step 1: Environment Setup
echo "📋 Step 1: Environment Setup"
echo "----------------------------"

# Check Python version
python_version=$(python3 --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
if [[ "$python_version" != "$PYTHON_VERSION" ]]; then
    log_error "Python $PYTHON_VERSION required, found $python_version"
    exit 1
fi
log_success "Python version check passed: $python_version"

# Install dependencies
log_info "Installing dependencies..."
pip install -r requirements.txt
pip install pytest pytest-cov prometheus-client

# Step 2: Unit Tests for Domain Priority System
echo "🧪 Step 2: Unit Tests - Domain Priority System"
echo "--------------------------------------------"

log_info "Running domain priority system unit tests..."
python -m pytest tests/test_domain_priority_system.py -v --cov=core/domain_priority_manager --cov-report=xml --cov-report=term --cov-fail-under=$COVERAGE_THRESHOLD

if [ $? -eq 0 ]; then
    log_success "Domain priority system unit tests passed"
else
    log_error "Domain priority system unit tests failed"
    exit 1
fi

# Step 3: Unit Tests for Mode Transitions
echo "🔄 Step 3: Unit Tests - Mode Transitions"
echo "-------------------------------------"

log_info "Running mode transition unit tests..."
python -m pytest tests/test_enhanced_sighted_degraded_mode.py -v --cov=core/reality_auditor --cov-report=xml --cov-report=term --cov-fail-under=$COVERAGE_THRESHOLD

if [ $? -eq 0 ]; then
    log_success "Mode transition unit tests passed"
else
    log_error "Mode transition unit tests failed"
    exit 1
fi

# Step 4: Fault Injection Tests
echo "💥 Step 4: Fault Injection Tests"
echo "-----------------------------"

log_info "Running fault injection tests..."
python -m pytest tests/test_fault_injection.py -v --tb=short

if [ $? -eq 0 ]; then
    log_success "Fault injection tests passed"
else
    log_error "Fault injection tests failed"
    exit 1
fi

# Step 5: Integration Tests - SIGHTED_DEGRADED Activation
echo "🚀 Step 5: Integration Tests - SIGHTED_DEGRADED Activation"
echo "-----------------------------------------------------"

log_info "Starting integration test environment..."

# Start the server in background
python -m web.main &
SERVER_PID=$!

# Wait for server to start
log_info "Waiting for server to start..."
for i in {1..30}; do
    if curl -s http://127.0.0.1:8001/api/v1/reality/status > /dev/null; then
        log_success "Server started successfully"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Server failed to start within 30 seconds"
        kill $SERVER_PID 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# Run integration test
log_info "Running SIGHTED_DEGRADED integration test..."
python test_production_sighted_degraded_activation.py

INTEGRATION_RESULT=$?

# Stop the server
log_info "Stopping server..."
kill $SERVER_PID 2>/dev/null || true
wait $SERVER_PID 2>/dev/null || true

if [ $INTEGRATION_RESULT -eq 0 ]; then
    log_success "SIGHTED_DEGRADED integration test passed"
else
    log_error "SIGHTED_DEGRADED integration test failed"
    exit 1
fi

# Step 6: Safety Check Validation
echo "🛡️  Step 6: Safety Check Validation"
echo "-----------------------------------"

log_info "Running safety check validation..."

# Create a temporary test script
cat > safety_check_validation.py << 'EOF'
import requests
import time
import json

def validate_safety_checks():
    """Validate that safety checks properly block unsafe operations."""
    
    # Load demo data to trigger safety checks
    domains = ["market", "onchain", "simulation", "agent"]
    
    for domain in domains:
        response = requests.post(f"http://127.0.0.1:8001/api/v1/{domain}/demo-data", timeout=10)
        if response.status_code != 200:
            print(f"❌ Failed to load {domain} demo data")
            return False
    
    # Check that execution is still blocked
    response = requests.post("http://127.0.0.1:8001/api/v1/domain-priority/check-access", 
                           json={"domain": "execution", "operation": "execute", "actor_id": "safety_test"}, 
                           timeout=10)
    
    if response.status_code != 200:
        print("❌ Failed to check execution access")
        return False
    
    result = response.json()
    if result.get("allowed", False):
        print("❌ Execution should be blocked by safety checks")
        return False
    
    print("✅ Safety checks properly block unsafe operations")
    return True

if __name__ == "__main__":
    success = validate_safety_checks()
    exit(0 if success else 1)
EOF

# Run safety check validation
python safety_check_validation.py

if [ $? -eq 0 ]; then
    log_success "Safety check validation passed"
else
    log_error "Safety check validation failed"
    exit 1
fi

# Step 7: Priority Violation Detection
echo "🚫 Step 7: Priority Violation Detection"
echo "--------------------------------------"

log_info "Testing priority violation detection..."

# Create violation detection test
cat > violation_detection_test.py << 'EOF'
import requests
import time

def test_violation_detection():
    """Test that priority violations are detected and logged."""
    
    # Try to access blocked domains
    blocked_domains = ["execution", "governance", "treasury", "system"]
    operations = ["execute", "write", "read"]
    
    violations_detected = 0
    
    for domain in blocked_domains:
        for operation in operations:
            response = requests.post("http://127.0.0.1:8001/api/v1/domain-priority/check-access",
                                   json={"domain": domain, "operation": operation, "actor_id": "violation_test"},
                                   timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                if not result.get("allowed", True):
                    violations_detected += 1
    
    # Check violations endpoint
    response = requests.get("http://127.0.0.1:8001/api/v1/domain-priority/violations", timeout=10)
    
    if response.status_code == 200:
        violations_data = response.json()
        logged_violations = violations_data.get("total_count", 0)
        
        if logged_violations >= violations_detected:
            print(f"✅ Priority violations detected and logged: {logged_violations}")
            return True
        else:
            print(f"❌ Expected {violations_detected} violations, found {logged_violations}")
            return False
    else:
        print("❌ Failed to retrieve violations")
        return False

if __name__ == "__main__":
    success = test_violation_detection()
    exit(0 if success else 1)
EOF

# Run violation detection test
python violation_detection_test.py

if [ $? -eq 0 ]; then
    log_success "Priority violation detection passed"
else
    log_error "Priority violation detection failed"
    exit 1
fi

# Step 8: Metrics Validation
echo "📊 Step 8: Metrics Validation"
echo "----------------------------"

log_info "Validating metrics collection..."

# Create metrics validation test
cat > metrics_validation_test.py << 'EOF'
import requests
import time

def test_metrics_availability():
    """Test that metrics are available and being collected."""
    
    # Test that metrics endpoint is accessible
    response = requests.get("http://127.0.0.1:8001/metrics", timeout=10)
    
    if response.status_code != 200:
        print("❌ Metrics endpoint not accessible")
        return False
    
    metrics_text = response.text
    
    # Check for key metrics
    required_metrics = [
        "reality_valid_assertions",
        "reality_mode",
        "reality_priority_violations_total",
        "reality_safety_checks_passed"
    ]
    
    missing_metrics = []
    for metric in required_metrics:
        if metric not in metrics_text:
            missing_metrics.append(metric)
    
    if missing_metrics:
        print(f"❌ Missing metrics: {missing_metrics}")
        return False
    
    print("✅ All required metrics are available")
    return True

if __name__ == "__main__":
    success = test_metrics_availability()
    exit(0 if success else 1)
EOF

# Run metrics validation
python metrics_validation_test.py

if [ $? -eq 0 ]; then
    log_success "Metrics validation passed"
else
    log_error "Metrics validation failed"
    exit 1
fi

# Step 9: Audit Trail Validation
echo "📋 Step 9: Audit Trail Validation"
echo "--------------------------------"

log_info "Validating audit trail functionality..."

# Check that audit log file exists and is being written
if [ -f "audit/mode_transitions.jsonl" ]; then
    log_success "Audit log file exists"
    
    # Check that audit log has entries
    if [ -s "audit/mode_transitions.jsonl" ]; then
        log_success "Audit log has entries"
        
        # Validate JSON format of recent entries
        tail -n 5 audit/mode_transitions.jsonl | while read line; do
            if [[ "$line" != "#"* ]]; then
                if ! echo "$line" | python -m json.tool > /dev/null 2>&1; then
                    log_error "Invalid JSON in audit log: $line"
                    exit 1
                fi
            fi
        done
        
        log_success "Audit log JSON format is valid"
    else
        log_error "Audit log file is empty"
        exit 1
    fi
else
    log_error "Audit log file does not exist"
    exit 1
fi

# Step 10: Final Validation Summary
echo "📋 Step 10: Final Validation Summary"
echo "--------------------------------"

log_success "All CI/CD reality layer checks passed!"
echo ""
echo "🎯 VALIDATION SUMMARY:"
echo "✅ Environment setup complete"
echo "✅ Domain priority system unit tests passed"
echo "✅ Mode transition unit tests passed"
echo "✅ Fault injection tests passed"
echo "✅ SIGHTED_DEGRADED integration test passed"
echo "✅ Safety check validation passed"
echo "✅ Priority violation detection working"
echo "✅ Metrics collection validated"
echo "✅ Audit trail functionality verified"
echo ""
echo "🚀 READY FOR DEPLOYMENT!"
echo "The reality layer with domain priority system and SIGHTED_DEGRADED mode"
echo "has passed all production safety and quality gates."

# Clean up temporary files
rm -f safety_check_validation.py violation_detection_test.py metrics_validation_test.py

exit 0
