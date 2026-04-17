"""
UI Telemetry Sentinel Agent

Swarm agent that monitors UI health and performance metrics for local venue.
"""

from __future__ import annotations

import asyncio
import time
import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger(__name__)


class TelemetryIssueType(Enum):
    """Types of telemetry issues."""
    WEBSOCKET_ERROR = "websocket_error"
    HIGH_RECONNECT_COUNT = "high_reconnect_count"
    SLOW_PANEL_LOAD = "slow_panel_load"
    HIGH_FALLBACK_RATE = "high_fallback_rate"
    MISSING_DATA = "missing_data"
    UI_ERROR = "ui_error"


@dataclass
class TelemetryIssue:
    """Telemetry issue detected by sentinel."""
    issue_id: str
    issue_type: TelemetryIssueType
    severity: str  # low, medium, high, critical
    title: str
    description: str
    component: str
    timestamp: float = field(default_factory=time.time)
    metrics: Dict[str, Any] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    stack_trace: Optional[str] = None


@dataclass
class PerformanceMetrics:
    """Performance metrics tracking."""
    panel_load_times: Dict[str, List[float]] = field(default_factory=dict)
    websocket_reconnects: int = 0
    websocket_errors: int = 0
    fallback_activations: int = 0
    ui_errors: int = 0
    missing_data_events: int = 0
    last_update: float = field(default_factory=time.time)


