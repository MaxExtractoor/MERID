#!/usr/bin/env python3
"""
MERID Live Data Integration Execution Tracker

This script tracks the progress of the live data integration process
and provides a real-time dashboard for monitoring execution status.

Usage:
    python track_execution.py [--port 8081] [--refresh 60]
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Any
from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles
import uvicorn

app = FastAPI(title="MERID Integration Tracker")

# Global execution state
execution_state = {
    "phase": "coordination",
    "status": "not_started",
    "progress": 0,
    "milestones": [
        {
            "id": "coordination_sent",
            "name": "Coordination Email Sent",
            "phase": "coordination",
            "status": "pending",
            "completed_at": None,
            "notes": ""
        },
        {
            "id": "implementation_choice",
            "name": "Implementation Approach Chosen",
            "phase": "coordination",
            "status": "pending",
            "completed_at": None,
            "notes": ""
        },
        {
            "id": "implementation_started",
            "name": "Live Feed Implementation Started",
            "phase": "implementation",
            "status": "pending",
            "completed_at": None,
            "notes": ""
        },
        {
            "id": "integration_testing",
            "name": "Integration Testing",
            "phase": "validation",
            "status": "pending",
            "completed_at": None,
            "notes": ""
        },
        {
            "id": "production_deployment",
            "name": "Production Deployment",
            "phase": "deployment",
            "status": "pending",
            "completed_at": None,
            "notes": ""
        },
        {
            "id": "live_experiments",
            "name": "Live Experiments Started",
            "phase": "production",
            "status": "pending",
            "completed_at": None,
            "notes": ""
        }
    ],
    "timeline": [],
    "alerts": []
}

class ExecutionTracker:
    def __init__(self):
        self.phases = ["coordination", "implementation", "validation", "deployment", "production"]
        self.current_phase = 0
    
    def update_milestone(self, milestone_id: str, status: str, notes: str = ""):
        """Update a specific milestone status."""
        for milestone in execution_state["milestones"]:
            if milestone["id"] == milestone_id:
                milestone["status"] = status
                milestone["completed_at"] = datetime.now(timezone.utc).isoformat() if status == "completed" else None
                milestone["notes"] = notes
                
                # Add to timeline
                execution_state["timeline"].append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "milestone": milestone_id,
                    "status": status,
                    "notes": notes
                })
                
                # Update progress
                self.update_progress()
                break
    
    def update_progress(self):
        """Calculate overall progress based on completed milestones."""
        completed = sum(1 for m in execution_state["milestones"] if m["status"] == "completed")
        execution_state["progress"] = (completed / len(execution_state["milestones"])) * 100
        
        # Update phase
        for i, milestone in enumerate(execution_state["milestones"]):
            if milestone["status"] != "completed":
                execution_state["phase"] = milestone["phase"]
                break
        else:
            execution_state["phase"] = "completed"
        
        # Update overall status
        if execution_state["progress"] == 0:
            execution_state["status"] = "not_started"
        elif execution_state["progress"] == 100:
            execution_state["status"] = "completed"
        else:
            execution_state["status"] = "in_progress"
    
    def add_alert(self, level: str, message: str, milestone_id: str = None):
        """Add an alert to the execution tracker."""
        alert = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "milestone_id": milestone_id
        }
        execution_state["alerts"].append(alert)
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get current execution status summary."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "phase": execution_state["phase"],
            "status": execution_state["status"],
            "progress": execution_state["progress"],
            "milestones": execution_state["milestones"],
            "timeline": execution_state["timeline"][-10:],  # Last 10 timeline events
            "alerts": execution_state["alerts"][-5:]  # Last 5 alerts
        }

# Global tracker instance
tracker = ExecutionTracker()

@app.get("/")
async def dashboard():
    """Serve the execution tracking dashboard."""
    return Response(generate_dashboard_html(), media_type="text/html")

@app.get("/api/status")
async def get_status():
    """Get current execution status."""
    return tracker.get_status_summary()

@app.post("/api/milestone/{milestone_id}")
async def update_milestone(milestone_id: str, status: str, notes: str = ""):
    """Update a milestone status."""
    tracker.update_milestone(milestone_id, status, notes)
    return {"status": "success", "milestone": milestone_id, "new_status": status}

@app.post("/api/alert")
async def add_alert(level: str, message: str, milestone_id: str = None):
    """Add an alert."""
    tracker.add_alert(level, message, milestone_id)
    return {"status": "success", "alert_added": True}

def generate_dashboard_html() -> str:
    """Generate the execution tracking dashboard HTML."""
    return """
