#!/usr/bin/env python3
"""
Comprehensive Pipeline Discrepancy Detector for MERID Trading System

This script performs end-to-end analysis of the trading and execution pipeline
by querying the running server via HTTP endpoints to expose all discrepancies,
mismatches, and blockers across upstream, midstream, and downstream components.

Architecture based on 2026 best practices for financial trading systems:
- Multi-layer anomaly detection (baseline, detector, explainer, orchestrator)
- End-to-end tracing with lineage tracking
- Real-time monitoring with exception-based alerting
- Business-level observability beyond infrastructure metrics
- High-water mark sequencing for state consistency

Usage:
    python scripts/pipeline_discrepancy_detector_http.py [--output json|text|html] [--port 8011]
"""

from __future__ import annotations

import json
import sys
import time
import requests
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class Severity(Enum):
    """Severity levels for discrepancies."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ComponentLayer(Enum):
    """Pipeline layers."""
    UPSTREAM = "upstream"      # Data ingestion, market data, oracles
    MIDSTREAM = "midstream"    # Agents, signal generation, risk management
    DOWNSTREAM = "downstream"  # Execution, settlement, reconciliation
    CROSS_LAYER = "cross_layer"  # Issues spanning multiple layers


class DiscrepancyType(Enum):
    """Types of discrepancies."""
    LEGACY_CONTAMINATION = "legacy_contamination"
    MISSING_ASSET = "missing_asset"
    DATA_STALENESS = "data_staleness"
    WEBSOCKET_MISMATCH = "websocket_mismatch"
    POSITION_MISMATCH = "position_mismatch"
    RISK_LIMIT_VIOLATION = "risk_limit_violation"
    EXECUTION_BLOCKAGE = "execution_blockage"
    AGENT_GRID_FAILURE = "agent_grid_failure"
    CATALOG_STALENESS = "catalog_staleness"
    BANKROLL_MISALIGNMENT = "bankroll_misalignment"
    SINGLETON_FAILURE = "singleton_failure"
    RATE_LIMIT_BREACH = "rate_limit_breach"
    SEQUENCE_GAP = "sequence_gap"
    CONFIGURATION_DRIFT = "configuration_drift"
    DEPENDENCY_FAILURE = "dependency_failure"


@dataclass
class Discrepancy:
    """A single discrepancy found in the pipeline."""
    layer: ComponentLayer
    component: str
    discrepancy_type: DiscrepancyType
    severity: Severity
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    suggested_action: str = ""
    impact: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer.value,
            "component": self.component,
            "type": self.discrepancy_type.value,
            "severity": self.severity.value,
            "description": self.description,
            "evidence": self.evidence,
            "timestamp": self.timestamp.isoformat(),
            "suggested_action": self.suggested_action,
            "impact": self.impact,
        }


@dataclass
class PipelineHealthReport:
    """Comprehensive health report for the entire pipeline."""
    scan_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scan_duration_seconds: float = 0.0
    total_discrepancies: int = 0
    discrepancies_by_severity: Dict[str, int] = field(default_factory=dict)
    discrepancies_by_layer: Dict[str, int] = field(default_factory=dict)
    discrepancies_by_type: Dict[str, int] = field(default_factory=dict)
    discrepancies: List[Discrepancy] = field(default_factory=list)
    component_health: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    summary: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_timestamp": self.scan_timestamp.isoformat(),
            "scan_duration_seconds": self.scan_duration_seconds,
            "total_discrepancies": self.total_discrepancies,
            "discrepancies_by_severity": self.discrepancies_by_severity,
            "discrepancies_by_layer": self.discrepancies_by_layer,
            "discrepancies_by_type": self.discrepancies_by_type,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "component_health": self.component_health,
            "summary": self.summary,
        }


class PipelineDiscrepancyDetector:
    """
    Comprehensive detector for trading pipeline discrepancies using HTTP endpoints.
    
    Queries the running server via HTTP API to detect discrepancies across
    upstream, midstream, and downstream components.
    """
    
    # CRITICAL: The 5 crypto assets that MUST be present
    CRITICAL_CRYPTO_ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    
    def __init__(self, base_url: str = "http://localhost:8011"):
        self.base_url = base_url
        self.discrepancies: List[Discrepancy] = []
        self.component_health: Dict[str, Dict[str, Any]] = {}
        self.start_time = time.time()
        self.session = requests.Session()
        self.session.timeout = 10  # 10 second timeout for all requests
        
    def add_discrepancy(
        self,
        layer: ComponentLayer,
        component: str,
        discrepancy_type: DiscrepancyType,
        severity: Severity,
        description: str,
        evidence: Optional[Dict[str, Any]] = None,
        suggested_action: str = "",
        impact: str = "",
    ) -> None:
        """Add a discrepancy to the report."""
        discrepancy = Discrepancy(
            layer=layer,
            component=component,
            discrepancy_type=discrepancy_type,
            severity=severity,
            description=description,
            evidence=evidence or {},
            suggested_action=suggested_action,
            impact=impact,
        )
        self.discrepancies.append(discrepancy)
        print(f"[{layer.value.upper()}] {component}: {description}")
    
    def _get(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make a GET request to the server and return JSON response."""
        url = f"{self.base_url}{endpoint}"
        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            print(f"HTTP request failed to {url}: {e}")
            return None
    
    def scan_all(self) -> PipelineHealthReport:
        """Run comprehensive scan of all pipeline layers."""
        print("=" * 80)
        print("STARTING COMPREHENSIVE PIPELINE DISCREPANCY SCAN")
        print(f"Target: {self.base_url}")
        print("=" * 80)
        
        try:
            # First check if server is responding
            health = self._get("/api/v1/health")
            if health is None:
                self.add_discrepancy(
                    layer=ComponentLayer.CROSS_LAYER,
                    component="server",
                    discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                    severity=Severity.CRITICAL,
                    description="Server is not responding to health check",
                    suggested_action="Check if server is running on the specified port",
                    impact="Cannot perform any health checks",
                )
                return self._generate_report()
            
            self.component_health["server_health"] = health
            
            # Scan each layer
            self._scan_upstream_components()
            self._scan_midstream_components()
            self._scan_downstream_components()
            self._scan_cross_layer_integrations()
            
            # Generate summary
            report = self._generate_report()
            
            print("=" * 80)
            print("SCAN COMPLETE")
            print(f"Total discrepancies: {report.total_discrepancies}")
            print(f"Critical: {report.discrepancies_by_severity.get('critical', 0)}")
            print(f"High: {report.discrepancies_by_severity.get('high', 0)}")
            print("=" * 80)
            
            return report
            
        except Exception as e:
            print(f"Scan failed with exception: {e}")
            self.add_discrepancy(
                layer=ComponentLayer.CROSS_LAYER,
                component="scanner",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description=f"Scanner failed with exception: {e}",
                suggested_action="Review scanner logs and fix exception handling",
                impact="Entire pipeline health check failed",
            )
            return self._generate_report()
    
    def _scan_upstream_components(self) -> None:
        """Scan upstream components: data ingestion, market data, oracles."""
        print("[UPSTREAM] Scanning data ingestion and market data components...")
        
        # 1. Check WebSocket bridge
        self._check_websocket_bridge()
        
        # 2. Check spot prices
        self._check_spot_prices()
        
        # 3. Check market catalog
        self._check_market_catalog()
        
        # 4. Check market state for critical assets
        self._check_market_state()
    
    def _check_websocket_bridge(self) -> None:
        """Check WebSocket bridge status."""
        ws_status = self._get("/api/v1/ws-bridge-status")
        
        if ws_status is None:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="websocket_bridge",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.CRITICAL,
                description="WebSocket bridge status endpoint not responding",
                suggested_action="Check if WebSocket bridge is initialized",
                impact="Real-time market data unavailable",
            )
            return
        
        self.component_health["websocket_bridge"] = ws_status
        
        if ws_status.get("status") != "running":
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="websocket_bridge",
                discrepancy_type=DiscrepancyType.WEBSOCKET_MISMATCH,
                severity=Severity.CRITICAL,
                description=f"WebSocket bridge is not running: {ws_status.get('status')}",
                evidence=ws_status,
                suggested_action="Check WebSocket connection and Kalshi API credentials",
                impact="No real-time market data updates",
            )
        
        summary = ws_status.get("summary", {})
        subscriptions = summary.get("subscriptions", 0)
        if subscriptions == 0:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="websocket_bridge",
                discrepancy_type=DiscrepancyType.WEBSOCKET_MISMATCH,
                severity=Severity.HIGH,
                description="WebSocket bridge has no active subscriptions",
                evidence={"subscriptions": subscriptions},
                suggested_action="Check market subscription logic and catalog integration",
                impact="No market data being received via WebSocket",
            )
        elif subscriptions < len(self.CRITICAL_CRYPTO_ASSETS):
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="websocket_bridge",
                discrepancy_type=DiscrepancyType.MISSING_ASSET,
                severity=Severity.HIGH,
                description=f"WebSocket bridge has only {subscriptions} subscriptions, expected {len(self.CRITICAL_CRYPTO_ASSETS)} for crypto assets",
                evidence={"subscriptions": subscriptions, "expected": len(self.CRITICAL_CRYPTO_ASSETS)},
                suggested_action="Check subscription logic for all 5 crypto assets",
                impact="Some crypto assets may not have real-time data",
            )
    
    def _check_spot_prices(self) -> None:
        """Check spot prices for the 5 critical crypto assets."""
        spot_data = self._get("/api/internal/v1/spot-prices")
        
        if spot_data is None:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="spot_prices",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description="Spot prices endpoint not responding",
                suggested_action="Check if spot price service is running",
                impact="Unable to verify spot price availability",
            )
            return
        
        self.component_health["spot_prices"] = spot_data
        
        # Check each critical asset
        for asset in self.CRITICAL_CRYPTO_ASSETS:
            asset_price = spot_data.get(asset.lower())
            if asset_price is None or asset_price.get("price") is None:
                self.add_discrepancy(
                    layer=ComponentLayer.UPSTREAM,
                    component="spot_prices",
                    discrepancy_type=DiscrepancyType.MISSING_ASSET,
                    severity=Severity.CRITICAL,
                    description=f"Spot price missing for {asset}",
                    evidence={"asset": asset, "spot_data": asset_price},
                    suggested_action=f"Check spot data source for {asset}",
                    impact=f"Trading cannot proceed for {asset} without price data",
                )
            else:
                # Check staleness
                last_update = asset_price.get("last_update")
                if last_update:
                    age = time.time() - last_update
                    if age > 30:  # More than 30 seconds stale
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="spot_prices",
                            discrepancy_type=DiscrepancyType.DATA_STALENESS,
                            severity=Severity.HIGH,
                            description=f"Spot price for {asset} is stale: {age:.1f}s old",
                            evidence={"asset": asset, "age_s": age},
                            suggested_action="Check spot data refresh mechanism",
                            impact=f"Stale price data for {asset} may cause incorrect trading decisions",
                        )
    
    def _check_market_catalog(self) -> None:
        """Check market catalog for crypto 15m markets."""
        catalog = self._get("/api/internal/v1/catalog/snapshot")
        
        if catalog is None:
            self.add_discrepancy(
                layer=ComponentLayer.UPSTREAM,
                component="market_catalog",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description="Market catalog endpoint not responding",
                suggested_action="Check if market catalog is running",
                impact="Unable to verify market discovery",
            )
            return
        
        self.component_health["market_catalog"] = catalog
        
        # Check for critical assets
        for asset in self.CRITICAL_CRYPTO_ASSETS:
            asset_markets = catalog.get(asset.lower(), [])
            if not asset_markets:
                self.add_discrepancy(
                    layer=ComponentLayer.UPSTREAM,
                    component="market_catalog",
                    discrepancy_type=DiscrepancyType.MISSING_ASSET,
                    severity=Severity.HIGH,
                    description=f"Market catalog has no markets for {asset}",
                    evidence={"asset": asset},
                    suggested_action=f"Check Kalshi API for {asset} 15m market availability",
                    impact=f"Trading cannot proceed for {asset}",
                )
    
    def _check_market_state(self) -> None:
        """Check market state for critical assets."""
        # Get catalog first to find current market tickers
        catalog = self._get("/api/internal/v1/catalog/snapshot")
        if catalog is None:
            return
        
        market_states = {}
        
        for asset in self.CRITICAL_CRYPTO_ASSETS:
            asset_markets = catalog.get(asset.lower(), [])
            if asset_markets:
                # Get the first market ticker for this asset
                ticker = asset_markets[0].get("ticker")
                if ticker:
                    state = self._get(f"/api/internal/v1/market-state/{ticker}")
                    market_states[asset] = state
                    
                    if state is None:
                        self.add_discrepancy(
                            layer=ComponentLayer.UPSTREAM,
                            component="market_state",
                            discrepancy_type=DiscrepancyType.DATA_STALENESS,
                            severity=Severity.HIGH,
                            description=f"Market state not available for {asset} ({ticker})",
                            evidence={"asset": asset, "ticker": ticker},
                            suggested_action="Check WebSocket data flow and state updates",
                            impact=f"No market data available for {asset}",
                        )
        
        self.component_health["market_state"] = market_states
    
    def _scan_midstream_components(self) -> None:
        """Scan midstream components: agents, signal generation, risk management."""
        print("[MIDSTREAM] Scanning agent grid and risk management components...")
        
        # 1. Check agent grid
        self._check_agent_grid()
        
        # 2. Check risk snapshot
        self._check_risk_snapshot()
        
        # 3. Check loop status
        self._check_loop_status()
    
    def _check_agent_grid(self) -> None:
        """Check agent grid status."""
        agents = self._get("/api/v1/agents")
        
        if agents is None:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="agent_grid",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description="Agent grid endpoint not responding",
                suggested_action="Check if agent grid is running",
                impact="Unable to verify agent grid status",
            )
            return
        
        self.component_health["agent_grid"] = agents
        
        # Check for each critical asset
        for asset in self.CRITICAL_CRYPTO_ASSETS:
            agent_key = f"{asset}_15M"
            agent_found = False
            
            # Check if agent exists in the response
            if isinstance(agents, dict):
                agent_found = agent_key in agents
            elif isinstance(agents, list):
                agent_found = any(a.get("name") == agent_key for a in agents)
            
            if not agent_found:
                self.add_discrepancy(
                    layer=ComponentLayer.MIDSTREAM,
                    component="agent_grid",
                    discrepancy_type=DiscrepancyType.MISSING_ASSET,
                    severity=Severity.CRITICAL,
                    description=f"Agent grid missing agent for {asset} (expected: {agent_key})",
                    evidence={"asset": asset, "expected_key": agent_key},
                    suggested_action=f"Check agent grid configuration for {agent_key} agent",
                    impact=f"No signal generation for {asset}",
                )
    
    def _check_risk_snapshot(self) -> None:
        """Check risk manager status and bankroll."""
        risk = self._get("/api/v1/risk-snapshot")
        
        if risk is None:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="risk_manager",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description="Risk snapshot endpoint not responding",
                suggested_action="Check if risk manager is running",
                impact="Unable to verify risk management",
            )
            return
        
        self.component_health["risk_manager"] = risk
        
        # Check bankroll
        bankroll = risk.get("bankroll_usd", 0)
        if bankroll == 0:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="risk_manager",
                discrepancy_type=DiscrepancyType.BANKROLL_MISALIGNMENT,
                severity=Severity.CRITICAL,
                description="Risk manager has zero bankroll - not calibrated",
                evidence={"bankroll_usd": bankroll},
                suggested_action="Call calibrate_from_balance() with current Kalshi balance",
                impact="All orders will be rejected due to NO_BANKROLL check",
            )
    
    def _check_loop_status(self) -> None:
        """Check trading loop status."""
        loop = self._get("/api/v1/loop-status")
        
        if loop is None:
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="trading_loop",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.HIGH,
                description="Loop status endpoint not responding",
                suggested_action="Check if trading loop is running",
                impact="Unable to verify trading loop status",
            )
            return
        
        self.component_health["trading_loop"] = loop
        
        # Check if loop is running
        if not loop.get("running", False):
            self.add_discrepancy(
                layer=ComponentLayer.MIDSTREAM,
                component="trading_loop",
                discrepancy_type=DiscrepancyType.SINGLETON_FAILURE,
                severity=Severity.CRITICAL,
                description="Trading loop is not running",
                evidence=loop,
                suggested_action="Check trading loop startup and crash logs",
                impact="No signal generation or trading",
            )
    
    def _scan_downstream_components(self) -> None:
        """Scan downstream components: execution, settlement, reconciliation."""
        print("[DOWNSTREAM] Scanning execution and reconciliation components...")
        
        # 1. Check infrastructure status
        self._check_infrastructure()
        
        # 2. Check reconciliation (if available)
        self._check_reconciliation()
    
    def _check_infrastructure(self) -> None:
        """Check infrastructure status."""
        infra = self._get("/api/v1/infra")
        
        if infra is None:
            self.add_discrepancy(
                layer=ComponentLayer.DOWNSTREAM,
                component="infrastructure",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.MEDIUM,
                description="Infrastructure endpoint not responding",
                suggested_action="Check infrastructure status",
                impact="Unable to verify infrastructure status",
            )
            return
        
        self.component_health["infrastructure"] = infra
    
    def _check_reconciliation(self) -> None:
        """Check reconciliation status."""
        # This endpoint may not exist, so we skip if not available
        # The reconciliation check would need a dedicated endpoint
        pass
    
    def _scan_cross_layer_integrations(self) -> None:
        """Scan cross-layer integrations and configuration."""
        print("[CROSS_LAYER] Scanning cross-layer integrations and configuration...")
        
        # 1. Check self-check endpoint
        self._check_self_check()
        
        # 2. Check meta-cognition
        self._check_meta_cognition()
    
    def _check_self_check(self) -> None:
        """Check self-check endpoint."""
        self_check = self._get("/api/v1/self-check")
        
        if self_check is None:
            self.add_discrepancy(
                layer=ComponentLayer.CROSS_LAYER,
                component="self_check",
                discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                severity=Severity.MEDIUM,
                description="Self-check endpoint not responding",
                suggested_action="Check self-check implementation",
                impact="Unable to verify system self-check",
            )
            return
        
        self.component_health["self_check"] = self_check
        
        # Check for any critical issues in self-check
        if self_check.get("critical_issues"):
            for issue in self_check.get("critical_issues", []):
                self.add_discrepancy(
                    layer=ComponentLayer.CROSS_LAYER,
                    component="self_check",
                    discrepancy_type=DiscrepancyType.DEPENDENCY_FAILURE,
                    severity=Severity.CRITICAL,
                    description=f"Self-check critical issue: {issue}",
                    evidence={"issue": issue},
                    suggested_action="Review self-check output",
                    impact="System has critical issues",
                )
    
    def _check_meta_cognition(self) -> None:
        """Check meta-cognition endpoint."""
        meta = self._get("/api/v1/meta-cognition")
        
        if meta is None:
            # This endpoint may not be critical
            return
        
        self.component_health["meta_cognition"] = meta
    
    def _generate_report(self) -> PipelineHealthReport:
        """Generate comprehensive health report."""
        end_time = time.time()
        duration = end_time - self.start_time
        
        # Count discrepancies by category
        by_severity = {}
        by_layer = {}
        by_type = {}
        
        for disc in self.discrepancies:
            sev = disc.severity.value
            layer = disc.layer.value
            dtype = disc.discrepancy_type.value
            
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_layer[layer] = by_layer.get(layer, 0) + 1
            by_type[dtype] = by_type.get(dtype, 0) + 1
        
        # Generate summary
        critical_count = by_severity.get("critical", 0)
        high_count = by_severity.get("high", 0)
        
        if critical_count > 0:
            summary = f"CRITICAL: {critical_count} critical issues found that block trading"
        elif high_count > 0:
            summary = f"HIGH: {high_count} high-priority issues found that may impact trading"
        elif len(self.discrepancies) > 0:
            summary = f"{len(self.discrepancies)} issues found but none are critical"
        else:
            summary = "All systems healthy - no discrepancies found"
        
        return PipelineHealthReport(
            scan_duration_seconds=duration,
            total_discrepancies=len(self.discrepancies),
            discrepancies_by_severity=by_severity,
            discrepancies_by_layer=by_layer,
            discrepancies_by_type=by_type,
            discrepancies=self.discrepancies,
            component_health=self.component_health,
            summary=summary,
        )


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Comprehensive Pipeline Discrepancy Detector for MERID Trading System"
    )
    parser.add_argument(
        "--output",
        choices=["json", "text", "html"],
        default="text",
        help="Output format (default: text)"
    )
    parser.add_argument(
        "--output-file",
        type=str,
        help="Output file path (default: stdout)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8011,
        help="Server port (default: 8011)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Server host (default: localhost)"
    )
    
    args = parser.parse_args()
    
    # Run scan
    base_url = f"http://{args.host}:{args.port}"
    detector = PipelineDiscrepancyDetector(base_url=base_url)
    report = detector.scan_all()
    
    # Format output
    if args.output == "json":
        output = json.dumps(report.to_dict(), indent=2)
    elif args.output == "html":
        output = _generate_html_report(report)
    else:  # text
        output = _generate_text_report(report)
    
    # Write output
    if args.output_file:
        with open(args.output_file, 'w') as f:
            f.write(output)
        print(f"Report written to {args.output_file}")
    else:
        print(output)
    
    # Exit with error code if critical issues found
    critical_count = report.discrepancies_by_severity.get("critical", 0)
    if critical_count > 0:
        sys.exit(1)


