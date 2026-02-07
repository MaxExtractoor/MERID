#!/bin/bash
# MERID Pre-Commit Hook
# Run these checks before committing to ensure system integrity

echo "🔍 Running MERID pre-commit checks..."

# Syntax validation for critical files
echo "📋 Syntax validation..."
python -m py_compile agents/__init__.py core/settings.py db/neo4j.py merid_logging_config.py
if [ $? -ne 0 ]; then
    echo "❌ Syntax validation failed"
    exit 1
fi
echo "✅ Syntax validation passed"

# System health check
echo "📋 System health check..."
python meridctl_simple.py status
if [ $? -ne 0 ]; then
    echo "❌ System health check failed"
    exit 1
fi
echo "✅ System health check passed"

# Smoke tests (quick)
echo "📋 Running smoke tests..."
python -m pytest tests/smoke -q
if [ $? -ne 0 ]; then
    echo "❌ Smoke tests failed"
    exit 1
fi
echo "✅ Smoke tests passed"

echo "🚀 All pre-commit checks passed!"
