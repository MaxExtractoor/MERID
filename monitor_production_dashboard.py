#!/usr/bin/env python3
"""
MERID Predictions Production Monitoring Dashboard

This script provides real-time monitoring of the predictions API endpoints
and generates a comprehensive production dashboard.

Usage:
    python monitor_production_dashboard.py [--port 8080] [--refresh 30]
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Any
import requests
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="MERID Predictions Monitor")

# Global state
monitoring_data = {
    "last_update": None,
    "endpoints": {},
    "alerts": [],
    "metrics": {
        "total_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "average_response_time": 0,
        "data_freshness": None
    }
}

class ProductionMonitor:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.endpoints = [
            "/api/v1/institutional/predictions/markets",
            "/api/v1/institutional/predictions/drift", 
            "/api/v1/institutional/predictions/arbitrage"
        ]
    
    async def check_endpoint(self, endpoint: str) -> Dict[str, Any]:
        """Check a single endpoint and return status."""
        start_time = time.time()
        
        try:
            response = requests.get(f"{self.base_url}{endpoint}", timeout=10)
            response_time = (time.time() - start_time) * 1000
            
            if response.status_code == 200:
                data = response.json()
                
                # Extract key metrics
                data_key = self.get_data_key(endpoint)
                items = data.get(data_key, [])
                
                # Check freshness for live data
                freshness = None
                if "data_freshness" in data:
                    freshness_info = data["data_freshness"]
                    if "last_update" in freshness_info:
                        try:
                            last_update = datetime.fromisoformat(freshness_info["last_update"].replace('Z', '+00:00'))
                            age = (datetime.now(timezone.utc) - last_update).total_seconds()
                            freshness = {
                                "age_seconds": round(age, 2),
                                "max_age": freshness_info.get("max_age_seconds", 30),
                                "is_fresh": age <= freshness_info.get("max_age_seconds", 30)
                            }
                        except ValueError:
                            freshness = {"error": "Invalid timestamp"}
                
                return {
                    "status": "success",
                    "status_code": response.status_code,
                    "response_time_ms": round(response_time, 2),
                    "item_count": len(items),
                    "freshness": freshness,
                    "last_check": datetime.now(timezone.utc).isoformat(),
                    "sample_data": items[0] if items else None
                }
            else:
                return {
                    "status": "error",
                    "status_code": response.status_code,
                    "response_time_ms": round(response_time, 2),
                    "error": response.text,
                    "last_check": datetime.now(timezone.utc).isoformat()
                }
                
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "response_time_ms": round((time.time() - start_time) * 1000, 2),
                "last_check": datetime.now(timezone.utc).isoformat()
            }
    
    def get_data_key(self, endpoint: str) -> str:
        """Get the key that contains the main data array for each endpoint."""
        if "/markets" in endpoint:
            return "markets"
        elif "/drift" in endpoint:
            return "signals"
        elif "/arbitrage" in endpoint:
            return "opportunities"
        else:
            return "data"
    
    async def check_all_endpoints(self) -> Dict[str, Any]:
        """Check all endpoints and return comprehensive status."""
        results = {}
        total_response_time = 0
        successful_count = 0
        
        for endpoint in self.endpoints:
            result = await self.check_endpoint(endpoint)
            results[endpoint] = result
            total_response_time += result.get("response_time_ms", 0)
            
            if result["status"] == "success":
                successful_count += 1
        
        # Update global metrics
        monitoring_data["metrics"]["total_requests"] += 1
        monitoring_data["metrics"]["successful_requests"] += successful_count
        monitoring_data["metrics"]["failed_requests"] += (len(self.endpoints) - successful_count)
        monitoring_data["metrics"]["average_response_time"] = total_response_time / len(self.endpoints)
        monitoring_data["last_update"] = datetime.now(timezone.utc).isoformat()
        monitoring_data["endpoints"] = results
        
        # Generate alerts
        alerts = self.generate_alerts(results)
        monitoring_data["alerts"] = alerts
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoints": results,
            "metrics": monitoring_data["metrics"],
            "alerts": alerts,
            "overall_status": "healthy" if successful_count == len(self.endpoints) else "degraded"
        }
    
    def generate_alerts(self, results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate alerts based on endpoint status."""
        alerts = []
        
        for endpoint, result in results.items():
            if result["status"] == "error":
                alerts.append({
                    "level": "critical",
                    "endpoint": endpoint,
                    "message": f"Endpoint returned error: {result.get('error', 'Unknown error')}",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            
            # Check response time
            if result.get("response_time_ms", 0) > 5000:
                alerts.append({
                    "level": "warning",
                    "endpoint": endpoint,
                    "message": f"Slow response time: {result.get('response_time_ms', 0)}ms",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            
            # Check data freshness
            freshness = result.get("freshness", {})
            if freshness and not freshness.get("is_fresh", True):
                alerts.append({
                    "level": "warning",
                    "endpoint": endpoint,
                    "message": f"Stale data: {freshness.get('age_seconds', 0)}s old (max: {freshness.get('max_age', 30)}s)",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
            
            # Check empty data
            if result.get("item_count", 0) == 0 and result["status"] == "success":
                alerts.append({
                    "level": "info",
                    "endpoint": endpoint,
                    "message": "No data returned from endpoint",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
        
        return alerts

# Global monitor instance
monitor = ProductionMonitor()

@app.get("/")
async def dashboard():
    """Serve the monitoring dashboard."""
    return Response(generate_dashboard_html(), media_type="text/html")

@app.get("/api/status")
async def get_status():
    """Get current monitoring status."""
    return await monitor.check_all_endpoints()

@app.get("/api/metrics")
async def get_metrics():
    """Get detailed metrics."""
    return monitoring_data

def generate_dashboard_html() -> str:
    """Generate the HTML dashboard."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>MERID Predictions Monitor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
    <style>
        .status-healthy { background-color: #10b981; }
        .status-degraded { background-color: #f59e0b; }
        .status-error { background-color: #ef4444; }
        .alert-critical { border-left: 4px solid #ef4444; }
        .alert-warning { border-left: 4px solid #f59e0b; }
        .alert-info { border-left: 4px solid #3b82f6; }
    </style>
</head>
<body class="bg-gray-900 text-white p-6">
    <div class="max-w-7xl mx-auto">
        <h1 class="text-3xl font-bold mb-6">🎯 MERID Predictions Monitor</h1>
        
        <!-- Overall Status -->
        <div id="overall-status" class="mb-6 p-4 rounded-lg bg-gray-800">
            <h2 class="text-xl font-semibold mb-2">Overall Status</h2>
            <div class="flex items-center space-x-4">
                <div id="status-indicator" class="px-3 py-1 rounded-full text-sm font-medium">
                    Loading...
                </div>
                <div id="last-update" class="text-gray-400">
                    Last update: --
                </div>
            </div>
        </div>
        
        <!-- Metrics -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
            <div class="bg-gray-800 p-4 rounded-lg">
                <h3 class="text-sm font-medium text-gray-400">Total Requests</h3>
                <p id="total-requests" class="text-2xl font-bold">--</p>
            </div>
            <div class="bg-gray-800 p-4 rounded-lg">
                <h3 class="text-sm font-medium text-gray-400">Success Rate</h3>
                <p id="success-rate" class="text-2xl font-bold">--</p>
            </div>
            <div class="bg-gray-800 p-4 rounded-lg">
                <h3 class="text-sm font-medium text-gray-400">Avg Response Time</h3>
                <p id="avg-response-time" class="text-2xl font-bold">--</p>
            </div>
            <div class="bg-gray-800 p-4 rounded-lg">
                <h3 class="text-sm font-medium text-gray-400">Data Freshness</h3>
                <p id="data-freshness" class="text-2xl font-bold">--</p>
            </div>
        </div>
        
        <!-- Endpoints -->
        <div class="mb-6">
            <h2 class="text-xl font-semibold mb-4">Endpoint Status</h2>
            <div id="endpoints" class="space-y-4">
                <!-- Endpoint cards will be inserted here -->
            </div>
        </div>
        
        <!-- Alerts -->
        <div class="mb-6">
            <h2 class="text-xl font-semibold mb-4">Alerts</h2>
            <div id="alerts" class="space-y-2">
                <!-- Alerts will be inserted here -->
            </div>
        </div>
    </div>
    
    <script>
        async function updateDashboard() {
            try {
                const response = await axios.get('/api/status');
                const data = response.data;
                
                // Update overall status
                const statusIndicator = document.getElementById('status-indicator');
                statusIndicator.textContent = data.overall_status.toUpperCase();
                statusIndicator.className = `px-3 py-1 rounded-full text-sm font-medium status-${data.overall_status}`;
                
                // Update last update
                document.getElementById('last-update').textContent = `Last update: ${new Date(data.timestamp).toLocaleString()}`;
                
                // Update metrics
                document.getElementById('total-requests').textContent = data.metrics.total_requests;
                const successRate = data.metrics.total_requests > 0 ? 
                    ((data.metrics.successful_requests / data.metrics.total_requests) * 100).toFixed(1) : 0;
                document.getElementById('success-rate').textContent = `${successRate}%`;
                document.getElementById('avg-response-time').textContent = `${data.metrics.average_response_time.toFixed(0)}ms`;
                
                // Update endpoints
                const endpointsDiv = document.getElementById('endpoints');
                endpointsDiv.innerHTML = '';
                
                for (const [endpoint, result] of Object.entries(data.endpoints)) {
                    const endpointCard = document.createElement('div');
                    endpointCard.className = 'bg-gray-800 p-4 rounded-lg';
                    endpointCard.innerHTML = `
                        <div class="flex justify-between items-start mb-2">
                            <h3 class="font-medium">${endpoint}</h3>
                            <span class="px-2 py-1 rounded text-xs font-medium ${
                                result.status === 'success' ? 'bg-green-600' : 'bg-red-600'
                            }">${result.status}</span>
                        </div>
                        <div class="grid grid-cols-2 gap-4 text-sm">
                            <div>
                                <span class="text-gray-400">Response Time:</span>
                                <span class="ml-2">${result.response_time_ms}ms</span>
                            </div>
                            <div>
                                <span class="text-gray-400">Items:</span>
                                <span class="ml-2">${result.item_count || 0}</span>
                            </div>
                            ${result.freshness ? `
                            <div>
                                <span class="text-gray-400">Freshness:</span>
                                <span class="ml-2">${result.freshness.age_seconds}s</span>
                            </div>
                            ` : ''}
                        </div>
                        ${result.error ? `<div class="text-red-400 text-sm mt-2">${result.error}</div>` : ''}
                    `;
                    endpointsDiv.appendChild(endpointCard);
                }
                
                // Update alerts
                const alertsDiv = document.getElementById('alerts');
                alertsDiv.innerHTML = '';
                
                if (data.alerts.length === 0) {
                    alertsDiv.innerHTML = '<div class="text-gray-400">No alerts</div>';
                } else {
                    for (const alert of data.alerts) {
                        const alertDiv = document.createElement('div');
                        alertDiv.className = `p-3 rounded bg-gray-800 alert-${alert.level}`;
                        alertDiv.innerHTML = `
                            <div class="flex justify-between items-start">
                                <div>
                                    <span class="font-medium">${alert.endpoint}</span>
                                    <span class="ml-2 text-gray-400">${alert.message}</span>
                                </div>
                                <span class="text-xs text-gray-400">${new Date(alert.timestamp).toLocaleString()}</span>
                            </div>
                        `;
                        alertsDiv.appendChild(alertDiv);
                    }
                }
                
            } catch (error) {
                console.error('Error updating dashboard:', error);
            }
        }
        
        // Update dashboard every 30 seconds
        updateDashboard();
        setInterval(updateDashboard, 30000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MERID Predictions Production Monitor")
    parser.add_argument("--port", type=int, default=8080, help="Port for monitoring dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host for monitoring dashboard")
    
    args = parser.parse_args()
    
    print(f"🚀 Starting MERID Predictions Monitor on http://{args.host}:{args.port}")
    print("📊 Dashboard will be available at: http://localhost:{args.port}")
    print("🔄 Auto-refresh every 30 seconds")
    
    uvicorn.run(app, host=args.host, port=args.port)
