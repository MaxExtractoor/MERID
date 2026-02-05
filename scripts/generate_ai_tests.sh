#!/bin/bash
# AI-assisted test generation script for MERID using PyTestAI-Generator
# Requires: pip install pytestai-generator
# Requires: export DEEPSEEK_API_KEY=sk-...

set -e

# Check for API key
if [ -z "$DEEPSEEK_API_KEY" ]; then
    echo "ERROR: DEEPSEEK_API_KEY environment variable not set"
    echo "Get your key from: https://platform.deepseek.com/api_keys"
    echo "Usage: export DEEPSEEK_API_KEY='sk-...'; $0"
    exit 1
fi

# Function to generate tests for a module
generate_tests() {
    local module=$1
    local output_file=$2
    local prompt=$3
    
    echo "=== Generating tests for $module ==="
    
    # Run PyTestAI-Generator with MERID-specific settings
    pytestai-gen "$module" \
        --output="$output_file" \
        --model=deepseek-coder \
        --provider=pytest-mock \
        --include-mocks \
        --coverage-target=85 \
        --prompt="$prompt"
    
    echo "Generated: $output_file"
    echo "Review and add @pytest.mark.tier2 markers"
    echo ""
}

# First, add @include_in_test decorators to key functions
echo "=== MERID AI Test Generation Setup ==="
echo "Before running, add @include_in_test decorators to key functions:"
echo ""
echo "from pytestai_generator import include_in_test"
echo ""
echo "Example for core/cache_manager.py:"
echo "@include_in_test"
echo "def get_balance(key: str) -> float:"
echo ""
echo "Example for core/agent_orchestrator.py:"
echo "@include_in_test"
echo "async def form_consensus(self, market_data: dict) -> ConsensusResult:"
echo ""
echo "Press Enter when ready..."
read -p ""

# Generate tests for low-coverage Tier 2 modules
echo "=== Generating Test Files ==="

# Agent orchestrator (currently ~76%)
generate_tests \
    "core/agent_orchestrator.py" \
    "tests/core/test_agent_orchestrator_ai.py" \
    "Generate pytest-mock tests for agent orchestration with async context managers. Cover consensus voting, arbitrage detection, market monitoring, and error handling. Use AsyncMock for telegram methods and MagicMock for agent getters."

# Cache manager (currently ~85%)
generate_tests \
    "core/cache_manager.py" \
    "tests/core/test_cache_manager_ai.py" \
    "Generate pytest tests for LRU cache with TTL, thread safety, bulk operations, and eviction policies. Cover cache hits/misses, expiration, warming, and statistics tracking."

# Observability manager (currently ~85%)
generate_tests \
    "core/observability_manager.py" \
    "tests/core/test_observability_manager_ai.py" \
    "Generate pytest tests for logging, metrics, and alerts with structured data. Cover log levels, counter/gauges, health monitoring, background threads, and error scenarios."

echo "=== Generation Complete ==="
echo "Review and integrate the generated test files:"
echo "- tests/core/test_agent_orchestrator_ai.py"
echo "- tests/core/test_cache_manager_ai.py" 
echo "- tests/core/test_observability_manager_ai.py"
echo ""
echo "Add @pytest.mark.tier2 markers and run:"
echo "pytest --cov=core --cov-report=term-missing tests/core/"
echo ""
echo "For Tier 1 modules (95% target):"
echo "pytestai trading/execution/engine.py --model=deepseek-coder --coverage-target=95"