<!DOCTYPE html>
<html>
<head>
    <title>MERID Integration Tracker</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/axios/dist/axios.min.js"></script>
    <style>
        .phase-coordination { background-color: #3b82f6; }
        .phase-implementation { background-color: #10b981; }
        .phase-validation { background-color: #f59e0b; }
        .phase-deployment { background-color: #ef4444; }
        .phase-production { background-color: #8b5cf6; }
        .phase-completed { background-color: #10b981; }
        
        .status-not_started { background-color: #6b7280; }
        .status-in_progress { background-color: #f59e0b; }
        .status-completed { background-color: #10b981; }
        
        .alert-critical { border-left: 4px solid #ef4444; }
        .alert-warning { border-left: 4px solid #f59e0b; }
        .alert-info { border-left: 4px solid #3b82f6; }
        .alert-success { border-left: 4px solid #10b981; }
    </style>
</head>
<body class="bg-gray-900 text-white p-6">
    <div class="max-w-7xl mx-auto">
        <h1 class="text-3xl font-bold mb-6">🚀 MERID Live Data Integration Tracker</h1>
        
        <!-- Overall Status -->
        <div id="overall-status" class="mb-6 p-4 rounded-lg bg-gray-800">
            <h2 class="text-xl font-semibold mb-2">Overall Status</h2>
            <div class="flex items-center space-x-4">
                <div id="phase-indicator" class="px-3 py-1 rounded-full text-sm font-medium">
                    Loading...
                </div>
                <div id="status-indicator" class="px-3 py-1 rounded-full text-sm font-medium">
                    Loading...
                </div>
                <div id="progress-bar" class="flex-1 bg-gray-700 rounded-full h-4">
                    <div id="progress-fill" class="bg-green-500 h-4 rounded-full transition-all duration-500" style="width: 0%"></div>
                </div>
                <div id="progress-text" class="text-sm text-gray-400">
                    0% Complete
                </div>
            </div>
        </div>
        
        <!-- Phase Progress -->
        <div class="mb-6">
            <h2 class="text-xl font-semibold mb-4">Phase Progress</h2>
            <div id="phases" class="grid grid-cols-5 gap-4">
                <!-- Phase cards will be inserted here -->
            </div>
        </div>
        
        <!-- Milestones -->
        <div class="mb-6">
            <h2 class="text-xl font-semibold mb-4">Milestones</h2>
            <div id="milestones" class="space-y-4">
                <!-- Milestone cards will be inserted here -->
            </div>
        </div>
        
        <!-- Timeline -->
        <div class="mb-6">
            <h2 class="text-xl font-semibold mb-4">Recent Timeline</h2>
            <div id="timeline" class="space-y-2">
                <!-- Timeline events will be inserted here -->
            </div>
        </div>
        
        <!-- Alerts -->
        <div class="mb-6">
            <h2 class="text-xl font-semibold mb-4">Alerts</h2>
            <div id="alerts" class="space-y-2">
                <!-- Alerts will be inserted here -->
            </div>
        </div>
        
        <!-- Actions -->
        <div class="mb-6">
            <h2 class="text-xl font-semibold mb-4">Actions</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <button onclick="sendCoordinationEmail()" class="bg-blue-600 hover:bg-blue-700 px-4 py-2 rounded-lg font-medium">
                    📧 Send Coordination Email
                </button>
                <button onclick="chooseImplementation()" class="bg-green-600 hover:bg-green-700 px-4 py-2 rounded-lg font-medium">
                    🔧 Choose Implementation
                </button>
                <button onclick="runValidation()" class="bg-yellow-600 hover:bg-yellow-700 px-4 py-2 rounded-lg font-medium">
                    ✅ Run Validation
                </button>
            </div>
        </div>
    </div>
    
    <script>
        const phases = [
            { id: 'coordination', name: 'Coordination', icon: '📧' },
            { id: 'implementation', name: 'Implementation', icon: '🔧' },
            { id: 'validation', name: 'Validation', icon: '✅' },
            { id: 'deployment', name: 'Deployment', icon: '🚀' },
            { id: 'production', name: 'Production', icon: '🎯' }
        ];
        
        async function updateDashboard() {
            try {
                const response = await axios.get('/api/status');
                const data = response.data;
                
                // Update phase indicator
                const phaseIndicator = document.getElementById('phase-indicator');
                const currentPhase = phases.find(p => p.id === data.phase);
                phaseIndicator.textContent = `${currentPhase.icon} ${currentPhase.name}`;
                phaseIndicator.className = `px-3 py-1 rounded-full text-sm font-medium phase-${data.phase}`;
                
                // Update status indicator
                const statusIndicator = document.getElementById('status-indicator');
                statusIndicator.textContent = data.status.replace('_', ' ').toUpperCase();
                statusIndicator.className = `px-3 py-1 rounded-full text-sm font-medium status-${data.status}`;
                
                // Update progress bar
                const progressFill = document.getElementById('progress-fill');
                progressFill.style.width = `${data.progress}%`;
                
                // Update progress text
                document.getElementById('progress-text').textContent = `${Math.round(data.progress)}% Complete`;
                
                // Update phases
                const phasesDiv = document.getElementById('phases');
                phasesDiv.innerHTML = '';
                
                phases.forEach((phase, index) => {
                    const isActive = phase.id === data.phase;
                    const isCompleted = index < phases.findIndex(p => p.id === data.phase);
                    
                    const phaseCard = document.createElement('div');
                    phaseCard.className = `p-4 rounded-lg text-center ${
                        isActive ? 'ring-2 ring-blue-500' : ''
                    } ${isCompleted ? 'opacity-50' : ''}`;
                    phaseCard.innerHTML = `
                        <div class="text-2xl mb-2">${phase.icon}</div>
                        <div class="font-medium">${phase.name}</div>
                        <div class="text-sm text-gray-400">${isActive ? 'Current' : isCompleted ? 'Completed' : 'Pending'}</div>
                    `;
                    phasesDiv.appendChild(phaseCard);
                });
                
                // Update milestones
                const milestonesDiv = document.getElementById('milestones');
                milestonesDiv.innerHTML = '';
                
                data.milestones.forEach(milestone => {
                    const milestoneCard = document.createElement('div');
                    milestoneCard.className = 'bg-gray-800 p-4 rounded-lg';
                    milestoneCard.innerHTML = `
                        <div class="flex justify-between items-start mb-2">
                            <h3 class="font-medium">${milestone.name}</h3>
                            <span class="px-2 py-1 rounded text-xs font-medium ${
                                milestone.status === 'completed' ? 'bg-green-600' : 
                                milestone.status === 'in_progress' ? 'bg-yellow-600' : 
                                milestone.status === 'failed' ? 'bg-red-600' : 'bg-gray-600'
                            }">${milestone.status}</span>
                        </div>
                        ${milestone.notes ? `<div class="text-sm text-gray-400 mb-2">${milestone.notes}</div>` : ''}
                        <div class="text-sm text-gray-500">
                            ${milestone.completed_at ? `Completed: ${new Date(milestone.completed_at).toLocaleString()}` : 'Not started'}
                        </div>
                    `;
                    milestonesDiv.appendChild(milestoneCard);
                });
                
                // Update timeline
                const timelineDiv = document.getElementById('timeline');
                timelineDiv.innerHTML = '';
                
                if (data.timeline.length === 0) {
                    timelineDiv.innerHTML = '<div class="text-gray-400">No timeline events yet</div>';
                } else {
                    data.timeline.forEach(event => {
                        const eventDiv = document.createElement('div');
                        eventDiv.className = 'flex items-start space-x-3 p-3 bg-gray-800 rounded';
                        eventDiv.innerHTML = `
                            <div class="text-xs text-gray-400">${new Date(event.timestamp).toLocaleString()}</div>
                            <div class="flex-1">
                                <div class="font-medium">${event.milestone}</div>
                                <div class="text-sm text-gray-400">${event.notes}</div>
                            </div>
                            <span class="px-2 py-1 rounded text-xs font-medium ${
                                event.status === 'completed' ? 'bg-green-600' : 'bg-blue-600'
                            }">${event.status}</span>
                        `;
                        timelineDiv.appendChild(eventDiv);
                    });
                }
                
                // Update alerts
                const alertsDiv = document.getElementById('alerts');
                alertsDiv.innerHTML = '';
                
                if (data.alerts.length === 0) {
                    alertsDiv.innerHTML = '<div class="text-gray-400">No alerts</div>';
                } else {
                    data.alerts.forEach(alert => {
                        const alertDiv = document.createElement('div');
                        alertDiv.className = `p-3 rounded bg-gray-800 alert-${alert.level}`;
                        alertDiv.innerHTML = `
                            <div class="flex justify-between items-start">
                                <div>
                                    <span class="font-medium">${alert.message}</span>
                                    ${alert.milestone_id ? `<span class="ml-2 text-gray-400">(${alert.milestone_id})</span>` : ''}
                                </div>
                                <span class="text-xs text-gray-400">${new Date(alert.timestamp).toLocaleString()}</span>
                            </div>
                        `;
                        alertsDiv.appendChild(alertDiv);
                    });
                }
                
            } catch (error) {
                console.error('Error updating dashboard:', error);
            }
        }
        
        // Action functions
        async function sendCoordinationEmail() {
            try {
                await axios.post('/api/milestone/coordination_sent', {
                    status: 'in_progress',
                    notes: 'Email sent to upstream team with complete integration package'
                });
                await updateDashboard();
                alert('Coordination email marked as in progress');
            } catch (error) {
                console.error('Error updating milestone:', error);
                alert('Error updating milestone');
            }
        }
        
        async function chooseImplementation() {
            const choice = confirm('Choose Implementation Approach:\\n\\nOption A: Enhance existing aggregator\\nOption B: Create dedicated service\\n\\nChoose OK for Option A, Cancel for Option B');
            
            const implementationChoice = choice ? 'aggregator' : 'service';
            
            try {
                await axios.post('/api/milestone/implementation_choice', {
                    status: 'completed',
                    notes: `Chose ${implementationChoice} approach for live data integration`
                });
                await updateDashboard();
                alert(`Implementation chosen: ${implementationChoice}`);
            } catch (error) {
                console.error('Error updating milestone:', error);
                alert('Error updating milestone');
            }
        }
        
        async function runValidation() {
            try {
                await axios.post('/api/milestone/integration_testing', {
                    status: 'in_progress',
                    notes: 'Running live data validation tests'
                });
                await updateDashboard();
                alert('Validation testing marked as in progress');
            } catch (error) {
                console.error('Error updating milestone:', error);
                alert('Error updating milestone');
            }
        }
        
        // Update dashboard every 60 seconds
        updateDashboard();
        setInterval(updateDashboard, 60000);
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="MERID Integration Execution Tracker")
    parser.add_argument("--port", type=int, default=8081, help="Port for tracking dashboard")
    parser.add_argument("--host", default="0.0.0.0", help="Host for tracking dashboard")
    
    args = parser.parse_args()
    
    print(f"🚀 Starting MERID Integration Tracker on http://{args.host}:{args.port}")
    print("📊 Tracking dashboard will be available at: http://localhost:{args.port}")
    print("🔄 Auto-refresh every 60 seconds")
    
    uvicorn.run(app, host=args.host, port=args.port)
