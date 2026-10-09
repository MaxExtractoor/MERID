#!/bin/bash
# Kalshi Event Dashboard Startup Script

echo "🚀 Starting Kalshi Event Dashboard..."
echo "📋 Prerequisites:"
echo "   1. FastAPI server running on http://localhost:8000"
echo "   2. Kalshi event bus initialized and emitting events"
echo "   3. Streamlit dashboard dependencies installed"
echo ""

# Check if requirements are installed
echo "🔍 Checking dependencies..."
if ! python -c "import streamlit, plotly, pandas, requests" 2>/dev/null; then
    echo "📦 Installing dashboard dependencies..."
    pip install -r requirements_dashboard.txt
fi

# Check if FastAPI server is running
echo "🔍 Checking FastAPI server..."
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ FastAPI server is running"
else
    echo "⚠️  FastAPI server not detected on http://localhost:8000"
    echo "💡 Make sure to start your FastAPI app first:"
    echo "   python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "❌ Exiting. Please start FastAPI server first."
        exit 1
    fi
fi

# Start Streamlit dashboard
echo "🚀 Starting Streamlit dashboard..."
echo "🌐 Dashboard will be available at: http://localhost:8501"
echo "📊 Open your browser and navigate to the dashboard URL"
echo ""
echo "🔄 The dashboard will auto-refresh every 2 seconds"
echo "⚙️  Use the sidebar to filter events and control refresh"
echo ""

# Start Streamlit
streamlit run kalshi_event_dashboard.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless false \
    --browser.gatherUsageStats false