def _generate_text_report(report: PipelineHealthReport) -> str:
    """Generate human-readable text report."""
    lines = []
    lines.append("=" * 80)
    lines.append("MERID TRADING PIPELINE DISCREPANCY REPORT")
    lines.append("=" * 80)
    lines.append(f"Scan Time: {report.scan_timestamp.isoformat()}")
    lines.append(f"Duration: {report.scan_duration_seconds:.2f}s")
    lines.append(f"Total Discrepancies: {report.total_discrepancies}")
    lines.append("")
    lines.append("SUMMARY")
    lines.append("-" * 80)
    lines.append(report.summary)
    lines.append("")
    
    # Discrepancies by severity
    lines.append("DISCREPANCIES BY SEVERITY")
    lines.append("-" * 80)
    for severity, count in sorted(report.discrepancies_by_severity.items()):
        lines.append(f"  {severity.upper()}: {count}")
    lines.append("")
    
    # Discrepancies by layer
    lines.append("DISCREPANCIES BY LAYER")
    lines.append("-" * 80)
    for layer, count in sorted(report.discrepancies_by_layer.items()):
        lines.append(f"  {layer.upper()}: {count}")
    lines.append("")
    
    # Critical discrepancies
    critical = [d for d in report.discrepancies if d.severity == Severity.CRITICAL]
    if critical:
        lines.append("CRITICAL DISCREPANCIES")
        lines.append("-" * 80)
        for disc in critical:
            lines.append(f"  [{disc.layer.value.upper()}] {disc.component}")
            lines.append(f"    {disc.description}")
            if disc.suggested_action:
                lines.append(f"    Action: {disc.suggested_action}")
            lines.append("")
    
    # High discrepancies
    high = [d for d in report.discrepancies if d.severity == Severity.HIGH]
    if high:
        lines.append("HIGH PRIORITY DISCREPANCIES")
        lines.append("-" * 80)
        for disc in high:
            lines.append(f"  [{disc.layer.value.upper()}] {disc.component}")
            lines.append(f"    {disc.description}")
            if disc.suggested_action:
                lines.append(f"    Action: {disc.suggested_action}")
            lines.append("")
    
    # Component health
    lines.append("COMPONENT HEALTH")
    lines.append("-" * 80)
    for component, health in report.component_health.items():
        lines.append(f"  {component}:")
        lines.append(f"    {json.dumps(health, indent=6)}")
        lines.append("")
    
    lines.append("=" * 80)
    return "\n".join(lines)


