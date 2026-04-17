#!/usr/bin/env python3
"""
Risk Controls Dashboard Component for MERID.

Displays real-time risk control status including mode, assertion health,
and priority violations for human operators.
"""

import json
import time
import requests
from typing import Dict, Any, List
from datetime import datetime, timedelta

class RiskControlsDashboard:
    """Real-time risk controls dashboard for MERID."""
    
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
    
    def get_risk_control_status(self) -> Dict[str, Any]:
        """Get comprehensive risk control status."""
        try:
            # Get system state
            system_state = self._get_system_state()
            
            # Get metrics
            metrics = self._get_metrics()
            
            # Get violations
            violations = self._get_violations()
            
            # Get safety checks
            safety_checks = self._get_safety_checks()
            
            # Calculate risk score
            risk_score = self._calculate_risk_score(system_state, metrics, violations, safety_checks)
            
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "system_state": system_state,
                "metrics": metrics,
                "violations": violations,
                "safety_checks": safety_checks,
                "risk_score": risk_score,
                "overall_status": self._determine_overall_status(risk_score)
            }
        except Exception as e:
            return {
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
                "system_state": {"mode": "unknown", "status": "error"},
                "metrics": {},
                "violations": {},
                "safety_checks": {},
                "risk_score": 0.0,
                "overall_status": "error"
            }
    
    def _get_system_state(self) -> Dict[str, Any]:
        """Get current system state."""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/reality/status",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"mode": "unknown", "status": "error", "error": str(e)}
    
    def _get_metrics(self) -> Dict[str, Any]:
        """Get current metrics."""
        try:
            response = requests.get(
                f"{self.base_url}/metrics",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return self._parse_metrics(response.text)
        except Exception as e:
            return {"error": str(e)}
    
    def _parse_metrics(self, metrics_text: str) -> Dict[str, Any]:
        """Parse Prometheus metrics into structured data."""
        metrics = {}
        
        for line in metrics_text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                parts = line.split()
                if len(parts) >= 2:
                    metric_name = parts[0]
                    value = float(parts[1])
                    
                    # Extract key metrics
                    if 'reality_valid_assertions' in metric_name:
                        domain = metric_name.split('{')[1].split('}')[0].split('=')[1].strip('"')
                        if 'valid_assertions' not in metrics:
                            metrics['valid_assertions'] = {}
                        metrics['valid_assertions'][domain] = value
                    
                    elif 'reality_mode' in metric_name:
                        metrics['current_mode'] = int(value)
                    
                    elif 'reality_mode_transitions_total' in metric_name:
                        if 'mode_transitions' not in metrics:
                            metrics['mode_transitions'] = 0
                        metrics['mode_transitions'] += value
                    
                    elif 'reality_mode_rollbacks_total' in metric_name:
                        if 'rollbacks' not in metrics:
                            metrics['rollbacks'] = 0
                        metrics['rollbacks'] += value
                    
                    elif 'reality_priority_violations_total' in metric_name:
                        if 'priority_violations' not in metrics:
                            metrics['priority_violations'] = 0
                        metrics['priority_violations'] += value
                    
                    elif 'reality_assertion_eval_latency_ms' in metric_name:
                        if 'assertion_latency' not in metrics:
                            metrics['assertion_latency'] = []
                        metrics['assertion_latency'].append(value)
                    
                    elif 'reality_priority_decision_latency_ms' in metric_name:
                        if 'priority_latency' not in metrics:
                            metrics['priority_latency'] = []
                        metrics['priority_latency'].append(value)
        
        # Calculate derived metrics
        if 'valid_assertions' in metrics:
            total_valid = sum(metrics['valid_assertions'].values())
            total_expected = len(metrics['valid_assertions']) * 5  # 5 per domain
            metrics['assertion_health_percentage'] = (total_valid / total_expected * 100) if total_expected > 0 else 0
        
        # Calculate latency percentiles
        if 'assertion_latency' in metrics and metrics['assertion_latency']:
            metrics['assertion_latency_p95'] = sorted(metrics['assertion_latency'])[int(len(metrics['assertion_latency']) * 0.95)]
            metrics['assertion_latency_avg'] = sum(metrics['assertion_latency']) / len(metrics['assertion_latency'])
        
        if 'priority_latency' in metrics and metrics['priority_latency']:
            metrics['priority_latency_p95'] = sorted(metrics['priority_latency'])[int(len(metrics['priority_latency']) * 0.95)]
            metrics['priority_latency_avg'] = sum(metrics['priority_latency']) / len(metrics['priority_latency'])
        
        return metrics
    
    def _get_violations(self) -> Dict[str, Any]:
        """Get recent priority violations."""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/domain-priority/violations",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "violations": []}
    
    def _get_safety_checks(self) -> Dict[str, Any]:
        """Get safety check status."""
        try:
            response = requests.get(
                f"{self.base_url}/api/v1/reality/safety-checks",
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"error": str(e), "checks": {}}
    
    def _calculate_risk_score(self, system_state: Dict, metrics: Dict, 
                            violations: Dict, safety_checks: Dict) -> float:
        """Calculate overall risk score (0-100, higher is better)."""
        score = 100.0
        
        # System mode score (30% weight)
        mode = system_state.get("system_state", {}).get("mode", "unknown")
        if mode == "SIGHTED_DEGRADED":
            mode_score = 90.0  # Good but needs monitoring
        elif mode == "OPERATIONAL":
            mode_score = 100.0  # Optimal
        elif mode == "BLIND":
            mode_score = 50.0  # Needs attention
        else:
            mode_score = 0.0  # Unknown/error
        
        score = score * 0.7 + mode_score * 0.3
        
        # Assertion health penalty (20% weight)
        assertion_health = metrics.get("assertion_health_percentage", 0)
        if assertion_health < 80:
            score -= (80 - assertion_health) * 0.5
        
        # Violations penalty (20% weight)
        violation_count = violations.get("total_count", 0)
        if violation_count > 0:
            score -= min(violation_count * 2, 20)
        
        # Rollbacks penalty (15% weight)
        rollback_count = metrics.get("rollbacks", 0)
        if rollback_count > 0:
            score -= min(rollback_count * 10, 15)
        
        # Latency penalty (15% weight)
        assertion_latency = metrics.get("assertion_latency_p95", 0)
        if assertion_latency > 100:  # 100ms threshold
            score -= min((assertion_latency - 100) * 0.1, 15)
        
        return max(0.0, min(100.0, score))
    
    def _determine_overall_status(self, risk_score: float) -> str:
        """Determine overall status based on risk score."""
        if risk_score >= 90:
            return "HEALTHY"
        elif risk_score >= 75:
            return "MONITOR"
        elif risk_score >= 50:
            return "ATTENTION"
        else:
            return "CRITICAL"
    
    def generate_dashboard_html(self) -> str:
        """Generate HTML dashboard."""
        status_data = self.get_risk_control_status()
        
        status_color = {
            "HEALTHY": "#28a745",
            "MONITOR": "#ffc107", 
            "ATTENTION": "#fd7e14",
            "CRITICAL": "#dc3545",
            "ERROR": "#6c757d"
        }.get(status_data["overall_status"], "#6c757d")
        
        mode_color = {
            "BLIND": "#dc3545",
            "SIGHTED_DEGRADED": "#ffc107",
            "OPERATIONAL": "#28a745",
            "unknown": "#6c757d"
        }.get(status_data.get("system_state", {}).get("mode", "unknown"), "#6c757d")
        
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MERID Risk Controls Dashboard</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f8f9fa;
            color: #333;
        }}
        .dashboard {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
        }}
        .header {{
            text-align: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 2px solid #eee;
        }}
        .status-indicator {{
            font-size: 24px;
            font-weight: bold;
            color: white;
            padding: 15px 30px;
            border-radius: 8px;
            display: inline-block;
            margin-bottom: 10px;
            text-transform: uppercase;
            background-color: {status_color};
        }}
        .risk-score {{
            font-size: 36px;
            font-weight: bold;
            color: #333;
            margin-bottom: 10px;
        }}
        .risk-score-bar {{
            width: 100%;
            height: 20px;
            background: #e9ecef;
            border-radius: 10px;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        .risk-score-fill {{
            height: 100%;
            background: linear-gradient(90deg, #dc3545 0%, #ffc107 50%, #28a745 100%);
            transition: width 0.3s ease;
        }}
        .grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }}
        .card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            border-left: 4px solid #007bff;
        }}
        .card.critical {{
            border-left-color: #dc3545;
        }}
        .card.warning {{
            border-left-color: #ffc107;
        }}
        .card.success {{
            border-left-color: #28a745;
        }}
        .card h3 {{
            margin-top: 0;
            color: #333;
            font-size: 18px;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            padding: 10px 0;
            border-bottom: 1px solid #eee;
        }}
        .metric:last-child {{
            border-bottom: none;
        }}
        .metric-label {{
            font-weight: 500;
            color: #666;
        }}
        .metric-value {{
            font-weight: bold;
            color: #333;
        }}
        .mode-indicator {{
            display: inline-block;
            padding: 5px 10px;
            border-radius: 4px;
            color: white;
            font-weight: bold;
            font-size: 12px;
            text-transform: uppercase;
            background-color: {mode_color};
        }}
        .violation {{
            background: #f8f9fa;
            border-left: 3px solid #dc3545;
            padding: 10px;
            margin-bottom: 10px;
            border-radius: 4px;
            font-size: 14px;
        }}
        .timestamp {{
            color: #666;
            font-size: 12px;
            text-align: center;
            margin-top: 20px;
        }}
        .refresh-button {{
            background: #007bff;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 14px;
        }}
        .refresh-button:hover {{
            background: #0056b3;
        }}
        .alert {{
            background: #f8d7da;
            border: 1px solid #f5c6cb;
            color: #721c24;
            padding: 15px;
            border-radius: 4px;
            margin-bottom: 20px;
        }}
        .alert.warning {{
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            color: #856404;
        }}
        .alert.success {{
            background: #d4edda;
            border: 1px solid #c3e6cb;
            color: #155724;
        }}
    </style>
    <script>
        function refreshDashboard() {{
            location.reload();
        }}
        
        // Auto-refresh every 30 seconds
        setInterval(refreshDashboard, 30000);
    </script>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <h1>MERID Risk Controls Dashboard</h1>
            <div class="status-indicator">{status_data['overall_status']}</div>
            <div class="risk-score">{status_data.get('risk_score', 0):.1f}%</div>
            <div class="risk-score-bar">
                <div class="risk-score-fill" style="width: {status_data.get('risk_score', 0)}%"></div>
            </div>
            <p>System Mode: <span class="mode-indicator">{status_data.get('system_state', {}).get('mode', 'unknown')}</span></p>
            <button class="refresh-button" onclick="refreshDashboard()">Refresh</button>
        </div>
        
        {self._generate_alerts_html(status_data)}
        
        <div class="grid">
            <div class="card">
                <h3>System State</h3>
                <div class="metric">
                    <span class="metric-label">Current Mode:</span>
                    <span class="metric-value">
                        <span class="mode-indicator">{status_data.get('system_state', {}).get('mode', 'unknown')}</span>
                    </span>
                </div>
                <div class="metric">
                    <span class="metric-label">Valid Assertions:</span>
                    <span class="metric-value">{status_data.get('metrics', {}).get('assertion_health_percentage', 0):.1f}%</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Mode Transitions:</span>
                    <span class="metric-value">{status_data.get('metrics', {}).get('mode_transitions', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Rollbacks:</span>
                    <span class="metric-value">{status_data.get('metrics', {}).get('rollbacks', 0)}</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Performance Metrics</h3>
                <div class="metric">
                    <span class="metric-label">Assertion Latency (P95):</span>
                    <span class="metric-value">{status_data.get('metrics', {}).get('assertion_latency_p95', 0):.1f}ms</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Priority Latency (P95):</span>
                    <span class="metric-value">{status_data.get('metrics', {}).get('priority_latency_p95', 0):.1f}ms</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Priority Violations:</span>
                    <span class="metric-value">{status_data.get('metrics', {}).get('priority_violations', 0)}</span>
                </div>
                <div class="metric">
                    <span class="metric-label">Risk Score:</span>
                    <span class="metric-value">{status_data.get('risk_score', 0):.1f}%</span>
                </div>
            </div>
            
            <div class="card">
                <h3>Domain Health</h3>
                {self._generate_domain_health_html(status_data.get('metrics', {}).get('valid_assertions', {}))}
            </div>
        </div>
        
        <div class="card">
            <h3>Recent Priority Violations</h3>
            {self._generate_violations_html(status_data.get('violations', {}).get('violations', []))}
        </div>
        
        <div class="card">
            <h3>Safety Checks</h3>
            {self._generate_safety_checks_html(status_data.get('safety_checks', {}).get('checks', {}))}
        </div>
        
        <div class="timestamp">
            Last updated: {status_data.get('timestamp', 'Unknown')}
        </div>
    </div>
</body>
</html>
        """
        return html
    
    def _generate_alerts_html(self, status_data: Dict) -> str:
        """Generate alert HTML based on status."""
        alerts = []
        
        if status_data.get('overall_status') == 'CRITICAL':
            alerts.append("""
            <div class="alert">
                <strong>Critical Risk Status:</strong> System requires immediate attention. Risk score below 50%.
            </div>
            """)
        elif status_data.get('overall_status') == 'ATTENTION':
            alerts.append("""
            <div class="alert warning">
                <strong>Attention Required:</strong> System needs monitoring. Risk score between 50-75%.
            </div>
            """)
        elif status_data.get('overall_status') == 'MONITOR':
            alerts.append("""
            <div class="alert warning">
                <strong>Monitor Closely:</strong> System is stable but requires monitoring. Risk score between 75-90%.
            </div>
            """)
        elif status_data.get('overall_status') == 'HEALTHY':
            alerts.append("""
            <div class="alert success">
                <strong>System Healthy:</strong> All risk controls operating normally. Risk score above 90%.
            </div>
            """)
        
        # Check for specific issues
        mode = status_data.get('system_state', {}).get('mode', 'unknown')
        if mode == 'BLIND':
            alerts.append("""
            <div class="alert">
                <strong>System in BLIND Mode:</strong> Risk controls are inactive. System is operating in safe mode.
            </div>
            """)
        
        violation_count = status_data.get('metrics', {}).get('priority_violations', 0)
        if violation_count > 10:
            alerts.append(f"""
            <div class="alert">
                <strong>High Violation Rate:</strong> {violation_count} priority violations detected.
            </div>
            """)
        
        assertion_health = status_data.get('metrics', {}).get('assertion_health_percentage', 0)
        if assertion_health < 80:
            alerts.append(f"""
            <div class="alert">
                <strong>Low Assertion Health:</strong> Only {assertion_health:.1f}% of expected assertions are valid.
            </div>
            """)
        
        return "".join(alerts)
    
    def _generate_domain_health_html(self, valid_assertions: Dict) -> str:
        """Generate domain health HTML."""
        if not valid_assertions:
            return "<div class='metric'><span class='metric-value'>No assertion data available</span></div>"
        
        html_parts = []
        for domain, count in valid_assertions.items():
            health = (count / 5) * 100  # 5 assertions per domain expected
            health_color = "#28a745" if health >= 80 else "#ffc107" if health >= 60 else "#dc3545"
            
            html_parts.append(f"""
            <div class="metric">
                <span class="metric-label">{domain.title()}:</span>
                <span class="metric-value" style="color: {health_color}">
                    {count}/5 ({health:.0f}%)
                </span>
            </div>
            """)
        
        return "".join(html_parts)
    
    def _generate_violations_html(self, violations: List) -> str:
        """Generate violations HTML."""
        if not violations:
            return "<div class='metric'><span class='metric-value'>No recent violations</span></div>"
        
        html_parts = []
        for violation in violations[:5]:  # Show last 5 violations
            timestamp = violation.get('timestamp', 'Unknown')
            domain = violation.get('domain', 'Unknown')
            operation = violation.get('operation', 'Unknown')
            actor = violation.get('actor_id', 'Unknown')
            
            html_parts.append(f"""
            <div class="violation">
                <strong>{domain}.{operation}</strong> by {actor}<br>
                <small>{timestamp}</small>
            </div>
            """)
        
        if len(violations) > 5:
            html_parts.append(f"<div class='metric'><span class='metric-value'>... and {len(violations) - 5} more</span></div>")
        
        return "".join(html_parts)
    
    def _generate_safety_checks_html(self, safety_checks: Dict) -> str:
        """Generate safety checks HTML."""
        if not safety_checks:
            return "<div class='metric'><span class='metric-value'>No safety check data available</span></div>"
        
        html_parts = []
        for check_name, check_result in safety_checks.items():
            status = "✅" if check_result.get('passed', False) else "❌"
            reason = check_result.get('reason', 'No reason provided')
            
            html_parts.append(f"""
            <div class="metric">
                <span class="metric-label">{check_name}:</span>
                <span class="metric-value">{status} {reason}</span>
            </div>
            """)
        
        return "".join(html_parts)


def main():
    """Main entry point for risk controls dashboard."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Generate MERID risk controls dashboard')
    parser.add_argument('--base-url', default='http://localhost:8001', help='Base URL for MERID API')
    parser.add_argument('--api-key', help='API key for authentication')
    parser.add_argument('--output', default='risk-controls-dashboard.html', help='Output filename')
    parser.add_argument('--port', type=int, default=8080, help='Port to serve dashboard on')
    
    args = parser.parse_args()
    
    # Create dashboard
    dashboard = RiskControlsDashboard(args.base_url, args.api_key)
    
    # Generate HTML dashboard
    html_content = dashboard.generate_dashboard_html()
    
    # Save dashboard
    with open(args.output, 'w') as f:
        f.write(html_content)
    
    print(f"Risk controls dashboard saved to {args.output}")
    
    # Optionally serve the dashboard
    if args.port:
        import http.server
        import socketserver
        import os
        
        os.chdir(os.path.dirname(os.path.abspath(args.output)))
        
        handler = http.server.SimpleHTTPRequestHandler
        httpd = socketserver.TCPServer(("", args.port), handler)
        
        print(f"Serving dashboard at http://localhost:{args.port}/{os.path.basename(args.output)}")
        print("Press Ctrl+C to stop")
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nDashboard server stopped")


if __name__ == "__main__":
    main()
