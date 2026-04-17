"""
Local Venue Dashboard Integration

Integration components for displaying local venue validation status
in the Unified Control Center dashboard.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

from utils.logger import get_logger
from web.api.local_venue_validation import get_validation_status, get_validation_summary
from swarm.agents.local_venue_guardian import create_guardian_agent
from swarm.agents.ui_telemetry_sentinel import create_sentinel_agent

logger = get_logger(__name__)


@dataclass
class DashboardCard:
    """Dashboard card for displaying validation status."""
    card_id: str
    title: str
    status: str  # green, amber, red
    value: str
    description: str
    timestamp: float
    details: Dict[str, Any]
    actions: List[str]


class LocalVenueDashboardIntegration:
    """
    Integration layer for local venue validation status in the Unified Control Center.
    
    Provides dashboard cards, metrics, and alerts for the local venue system.
    """
    
    def __init__(self):
        self.guardian = create_guardian_agent()
        self.sentinel = create_sentinel_agent()
        self.last_update = 0.0
        self.update_interval = 30.0  # 30 seconds
    
    async def get_dashboard_cards(self) -> List[DashboardCard]:
        """Get dashboard cards for local venue validation status."""
        try:
            status = get_validation_status()
            summary = get_validation_summary()
            
            cards = []
            
            # Overall status card
            overall_card = DashboardCard(
                card_id="local_venue_overall",
                title="Local Venue Validation",
                status=self._get_status_color(status.overall_status),
                value=status.overall_status,
                description=f"Current Phase: {status.current_phase}",
                timestamp=time.time(),
                details={
                    "current_phase": status.current_phase,
                    "completed_phases": summary["completed_phases"],
                    "failed_phases": summary["failed_phases"],
                    "total_phases": summary["total_phases"]
                },
                actions=[
                    "View Phase Progress",
                    "Check Known Good Snapshot",
                    "Run Validation Tests"
                ]
            )
            cards.append(overall_card)
            
            # Phase status cards
            for phase in status.phases:
                phase_card = DashboardCard(
                    card_id=f"phase_{phase.phase_name.lower().replace(' ', '_')}",
                    title=f"Phase {phase.phase_name}",
                    status=self._get_status_color(phase.status),
                    value=f"{phase.completion_percentage:.1f}%",
                    description=phase.status,
                    timestamp=phase.last_run_timestamp,
                    details={
                        "completion": phase.completion_percentage,
                        "test_results": phase.test_results,
                        "blockers": phase.blockers,
                        "recommendations": phase.recommendations
                    },
                    actions=[
                        "Run Phase Tests",
                        "View Test Results",
                        "Fix Blockers"
                    ]
                )
                cards.append(phase_card)
            
            # Coverage metrics card
            coverage_card = DashboardCard(
                card_id="local_venue_coverage",
                title="Test Coverage",
                status=self._get_coverage_status(status.coverage_metrics),
                value=f"{summary['average_coverage']:.1f}%",
                description="Average test coverage across components",
                timestamp=time.time(),
                details={
                    "feed_handlers": status.coverage_metrics.get("feed_handlers", 0.0),
                    "matching_engine": status.coverage_metrics.get("matching_engine", 0.0),
                    "ui_components": status.coverage_metrics.get("ui_components", 0.0),
                    "integration_points": status.coverage_metrics.get("integration_points", 0.0)
                },
                actions=[
                    "Run Coverage Tests",
                    "View Coverage Report",
                    "Add Missing Tests"
                ]
            )
            cards.append(coverage_card)
            
            # Performance metrics card
            perf_metrics = status.performance_metrics
            perf_card = DashboardCard(
                card_id="local_venue_performance",
                title="Performance Metrics",
                status=self._get_performance_status(perf_metrics),
                value=self._get_performance_summary(perf_metrics),
                description="System performance indicators",
                timestamp=time.time(),
                details=perf_metrics,
                actions=[
                    "Run Performance Tests",
                    "View Performance Report",
                    "Optimize Slow Operations"
                ]
            )
            cards.append(perf_card)
            
            # System health card
            health_card = DashboardCard(
                card_id="local_venue_health",
                title="System Health",
                status=self._get_health_status(status.system_health),
                value=f"{status.system_health.get('feed_handlers_healthy', 0)}/{status.system_health.get('total_handlers', 0)}",
                description="Component health indicators",
                timestamp=time.time(),
                details=status.system_health,
                actions=[
                    "Check Component Status",
                    "Restart Failed Components",
                    "View System Logs"
                ]
            )
            cards.append(health_card)
            
            # Recent alerts card
            alerts = await self.guardian.get_alerts()
            recent_alerts = alerts[-5:]  # Last 5 alerts
            
            alerts_card = DashboardCard(
                card_id="local_venue_alerts",
                title="Recent Alerts",
                status="amber" if recent_alerts else "green",
                value=str(len(recent_alerts)),
                description="Recent validation alerts",
                timestamp=time.time(),
                details={
                    "recent_alerts": [
                        {
                            "title": alert.title,
                            "severity": alert.severity.value,
                            "description": alert.description,
                            "timestamp": alert.timestamp
                        }
                        for alert in recent_alerts
                    ]
                },
                actions=[
                    "View All Alerts",
                    "Acknowledge Alerts",
                    "Fix Issues"
                ]
            )
            cards.append(alerts_card)
            
            self.last_update = time.time()
            return cards
            
        except Exception as e:
            logger.error(f"Error getting dashboard cards: {e}")
            return []
    
    async def get_analytics_integration(self) -> Dict[str, Any]:
        """Get analytics integration data for local venue."""
        try:
            status = get_validation_status()
            summary = get_validation_summary()
            
            return {
                "local_venue_metrics": {
                    "validation_status": status.overall_status,
                    "current_phase": status.current_phase,
                    "phase_completion": {
                        phase.phase_name: phase.completion_percentage
                        for phase in status.phases
                    },
                    "coverage_metrics": status.coverage_metrics,
                    "performance_metrics": status.performance_metrics,
                    "system_health": status.system_health,
                    "last_swarm_run": status.last_swarm_run
                },
                "risk_indicators": {
                    "validation_risk": self._calculate_validation_risk(status),
                    "performance_risk": self._calculate_performance_risk(status.performance_metrics),
                    "coverage_risk": self._calculate_coverage_risk(status.coverage_metrics)
                },
                "governance_status": await self.guardian.get_governance_recommendations(),
                "telemetry_summary": await self.sentinel.get_performance_summary()
            }
            
        except Exception as e:
            logger.error(f"Error getting analytics integration: {e}")
            return {"error": str(e), "timestamp": time.time()}
    
    async def get_risk_panel_integration(self) -> Dict[str, Any]:
        """Get risk panel integration data for local venue."""
        try:
            status = get_validation_status()
            alerts = await self.guardian.get_alerts()
            
            # Calculate risk metrics
            validation_risk = self._calculate_validation_risk(status)
            performance_risk = self._calculate_performance_risk(status.performance_metrics)
            coverage_risk = self._calculate_coverage_risk(status.coverage_metrics)
            
            # Get critical alerts
            critical_alerts = [alert for alert in alerts if alert.severity.value in ["high", "critical"]]
            
            return {
                "local_venue_risk": {
                    "overall_risk": max(validation_risk, performance_risk, coverage_risk),
                    "validation_risk": validation_risk,
                    "performance_risk": performance_risk,
                    "coverage_risk": coverage_risk,
                    "critical_alerts": len(critical_alerts),
                    "risk_trend": self._calculate_risk_trend(alerts),
                    "mitigation_actions": self._get_mitigation_actions(status, alerts)
                },
                "risk_factors": {
                    "failed_phases": len([p for p in status.phases if p.status == "FAIL"]),
                    "low_coverage_components": len([c for c, v in status.coverage_metrics.items() if v < 80.0]),
                    "performance_violations": len([k for k, v in status.performance_metrics.items() if v > 100.0]),
                    "system_health_issues": not status.system_health.get("engine_running", False)
                },
                "recommendations": await self.guardian.get_recommendations()
            }
            
        except Exception as e:
            logger.error(f"Error getting risk panel integration: {e}")
            return {"error": str(e), "timestamp": time.time()}
    
    def _get_status_color(self, status: str) -> str:
        """Convert status to dashboard color."""
        status_colors = {
            "HEALTHY": "green",
            "DEGRADED": "amber", 
            "FAILING": "red",
            "UNKNOWN": "amber",
            "PASS": "green",
            "FAIL": "red",
            "IN_PROGRESS": "amber",
            "NOT_STARTED": "amber"
        }
        return status_colors.get(status, "amber")
    
    def _get_coverage_status(self, coverage_metrics: Dict[str, float]) -> str:
        """Get coverage status based on metrics."""
        if not coverage_metrics:
            return "amber"
        
        avg_coverage = sum(coverage_metrics.values()) / len(coverage_metrics)
        
        if avg_coverage >= 90.0:
            return "green"
        elif avg_coverage >= 75.0:
            return "amber"
        else:
            return "red"
    
    def _get_performance_status(self, perf_metrics: Dict[str, float]) -> str:
        """Get performance status based on metrics."""
        if not perf_metrics:
            return "amber"
        
        # Check if any metric exceeds thresholds
        thresholds = {
            "order_submission_ms": 100.0,
            "order_book_updates_ms": 50.0,
            "ui_api_response_ms": 200.0,
            "websocket_updates_ms": 10.0
        }
        
        violations = 0
        for metric, value in perf_metrics.items():
            threshold = thresholds.get(metric, float('inf'))
            if value > threshold:
                violations += 1
        
        if violations == 0:
            return "green"
        elif violations <= 2:
            return "amber"
        else:
            return "red"
    
    def _get_performance_summary(self, perf_metrics: Dict[str, float]) -> str:
        """Get performance summary string."""
        if not perf_metrics:
            return "No data"
        
        # Count violations
        thresholds = {
            "order_submission_ms": 100.0,
            "order_book_updates_ms": 50.0,
            "ui_api_response_ms": 200.0,
            "websocket_updates_ms": 10.0
        }
        
        violations = 0
        for metric, value in perf_metrics.items():
            threshold = thresholds.get(metric, float('inf'))
            if value > threshold:
                violations += 1
        
        if violations == 0:
            return "All OK"
        else:
            return f"{violations} violations"
    
    def _get_health_status(self, health_metrics: Dict[str, Any]) -> str:
        """Get health status based on system health."""
        if not health_metrics:
            return "amber"
        
        issues = 0
        if not health_metrics.get("engine_running", False):
            issues += 1
        
        if health_metrics.get("feed_handlers_healthy", 0) == 0:
            issues += 1
        
        if issues == 0:
            return "green"
        elif issues == 1:
            return "amber"
        else:
            return "red"
    
    def _calculate_validation_risk(self, status: Any) -> float:
        """Calculate validation risk score (0-1)."""
        risk_score = 0.0
        
        # Risk from overall status
        status_risk = {
            "HEALTHY": 0.0,
            "DEGRADED": 0.3,
            "FAILING": 0.8,
            "UNKNOWN": 0.5
        }
        risk_score += status_risk.get(status.overall_status, 0.5)
        
        # Risk from failed phases
        failed_phases = len([p for p in status.phases if p.status == "FAIL"])
        risk_score += failed_phases * 0.2
        
        # Risk from incomplete phases
        incomplete_phases = len([p for p in status.phases if p.completion_percentage < 50.0])
        risk_score += incomplete_phases * 0.1
        
        return min(risk_score, 1.0)
    
    def _calculate_performance_risk(self, perf_metrics: Dict[str, float]) -> float:
        """Calculate performance risk score (0-1)."""
        if not perf_metrics:
            return 0.5
        
        risk_score = 0.0
        thresholds = {
            "order_submission_ms": 100.0,
            "order_book_updates_ms": 50.0,
            "ui_api_response_ms": 200.0,
            "websocket_updates_ms": 10.0
        }
        
        for metric, value in perf_metrics.items():
            threshold = thresholds.get(metric, float('inf'))
            if value > threshold:
                # Risk increases with severity of violation
                violation_ratio = value / threshold
                risk_score += min(violation_ratio - 1.0, 1.0) * 0.25
        
        return min(risk_score, 1.0)
    
    def _calculate_coverage_risk(self, coverage_metrics: Dict[str, float]) -> float:
        """Calculate coverage risk score (0-1)."""
        if not coverage_metrics:
            return 0.5
        
        risk_score = 0.0
        target_coverage = 85.0
        
        for component, coverage in coverage_metrics.items():
            if coverage < target_coverage:
                # Risk increases with coverage gap
                coverage_gap = target_coverage - coverage
                risk_score += (coverage_gap / target_coverage) * 0.25
        
        return min(risk_score, 1.0)
    
    def _calculate_risk_trend(self, alerts: List[Any]) -> str:
        """Calculate risk trend based on recent alerts."""
        if len(alerts) < 10:
            return "insufficient_data"
        
        # Compare recent vs older alerts
        recent_alerts = alerts[-5:]
        older_alerts = alerts[-10:-5]
        
        recent_critical = len([a for a in recent_alerts if a.severity.value in ["high", "critical"]])
        older_critical = len([a for a in older_alerts if a.severity.value in ["high", "critical"]])
        
        if recent_critical > older_critical:
            return "increasing"
        elif recent_critical < older_critical:
            return "decreasing"
        else:
            return "stable"
    
    def _get_mitigation_actions(self, status: Any, alerts: List[Any]) -> List[str]:
        """Get mitigation actions for current issues."""
        actions = []
        
        # Based on validation status
        if status.overall_status != "HEALTHY":
            actions.append("Fix validation issues")
        
        # Based on failed phases
        failed_phases = [p for p in status.phases if p.status == "FAIL"]
        for phase in failed_phases:
            actions.append(f"Fix {phase.phase_name} issues")
        
        # Based on critical alerts
        critical_alerts = [a for a in alerts if a.severity.value in ["high", "critical"]]
        for alert in critical_alerts[-3:]:  # Last 3 critical alerts
            actions.extend(alert.recommendations[:1])  # First recommendation
        
        return list(set(actions))  # Remove duplicates


# Integration functions for dashboard
async def get_local_venue_dashboard_data() -> Dict[str, Any]:
    """Get local venue data for dashboard integration."""
    integration = LocalVenueDashboardIntegration()
    
    return {
        "cards": await integration.get_dashboard_cards(),
        "analytics": await integration.get_analytics_integration(),
        "risk_panel": await integration.get_risk_panel_integration(),
        "last_update": integration.last_update
    }


# WebSocket integration for real-time updates
async def local_venue_websocket_handler(websocket):
    """WebSocket handler for local venue real-time updates."""
    integration = LocalVenueDashboardIntegration()
    
    try:
        while True:
            # Get current data
            data = await get_local_venue_dashboard_data()
            
            # Send update
            await websocket.send_json(data)
            
            # Wait for next update
            await asyncio.sleep(integration.update_interval)
            
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await websocket.close()


# CLI interface for testing
def main():
    """Main entry point for standalone testing."""
    import asyncio
    
    async def run():
        integration = LocalVenueDashboardIntegration()
        print("Local Venue Dashboard Integration")
        print("=" * 50)
        
        # Get dashboard cards
        cards = await integration.get_dashboard_cards()
        print(f"Dashboard Cards: {len(cards)}")
        for card in cards:
            print(f"  - {card.title}: {card.value} ({card.status})")
        
        # Get analytics integration
        analytics = await integration.get_analytics_integration()
        print(f"\nAnalytics Integration: {len(analytics)} sections")
        
        # Get risk panel integration
        risk = await integration.get_risk_panel_integration()
        print(f"Risk Panel: {risk.get('local_venue_risk', {}).get('overall_risk', 'unknown'):.2f} risk score")
    
    asyncio.run(run())


if __name__ == "__main__":
    main()
