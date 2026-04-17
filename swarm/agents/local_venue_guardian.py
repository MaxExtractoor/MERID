"""
Local Venue Guardian Agent

Swarm agent that monitors local venue test coverage, results, and SLO compliance.
"""

from __future__ import annotations

import asyncio
import time
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger
from web.api.local_venue_validation import get_validation_status, get_validation_summary

logger = get_logger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class ValidationAlert:
    """Validation alert for swarm notification."""
    alert_id: str
    severity: AlertSeverity
    title: str
    description: str
    component: str
    timestamp: float = field(default_factory=time.time)
    recommendations: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnownGoodSnapshot:
    """Known good snapshot for rollback reference."""
    git_ref: str
    test_run_id: str
    timestamp: float
    coverage_metrics: Dict[str, float]
    performance_metrics: Dict[str, float]
    test_results: Dict[str, Any]
    status: str = "good"


class LocalVenueGuardian:
    """
    Local Venue Guardian Agent
    
    Monitors coverage and test results for local venue components,
    files tickets when coverage or SLOs slip, and maintains known-good snapshots.
    """
    
    def __init__(self):
        self.alerts: List[ValidationAlert] = []
        self.known_good_snapshot: Optional[KnownGoodSnapshot] = None
        self.last_check_time = 0.0
        self.check_interval = 300.0  # 5 minutes
        self.coverage_thresholds = {
            "feed_handlers": 95.0,
            "matching_engine": 90.0,
            "ui_components": 80.0,
            "integration_points": 85.0
        }
        self.performance_thresholds = {
            "order_submission_ms": 100.0,
            "order_book_updates_ms": 50.0,
            "ui_api_response_ms": 200.0,
            "websocket_updates_ms": 10.0
        }
    
    async def start_monitoring(self):
        """Start continuous monitoring."""
        logger.info("Local Venue Guardian starting monitoring")
        
        while True:
            try:
                await self.check_validation_status()
                await self.check_strategy_dependencies()
                await self.check_integration_dependencies()
                await self.propose_auto_improvements()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(60)  # Wait 1 minute on error
    
    async def check_validation_status(self):
        """Check current validation status and generate alerts."""
        try:
            status = get_validation_status()
            summary = get_validation_summary()
            
            # Check coverage metrics
            await self.check_coverage_metrics(status.coverage_metrics)
            
            # Check performance metrics
            await self.check_performance_metrics(status.performance_metrics)
            
            # Check phase progress
            await self.check_phase_progress(status.phases)
            
            # Check overall health
            await self.check_overall_health(summary)
            
            # Update known good snapshot if needed
            await self.update_known_good_snapshot(status)
            
            self.last_check_time = time.time()
            
        except Exception as e:
            logger.error(f"Error checking validation status: {e}")
    
    async def check_coverage_metrics(self, coverage_metrics: Dict[str, float]):
        """Check if coverage metrics meet thresholds."""
        for component, coverage in coverage_metrics.items():
            threshold = self.coverage_thresholds.get(component, 0.0)
            
            if coverage < threshold:
                severity = AlertSeverity.HIGH if coverage < threshold * 0.8 else AlertSeverity.MEDIUM
                
                alert = ValidationAlert(
                    alert_id=f"coverage_{component}_{int(time.time())}",
                    severity=severity,
                    title=f"Low Coverage in {component}",
                    description=f"Coverage {coverage:.1f}% below threshold {threshold:.1f}%",
                    component=component,
                    recommendations=[
                        f"Add unit tests to reach {threshold:.1f}% coverage",
                        "Review test gaps and missing scenarios",
                        "Consider integration tests for edge cases"
                    ],
                    metrics={"current_coverage": coverage, "threshold": threshold}
                )
                
                self.alerts.append(alert)
                await self.notify_swarm(alert)
    
    async def check_performance_metrics(self, performance_metrics: Dict[str, float]):
        """Check if performance metrics meet thresholds."""
        for metric, value in performance_metrics.items():
            threshold = self.performance_thresholds.get(metric, float('inf'))
            
            if value > threshold:
                severity = AlertSeverity.HIGH if value > threshold * 1.5 else AlertSeverity.MEDIUM
                
                alert = ValidationAlert(
                    alert_id=f"performance_{metric}_{int(time.time())}",
                    severity=severity,
                    title=f"Performance Degradation in {metric}",
                    description=f"Performance {value:.1f}ms exceeds threshold {threshold:.1f}ms",
                    component="performance",
                    recommendations=[
                        "Profile slow operations",
                        "Check for resource bottlenecks",
                        "Optimize database queries or API calls"
                    ],
                    metrics={"current_value": value, "threshold": threshold}
                )
                
                self.alerts.append(alert)
                await self.notify_swarm(alert)
    
    async def check_phase_progress(self, phases: List[Any]):
        """Check phase progress and identify blockers."""
        for phase in phases:
            if phase.status == "FAIL" and phase.blockers:
                alert = ValidationAlert(
                    alert_id=f"phase_{phase.phase_name}_{int(time.time())}",
                    severity=AlertSeverity.HIGH,
                    title=f"Phase {phase.phase_name} Blocked",
                    description=f"Phase blocked by: {', '.join(phase.blockers)}",
                    component=phase.phase_name,
                    recommendations=phase.recommendations,
                    metrics={
                        "completion": phase.completion_percentage,
                        "blockers_count": len(phase.blockers)
                    }
                )
                
                self.alerts.append(alert)
                await self.notify_swarm(alert)
    
    async def check_overall_health(self, summary: Dict[str, Any]):
        """Check overall system health."""
        if summary["overall_status"] == "FAILING":
            alert = ValidationAlert(
                alert_id=f"overall_health_{int(time.time())}",
                severity=AlertSeverity.CRITICAL,
                title="Local Venue System Failing",
                description=f"System status: {summary['overall_status']}",
                component="system",
                recommendations=[
                    "Check system logs for errors",
                    "Verify all components are running",
                    "Run full test suite to identify issues"
                ],
                metrics=summary
            )
            
            self.alerts.append(alert)
            await self.notify_swarm(alert)
    
    async def update_known_good_snapshot(self, status: Any):
        """Update known good snapshot if current status is better."""
        if self.known_good_snapshot is None:
            # Initialize with current status
            self.known_good_snapshot = KnownGoodSnapshot(
                git_ref="current",
                test_run_id="initial",
                timestamp=time.time(),
                coverage_metrics=status.coverage_metrics,
                performance_metrics=status.performance_metrics,
                test_results={"total_tests": 0, "passed": 0, "failed": 0}
            )
            return
        
        # Check if current status is better
        current_avg_coverage = sum(status.coverage_metrics.values()) / len(status.coverage_metrics) if status.coverage_metrics else 0.0
        known_avg_coverage = sum(self.known_good_snapshot.coverage_metrics.values()) / len(self.known_good_snapshot.coverage_metrics) if self.known_good_snapshot.coverage_metrics else 0.0
        
        if current_avg_coverage > known_avg_coverage and status.overall_status == "HEALTHY":
            self.known_good_snapshot = KnownGoodSnapshot(
                git_ref="current",
                test_run_id=f"guardian_{int(time.time())}",
                timestamp=time.time(),
                coverage_metrics=status.coverage_metrics.copy(),
                performance_metrics=status.performance_metrics.copy(),
                test_results={"total_tests": 0, "passed": 0, "failed": 0}
            )
            
            logger.info(f"Updated known good snapshot with {current_avg_coverage:.1f}% coverage")
    
    async def notify_swarm(self, alert: ValidationAlert):
        """Notify swarm of alert."""
        # In a real implementation, this would send to swarm coordination system
        logger.warning(f"Local Venue Alert: {alert.title} - {alert.description}")
        
        # Store alert for dashboard display
        if len(self.alerts) > 100:  # Keep only recent alerts
            self.alerts = self.alerts[-100:]
    
    async def propose_rollback(self, reason: str):
        """Propose rollback to known good snapshot."""
        if self.known_good_snapshot is None:
            logger.error("No known good snapshot available for rollback")
            return
        
        alert = ValidationAlert(
            alert_id=f"rollback_proposal_{int(time.time())}",
            severity=AlertSeverity.HIGH,
            title="Rollback Proposal",
            description=f"Propose rollback to {self.known_good_snapshot.git_ref} due to: {reason}",
            component="system",
            recommendations=[
                f"Rollback to git ref {self.known_good_snapshot.git_ref}",
                "Investigate cause of degradation",
                "Run validation tests after rollback"
            ],
            metrics={
                "snapshot_timestamp": self.known_good_snapshot.timestamp,
                "snapshot_coverage": sum(self.known_good_snapshot.coverage_metrics.values()) / len(self.known_good_snapshot.coverage_metrics) if self.known_good_snapshot.coverage_metrics else 0.0
            }
        )
        
        self.alerts.append(alert)
        await self.notify_swarm(alert)
    
    async def get_alerts(self, severity: Optional[AlertSeverity] = None) -> List[ValidationAlert]:
        """Get recent alerts, optionally filtered by severity."""
        if severity is None:
            return self.alerts.copy()
        return [alert for alert in self.alerts if alert.severity == severity]
    
    async def get_recommendations(self) -> List[str]:
        """Get aggregated recommendations from all alerts."""
        recommendations = set()
        for alert in self.alerts[-20:]:  # Last 20 alerts
            recommendations.update(alert.recommendations)
        return list(recommendations)
    
    async def check_strategy_dependencies(self):
        """Check if any strategies depend on LOCAL_SIM and block promotion if validation status is poor."""
        try:
            status = get_validation_status()
            
            # Block promotion if overall status is not healthy
            if status.overall_status != "HEALTHY":
                alert = ValidationAlert(
                    alert_id=f"strategy_block_{int(time.time())}",
                    severity=AlertSeverity.HIGH,
                    title="Local Venue Strategy Promotion Blocked",
                    description=f"Local venue validation status is {status.overall_status}. Strategies depending on LOCAL_SIM cannot be promoted.",
                    component="governance",
                    metrics={
                        "overall_status": status.overall_status,
                        "current_phase": status.current_phase,
                        "failed_phases": len([p for p in status.phases if p.status == "FAIL"])
                    },
                    recommendations=[
                        "Fix validation issues before promoting LOCAL_SIM strategies",
                        "Wait for all phases to pass validation",
                        "Consider using alternative venues until validation is healthy"
                    ]
                )
                
                self.alerts.append(alert)
                await self.notify_swarm(alert)
                
                # In a real implementation, this would block strategy promotion
                logger.warning(f"Blocking LOCAL_SIM strategy promotion due to validation status: {status.overall_status}")
            
            # Block promotion if any phase is below completion threshold
            for phase in status.phases:
                if phase.completion_percentage < 50.0 and phase.status != "PASS":
                    alert = ValidationAlert(
                        alert_id=f"phase_block_{phase.phase_name}_{int(time.time())}",
                        severity=AlertSeverity.MEDIUM,
                        title=f"Phase {phase.phase_name} Incomplete",
                        description=f"Phase {phase.phase_name} is only {phase.completion_percentage:.1f}% complete. Strategies depending on LOCAL_SIM may be unstable.",
                        component=phase.phase_name,
                        metrics={
                            "completion": phase.completion_percentage,
                            "status": phase.status,
                            "blockers": len(phase.blockers)
                        },
                        recommendations=[
                            f"Complete {phase.phase_name} validation to {100.0}%",
                            "Address blockers: {', '.join(phase.blockers)}",
                            "Verify all tests are passing"
                        ]
                    )
                    
                    self.alerts.append(alert)
                    await self.notify_swarm(alert)
                    
                    logger.warning(f"Blocking LOCAL_SIM strategy promotion due to {phase.phase_name} completion: {phase.completion_percentage:.1f}%")
            
        except Exception as e:
            logger.error(f"Error checking strategy dependencies: {e}")
    
    async def check_integration_dependencies(self):
        """Check integration with analytics and observability dashboards."""
        try:
            # In a real implementation, this would integrate with:
            # - Analytics dashboards
            # - Observability systems
            # - Risk management dashboards
            # - Governance systems
            
            # For now, we'll simulate integration
            status = get_validation_status()
            
            # Check if local venue health should be reflected in other dashboards
            if status.overall_status != "HEALTHY":
                logger.warning(f"Local venue health ({status.overall_status}) should be reflected in system dashboards")
            
            # Create integration alert for dashboard display
            alert = ValidationAlert(
                alert_id=f"dashboard_integration_{int(time.time())}",
                severity=AlertSeverity.MEDIUM,
                title="Dashboard Integration Alert",
                description=f"Local venue status ({status.overall_status}) should be reflected in system dashboards",
                component="integration",
                metrics=status.system_health,
                recommendations=[
                    "Update system health dashboard with local venue status",
                    "Add local venue metrics to analytics dashboards",
                    "Include local venue in risk management calculations"
                ]
            )
            
            self.alerts.append(alert)
            await self.notify_swarm(alert)
            
        except Exception as e:
            logger.error(f"Error checking integration dependencies: {e}")
    
    async def propose_auto_improvements(self):
        """Propose automatic improvements based on observed patterns."""
        try:
            # Analyze recent issues for patterns
            recent_issues = self.issues[-50:]  # Last 50 issues
            
            # Count issue types
            issue_counts = {}
            for issue in recent_issues:
                issue_type = issue.issue_type.value
                issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1
            
            # Generate suggestions based on patterns
            suggestions = []
            
            if issue_counts.get("websocket_error", 0) > 5:
                suggestions.append("Add WebSocket connection status indicator to UI")
                suggestions.append("Implement automatic reconnection with exponential backoff")
                suggestions.append("Add WebSocket health monitoring to observability")
            
            if issue_counts.get("slow_panel_load", 0) > 3:
                suggestions.append("Implement progressive loading for slow panels")
                suggestions.append("Add loading indicators for better UX")
                suggestions.append("Optimize data fetching and rendering")
            
            if issue_counts.get("ui_error", 0) > 2:
                suggestions.append("Add error boundaries to prevent UI crashes")
                suggestions.append("Implement user-friendly error messages")
                suggestions.append("Add client-side error logging")
            
            if self.metrics.fallback_activations > 10:
                suggestions.append("Improve WebSocket connection reliability")
                suggestions.append("Add offline mode capability")
                suggestions.append("Implement connection pooling")
            
            # Add suggestions based on coverage gaps
            current_status = get_validation_status()
            for component, coverage in current_status.coverage_metrics.items():
                threshold = self.coverage_thresholds.get(component, 0.0)
                if coverage < threshold:
                    suggestions.append(f"Add {threshold - coverage:.1f}% coverage tests for {component}")
            
            # Store suggestions for swarm agents
            if suggestions:
                logger.info(f"Auto-improvement suggestions: {suggestions}")
                
        except Exception as e:
            logger.error(f"Error generating auto-improvements: {e}")
    
    async def generate_test_suggestions(self) -> List[str]:
        """Generate test suggestions based on coverage gaps."""
        suggestions = []
        
        if self.known_good_snapshot:
            current_status = get_validation_status()
            
            for component, threshold in self.coverage_thresholds.items():
                current_coverage = current_status.coverage_metrics.get(component, 0.0)
                known_coverage = self.known_good_snapshot.coverage_metrics.get(component, 0.0)
                
                if current_coverage < threshold:
                    gap = threshold - current_coverage
                    suggestions.append(f"Add {gap:.1f}% coverage tests for {component}")
                
                if current_coverage < known_coverage:
                    regression = known_coverage - current_coverage
                    suggestions.append(f"Fix {regression:.1f}% coverage regression in {component}")
        
        return suggestions
    
    async def get_governance_recommendations(self) -> Dict[str, Any]:
        """Get governance recommendations for swarm coordination."""
        try:
            status = get_validation_status()
            
            return {
                "validation_status": status.overall_status,
                "current_phase": status.current_phase,
                "phase_completion": {
                    phase.phase_name: phase.completion_percentage
                    for phase in status.phases
                },
                "critical_issues": [
                    {
                        "type": alert.issue_type.value,
                        "severity": alert.severity,
                        "title": alert.title,
                        "description": alert.description,
                        "component": alert.component,
                        "recommendations": alert.recommendations
                    }
                    for alert in self.issues if alert.severity in [AlertSeverity.HIGH, AlertSeverity.CRITICAL]
                ],
                "auto_improvements": await self.generate_test_suggestions(),
                "known_good_snapshot": self.known_good_snapshot,
                "last_check": self.last_check_time,
                "governance_actions": {
                    "block_strategies": status.overall_status != "HEALTHY",
                    "require_phase_completion": any(phase.completion_percentage < 50.0 for phase in status.phases),
                    "dashboard_integration": status.overall_status != "HEALTHY"
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting governance recommendations: {e}")
            return {
                "error": str(e),
                "timestamp": time.time()
            }


# Swarm integration functions
def create_guardian_agent() -> LocalVenueGuardian:
    """Create and return a guardian agent instance."""
    return LocalVenueGuardian()


async def run_guardian_monitoring():
    """Run the guardian monitoring loop."""
    guardian = create_guardian_agent()
    await guardian.start_monitoring()


# Test result processing
async def process_pytest_results(test_results: Dict[str, Any]):
    """Process pytest results and update validation status."""
    try:
        from web.api.local_venue_validation import update_validation_from_test_results
        
        # Determine phase based on test markers
        markers = test_results.get("markers", [])
        if "feed_handlers" in markers or "matching_engine" in markers:
            phase = "Phase 0"
        elif "ui_integration" in markers or "ui_api" in markers:
            phase = "Phase 1"
        elif "e2e" in markers:
            phase = "Phase 2"
        elif "performance" in markers or "failure_scenarios" in markers:
            phase = "Phase 3"
        else:
            phase = "Phase 0"
        
        update_validation_from_test_results(test_results, phase)
        logger.info(f"Processed pytest results for {phase}")
        
    except Exception as e:
        logger.error(f"Error processing pytest results: {e}")


# Dashboard integration
async def get_dashboard_data() -> Dict[str, Any]:
    """Get data for dashboard display."""
    guardian = create_guardian_agent()
    
    return {
        "alerts": await guardian.get_alerts(),
        "recommendations": await guardian.get_recommendations(),
        "test_suggestions": await guardian.generate_test_suggestions(),
        "known_good_snapshot": guardian.known_good_snapshot,
        "last_check_time": guardian.last_check_time
    }


# CLI interface for swarm agents
def main():
    """Main entry point for standalone execution."""
    import asyncio
    
    async def run():
        guardian = create_guardian_agent()
        print("Local Venue Guardian Agent")
        print("=" * 50)
        
        # Run one check cycle
        await guardian.check_validation_status()
        
        # Display results
        alerts = await guardian.get_alerts()
        recommendations = await guardian.get_recommendations()
        suggestions = await guardian.generate_test_suggestions()
        
        print(f"Active Alerts: {len(alerts)}")
        for alert in alerts[-5:]:  # Last 5 alerts
            print(f"  - {alert.severity.value.upper()}: {alert.title}")
        
        print(f"\nRecommendations: {len(recommendations)}")
        for rec in recommendations[:3]:  # First 3 recommendations
            print(f"  - {rec}")
        
        print(f"\nTest Suggestions: {len(suggestions)}")
        for suggestion in suggestions[:3]:  # First 3 suggestions
            print(f"  - {suggestion}")
        
        if guardian.known_good_snapshot:
            print(f"\nKnown Good Snapshot: {guardian.known_good_snapshot.git_ref}")
            print(f"  Coverage: {sum(guardian.known_good_snapshot.coverage_metrics.values()) / len(guardian.known_good_snapshot.coverage_metrics):.1f}%")
    
    asyncio.run(run())


if __name__ == "__main__":
    main()
