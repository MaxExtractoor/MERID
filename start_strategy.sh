#!/bin/bash
# Strategy Startup Script

echo "🚀 Starting 15M Crypto Strategy..."
echo "📋 Prerequisites:"
echo "   1. Event bus and FastAPI server running"
echo "   2. Strategy dependencies installed"
echo "   3. Kalshi API credentials configured"
echo ""

# Check if strategy dependencies are installed
echo "🔍 Checking strategy dependencies..."
if ! python -c "import numpy, pandas, schedule" 2>/dev/null; then
    echo "📦 Installing strategy dependencies..."
    pip install -r requirements_strategy.txt
fi

# Check if FastAPI server is running
echo "🔍 Checking FastAPI server..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ FastAPI server is running"
else
    echo "⚠️  FastAPI server not detected on http://localhost:8000"
    echo "💡 Make sure to start your FastAPI app first:"
    echo "   python -m uvicorn merid.api.main:app --host 0.0.0.0 --port 8000 --reload"
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Exiting. Please start FastAPI server first."
        exit 1
    fi
fi

# Start strategy
echo "🚀 Starting 15M Crypto Strategy..."
echo "📊 Strategy will run cycles every 15 minutes"
echo "📱 Use strategy_dashboard.py for monitoring"
echo "📱 Use Streamlit dashboard at http://localhost:8501"
echo ""

# Start strategy manager
python -c "
from merid.strategies.strategy_integration import strategy_manager
strategy_manager.start_strategy()
print('Strategy started. Press Ctrl+C to stop.')
try:
    while True:
        import time
        time.sleep(1)
except KeyboardInterrupt:
    strategy_manager.stop_strategy()
    print('Strategy stopped.')
"
