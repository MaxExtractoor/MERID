#!/usr/bin/env python3
"""
Season 1 Timeline View Generator for MERID.

Creates a single-page institutional narrative showing readiness trajectory,
shadow PnL bands, incident counts, and major changes across Season 1 weeks.
"""

import json
import argparse
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import glob
import re

class SeasonTimelineGenerator:
    """Generates Season 1 timeline view for institutional stakeholders."""
    
    def __init__(self, data_directory: str = "."):
        self.data_directory = data_directory
        self.timeline_data = {
            "season_metadata": {
                "season": 1,
                "year": 2024,
                "total_weeks": 0,
                "generation_timestamp": datetime.utcnow().isoformat()
            },
            "weekly_data": [],
            "promotion_gates": {
                "readiness_gate": {"target": 90.0, "current_status": "not_met", "weeks_met": 0},
                "incident_gate": {"target": 0, "current_status": "not_met", "weeks_met": 0},
                "pnl_gate": {"target": 5.0, "current_status": "not_met", "weeks_met": 0},
                "drill_gate": {"target": 85.0, "current_status": "not_met", "weeks_met": 0}
            },
            "key_milestones": [],
            "trend_analysis": {},
            "executive_summary": ""
        }
    
    def load_weekly_data(self) -> List[Dict[str, Any]]:
        """Load all weekly dossier JSON files."""
        weekly_files = glob.glob(os.path.join(self.data_directory, "weekly_summary_*.json"))
        weekly_data = []
        
        for file_path in sorted(weekly_files):
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)
                    weekly_data.append(data)
            except Exception as e:
                print(f"Warning: Could not load {file_path}: {e}")
        
        return weekly_data
    
    def extract_timeline_metrics(self, weekly_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract key metrics for timeline visualization."""
        timeline_points = []
        
        for week_data in weekly_data:
            week_num = week_data.get("week_metadata", {}).get("week_number", 0)
            week_start = week_data.get("week_metadata", {}).get("week_start", "")
            
            # Extract readiness score
            readiness_score = week_data.get("mode_promotion_readiness", {}).get("readiness_score", 0.0)
            
            # Extract shadow trading PnL
            shadow_pnl = week_data.get("mode_promotion_readiness", {}).get("shadow_trading_pnl", {})
            pnl_current = shadow_pnl.get("current", 0.0)
            pnl_target = shadow_pnl.get("target", 0.0)
            pnl_drawdown = shadow_pnl.get("drawdown", 0.0)
            
            # Extract incident metrics
            incidents = week_data.get("operational_metrics", {}).get("incidents", {})
            incident_count = incidents.get("total", 0)
            critical_incidents = incidents.get("critical", 0)
            
            # Extract rollbacks
            rollbacks = week_data.get("operational_metrics", {}).get("rollbacks", {})
            rollback_count = rollbacks.get("total", 0)
            
            # Extract war-game drill performance
            war_game_data = week_data.get("war_game_drills", {})
            drill_score = war_game_data.get("overall_performance", {}).get("score", 0.0)
            drill_grade = war_game_data.get("overall_performance", {}).get("grade", "F")
            drills_conducted = len(war_game_data.get("drills_conducted", []))
            
            # Extract major changes
            changes = week_data.get("change_summary", {})
            total_releases = changes.get("total_releases", 0)
            features_deployed = len(changes.get("features_deployed", []))
            risk_control_changes = len(changes.get("risk_control_changes", []))
            
            # Extract testing evidence
            testing = week_data.get("testing_evidence", {})
            unit_test_coverage = testing.get("unit_tests", {}).get("coverage", 0.0)
            security_critical = testing.get("security_scans", {}).get("critical", 0)
            
            timeline_point = {
                "week": week_num,
                "week_start": week_start,
                "readiness_score": readiness_score,
                "shadow_pnl": {
                    "current": pnl_current,
                    "target": pnl_target,
                    "drawdown": pnl_drawdown,
                    "within_bounds": abs(pnl_current - pnl_target) <= (pnl_target * 0.05) if pnl_target > 0 else False
                },
                "incidents": {
                    "total": incident_count,
                    "critical": critical_incidents,
                    "status": "clean" if critical_incidents == 0 else "critical_issues"
                },
                "rollbacks": rollback_count,
                "war_game_drills": {
                    "score": drill_score,
                    "grade": drill_grade,
                    "conducted": drills_conducted,
                    "passed": drill_score >= 85.0
                },
                "changes": {
                    "releases": total_releases,
                    "features": features_deployed,
                    "risk_controls": risk_control_changes
                },
                "testing": {
                    "unit_coverage": unit_test_coverage,
                    "critical_vulns": security_critical,
                    "status": "healthy" if security_critical == 0 else "security_issues"
                }
            }
            
            timeline_points.append(timeline_point)
        
        return timeline_points
    
    def calculate_promotion_gates(self, timeline_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate promotion gate status across all weeks."""
        gates = self.timeline_data["promotion_gates"]
        
        # Readiness gate: ≥90% for 8 consecutive weeks
        readiness_consecutive = 0
        max_readiness_consecutive = 0
        
        # Incident gate: 0 critical incidents for 12 consecutive weeks
        incident_consecutive = 0
        max_incident_consecutive = 0
        
        # PnL gate: Within ±5% bounds for 8 consecutive weeks
        pnl_consecutive = 0
        max_pnl_consecutive = 0
        
        # Drill gate: ≥85% score for 4 consecutive weeks
        drill_consecutive = 0
        max_drill_consecutive = 0
        
        for week_data in timeline_data:
            # Check readiness gate
            if week_data["readiness_score"] >= gates["readiness_gate"]["target"]:
                readiness_consecutive += 1
                max_readiness_consecutive = max(max_readiness_consecutive, readiness_consecutive)
            else:
                readiness_consecutive = 0
            
            # Check incident gate
            if week_data["incidents"]["critical"] == gates["incident_gate"]["target"]:
                incident_consecutive += 1
                max_incident_consecutive = max(max_incident_consecutive, incident_consecutive)
            else:
                incident_consecutive = 0
            
            # Check PnL gate
            if week_data["shadow_pnl"]["within_bounds"]:
                pnl_consecutive += 1
                max_pnl_consecutive = max(max_pnl_consecutive, pnl_consecutive)
            else:
                pnl_consecutive = 0
            
            # Check drill gate
            if week_data["war_game_drills"]["score"] >= gates["drill_gate"]["target"]:
                drill_consecutive += 1
                max_drill_consecutive = max(max_drill_consecutive, drill_consecutive)
            else:
                drill_consecutive = 0
        
        # Update gate status
        gates["readiness_gate"]["weeks_met"] = max_readiness_consecutive
        gates["readiness_gate"]["current_status"] = "met" if max_readiness_consecutive >= 8 else "not_met"
        
        gates["incident_gate"]["weeks_met"] = max_incident_consecutive
        gates["incident_gate"]["current_status"] = "met" if max_incident_consecutive >= 12 else "not_met"
        
        gates["pnl_gate"]["weeks_met"] = max_pnl_consecutive
        gates["pnl_gate"]["current_status"] = "met" if max_pnl_consecutive >= 8 else "not_met"
        
        gates["drill_gate"]["weeks_met"] = max_drill_consecutive
        gates["drill_gate"]["current_status"] = "met" if max_drill_consecutive >= 4 else "not_met"
        
        return gates
    
    def identify_key_milestones(self, timeline_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify key milestones and notable events."""
        milestones = []
        
        for week_data in timeline_data:
            week = week_data["week"]
            
            # Readiness milestones
            if week_data["readiness_score"] >= 95:
                milestones.append({
                    "week": week,
                    "type": "readiness",
                    "title": f"Peak Readiness: {week_data['readiness_score']:.1f}%",
                    "description": "Achieved exceptional readiness score",
                    "impact": "positive"
                })
            elif week_data["readiness_score"] >= 90:
                milestones.append({
                    "week": week,
                    "type": "readiness",
                    "title": f"Target Readiness Met: {week_data['readiness_score']:.1f}%",
                    "description": "Met minimum readiness threshold for SIGHTED_LIVE",
                    "impact": "positive"
                })
            
            # Incident milestones
            if week_data["incidents"]["critical"] > 0:
                milestones.append({
                    "week": week,
                    "type": "incident",
                    "title": f"Critical Incidents: {week_data['incidents']['critical']}",
                    "description": "Critical incidents detected this week",
                    "impact": "negative"
                })
            
            # War-game drill milestones
            if week_data["war_game_drills"]["grade"] == "A":
                milestones.append({
                    "week": week,
                    "type": "drill",
                    "title": f"Perfect Drill Performance: Grade {week_data['war_game_drills']['grade']}",
                    "description": "Achieved top-tier war-game drill performance",
                    "impact": "positive"
                })
            
            # Release milestones
            if week_data["changes"]["features"] >= 3:
                milestones.append({
                    "week": week,
                    "type": "release",
                    "title": f"Major Feature Release: {week_data['changes']['features']} features",
                    "description": "Significant feature deployment this week",
                    "impact": "neutral"
                })
            
            # Shadow PnL milestones
            if week_data["shadow_pnl"]["current"] > 0 and week_data["shadow_pnl"]["within_bounds"]:
                milestones.append({
                    "week": week,
                    "type": "trading",
                    "title": f"Positive Shadow PnL: ${week_data['shadow_pnl']['current']:,.2f}",
                    "description": "Shadow trading achieved positive returns within bounds",
                    "impact": "positive"
                })
        
        return sorted(milestones, key=lambda x: x["week"])
    
    def calculate_trend_analysis(self, timeline_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate trend analysis across the season."""
        if not timeline_data:
            return {}
        
        # Readiness trend
        readiness_scores = [week["readiness_score"] for week in timeline_data]
        readiness_trend = "improving" if readiness_scores[-1] > readiness_scores[0] else "declining"
        readiness_avg = sum(readiness_scores) / len(readiness_scores)
        readiness_volatility = max(readiness_scores) - min(readiness_scores)
        
        # Incident trend
        incident_counts = [week["incidents"]["total"] for week in timeline_data]
        incident_trend = "improving" if incident_counts[-1] < incident_counts[0] else "worsening"
        total_incidents = sum(incident_counts)
        
        # PnL trend
        pnl_values = [week["shadow_pnl"]["current"] for week in timeline_data if week["shadow_pnl"]["current"] > 0]
        pnl_trend = "positive" if len(pnl_values) > 1 and pnl_values[-1] > pnl_values[0] else "negative"
        
        # Drill performance trend
        drill_scores = [week["war_game_drills"]["score"] for week in timeline_data if week["war_game_drills"]["score"] > 0]
        drill_trend = "improving" if len(drill_scores) > 1 and drill_scores[-1] > drill_scores[0] else "declining"
        avg_drill_score = sum(drill_scores) / len(drill_scores) if drill_scores else 0
        
        return {
            "readiness": {
                "trend": readiness_trend,
                "average": readiness_avg,
                "volatility": readiness_volatility,
                "current": readiness_scores[-1] if readiness_scores else 0
            },
            "incidents": {
                "trend": incident_trend,
                "total": total_incidents,
                "average_per_week": total_incidents / len(timeline_data),
                "current": incident_counts[-1] if incident_counts else 0
            },
            "shadow_pnl": {
                "trend": pnl_trend,
                "total_pnl": sum(pnl_values),
                "weeks_with_pnl": len(pnl_values),
                "current": pnl_values[-1] if pnl_values else 0
            },
            "war_game_drills": {
                "trend": drill_trend,
                "average_score": avg_drill_score,
                "total_drills": sum(week["war_game_drills"]["conducted"] for week in timeline_data),
                "current_score": drill_scores[-1] if drill_scores else 0
            }
        }
    
    def generate_executive_summary(self, timeline_data: List[Dict[str, Any]], gates: Dict[str, Any]) -> str:
        """Generate executive summary for institutional stakeholders."""
        if not timeline_data:
            return "No data available for executive summary."
        
        total_weeks = len(timeline_data)
        latest_week = timeline_data[-1]
        current_readiness = latest_week["readiness_score"]
        
        # Count met gates
        met_gates = sum(1 for gate in gates.values() if gate["current_status"] == "met")
        total_gates = len(gates)
        
        # Calculate key metrics
        total_incidents = sum(week["incidents"]["total"] for week in timeline_data)
        critical_incidents = sum(week["incidents"]["critical"] for week in timeline_data)
        total_drills = sum(week["war_game_drills"]["conducted"] for week in timeline_data)
        avg_drill_score = sum(week["war_game_drills"]["score"] for week in timeline_data if week["war_game_drills"]["score"] > 0) / total_drills if total_drills > 0 else 0
        
        summary = f"""
## MERID Season 1 Executive Summary

### Current Status
- **Weeks Analyzed**: {total_weeks}
- **Current Readiness Score**: {current_readiness:.1f}%
- **Promotion Gates Met**: {met_gates}/{total_gates}
- **Overall Trend**: {"POSITIVE" if current_readiness >= 85 else "NEEDS IMPROVEMENT"}

### Key Performance Indicators
- **Total Incidents**: {total_incidents} ({critical_incidents} critical)
- **War-Game Drills**: {total_drills} conducted (avg score: {avg_drill_score:.1f}%)
- **System Stability**: {"STABLE" if critical_incidents == 0 else "NEEDS ATTENTION"}
- **Operational Readiness**: {"HIGH" if current_readiness >= 90 else "DEVELOPING"}

### Promotion Readiness
"""
        
        for gate_name, gate_data in gates.items():
            gate_display = gate_name.replace("_gate", "").replace("_", " ").title()
            summary += f"- **{gate_display}**: {gate_data['current_status'].upper()} ({gate_data['weeks_met']} weeks met)\n"
        
        summary += f"""
### Strategic Assessment
MERID Season 1 demonstrates {"strong" if current_readiness >= 85 else "developing"} institutional readiness. 
The governance engine has generated {total_weeks} weeks of immutable evidence, with {"excellent" if avg_drill_score >= 85 else "improving"} 
operator performance through war-game drills.

{"The system is approaching SIGHTED_LIVE readiness criteria." if met_gates >= 3 else "Additional evidence accumulation needed before SIGHTED_LIVE promotion."}
"""
        
        return summary
    
    def generate_html_timeline(self, timeline_data: List[Dict[str, Any]], gates: Dict[str, Any], milestones: List[Dict[str, Any]], trends: Dict[str, Any]) -> str:
        """Generate interactive HTML timeline view."""
        
        # Prepare data for JavaScript
        timeline_json = json.dumps(timeline_data)
        gates_json = json.dumps(gates)
        milestones_json = json.dumps(milestones)
        trends_json = json.dumps(trends)
        
        html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MERID Season 1 Timeline View</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 3px solid #007bff;
            padding-bottom: 20px;
        }}
        .header h1 {{
            color: #007bff;
            margin: 0;
            font-size: 2.5em;
        }}
        .header p {{
            color: #666;
            font-size: 1.2em;
            margin: 10px 0 0 0;
        }}
        .status-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px;
            margin-bottom: 40px;
        }}
        .status-card {{
            background: #f8f9fa;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #007bff;
        }}
        .status-card h3 {{
            margin: 0 0 10px 0;
            color: #333;
        }}
        .status-card .value {{
            font-size: 2em;
            font-weight: bold;
            color: #007bff;
        }}
        .status-card .label {{
            color: #666;
            font-size: 0.9em;
        }}
        .chart-container {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}
        .chart-container h2 {{
            color: #333;
            margin-top: 0;
            border-bottom: 2px solid #f0f0f0;
            padding-bottom: 10px;
        }}
        .gates-container {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .gate-card {{
            padding: 20px;
            border-radius: 8px;
            border: 2px solid #ddd;
        }}
        .gate-card.met {{
            border-color: #28a745;
            background: #d4edda;
        }}
        .gate-card.not-met {{
            border-color: #dc3545;
            background: #f8d7da;
        }}
        .gate-card h3 {{
            margin: 0 0 10px 0;
        }}
        .milestone {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            border-radius: 4px;
            padding: 10px;
            margin: 5px 0;
        }}
        .milestone.positive {{
            background: #d4edda;
            border-color: #c3e6cb;
        }}
        .milestone.negative {{
            background: #f8d7da;
            border-color: #f5c6cb;
        }}
        .executive-summary {{
            background: #e9ecef;
            padding: 25px;
            border-radius: 8px;
            margin-bottom: 30px;
        }}
        .executive-summary h2 {{
            color: #495057;
            margin-top: 0;
        }}
        .trend-indicator {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.8em;
            font-weight: bold;
            margin-left: 10px;
        }}
        .trend-up {{
            background: #d4edda;
            color: #155724;
        }}
        .trend-down {{
            background: #f8d7da;
            color: #721c24;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>MERID Season 1 Timeline View</h1>
            <p>Institutional Narrative & Governance Evidence</p>
            <p>Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        </div>

        <div class="executive-summary">
            <h2>Executive Summary</h2>
            <div id="executive-summary-content">
                Loading executive summary...
            </div>
        </div>

        <div class="status-grid">
            <div class="status-card">
                <h3>Current Readiness</h3>
                <div class="value" id="current-readiness">-</div>
                <div class="label">Score (%)</div>
            </div>
            <div class="status-card">
                <h3>Weeks Analyzed</h3>
                <div class="value" id="total-weeks">-</div>
                <div class="label">Total Weeks</div>
            </div>
            <div class="status-card">
                <h3>Gates Met</h3>
                <div class="value" id="gates-met">-</div>
                <div class="label">Promotion Gates</div>
            </div>
            <div class="status-card">
                <h3>System Status</h3>
                <div class="value" id="system-status">-</div>
                <div class="label">Overall Health</div>
            </div>
        </div>

        <div class="chart-container">
            <h2>Readiness Score Trajectory</h2>
            <div id="readiness-chart"></div>
        </div>

        <div class="chart-container">
            <h2>Shadow PnL Performance</h2>
            <div id="pnl-chart"></div>
        </div>

        <div class="chart-container">
            <h2>Incident & Rollback History</h2>
            <div id="incident-chart"></div>
        </div>

        <div class="chart-container">
            <h2>War-Game Drill Performance</h2>
            <div id="drill-chart"></div>
        </div>

        <div class="gates-container" id="gates-container">
            <!-- Gates will be populated by JavaScript -->
        </div>

        <div class="chart-container">
            <h2>Key Milestones</h2>
            <div id="milestones-container">
                <!-- Milestones will be populated by JavaScript -->
            </div>
        </div>
    </div>

    <script>
        // Data from Python
        const timelineData = {timeline_json};
        const gatesData = {gates_json};
        const milestonesData = {milestones_json};
        const trendsData = {trends_json};

        // Update executive summary
        document.getElementById('executive-summary-content').innerHTML = `
            <pre style="white-space: pre-wrap; font-family: inherit; margin: 0;">
{self.generate_executive_summary(timeline_data, gates)}
            </pre>
        `;

        // Update status cards
        if (timelineData.length > 0) {{
            const latestWeek = timelineData[timelineData.length - 1];
            document.getElementById('current-readiness').textContent = latestWeek.readiness_score.toFixed(1) + '%';
            document.getElementById('total-weeks').textContent = timelineData.length;
            
            const metGates = Object.values(gatesData).filter(gate => gate.current_status === 'met').length;
            document.getElementById('gates-met').textContent = metGates + '/' + Object.keys(gatesData).length;
            
            const systemStatus = latestWeek.readiness_score >= 90 ? 'READY' : 
                               latestWeek.readiness_score >= 75 ? 'DEVELOPING' : 'NEEDS WORK';
            document.getElementById('system-status').textContent = systemStatus;
        }}

        // Readiness Score Chart
        const readinessTrace = {{
            x: timelineData.map(d => d.week),
            y: timelineData.map(d => d.readiness_score),
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Readiness Score',
            line: {{color: '#007bff', width: 3}},
            marker: {{size: 8}}
        }};

        const readinessLayout = {{
            title: '',
            xaxis: {{title: 'Week'}},
            yaxis: {{title: 'Readiness Score (%)', range: [0, 100]}},
            hovermode: 'x unified'
        }};

        Plotly.newPlot('readiness-chart', [readinessTrace], readinessLayout);

        // Shadow PnL Chart
        const pnlTrace = {{
            x: timelineData.map(d => d.week),
            y: timelineData.map(d => d.shadow_pnl.current),
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Shadow PnL',
            line: {{color: '#28a745', width: 3}},
            marker: {{size: 8}}
        }};

        const pnlTargetTrace = {{
            x: timelineData.map(d => d.week),
            y: timelineData.map(d => d.shadow_pnl.target),
            type: 'scatter',
            mode: 'lines',
            name: 'Target',
            line: {{color: '#dc3545', width: 2, dash: 'dash'}}
        }};

        const pnlLayout = {{
            title: '',
            xaxis: {{title: 'Week'}},
            yaxis: {{title: 'PnL ($)'}},
            hovermode: 'x unified'
        }};

        Plotly.newPlot('pnl-chart', [pnlTrace, pnlTargetTrace], pnlLayout);

        // Incident Chart
        const incidentTrace = {{
            x: timelineData.map(d => d.week),
            y: timelineData.map(d => d.incidents.total),
            type: 'bar',
            name: 'Total Incidents',
            marker: {{color: '#ffc107'}}
        }};

        const criticalIncidentTrace = {{
            x: timelineData.map(d => d.week),
            y: timelineData.map(d => d.incidents.critical),
            type: 'bar',
            name: 'Critical Incidents',
            marker: {{color: '#dc3545'}}
        }};

        const incidentLayout = {{
            title: '',
            xaxis: {{title: 'Week'}},
            yaxis: {{title: 'Count'}},
            barmode: 'stack',
            hovermode: 'x unified'
        }};

        Plotly.newPlot('incident-chart', [incidentTrace, criticalIncidentTrace], incidentLayout);

        // War-Game Drill Chart
        const drillTrace = {{
            x: timelineData.map(d => d.week),
            y: timelineData.map(d => d.war_game_drills.score),
            type: 'scatter',
            mode: 'lines+markers',
            name: 'Drill Score',
            line: {{color: '#6f42c1', width: 3}},
            marker: {{size: 8}}
        }};

        const drillLayout = {{
            title: '',
            xaxis: {{title: 'Week'}},
            yaxis: {{title: 'Score (%)', range: [0, 100]}},
            hovermode: 'x unified'
        }};

        Plotly.newPlot('drill-chart', [drillTrace], drillLayout);

        // Populate gates
        const gatesContainer = document.getElementById('gates-container');
        Object.entries(gatesData).forEach(([gateKey, gateData]) => {{
            const gateName = gateKey.replace('_gate', '').replace(/_/g, ' ').replace(/\\b\\w/g, l => l.toUpperCase());
            const gateCard = document.createElement('div');
            gateCard.className = `gate-card ${{gateData.current_status}}`;
            gateCard.innerHTML = `
                <h3>${{gateName}}</h3>
                <p><strong>Status:</strong> ${{gateData.current_status.toUpperCase()}}</p>
                <p><strong>Weeks Met:</strong> ${{gateData.weeks_met}}</p>
                <p><strong>Target:</strong> ${{gateData.target}}${{gateKey.includes('readiness') || gateKey.includes('drill') ? '%' : gateKey.includes('pnl') ? '%' : ''}}</p>
            `;
            gatesContainer.appendChild(gateCard);
        }});

        // Populate milestones
        const milestonesContainer = document.getElementById('milestones-container');
        milestonesData.forEach(milestone => {{
            const milestoneDiv = document.createElement('div');
            milestoneDiv.className = `milestone ${{milestone.impact}}`;
            milestoneDiv.innerHTML = `
                <strong>Week ${{milestone.week}}:</strong> ${{milestone.title}}
                <br><em>${{milestone.description}}</em>
            `;
            milestonesContainer.appendChild(milestoneDiv);
        }});
    </script>
</body>
</html>
        """
        
        return html_content
    
    def generate_timeline(self, output_path: str = "season1_timeline.html"):
        """Generate complete Season 1 timeline view."""
        print("Loading weekly data...")
        weekly_data = self.load_weekly_data()
        
        if not weekly_data:
            print("No weekly data found. Generating sample data...")
            weekly_data = self.generate_sample_data()
        
        print("Extracting timeline metrics...")
        timeline_data = self.extract_timeline_metrics(weekly_data)
        
        print("Calculating promotion gates...")
        gates = self.calculate_promotion_gates(timeline_data)
        
        print("Identifying key milestones...")
        milestones = self.identify_key_milestones(timeline_data)
        
        print("Calculating trend analysis...")
        trends = self.calculate_trend_analysis(timeline_data)
        
        print("Generating executive summary...")
        executive_summary = self.generate_executive_summary(timeline_data, gates)
        
        print("Generating HTML timeline...")
        html_content = self.generate_html_timeline(timeline_data, gates, milestones, trends)
        
        # Update timeline data
        self.timeline_data["weekly_data"] = timeline_data
        self.timeline_data["promotion_gates"] = gates
        self.timeline_data["key_milestones"] = milestones
        self.timeline_data["trend_analysis"] = trends
        self.timeline_data["executive_summary"] = executive_summary
        self.timeline_data["season_metadata"]["total_weeks"] = len(timeline_data)
        
        # Save HTML timeline
        with open(output_path, 'w') as f:
            f.write(html_content)
        
        # Save JSON data
        json_path = output_path.replace('.html', '.json')
        with open(json_path, 'w') as f:
            json.dump(self.timeline_data, f, indent=2)
        
        print(f"Season 1 timeline generated: {output_path}")
        print(f"Timeline data saved: {json_path}")
        
        # Print summary
        if timeline_data:
            latest_week = timeline_data[-1]
            met_gates = sum(1 for gate in gates.values() if gate["current_status"] == "met")
            print(f"\n=== SEASON 1 SUMMARY ===")
            print(f"Weeks Analyzed: {len(timeline_data)}")
            print(f"Current Readiness: {latest_week['readiness_score']:.1f}%")
            print(f"Promotion Gates Met: {met_gates}/{len(gates)}")
            print(f"Total Incidents: {sum(week['incidents']['total'] for week in timeline_data)}")
            print(f"War-Game Drills: {sum(week['war_game_drills']['conducted'] for week in timeline_data)}")
            print(f"Key Milestones: {len(milestones)}")
        
        return self.timeline_data
    
    def generate_sample_data(self) -> List[Dict[str, Any]]:
        """Generate sample data for demonstration."""
        sample_data = []
        
        for week in range(1, 13):  # 12 weeks of sample data
            # Simulate improving readiness over time
            base_readiness = 65 + (week * 2.5) + (week % 3 * 2)
            readiness_score = min(95, base_readiness + (week % 4 * 1.5))
            
            # Simulate shadow PnL
            pnl_target = 10000.0
            pnl_current = pnl_target * (0.8 + (week / 20) + (week % 5 * 0.02))
            pnl_drawdown = 0.02 + (week % 7 * 0.005)
            
            # Simulate incidents (decreasing over time)
            incident_count = max(0, 3 - (week // 3) + (week % 4))
            critical_incidents = 1 if week <= 4 else 0
            
            # Simulate war-game drills (improving over time)
            drill_score = 70 + (week * 2) + (week % 3 * 3)
            drill_grade = "A" if drill_score >= 90 else "B" if drill_score >= 80 else "C" if drill_score >= 70 else "F"
            
            sample_data.append({
                "week": week,
                "week_start": f"2024-W{week-1}-1",
                "readiness_score": readiness_score,
                "shadow_pnl": {
                    "current": pnl_current,
                    "target": pnl_target,
                    "drawdown": pnl_drawdown,
                    "within_bounds": abs(pnl_current - pnl_target) <= (pnl_target * 0.05)
                },
                "incidents": {
                    "total": incident_count,
                    "critical": critical_incidents,
                    "status": "clean" if critical_incidents == 0 else "critical_issues"
                },
                "rollbacks": max(0, 2 - (week // 4)),
                "war_game_drills": {
                    "score": drill_score,
                    "grade": drill_grade,
                    "conducted": 1,
                    "passed": drill_score >= 85.0
                },
                "changes": {
                    "releases": 2 + (week % 3),
                    "features": 1 + (week % 2),
                    "risk_controls": week % 3
                },
                "testing": {
                    "unit_coverage": 75 + (week * 1.5),
                    "critical_vulns": max(0, 3 - (week // 2)),
                    "status": "healthy" if week >= 6 else "security_issues"
                }
            })
        
        return sample_data


def main():
    """Main entry point for Season 1 timeline generation."""
    parser = argparse.ArgumentParser(description='Generate MERID Season 1 timeline view')
    parser.add_argument('--data-dir', default='.', help='Directory containing weekly summary files')
    parser.add_argument('--output', default='season1_timeline.html', help='Output HTML file')
    
    args = parser.parse_args()
    
    generator = SeasonTimelineGenerator(args.data_dir)
    generator.generate_timeline(args.output)


if __name__ == "__main__":
    main()