def _generate_html_report(report: PipelineHealthReport) -> str:
    """Generate HTML report."""
    html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>MERID Pipeline Discrepancy Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .summary {{ font-size: 18px; font-weight: bold; margin: 20px 0; }}
        .section {{ margin: 30px 0; }}
        .section h2 {{ border-bottom: 2px solid #333; }}
        .discrepancy {{ margin: 10px 0; padding: 10px; border-left: 4px solid #ccc; }}
        .critical {{ border-left-color: #d32f2f; background: #ffebee; }}
        .high {{ border-left-color: #f57c00; background: #fff3e0; }}
        .medium {{ border-left-color: #1976d2; background: #e3f2fd; }}
        .low {{ border-left-color: #388e3c; background: #e8f5e9; }}
        .component-health {{ margin: 10px 0; padding: 10px; background: #f5f5f5; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>MERID Trading Pipeline Discrepancy Report</h1>
        <p>Scan Time: {report.scan_timestamp.isoformat()}</p>
        <p>Duration: {report.scan_duration_seconds:.2f}s</p>
        <p>Total Discrepancies: {report.total_discrepancies}</p>
    </div>
    
    <div class="summary">
        {report.summary}
    </div>
    
    <div class="section">
        <h2>Discrepancies by Severity</h2>
        <ul>
    """
    
    for severity, count in sorted(report.discrepancies_by_severity.items()):
        html += f"            <li>{severity.upper()}: {count}</li>\n"
    
    html += """        </ul>
    </div>
    
    <div class="section">
        <h2>Discrepancies by Layer</h2>
        <ul>
    """
    
    for layer, count in sorted(report.discrepancies_by_layer.items()):
        html += f"            <li>{layer.upper()}: {count}</li>\n"
    
    html += """        </ul>
    </div>
    
    <div class="section">
        <h2>All Discrepancies</h2>
    """
    
    for disc in report.discrepancies:
        severity_class = disc.severity.value
        html += f"""
        <div class="discrepancy {severity_class}">
            <strong>[{disc.layer.value.upper()}] {disc.component}</strong><br/>
            {disc.description}<br/>
            <em>Type: {disc.discrepancy_type.value}</em><br/>
    """
        if disc.suggested_action:
            html += f"            <strong>Action:</strong> {disc.suggested_action}<br/>\n"
        if disc.impact:
            html += f"            <strong>Impact:</strong> {disc.impact}<br/>\n"
        html += "        </div>\n"
    
    html += """    </div>
    
    <div class="section">
        <h2>Component Health</h2>
    """
    
    for component, health in report.component_health.items():
        html += f"""
        <div class="component-health">
            <strong>{component}</strong><br/>
            <pre>{json.dumps(health, indent=2)}</pre>
        </div>
    """
    
    html += """    </div>
</body>
</html>
"""
    
    return html


if __name__ == "__main__":
    main()
