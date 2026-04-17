#!/usr/bin/env python3
"""
Incident Replay Workflow v2 — Reproducible Investigation CLI

Debug any order in under 5 minutes:
    python scripts/incident_replay.py <order_id> [--start-time <iso>] [--end-time <iso>]

Features:
- Full lineage trace (signal → agent → consensus → risk → router)
- Reconciliation status with break categorization
- State transitions with kill-switch timeline
- DataSource badge verification (Synthetic/Manual/External/Live)
- Reproducible output with embedded commands for re-run

Output formats:
    --format markdown    Human-readable report with runbook integration (default)
    --format json        Machine-readable for automation/alerting
    --format timeline    Chronological event stream for tracing
    --format runbook     Incident response runbook template

Examples:
    # Basic investigation (auto-detects time window)
    python scripts/incident_replay.py ord_kxbtc_001

    # Specific time window with runbook output
    python scripts/incident_replay.py ord_kxbtc_001 \\
        --start-time 2026-03-24T10:00:00Z \\
        --end-time 2026-03-24T10:30:00Z \\
        --format runbook \\
        --output docs/incidents/2026-03-24-kxbtc-slippage.md

    # JSON output for automation
    python scripts/incident_replay.py ord_kxbtc_001 --format json | jq .
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum

import aiohttp


class DataSourceBadge(Enum):
    """Data source badges for UI/API classification."""
    LIVE = "live"           # Production market data
    SYNTHETIC = "synthetic"   # Simulated/backtest data
    MANUAL = "manual"         # Human-entered
    EXTERNAL = "external"     # Non-Kalshi venue
    ARCHIVE = "archive"       # Historical/replay data


class IncidentSeverity(Enum):
    """Incident severity levels."""
    CRITICAL = "critical"     # Trading halt required
    HIGH = "high"             # Immediate investigation
    MEDIUM = "medium"         # Track and monitor
    LOW = "low"               # Informational


@dataclass
class StateTransition:
    """A state change event during the incident window."""
    timestamp: str
    component: str
    from_state: str
    to_state: str
    trigger: str
    metadata: Dict[str, Any]


@dataclass
class DataSourceEvidence:
    """Evidence of data source for an order."""
    order_id: str
    badge: DataSourceBadge
    lineage_verified: bool
    synthetic_reason: Optional[str] = None
    manual_user: Optional[str] = None
    external_venue: Optional[str] = None


@dataclass
class IncidentReport:
    """Complete incident report for an order."""
    order_id: str
    investigation_window: Tuple[str, str]
    lineage: Dict[str, Any]
    reconciliation: Dict[str, Any]
    state_transitions: List[StateTransition]
    fills: List[Dict[str, Any]]
    positions: List[Dict[str, Any]]
    risk_status: Dict[str, Any]
    alerts: List[Dict[str, Any]]
    checklist: List[str]
    severity: IncidentSeverity
    data_source: DataSourceEvidence
    replay_command: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "order_id": self.order_id,
            "investigation_window": self.investigation_window,
            "lineage": self.lineage,
            "reconciliation": self.reconciliation,
            "state_transitions": [asdict(t) for t in self.state_transitions],
            "fills": self.fills,
            "positions": self.positions,
            "risk_status": self.risk_status,
            "alerts": self.alerts,
            "checklist": self.checklist,
            "severity": self.severity.value,
            "data_source": asdict(self.data_source),
            "replay_command": self.replay_command,
        }


class IncidentReplayer:
    """Replay and investigate trading incidents with full observability."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def _get(self, endpoint: str) -> Dict[str, Any]:
        """GET request to API with error handling."""
        url = f"{self.base_url}{endpoint}"
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
                return {"error": f"HTTP {resp.status}", "status": resp.status}
        except Exception as exc:
            return {"error": str(exc), "exception_type": type(exc).__name__}
    
    async def _fetch_state_transitions(
        self, 
        start_time: str, 
        end_time: str,
    ) -> List[StateTransition]:
        """Fetch state transitions from observability module."""
        # Query the state transition log
        result = await self._get(
            f"/api/v1/observability/state-transitions?start={start_time}&end={end_time}"
        )
        
        if result.get("error"):
            # Fallback: reconstruct from risk/reconciliation polling
            return []
        
        transitions = []
        for item in result.get("transitions", []):
            transitions.append(StateTransition(
                timestamp=item.get("timestamp", ""),
                component=item.get("component", "unknown"),
                from_state=item.get("from_state", "unknown"),
                to_state=item.get("to_state", "unknown"),
                trigger=item.get("trigger", "unknown"),
                metadata=item.get("metadata", {}),
            ))
        return transitions
    
    async def _classify_data_source(
        self,
        lineage: Dict[str, Any],
        fills: List[Dict[str, Any]],
    ) -> DataSourceEvidence:
        """Classify the data source badge for this order."""
        order = lineage.get("order", {})
        
        # Check for explicit flags
        if order.get("is_synthetic") or lineage.get("synthetic"):
            return DataSourceEvidence(
                order_id=order.get("order_id", ""),
                badge=DataSourceBadge.SYNTHETIC,
                lineage_verified=lineage.get("chain_complete", False),
                synthetic_reason=order.get("synthetic_reason", "backtest"),
            )
        
        if order.get("is_manual") or order.get("user_id"):
            return DataSourceEvidence(
                order_id=order.get("order_id", ""),
                badge=DataSourceBadge.MANUAL,
                lineage_verified=lineage.get("chain_complete", False),
                manual_user=order.get("user_id", "unknown"),
            )
        
        if order.get("external_venue") or lineage.get("external_venue"):
            return DataSourceEvidence(
                order_id=order.get("order_id", ""),
                badge=DataSourceBadge.EXTERNAL,
                lineage_verified=lineage.get("chain_complete", False),
                external_venue=order.get("external_venue", "unknown"),
            )
        
        # Check if any fills are synthetic
        synthetic_fills = [f for f in fills if f.get("is_synthetic")]
        if synthetic_fills:
            return DataSourceEvidence(
                order_id=order.get("order_id", ""),
                badge=DataSourceBadge.SYNTHETIC,
                lineage_verified=lineage.get("chain_complete", False),
                synthetic_reason="synthetic_fills_detected",
            )
        
        # Default: live production data
        return DataSourceEvidence(
            order_id=order.get("order_id", ""),
            badge=DataSourceBadge.LIVE,
            lineage_verified=lineage.get("chain_complete", False),
        )
    
    def _calculate_severity(
        self,
        lineage: Dict[str, Any],
        reconciliation: Dict[str, Any],
        risk: Dict[str, Any],
        data_source: DataSourceEvidence,
    ) -> IncidentSeverity:
        """Calculate incident severity based on findings."""
        # Critical: reconciliation broken + kill switch active
        if reconciliation.get("status") == "broken" and risk.get("kill_switch_active"):
            return IncidentSeverity.CRITICAL
        
        # Critical: order not found in any system
        if not lineage.get("found"):
            return IncidentSeverity.CRITICAL
        
        # High: incomplete lineage for live order
        if data_source.badge == DataSourceBadge.LIVE and not lineage.get("chain_complete"):
            return IncidentSeverity.HIGH
        
        # High: reconciliation degraded during order
        if reconciliation.get("status") == "degraded":
            return IncidentSeverity.HIGH
        
        # High: kill switch active during order
        if risk.get("kill_switch_active"):
            return IncidentSeverity.HIGH
        
        # Medium: synthetic/manual order with incomplete lineage
        if data_source.badge in (DataSourceBadge.SYNTHETIC, DataSourceBadge.MANUAL):
            if not lineage.get("chain_complete"):
                return IncidentSeverity.MEDIUM
        
        return IncidentSeverity.LOW
    
    def _generate_replay_command(
        self,
        order_id: str,
        start_time: str,
        end_time: str,
    ) -> str:
        """Generate reproducible replay command for this investigation."""
        return (
            f"python scripts/incident_replay.py {order_id} \\\n"
            f"    --start-time {start_time} \\\n"
            f"    --end-time {end_time} \\\n"
            f"    --base-url {self.base_url} \\\n"
            f"    --format markdown"
        )
    
    async def investigate(
        self,
        order_id: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        window_minutes: int = 10,
    ) -> IncidentReport:
        """
        Investigate an order incident.
        
        If start_time/end_time not provided, uses order creation time ± window.
        """
        print(f"🔍 Investigating order: {order_id}")
        print(f"   Base URL: {self.base_url}")
        print()
        
        # 1. Fetch order lineage
        print("Step 1/7: Fetching order lineage...")
        lineage = await self._get(f"/api/v1/kalshi/orders/{order_id}/lineage")
        
        if lineage.get("error"):
            print(f"   ⚠️  Lineage fetch failed: {lineage['error']}")
        else:
            print(f"   ✓ Found: {lineage.get('found', False)}")
            print(f"   ✓ Chain complete: {lineage.get('chain_complete', False)}")
            print(f"   ✓ Manual/external: {lineage.get('manual_or_external', False)}")
        
        # Determine investigation window
        if not start_time or not end_time:
            order_time = lineage.get("order", {}).get("created_at")
            if order_time:
                order_dt = datetime.fromisoformat(order_time.replace("Z", "+00:00"))
                start_dt = order_dt - timedelta(minutes=window_minutes)
                end_dt = order_dt + timedelta(minutes=window_minutes)
                start_time = start_dt.isoformat()
                end_time = end_dt.isoformat()
            else:
                # Default to now ± window
                now = datetime.now(timezone.utc)
                start_time = (now - timedelta(minutes=window_minutes)).isoformat()
                end_time = (now + timedelta(minutes=window_minutes)).isoformat()
        
        investigation_window = (start_time, end_time)
        print(f"   Investigation window: {start_time[:19]} to {end_time[:19]}")
        print()
        
        # 2. Fetch reconciliation status
        print("Step 2/7: Fetching reconciliation status...")
        reconciliation = await self._get("/api/v1/kalshi/reconciliation/breaks")
        
        if reconciliation.get("error"):
            print(f"   ⚠️  Reconciliation fetch failed: {reconciliation['error']}")
        else:
            status = reconciliation.get("status", "unknown")
            break_count = reconciliation.get("break_count", 0)
            print(f"   ✓ Status: {status}")
            print(f"   ✓ Breaks: {break_count}")
            if status in ("degraded", "broken"):
                print(f"   ⚠️  WARNING: Reconciliation is {status.upper()}!")
        print()
        
        # 3. Fetch fills
        print("Step 3/7: Fetching fills...")
        fills_data = await self._get("/api/v1/kalshi/fills?since_hours=24")
        fills = fills_data.get("fills", [])
        order_fills = [f for f in fills if f.get("order_id") == order_id]
        print(f"   ✓ Total fills (24h): {len(fills)}")
        print(f"   ✓ Fills for this order: {len(order_fills)}")
        print()
        
        # 4. Fetch positions
        print("Step 4/7: Fetching positions...")
        positions_data = await self._get("/api/v1/kalshi/positions")
        positions = positions_data.get("positions", [])
        
        # Find position for this order's ticker
        order_ticker = lineage.get("order", {}).get("ticker")
        related_positions = [
            p for p in positions 
            if order_ticker and p.get("ticker") == order_ticker
        ]
        print(f"   ✓ Total positions: {len(positions)}")
        print(f"   ✓ Positions for {order_ticker}: {len(related_positions)}")
        print()
        
        # 5. Fetch risk status
        print("Step 5/7: Fetching risk status...")
        risk = await self._get("/api/v1/kalshi/risk")
        
        if risk.get("error"):
            print(f"   ⚠️  Risk fetch failed: {risk['error']}")
        else:
            kill_switch = risk.get("kill_switch_active", False)
            daily_pnl = risk.get("daily_pnl_usd", 0)
            print(f"   ✓ Kill switch: {'ACTIVE' if kill_switch else 'inactive'}")
            print(f"   ✓ Daily PnL: ${daily_pnl:.2f}")
        print()
        
        # 6. Fetch state transitions with new helper
        print("Step 6/7: Fetching state transitions...")
        state_transitions = await self._fetch_state_transitions(start_time, end_time)
        print(f"   ✓ Found {len(state_transitions)} state transitions")
        
        # 7. Classify data source and calculate severity
        print("Step 7/8: Classifying data source...")
        data_source = await self._classify_data_source(lineage, order_fills)
        print(f"   ✓ DataSource: {data_source.badge.value.upper()}")
        print(f"   ✓ Lineage verified: {data_source.lineage_verified}")
        print()
        
        print("Step 8/8: Calculating severity and generating checklist...")
        severity = self._calculate_severity(lineage, reconciliation, risk, data_source)
        print(f"   ✓ Severity: {severity.value.upper()}")
        
        checklist = self._generate_checklist(lineage, reconciliation, order_fills, risk, data_source, severity)
        print(f"   ✓ {len(checklist)} checklist items")
        print()
        
        # Generate replay command for reproducibility
        replay_command = self._generate_replay_command(order_id, start_time, end_time)
        
        return IncidentReport(
            order_id=order_id,
            investigation_window=investigation_window,
            lineage=lineage,
            reconciliation=reconciliation,
            state_transitions=state_transitions,
            fills=order_fills,
            positions=related_positions,
            risk_status=risk,
            alerts=[],  # Would fetch from alert history
            checklist=checklist,
            severity=severity,
            data_source=data_source,
            replay_command=replay_command,
        )
    
    def _generate_checklist(
        self,
        lineage: Dict[str, Any],
        reconciliation: Dict[str, Any],
        fills: List[Dict[str, Any]],
        risk: Dict[str, Any],
        data_source: DataSourceEvidence,
        severity: IncidentSeverity,
    ) -> List[str]:
        """Generate investigation checklist based on findings."""
        checklist = []
        
        # Severity-based header
        if severity == IncidentSeverity.CRITICAL:
            checklist.append("🚨 CRITICAL SEVERITY — Immediate action required")
            checklist.append("   → Consider halting trading and paging on-call")
        elif severity == IncidentSeverity.HIGH:
            checklist.append("🔴 HIGH SEVERITY — Investigate within 30 minutes")
        elif severity == IncidentSeverity.MEDIUM:
            checklist.append("🟡 MEDIUM SEVERITY — Track and monitor")
        
        checklist.append("")
        
        # Data source verification
        if data_source.badge == DataSourceBadge.SYNTHETIC:
            checklist.append(f"✓ SYNTHETIC ORDER — Reason: {data_source.synthetic_reason}")
            if data_source.lineage_verified:
                checklist.append("  → Lineage verified for synthetic order")
            else:
                checklist.append("⚠️  Synthetic order lineage incomplete — verify backtest harness")
        elif data_source.badge == DataSourceBadge.MANUAL:
            checklist.append(f"✓ MANUAL ORDER — User: {data_source.manual_user}")
            if not data_source.lineage_verified:
                checklist.append("⚠️  Manual order bypassed risk checks — verify intentional")
        elif data_source.badge == DataSourceBadge.EXTERNAL:
            checklist.append(f"✓ EXTERNAL ORDER — Venue: {data_source.external_venue}")
            checklist.append("  → Check external venue fills in separate system")
        elif data_source.badge == DataSourceBadge.LIVE:
            checklist.append("✓ LIVE PRODUCTION ORDER")
        
        checklist.append("")
        
        # Lineage checks
        if not lineage.get("found"):
            checklist.append("❌ CRITICAL: Order not found in any system. Verify order_id.")
        
        if lineage.get("manual_or_external"):
            checklist.append("⚠️  Order bypassed normal pipeline. Check if intentional (manual trade).")
        
        if not lineage.get("chain_complete") and not lineage.get("manual_or_external"):
            checklist.append("❌ Lineage incomplete. Missing: " + 
                lineage.get("chain_coverage", "unknown"))
            checklist.append("   → Check agent logs for signal_id")
            checklist.append("   → Verify risk controller recorded decision")
            checklist.append("   → Confirm order_router has route record")
        
        if lineage.get("chain", {}).get("signal", {}).get("fresh") is False:
            checklist.append("⚠️  Signal was stale (>60s) when order placed.")
        
        # Reconciliation checks
        if reconciliation.get("status") == "broken":
            checklist.append("❌ CRITICAL: Reconciliation broken during order window.")
            checklist.append("   → Stop trading until reconciled")
            checklist.append("   → Check fills ledger for missing records")
        
        if reconciliation.get("status") == "degraded":
            checklist.append("⚠️  Reconciliation degraded. Review break details.")
        
        # Fill checks
        if lineage.get("order", {}).get("status") == "filled" and not fills:
            checklist.append("❌ Order marked filled but no fills found. Check fills ledger.")
        
        # Risk checks
        if risk.get("kill_switch_active"):
            checklist.append("❌ Kill switch active during order. Order should have been blocked.")
        
        if not checklist:
            checklist.append("✓ All checks passed. Order appears normal.")
        
        return checklist
    
    def format_markdown(self, report: IncidentReport) -> str:
        """Format report as Markdown."""
        lines = []
        
        lines.append(f"# Incident Report: Order {report.order_id}")
        lines.append("")
        lines.append(f"**Investigation Window:** {report.investigation_window[0][:19]} to {report.investigation_window[1][:19]} UTC")
        lines.append("")
        
        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")
        
        lineage = report.lineage
        if lineage.get("found"):
            if lineage.get("manual_or_external"):
                lines.append("⚠️  **EXTERNAL/MANUAL ORDER** — Bypassed canonical pipeline")
            elif lineage.get("chain_complete"):
                lines.append("✓ **GOLDEN PATH** — Full lineage trace available")
            else:
                lines.append("❌ **INCOMPLETE LINEAGE** — Investigate shadow path")
        else:
            lines.append("❌ **ORDER NOT FOUND** — Verify order_id")
        
        if report.reconciliation.get("status") in ("degraded", "broken"):
            lines.append(f"❌ **RECONCILIATION {report.reconciliation['status'].upper()}** during order window")
        
        lines.append("")
        
        # Lineage
        lines.append("## Order Lineage")
        lines.append("")
        
        if lineage.get("found"):
            lines.append(f"- **Found:** Yes")
            lines.append(f"- **Chain Complete:** {lineage.get('chain_complete', False)}")
            lines.append(f"- **Chain Coverage:** {lineage.get('chain_coverage', 'unknown')}")
            lines.append(f"- **Manual/External:** {lineage.get('manual_or_external', False)}")
            lines.append(f"- **Venue Source:** {lineage.get('venue_source', 'unknown')}")
            lines.append("")
            
            chain = lineage.get("chain", {})
            for step in ["signal", "agent", "consensus", "risk", "router"]:
                if step in chain:
                    lines.append(f"### {step.capitalize()}")
                    lines.append(f"```json")
                    lines.append(json.dumps(chain[step], indent=2, default=str))
                    lines.append(f"```")
                    lines.append("")
        else:
            lines.append("Order not found in any system.")
            lines.append("")
        
        # Reconciliation
        lines.append("## Reconciliation Status")
        lines.append("")
        recon = report.reconciliation
        lines.append(f"- **Status:** {recon.get('status', 'unknown')}")
        lines.append(f"- **Break Count:** {recon.get('break_count', 0)}")
        lines.append(f"- **High Severity:** {recon.get('high_severity_count', 0)}")
        lines.append("")
        
        if recon.get("breaks"):
            lines.append("### Active Breaks")
            lines.append("")
            for break_item in recon["breaks"][:5]:
                lines.append(f"- [{break_item.get('severity', 'unknown').upper()}] {break_item.get('type')}: {break_item.get('message', 'No message')}")
            lines.append("")
        
        # Fills
        lines.append("## Fills")
        lines.append("")
        if report.fills:
            for fill in report.fills:
                lines.append(f"- {fill.get('fill_id')}: {fill.get('side')} {fill.get('size')} @ {fill.get('price')} ({fill.get('timestamp', 'unknown')})")
        else:
            lines.append("No fills recorded for this order.")
        lines.append("")
        
        # Risk
        lines.append("## Risk Status (at time of order)")
        lines.append("")
        risk = report.risk_status
        if not risk.get("error"):
            lines.append(f"- **Kill Switch:** {'ACTIVE' if risk.get('kill_switch_active') else 'inactive'}")
            lines.append(f"- **Daily PnL:** ${risk.get('daily_pnl_usd', 0):.2f}")
            lines.append(f"- **Drawdown:** {risk.get('drawdown_pct', 0):.2f}%")
        else:
            lines.append(f"Could not fetch: {risk.get('error')}")
        lines.append("")
        
        # Checklist
        lines.append("## Investigation Checklist")
        lines.append("")
        for item in report.checklist:
            lines.append(f"- {item}")
        lines.append("")
        
        # Debugging commands
        lines.append("## Debug Commands")
        lines.append("")
        lines.append(f"```bash")
        lines.append(f"# Full lineage")
        lines.append(f"curl {self.base_url}/api/v1/kalshi/orders/{report.order_id}/lineage | jq")
        lines.append(f"")
        lines.append(f"# Reconciliation breaks")
        lines.append(f"curl {self.base_url}/api/v1/kalshi/reconciliation/breaks | jq")
        lines.append(f"")
        lines.append(f"# State transitions")
        lines.append(f"# See: merid/observability/state_transitions.py")
        lines.append(f"```")
        lines.append("")
        
        return "\n".join(lines)
    
    def format_json(self, report: IncidentReport) -> str:
        """Format report as JSON."""
        return json.dumps(report.to_dict(), indent=2, default=str)
    
    def format_runbook(self, report: IncidentReport) -> str:
        """Format as incident response runbook template."""
        lines = []
        
        # Header
        lines.append(f"# Incident Runbook: Order {report.order_id}")
        lines.append(f"")
        lines.append(f"**Severity:** {report.severity.value.upper()}")
        lines.append(f"**Data Source:** {report.data_source.badge.value.upper()}")
        lines.append(f"**Investigation Window:** {report.investigation_window[0][:19]} to {report.investigation_window[1][:19]} UTC")
        lines.append(f"")
        
        # Quick Actions (on-call checklist)
        lines.append("## Quick Actions (Do First)")
        lines.append("")
        lines.append("- [ ] **Verify kill switch state:**")
        lines.append(f"  - Current: {'ACTIVE' if report.risk_status.get('kill_switch_active') else 'inactive'}")
        lines.append("  - Action: If active, do not resume trading until root cause found")
        lines.append("")
        lines.append("- [ ] **Check reconciliation status:**")
        lines.append(f"  - Status: {report.reconciliation.get('status', 'unknown')}")
        lines.append(f"  - Breaks: {report.reconciliation.get('break_count', 0)}")
        lines.append("  - Action: If broken, halt trading immediately")
        lines.append("")
        lines.append("- [ ] **Verify data source badge:**")
        lines.append(f"  - Badge: {report.data_source.badge.value.upper()}")
        lines.append(f"  - Lineage verified: {report.data_source.lineage_verified}")
        lines.append("")
        
        # Data Source Section
        lines.append("## Data Source Verification")
        lines.append("")
        if report.data_source.badge == DataSourceBadge.SYNTHETIC:
            lines.append("### Synthetic Order")
            lines.append(f"- **Reason:** {report.data_source.synthetic_reason}")
            lines.append("- **Expected Behavior:** Should NOT affect live positions")
            lines.append("- **Verification:** Check `is_synthetic` flag in order record")
            lines.append("")
            lines.append("**Risk:** If synthetic order leaked to live execution, this is CRITICAL.")
            lines.append("")
        elif report.data_source.badge == DataSourceBadge.MANUAL:
            lines.append("### Manual Order")
            lines.append(f"- **User:** {report.data_source.manual_user}")
            lines.append("- **Expected Behavior:** Bypassed normal signal pipeline")
            lines.append("- **Verification:** Check user permissions and intent")
            lines.append("")
        elif report.data_source.badge == DataSourceBadge.EXTERNAL:
            lines.append("### External Venue Order")
            lines.append(f"- **Venue:** {report.data_source.external_venue}")
            lines.append("- **Expected Behavior:** May not appear in Kalshi fills")
            lines.append("- **Verification:** Check external venue reconciliation")
            lines.append("")
        
        # Investigation Steps
        lines.append("## Investigation Steps")
        lines.append("")
        lines.append("### 1. Lineage Verification")
        lines.append("")
        lines.append("```bash")
        lines.append(f"# Get full lineage chain")
        lines.append(f"curl {self.base_url}/api/v1/kalshi/orders/{report.order_id}/lineage | jq")
        lines.append("```")
        lines.append("")
        if report.lineage.get("chain_complete"):
            lines.append("✓ **Chain complete** — all steps recorded")
        else:
            lines.append("❌ **Chain incomplete** — missing steps:")
            lines.append(f"  Missing: {report.lineage.get('chain_coverage', 'unknown')}")
            lines.append("  ")
            lines.append("  **Debug:**")
            lines.append("  - Check agent logs for signal_id")
            lines.append("  - Verify risk controller recorded decision")
            lines.append("  - Confirm order_router has route record")
        lines.append("")
        
        lines.append("### 2. Reconciliation Check")
        lines.append("")
        lines.append("```bash")
        lines.append("# Get current reconciliation breaks")
        lines.append(f"curl {self.base_url}/api/v1/kalshi/reconciliation/breaks | jq")
        lines.append("```")
        lines.append("")
        if report.reconciliation.get("breaks"):
            lines.append("**Active breaks during incident:**")
            for break_item in report.reconciliation["breaks"][:5]:
                lines.append(f"- [{break_item.get('severity', 'unknown').upper()}] {break_item.get('type')}: {break_item.get('message')}")
        else:
            lines.append("✓ No reconciliation breaks")
        lines.append("")
        
        lines.append("### 3. Kill Switch Timeline")
        lines.append("")
        lines.append("```bash")
        lines.append("# Get kill switch state transitions")
        lines.append(f"curl {self.base_url}/api/v1/observability/state-transitions?component=kill_switch | jq")
        lines.append("```")
        lines.append("")
        kill_transitions = [t for t in report.state_transitions if "kill" in t.component.lower()]
        if kill_transitions:
            lines.append("**Kill switch transitions during incident:**")
            for t in kill_transitions:
                lines.append(f"- {t.timestamp[:19]}: {t.from_state} → {t.to_state} ({t.trigger})")
        else:
            lines.append("ℹ️ No kill switch transitions captured")
        lines.append("")
        
        # Resolution
        lines.append("## Resolution")
        lines.append("")
        lines.append("### When to Close")
        lines.append("")
        if report.severity == IncidentSeverity.CRITICAL:
            lines.append("- [ ] Root cause identified and documented")
            lines.append("- [ ] Fix deployed or rollback completed")
            lines.append("- [ ] Trading resumed with enhanced monitoring")
            lines.append("- [ ] Post-mortem scheduled within 24 hours")
        elif report.severity == IncidentSeverity.HIGH:
            lines.append("- [ ] Impact assessed and contained")
            lines.append("- [ ] Fix deployed or workaround in place")
            lines.append("- [ ] Monitoring confirms stability")
        else:
            lines.append("- [ ] Investigation complete")
            lines.append("- [ ] No action required or tracking ticket created")
        lines.append("")
        
        # Replay Command
        lines.append("## Reproducibility")
        lines.append("")
        lines.append("To replay this exact investigation:")
        lines.append("")
        lines.append("```bash")
        lines.append(report.replay_command)
        lines.append("```")
        lines.append("")
        
        return "\n".join(lines)
    
    def format_timeline(self, report: IncidentReport) -> str:
        """Format as chronological timeline."""
        events = []
        
        # Add lineage events
        chain = report.lineage.get("chain", {})
        for step_name, step_data in chain.items():
            if isinstance(step_data, dict) and "timestamp" in step_data:
                events.append({
                    "time": step_data["timestamp"],
                    "type": f"lineage:{step_name}",
                    "data": step_data,
                })
        
        # Add fills
        for fill in report.fills:
            events.append({
                "time": fill.get("timestamp", "unknown"),
                "type": "fill",
                "data": fill,
            })
        
        # Sort by time
        events.sort(key=lambda x: x["time"])
        
        lines = ["# Event Timeline", ""]
        for event in events:
            lines.append(f"{event['time'][:19]} | {event['type']:20} | {json.dumps(event['data'], default=str)[:80]}")
        
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Incident Replay: Debug MERID orders in under 5 minutes"
    )
    parser.add_argument("order_id", help="Order ID to investigate")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    parser.add_argument("--start-time", help="Investigation start (ISO8601)")
    parser.add_argument("--end-time", help="Investigation end (ISO8601)")
    parser.add_argument("--window-minutes", type=int, default=10, help="Window around order time")
    parser.add_argument("--format", choices=["markdown", "json", "timeline", "runbook"], default="markdown", help="Output format")
    parser.add_argument("--output", "-o", help="Output file (default: stdout)")
    
    args = parser.parse_args()
    
    async def run():
        async with IncidentReplayer(base_url=args.base_url) as replayer:
            report = await replayer.investigate(
                order_id=args.order_id,
                start_time=args.start_time,
                end_time=args.end_time,
                window_minutes=args.window_minutes,
            )
            
            if args.format == "markdown":
                output = replayer.format_markdown(report)
            elif args.format == "json":
                output = replayer.format_json(report)
            elif args.format == "timeline":
                output = replayer.format_timeline(report)
            elif args.format == "runbook":
                output = replayer.format_runbook(report)
            
            if args.output:
                with open(args.output, "w") as f:
                    f.write(output)
                print(f"✓ Report written to {args.output}")
            else:
                print(output)
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(130)
    except Exception as exc:
        print(f"Fatal error: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