class UITelemetrySentinel:
    """
    UI Telemetry Sentinel Agent
    
    Scans logs and metrics for WebSocket errors, high fallback rates,
    slow panel load times, and proposes UX or infrastructure fixes.
    """
    
    def __init__(self):
        self.issues: List[TelemetryIssue] = []
        self.metrics = PerformanceMetrics()
        self.last_scan_time = 0.0
        self.scan_interval = 60.0  # 1 minute
        self.performance_thresholds = {
            "panel_load_time_ms": 500.0,
            "websocket_reconnect_rate": 0.1,  # per minute
            "fallback_rate": 0.05,  # per minute
            "ui_error_rate": 0.02  # per minute
        }
        self.log_patterns = {
            "websocket_error": [
                r"WebSocket.*error",
                r"WebSocket.*failed",
                r"Connection.*lost",
                r"reconnect.*failed"
            ],
            "ui_error": [
                r"TypeError.*undefined",
                r"ReferenceError.*not defined",
                r"Failed to load.*component",
                r"Error rendering.*panel"
            ],
            "slow_load": [
                r"Panel.*load.*slow",
                r"Timeout.*loading",
                r"Performance.*warning"
            ]
        }
    
    async def start_monitoring(self):
        """Start continuous monitoring."""
        logger.info("UI Telemetry Sentinel starting monitoring")
        
        while True:
            try:
                await self.scan_telemetry_data()
                await asyncio.sleep(self.scan_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)  # Wait 30 seconds on error
    
    async def scan_telemetry_data(self):
        """Scan telemetry data for issues."""
        try:
            # Scan logs for errors and performance issues
            await self.scan_logs()
            
            # Check performance metrics
            await self.check_performance_metrics()
            
            # Analyze WebSocket health
            await self.check_websocket_health()
            
            # Check fallback usage
            await self.check_fallback_usage()
            
            # Validate UI data integrity
            await self.check_data_integrity()
            
            self.last_scan_time = time.time()
            
        except Exception as e:
            logger.error(f"Error scanning telemetry data: {e}")
    
    async def scan_logs(self):
        """Scan logs for patterns indicating issues."""
        try:
            # In a real implementation, this would scan actual log files
            # For now, we'll simulate log scanning
            
            log_entries = await self.get_recent_log_entries()
            
            for entry in log_entries:
                await self.analyze_log_entry(entry)
                
        except Exception as e:
            logger.error(f"Error scanning logs: {e}")
    
    async def get_recent_log_entries(self) -> List[str]:
        """Get recent log entries for analysis."""
        # Simulate log entries - in real implementation, read from log files
        current_time = time.time()
        
        # Simulate some log patterns
        entries = []
        
        # Simulate WebSocket errors
        if self.metrics.websocket_errors > 0:
            entries.append(f"[{current_time}] WebSocket connection failed: Connection refused")
        
        # Simulate UI errors
        if self.metrics.ui_errors > 0:
            entries.append(f"[{current_time}] TypeError: Cannot read property 'undefined' of undefined")
        
        # Simulate slow loads
        if any(max(times) > self.performance_thresholds["panel_load_time_ms"] for times in self.metrics.panel_load_times.values()):
            entries.append(f"[{current_time}] Performance warning: Local Venue panel load time 1200ms")
        
        return entries
    
    async def analyze_log_entry(self, log_entry: str):
        """Analyze a single log entry for issues."""
        timestamp_str = re.search(r'\[([0-9.]+)\]', log_entry)
        timestamp = float(timestamp_str.group(1)) if timestamp_str else time.time()
        
        # Check for WebSocket errors
        for pattern in self.log_patterns["websocket_error"]:
            if re.search(pattern, log_entry, re.IGNORECASE):
                issue = TelemetryIssue(
                    issue_id=f"ws_error_{int(timestamp)}",
                    issue_type=TelemetryIssueType.WEBSOCKET_ERROR,
                    severity="high",
                    title="WebSocket Connection Error",
                    description=log_entry,
                    component="websocket",
                    metrics={"error_count": self.metrics.websocket_errors + 1},
                    recommendations=[
                        "Check WebSocket server status",
                        "Verify network connectivity",
                        "Review WebSocket reconnection logic"
                    ]
                )
                
                self.issues.append(issue)
                self.metrics.websocket_errors += 1
                await self.notify_swarm(issue)
        
        # Check for UI errors
        for pattern in self.log_patterns["ui_error"]:
            if re.search(pattern, log_entry, re.IGNORECASE):
                issue = TelemetryIssue(
                    issue_id=f"ui_error_{int(timestamp)}",
                    issue_type=TelemetryIssueType.UI_ERROR,
                    severity="medium",
                    title="UI JavaScript Error",
                    description=log_entry,
                    component="ui",
                    metrics={"error_count": self.metrics.ui_errors + 1},
                    recommendations=[
                        "Review JavaScript code for null checks",
                        "Add error boundaries for components",
                        "Validate data before rendering"
                    ]
                )
                
                self.issues.append(issue)
                self.metrics.ui_errors += 1
                await self.notify_swarm(issue)
        
        # Check for performance warnings
        for pattern in self.log_patterns["slow_load"]:
            if re.search(pattern, log_entry, re.IGNORECASE):
                issue = TelemetryIssue(
                    issue_id=f"slow_load_{int(timestamp)}",
                    issue_type=TelemetryIssueType.SLOW_PANEL_LOAD,
                    severity="medium",
                    title="Slow Panel Load Time",
                    description=log_entry,
                    component="performance",
                    recommendations=[
                        "Optimize component rendering",
                        "Implement lazy loading",
                        "Review data fetching logic"
                    ]
                )
                
                self.issues.append(issue)
                await self.notify_swarm(issue)
    
    async def check_performance_metrics(self):
        """Check performance metrics against thresholds."""
        current_time = time.time()
        
        # Check panel load times
        for panel, times in self.metrics.panel_load_times.items():
            if times:
                avg_time = sum(times) / len(times)
                max_time = max(times)
                
                if avg_time > self.performance_thresholds["panel_load_time_ms"]:
                    issue = TelemetryIssue(
                        issue_id=f"panel_perf_{panel}_{int(current_time)}",
                        issue_type=TelemetryIssueType.SLOW_PANEL_LOAD,
                        severity="medium",
                        title=f"Slow Panel Load: {panel}",
                        description=f"Average load time {avg_time:.1f}ms exceeds threshold {self.performance_thresholds['panel_load_time_ms']:.1f}ms",
                        component=panel,
                        metrics={
                            "avg_time_ms": avg_time,
                            "max_time_ms": max_time,
                            "sample_count": len(times)
                        },
                        recommendations=[
                            "Optimize panel data loading",
                            "Implement virtual scrolling for large datasets",
                            "Cache panel data effectively"
                        ]
                    )
                    
                    self.issues.append(issue)
                    await self.notify_swarm(issue)
    
    async def check_websocket_health(self):
        """Check WebSocket connection health."""
        current_time = time.time()
        time_window = 300.0  # 5 minutes
        
        # Calculate reconnect rate
        reconnect_rate = self.metrics.websocket_reconnects / (time_window / 60)  # per minute
        
        if reconnect_rate > self.performance_thresholds["websocket_reconnect_rate"]:
            issue = TelemetryIssue(
                issue_id=f"ws_health_{int(current_time)}",
                issue_type=TelemetryIssueType.HIGH_RECONNECT_COUNT,
                severity="high",
                title="High WebSocket Reconnect Rate",
                description=f"WebSocket reconnect rate {reconnect_rate:.2f}/min exceeds threshold {self.performance_thresholds['websocket_reconnect_rate']:.2f}/min",
                component="websocket",
                metrics={
                    "reconnect_rate": reconnect_rate,
                    "total_reconnects": self.metrics.websocket_reconnects,
                    "time_window_minutes": time_window / 60
                },
                recommendations=[
                    "Investigate WebSocket connection stability",
                    "Check server capacity and load",
                    "Implement exponential backoff for reconnections"
                ]
            )
            
            self.issues.append(issue)
            await self.notify_swarm(issue)
    
    async def check_fallback_usage(self):
        """Check REST API fallback usage."""
        current_time = time.time()
        time_window = 300.0  # 5 minutes
        
        # Calculate fallback rate
        fallback_rate = self.metrics.fallback_activations / (time_window / 60)  # per minute
        
        if fallback_rate > self.performance_thresholds["fallback_rate"]:
            issue = TelemetryIssue(
                issue_id=f"fallback_{int(current_time)}",
                issue_type=TelemetryIssueType.HIGH_FALLBACK_RATE,
                severity="medium",
                title="High Fallback Rate",
                description=f"REST fallback rate {fallback_rate:.2f}/min exceeds threshold {self.performance_thresholds['fallback_rate']:.2f}/min",
                component="telemetry",
                metrics={
                    "fallback_rate": fallback_rate,
                    "total_fallbacks": self.metrics.fallback_activations,
                    "time_window_minutes": time_window / 60
                },
                recommendations=[
                    "Investigate WebSocket connection issues",
                    "Improve WebSocket error handling",
                    "Consider WebSocket connection pooling"
                ]
            )
            
            self.issues.append(issue)
            await self.notify_swarm(issue)
    
    async def check_data_integrity(self):
        """Check for missing or corrupted data."""
        current_time = time.time()
        
        # Check for missing data events
        if self.metrics.missing_data_events > 0:
            issue = TelemetryIssue(
                issue_id=f"data_integrity_{int(current_time)}",
                issue_type=TelemetryIssueType.MISSING_DATA,
                severity="medium",
                title="Data Integrity Issues",
                description=f"Detected {self.metrics.missing_data_events} missing data events",
                component="data",
                metrics={"missing_events": self.metrics.missing_data_events},
                recommendations=[
                    "Validate data before processing",
                    "Add data completeness checks",
                    "Implement data recovery mechanisms"
                ]
            )
            
            self.issues.append(issue)
            await self.notify_swarm(issue)
    
    async def notify_swarm(self, issue: TelemetryIssue):
        """Notify swarm of telemetry issue."""
        logger.warning(f"UI Telemetry Alert: {issue.title} - {issue.description}")
        
        # Store issue for dashboard display
        if len(self.issues) > 100:  # Keep only recent issues
            self.issues = self.issues[-100:]
    
    async def get_issues(self, issue_type: Optional[TelemetryIssueType] = None) -> List[TelemetryIssue]:
        """Get recent issues, optionally filtered by type."""
        if issue_type is None:
            return self.issues.copy()
        return [issue for issue in self.issues if issue.issue_type == issue_type]
    
    async def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary for dashboard."""
        return {
            "panel_performance": {
                panel: {
                    "avg_time_ms": sum(times) / len(times) if times else 0,
                    "max_time_ms": max(times) if times else 0,
                    "sample_count": len(times)
                }
                for panel, times in self.metrics.panel_load_times.items()
            },
            "websocket_health": {
                "reconnects": self.metrics.websocket_reconnects,
                "errors": self.metrics.websocket_errors,
                "reconnect_rate": self.metrics.websocket_reconnects / 5.0  # per minute
            },
            "fallback_usage": {
                "activations": self.metrics.fallback_activations,
                "fallback_rate": self.metrics.fallback_activations / 5.0  # per minute
            },
            "ui_errors": {
                "count": self.metrics.ui_errors,
                "error_rate": self.metrics.ui_errors / 5.0  # per minute
            },
            "data_integrity": {
                "missing_events": self.metrics.missing_data_events
            }
        }
    
    async def generate_ux_recommendations(self) -> List[str]:
        """Generate UX improvement recommendations."""
        recommendations = []
        
        # Analyze recent issues for patterns
        recent_issues = self.issues[-20:]  # Last 20 issues
        
        websocket_issues = [i for i in recent_issues if i.issue_type == TelemetryIssueType.WEBSOCKET_ERROR]
        performance_issues = [i for i in recent_issues if i.issue_type == TelemetryIssueType.SLOW_PANEL_LOAD]
        ui_errors = [i for i in recent_issues if i.issue_type == TelemetryIssueType.UI_ERROR]
        
        if len(websocket_issues) > 5:
            recommendations.append("Implement WebSocket connection status indicator")
            recommendations.append("Add manual reconnection button for users")
        
        if len(performance_issues) > 3:
            recommendations.append("Add loading indicators for slow panels")
            recommendations.append("Implement progressive data loading")
        
        if len(ui_errors) > 2:
            recommendations.append("Add error boundaries to prevent UI crashes")
            recommendations.append("Implement user-friendly error messages")
        
        # Check for high fallback rate
        if self.metrics.fallback_activations > 10:
            recommendations.append("Improve WebSocket connection reliability")
            recommendations.append("Add offline mode capability")
        
        return recommendations
    
    def record_panel_load_time(self, panel: str, load_time_ms: float):
        """Record panel load time for performance tracking."""
        if panel not in self.metrics.panel_load_times:
            self.metrics.panel_load_times[panel] = []
        
        self.metrics.panel_load_times[panel].append(load_time_ms)
        
        # Keep only recent measurements
        if len(self.metrics.panel_load_times[panel]) > 100:
            self.metrics.panel_load_times[panel] = self.metrics.panel_load_times[panel][-50:]
    
    def record_websocket_reconnect(self):
        """Record WebSocket reconnection event."""
        self.metrics.websocket_reconnects += 1
        self.metrics.last_update = time.time()
    
    def record_websocket_error(self):
        """Record WebSocket error event."""
        self.metrics.websocket_errors += 1
        self.metrics.last_update = time.time()
    
    def record_fallback_activation(self):
        """Record REST API fallback activation."""
        self.metrics.fallback_activations += 1
        self.metrics.last_update = time.time()
    
    def record_ui_error(self):
        """Record UI error event."""
        self.metrics.ui_errors += 1
        self.metrics.last_update = time.time()
    
    def record_missing_data(self):
        """Record missing data event."""
        self.metrics.missing_data_events += 1
        self.metrics.last_update = time.time()


# Swarm integration functions
def create_sentinel_agent() -> UITelemetrySentinel:
    """Create and return a sentinel agent instance."""
    return UITelemetrySentinel()


async def run_sentinel_monitoring():
    """Run the sentinel monitoring loop."""
    sentinel = create_sentinel_agent()
    await sentinel.start_monitoring()


# Dashboard integration
async def get_telemetry_dashboard_data() -> Dict[str, Any]:
    """Get data for telemetry dashboard display."""
    sentinel = create_sentinel_agent()
    
    return {
        "issues": await sentinel.get_issues(),
        "performance_summary": await sentinel.get_performance_summary(),
        "ux_recommendations": await sentinel.generate_ux_recommendations(),
        "last_scan_time": sentinel.last_scan_time
    }


# CLI interface for swarm agents
def main():
    """Main entry point for standalone execution."""
    import asyncio
    
    async def run():
        sentinel = create_sentinel_agent()
        print("UI Telemetry Sentinel Agent")
        print("=" * 50)
        
        # Run one scan cycle
        await sentinel.scan_telemetry_data()
        
        # Display results
        issues = await sentinel.get_issues()
        performance = await sentinel.get_performance_summary()
        recommendations = await sentinel.generate_ux_recommendations()
        
        print(f"Active Issues: {len(issues)}")
        for issue in issues[-5:]:  # Last 5 issues
            print(f"  - {issue.severity.upper()}: {issue.title}")
        
        print(f"\nPerformance Summary:")
        print(f"  - WebSocket Reconnects: {performance['websocket_health']['reconnects']}")
        print(f"  - Fallback Activations: {performance['fallback_usage']['activations']}")
        print(f"  - UI Errors: {performance['ui_errors']['count']}")
        
        print(f"\nUX Recommendations: {len(recommendations)}")
        for rec in recommendations[:3]:  # First 3 recommendations
            print(f"  - {rec}")
    
    asyncio.run(run())


if __name__ == "__main__":
    main()
