#!/usr/bin/env python3
"""
Kalshi WebSocket Health Audit Script

Systematically audits WebSocket implementation across critical areas:
1. Connection lifecycle management
2. Heartbeat and dead connection detection
3. Authentication and security hygiene
4. Message queue backpressure
5. Connection metrics tracking
6. Reconnection storm prevention
7. Kalshi-specific audit points

Usage:
    python scripts/audit_websocket_health.py [--verbose] [--json-output]
"""

import argparse
import ast
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class AuditFinding:
    """Represents a single audit finding."""
    category: str
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    title: str
    description: str
    file: str
    line: Optional[int] = None
    recommendation: str = ""
    code_snippet: Optional[str] = None


@dataclass
class AuditReport:
    """Complete audit report."""
    timestamp: str
    findings: List[AuditFinding] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    
    def add_finding(self, finding: AuditFinding):
        self.findings.append(finding)
        self.summary[finding.severity] = self.summary.get(finding.severity, 0) + 1
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "summary": self.summary,
            "findings": [
                {
                    "category": f.category,
                    "severity": f.severity,
                    "title": f.title,
                    "description": f.description,
                    "file": f.file,
                    "line": f.line,
                    "recommendation": f.recommendation,
                    "code_snippet": f.code_snippet,
                }
                for f in self.findings
            ]
        }


class WebSocketAuditor:
    """Audits WebSocket implementation for health and security issues."""
    
    def __init__(self, project_root: Path, verbose: bool = False):
        self.project_root = project_root
        self.verbose = verbose
        self.report = AuditReport(timestamp=datetime.now(timezone.utc).isoformat())
        
        # Key files to audit
        self.ws_file = project_root / "merid" / "event_venues" / "kalshi" / "ws.py"
        self.ws_bridge_file = project_root / "merid" / "event_venues" / "kalshi" / "ws_bridge.py"
        self.market_state_file = project_root / "merid" / "event_venues" / "kalshi" / "market_state.py"
        self.env_file = project_root / ".env"
        # NOTE: 15m lean stack uses new bridge at merid_core/kalshi/ws_bridge.py
        self.new_ws_bridge_file = project_root / "merid_core" / "kalshi" / "ws_bridge.py"
        
    def log(self, message: str):
        """Log message if verbose mode enabled."""
        if self.verbose:
            print(f"[AUDIT] {message}")
    
    def read_file_lines(self, file_path: Path) -> List[str]:
        """Read file lines for analysis."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.readlines()
        except Exception as e:
            self.log(f"Failed to read {file_path}: {e}")
            return []
    
    def search_pattern(self, lines: List[str], pattern: str, file_path: Path) -> List[Tuple[int, str]]:
        """Search for pattern in lines, return (line_num, line) matches."""
        matches = []
        regex = re.compile(pattern, re.IGNORECASE)
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                matches.append((i, line.rstrip()))
        return matches
    
    def audit_connection_lifecycle(self):
        """Audit connection lifecycle management."""
        self.log("Auditing connection lifecycle management...")
        
        lines = self.read_file_lines(self.ws_file)
        if not lines:
            return
        
        # Check 1: Connection cleanup on close/error
        close_matches = self.search_pattern(lines, r'def close\(|async def close\(', self.ws_file)
        if close_matches:
            for line_num, line in close_matches:
                # Check if cleanup happens in close() - look at more context
                context = "\n".join(lines[max(0, line_num-5):min(len(lines), line_num+40)])
                if "_subscriptions.clear()" in context or "self._subscriptions.clear()" in context:
                    self.log(f"✓ Found subscription cleanup in close() at line {line_num}")
                else:
                    self.report.add_finding(AuditFinding(
                        category="Connection Lifecycle",
                        severity="HIGH",
                        title="Missing subscription cleanup in close()",
                        description="WebSocket close() method may not clear subscriptions, potentially causing memory leaks",
                        file=str(self.ws_file),
                        line=line_num,
                        recommendation="Add self._subscriptions.clear() in close() method",
                        code_snippet=line
                    ))
        
        # Check 2: Orphaned connection prevention
        reconnect_matches = self.search_pattern(lines, r'def _reconnect\(|async def _reconnect\(', self.ws_file)
        if reconnect_matches:
            for line_num, line in reconnect_matches:
                # Look at even more context to find cleanup logic (up to 150 lines)
                context = "\n".join(lines[max(0, line_num-5):min(len(lines), line_num+150)])
                # Check for explicit cleanup OR call to connect()/close() which handle cleanup
                # Also check for self.connect() wrapped in other functions like asyncio.wait_for
                if "self._ws = None" in context or "self._ws.close()" in context or "await self.close()" in context or "self.connect()" in context:
                    self.log(f"✓ Found connection cleanup in _reconnect() at line {line_num}")
                else:
                    self.report.add_finding(AuditFinding(
                        category="Connection Lifecycle",
                        severity="HIGH",
                        title="Potential orphaned connections in _reconnect()",
                        description="Reconnect logic may not properly close old connections before creating new ones",
                        file=str(self.ws_file),
                        line=line_num,
                        recommendation="Ensure self._ws.close() and self._ws = None are called before reconnecting, or call self.connect() which handles cleanup",
                        code_snippet=line
                    ))
        
        # Check 3: Reconnect lock to prevent concurrent reconnects
        if "self._reconnect_lock" in "\n".join(lines):
            self.log("✓ Found reconnect lock to prevent concurrent reconnects")
        else:
            self.report.add_finding(AuditFinding(
                category="Connection Lifecycle",
                severity="CRITICAL",
                title="Missing reconnect lock",
                description="No lock mechanism to prevent concurrent reconnect attempts, which could cause reconnect storms",
                file=str(self.ws_file),
                recommendation="Add asyncio.Lock() for reconnect coordination",
                code_snippet=""
            ))
        
        # Check 4: Circuit breaker for repeated failures
        bridge_lines = self.read_file_lines(self.ws_bridge_file)
        if bridge_lines:
            if "circuit_breaker" in "\n".join(bridge_lines).lower():
                self.log("✓ Found circuit breaker mechanism in ws_bridge.py")
            else:
                self.report.add_finding(AuditFinding(
                    category="Connection Lifecycle",
                    severity="HIGH",
                    title="Missing circuit breaker for repeated failures",
                    description="No circuit breaker to prevent reconnect storms after repeated failures",
                    file=str(self.ws_bridge_file),
                    recommendation="Implement circuit breaker with failure counting and cooldown",
                    code_snippet=""
                ))
    
    def audit_heartbeat_dead_connection(self):
        """Audit heartbeat and dead connection detection."""
        self.log("Auditing heartbeat and dead connection detection...")
        
        lines = self.read_file_lines(self.ws_file)
        if not lines:
            return
        
        # Check 1: Ping-pong configuration
        ping_matches = self.search_pattern(lines, r'ping_interval|ping_timeout', self.ws_file)
        if ping_matches:
            for line_num, line in ping_matches:
                self.log(f"✓ Found ping configuration at line {line_num}: {line.strip()}")
                # Check if ping_timeout is reasonable (should be > ping_interval)
                if "ping_timeout" in line.lower():
                    try:
                        timeout_val = re.search(r'ping_timeout\s*=\s*(\d+)', line)
                        if timeout_val:
                            timeout = int(timeout_val.group(1))
                            if timeout < 30:
                                self.report.add_finding(AuditFinding(
                                    category="Heartbeat",
                                    severity="MEDIUM",
                                    title="Ping timeout too short",
                                    description=f"ping_timeout={timeout}s may be too short for event-loop lag tolerance",
                                    file=str(self.ws_file),
                                    line=line_num,
                                    recommendation="Increase ping_timeout to at least 60s to tolerate event-loop lag",
                                    code_snippet=line
                                ))
                    except (ValueError, AttributeError):
                        pass
        else:
            self.report.add_finding(AuditFinding(
                category="Heartbeat",
                severity="CRITICAL",
                title="Missing ping-pong configuration",
                description="No ping_interval or ping_timeout configured - dead connections may not be detected",
                file=str(self.ws_file),
                recommendation="Add ping_interval and ping_timeout to websockets.connect()",
                code_snippet=""
            ))
        
        # Check 2: Last message timestamp tracking
        if "_last_message_ts" in "\n".join(lines):
            self.log("✓ Found last message timestamp tracking")
        else:
            self.report.add_finding(AuditFinding(
                category="Heartbeat",
                severity="HIGH",
                title="Missing last message timestamp tracking",
                description="No tracking of last message timestamp - cannot detect zombie connections",
                file=str(self.ws_file),
                recommendation="Add self._last_message_ts updated on each message",
                code_snippet=""
            ))
        
        # Check 3: Connection health checks
        if "is_open" in "\n".join(lines) or "open" in "\n".join(lines):
            self.log("✓ Found connection state checks")
        else:
            self.report.add_finding(AuditFinding(
                category="Heartbeat",
                severity="MEDIUM",
                title="Missing connection state checks",
                description="No explicit checks for connection open state",
                file=str(self.ws_file),
                recommendation="Add periodic connection state validation",
                code_snippet=""
            ))
    
    def audit_authentication_security(self):
        """Audit authentication and security hygiene."""
        self.log("Auditing authentication and security hygiene...")
        
        lines = self.read_file_lines(self.ws_file)
        if not lines:
            return
        
        # Check 1: WSS (secure WebSocket) usage
        url_matches = self.search_pattern(lines, r'ws_url|wss://|ws://', self.ws_file)
        if url_matches:
            for line_num, line in url_matches:
                if "ws://" in line and "wss://" not in line:
                    self.report.add_finding(AuditFinding(
                        category="Security",
                        severity="CRITICAL",
                        title="Insecure WebSocket URL (ws://)",
                        description="Using insecure ws:// instead of wss:// for production connections",
                        file=str(self.ws_file),
                        line=line_num,
                        recommendation="Use wss:// for all production WebSocket connections",
                        code_snippet=line
                    ))
                elif "wss://" in line:
                    self.log(f"✓ Found secure WebSocket URL at line {line_num}")
        
        # Check 2: Authentication headers
        auth_headers = self.search_pattern(lines, r'KALSHI-ACCESS-KEY|KALSHI-ACCESS-SIGNATURE|KALSHI-ACCESS-TIMESTAMP', self.ws_file)
        if auth_headers:
            self.log(f"✓ Found Kalshi authentication headers ({len(auth_headers)} occurrences)")
        else:
            self.report.add_finding(AuditFinding(
                category="Security",
                severity="CRITICAL",
                title="Missing Kalshi authentication headers",
                description="WebSocket connection may not include required authentication headers",
                file=str(self.ws_file),
                recommendation="Add KALSHI-ACCESS-KEY, KALSHI-ACCESS-SIGNATURE, KALSHI-ACCESS-TIMESTAMP headers",
                code_snippet=""
            ))
        
        # Check 3: RSA-PSS signature
        if "PSS" in "\n".join(lines) and "SHA256" in "\n".join(lines):
            self.log("✓ Found RSA-PSS signature with SHA256")
        else:
            self.report.add_finding(AuditFinding(
                category="Security",
                severity="HIGH",
                title="Missing or incorrect signature algorithm",
                description="WebSocket authentication may not use RSA-PSS with SHA256 as required by Kalshi",
                file=str(self.ws_file),
                recommendation="Use RSA-PSS with SHA256 for signature generation",
                code_snippet=""
            ))
        
        # Check 4: Timestamp buffer for clock skew
        if "5000" in "\n".join(lines) or "buffer" in "\n".join(lines).lower():
            self.log("✓ Found timestamp buffer for clock skew")
        else:
            self.report.add_finding(AuditFinding(
                category="Security",
                severity="MEDIUM",
                title="Missing timestamp buffer for clock skew",
                description="No buffer added to timestamp - may fail due to clock skew",
                file=str(self.ws_file),
                recommendation="Add 5000ms buffer to timestamp to prevent clock skew failures",
                code_snippet=""
            ))
        
        # Check 5: Origin header validation (if applicable)
        # Note: This is more relevant for server-side validation, but we check if it's mentioned
        if "origin" in "\n".join(lines).lower():
            self.log("✓ Found Origin header handling")
    
    def audit_message_queue_backpressure(self):
        """Audit message queue backpressure handling."""
        self.log("Auditing message queue backpressure...")
        
        ws_lines = self.read_file_lines(self.ws_file)
        bridge_lines = self.read_file_lines(self.ws_bridge_file)
        
        # Check 1: Queue size configuration
        if ws_lines:
            queue_matches = self.search_pattern(ws_lines, r'Queue|maxsize|queue_size', self.ws_file)
            if queue_matches:
                for line_num, line in queue_matches:
                    if "maxsize" in line:
                        try:
                            size_match = re.search(r'maxsize\s*=\s*(\d+)', line)
                            if size_match:
                                size = int(size_match.group(1))
                                if size < 8192:
                                    self.report.add_finding(AuditFinding(
                                        category="Backpressure",
                                        severity="MEDIUM",
                                        title="Message queue size too small",
                                        description=f"Queue maxsize={size} may be too small for burst traffic",
                                        file=str(self.ws_file),
                                        line=line_num,
                                        recommendation="Increase queue size to at least 16384 for burst handling",
                                        code_snippet=line
                                    ))
                                else:
                                    self.log(f"✓ Found queue with maxsize={size}")
                        except (ValueError, AttributeError):
                            pass
        
        # Check 2: Queue full handling
        if ws_lines:
            if "QueueFull" in "\n".join(ws_lines):
                self.log("✓ Found QueueFull exception handling")
            else:
                self.report.add_finding(AuditFinding(
                    category="Backpressure",
                    severity="HIGH",
                    title="Missing QueueFull exception handling",
                    description="No handling for queue full scenario - messages may be lost",
                    file=str(self.ws_file),
                    recommendation="Add try/except for asyncio.QueueFull with selective dropping",
                    code_snippet=""
                ))
        
        # Check 3: Message dropping strategy
        if ws_lines:
            if "drop" in "\n".join(ws_lines).lower() and "priority" in "\n".join(ws_lines).lower():
                self.log("✓ Found priority-based message dropping")
            else:
                self.report.add_finding(AuditFinding(
                    category="Backpressure",
                    severity="MEDIUM",
                    title="Missing priority-based message dropping",
                    description="No priority-based dropping strategy - may drop critical messages",
                    file=str(self.ws_file),
                    recommendation="Implement priority-based dropping (keep fills, drop quotes)",
                    code_snippet=""
                ))
        
        # Check 4: Queue pressure monitoring
        if ws_lines:
            if "pressure" in "\n".join(ws_lines).lower() or "supervisor" in "\n".join(ws_lines).lower():
                self.log("✓ Found queue pressure monitoring")
            else:
                self.report.add_finding(AuditFinding(
                    category="Backpressure",
                    severity="MEDIUM",
                    title="Missing queue pressure monitoring",
                    description="No monitoring of queue pressure - cannot detect backpressure issues",
                    file=str(self.ws_file),
                    recommendation="Add queue pressure monitoring with periodic checks",
                    code_snippet=""
                ))
        
        # Check 5: Bridge queue backpressure
        if bridge_lines:
            if "_BRIDGE_QUEUE_SIZE" in "\n".join(bridge_lines):
                self.log("✓ Found bridge queue size configuration")
            else:
                self.report.add_finding(AuditFinding(
                    category="Backpressure",
                    severity="MEDIUM",
                    title="Missing bridge queue size configuration",
                    description="Bridge queue size not explicitly configured",
                    file=str(self.ws_bridge_file),
                    recommendation="Define _BRIDGE_QUEUE_SIZE constant",
                    code_snippet=""
                ))
    
    def audit_connection_metrics(self):
        """Audit connection metrics tracking."""
        self.log("Auditing connection metrics tracking...")
        
        ws_lines = self.read_file_lines(self.ws_file)
        bridge_lines = self.read_file_lines(self.ws_bridge_file)
        
        # Check 1: Message counter
        if ws_lines:
            if "_messages_received" in "\n".join(ws_lines):
                self.log("✓ Found messages received counter")
            else:
                self.report.add_finding(AuditFinding(
                    category="Metrics",
                    severity="MEDIUM",
                    title="Missing messages received counter",
                    description="No tracking of messages received",
                    file=str(self.ws_file),
                    recommendation="Add self._messages_received counter",
                    code_snippet=""
                ))
        
        # Check 2: Error counter
        if ws_lines:
            if "_errors_received" in "\n".join(ws_lines):
                self.log("✓ Found errors received counter")
            else:
                self.report.add_finding(AuditFinding(
                    category="Metrics",
                    severity="MEDIUM",
                    title="Missing errors received counter",
                    description="No tracking of errors received",
                    file=str(self.ws_file),
                    recommendation="Add self._errors_received counter",
                    code_snippet=""
                ))
        
        # Check 3: Reconnect counter
        if ws_lines:
            if "_reconnect_count" in "\n".join(ws_lines):
                self.log("✓ Found reconnect counter")
            else:
                self.report.add_finding(AuditFinding(
                    category="Metrics",
                    severity="MEDIUM",
                    title="Missing reconnect counter",
                    description="No tracking of reconnection attempts",
                    file=str(self.ws_file),
                    recommendation="Add self._reconnect_count counter",
                    code_snippet=""
                ))
        
        # Check 4: Connection duration tracking
        if ws_lines:
            if "_connect_ts" in "\n".join(ws_lines):
                self.log("✓ Found connection timestamp tracking")
            else:
                self.report.add_finding(AuditFinding(
                    category="Metrics",
                    severity="LOW",
                    title="Missing connection duration tracking",
                    description="No tracking of connection duration",
                    file=str(self.ws_file),
                    recommendation="Add self._connect_ts timestamp",
                    code_snippet=""
                ))
        
        # Check 5: Health status endpoint
        if bridge_lines:
            if "get_health_status" in "\n".join(bridge_lines):
                self.log("✓ Found health status method in bridge")
            else:
                self.report.add_finding(AuditFinding(
                    category="Metrics",
                    severity="LOW",
                    title="Missing health status method",
                    description="No health status method for monitoring integration",
                    file=str(self.ws_bridge_file),
                    recommendation="Add get_health_status() method returning metrics",
                    code_snippet=""
                ))
    
    def audit_reconnection_storm_prevention(self):
        """Audit reconnection storm prevention."""
        self.log("Auditing reconnection storm prevention...")
        
        ws_lines = self.read_file_lines(self.ws_file)
        bridge_lines = self.read_file_lines(self.ws_bridge_file)
        
        # Check 1: Exponential backoff
        if ws_lines:
            if "exponential" in "\n".join(ws_lines).lower() or "backoff" in "\n".join(ws_lines).lower():
                self.log("✓ Found exponential backoff in ws.py")
            else:
                self.report.add_finding(AuditFinding(
                    category="Reconnection",
                    severity="HIGH",
                    title="Missing exponential backoff",
                    description="No exponential backoff for reconnection attempts",
                    file=str(self.ws_file),
                    recommendation="Implement exponential backoff with jitter",
                    code_snippet=""
                ))
        
        # Check 2: Jitter
        if ws_lines:
            if "jitter" in "\n".join(ws_lines).lower() or "random" in "\n".join(ws_lines).lower():
                self.log("✓ Found jitter in reconnection")
            else:
                self.report.add_finding(AuditFinding(
                    category="Reconnection",
                    severity="MEDIUM",
                    title="Missing jitter in reconnection",
                    description="No jitter to prevent synchronized reconnection storms",
                    file=str(self.ws_file),
                    recommendation="Add random jitter to backoff delay",
                    code_snippet=""
                ))
        
        # Check 3: Max reconnect delay
        if ws_lines:
            if "_max_reconnect_delay" in "\n".join(ws_lines):
                self.log("✓ Found max reconnect delay")
            else:
                self.report.add_finding(AuditFinding(
                    category="Reconnection",
                    severity="MEDIUM",
                    title="Missing max reconnect delay",
                    description="No upper bound on reconnect delay",
                    file=str(self.ws_file),
                    recommendation="Add self._max_reconnect_delay constant",
                    code_snippet=""
                ))
        
        # Check 4: Circuit breaker in bridge
        if bridge_lines:
            if "_circuit_breaker" in "\n".join(bridge_lines).lower():
                self.log("✓ Found circuit breaker in ws_bridge.py")
                # Check threshold (but ignore warning log lines that check threshold - 2)
                threshold_matches = self.search_pattern(bridge_lines, r'_CIRCUIT_BREAKER_THRESHOLD\s*:\s*int\s*=\s*\d+', self.ws_bridge_file)
                if threshold_matches:
                    for line_num, line in threshold_matches:
                        try:
                            threshold = re.search(r'=\s*(\d+)', line)
                            if threshold:
                                val = int(threshold.group(1))
                                if val < 5:
                                    self.report.add_finding(AuditFinding(
                                        category="Reconnection",
                                        severity="LOW",
                                        title="Circuit breaker threshold too low",
                                        description=f"Threshold={val} may be too sensitive",
                                        file=str(self.ws_bridge_file),
                                        line=line_num,
                                        recommendation="Consider increasing threshold to 10-20",
                                        code_snippet=line
                                    ))
                        except (ValueError, AttributeError):
                            pass
            else:
                self.report.add_finding(AuditFinding(
                    category="Reconnection",
                    severity="HIGH",
                    title="Missing circuit breaker in bridge",
                    description="No circuit breaker to prevent reconnection storms",
                    file=str(self.ws_bridge_file),
                    recommendation="Implement circuit breaker with failure counting and cooldown",
                    code_snippet=""
                ))
    
    def audit_kalshi_specific(self):
        """Audit Kalshi-specific WebSocket requirements."""
        self.log("Auditing Kalshi-specific requirements...")
        
        ws_lines = self.read_file_lines(self.ws_file)
        bridge_lines = self.read_file_lines(self.ws_bridge_file)
        
        # Check 1: Subscription scope limiting
        if bridge_lines:
            if "_MAX_WS_SUBSCRIPTIONS" in "\n".join(bridge_lines):
                self.log("✓ Found max WS subscriptions limit")
                # Check value
                matches = self.search_pattern(bridge_lines, r'_MAX_WS_SUBSCRIPTIONS\s*=\s*(\d+)', self.ws_bridge_file)
                for line_num, line in matches:
                    try:
                        limit = int(re.search(r'(\d+)', line).group(1))
                        if limit > 200:
                            self.report.add_finding(AuditFinding(
                                category="Kalshi Specific",
                                severity="MEDIUM",
                                title="WS subscription limit too high",
                                description=f"Limit={limit} may exceed Kalshi rate limits",
                                file=str(self.ws_bridge_file),
                                line=line_num,
                                recommendation="Reduce to 150 or lower to respect Kalshi limits",
                                code_snippet=line
                            ))
                    except (ValueError, AttributeError):
                        pass
            else:
                self.report.add_finding(AuditFinding(
                    category="Kalshi Specific",
                    severity="HIGH",
                    title="Missing WS subscription limit",
                    description="No hard cap on number of WebSocket subscriptions",
                    file=str(self.ws_bridge_file),
                    recommendation="Add _MAX_WS_SUBSCRIPTIONS constant (recommended: 150)",
                    code_snippet=""
                ))
        
        # Check 2: Channel subscription filtering
        if bridge_lines:
            if "fills" in "\n".join(bridge_lines).lower() and "orderbook" in "\n".join(bridge_lines).lower():
                self.log("✓ Found channel subscription filtering")
            else:
                self.report.add_finding(AuditFinding(
                    category="Kalshi Specific",
                    severity="MEDIUM",
                    title="Missing channel subscription filtering",
                    description="No priority-based channel subscription (fills vs quotes)",
                    file=str(self.ws_bridge_file),
                    recommendation="Implement priority-based channel filtering",
                    code_snippet=""
                ))
        
        # Check 3: Chunked subscription
        if ws_lines:
            if "chunk" in "\n".join(ws_lines).lower() or "KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE" in "\n".join(ws_lines):
                self.log("✓ Found chunked subscription")
            else:
                self.report.add_finding(AuditFinding(
                    category="Kalshi Specific",
                    severity="MEDIUM",
                    title="Missing chunked subscription",
                    description="No chunking of large subscription lists",
                    file=str(self.ws_file),
                    recommendation="Implement chunked subscription with KALSHI_WS_MARKET_TICKERS_CHUNK_SIZE",
                    code_snippet=""
                ))
        
        # Check 4: Orderbook snapshot caching
        if ws_lines:
            if "_ob_snapshots" in "\n".join(ws_lines) or "snapshot" in "\n".join(ws_lines).lower():
                self.log("✓ Found orderbook snapshot caching")
            else:
                self.report.add_finding(AuditFinding(
                    category="Kalshi Specific",
                    severity="HIGH",
                    title="Missing orderbook snapshot caching",
                    description="No caching of orderbook snapshots before applying deltas",
                    file=str(self.ws_file),
                    recommendation="Add orderbook snapshot caching for delta application",
                    code_snippet=""
                ))
        
        # Check 5: Sequence tracking
        if ws_lines:
            if "_last_seq" in "\n".join(ws_lines) or "sequence" in "\n".join(ws_lines).lower():
                self.log("✓ Found sequence tracking")
            else:
                self.report.add_finding(AuditFinding(
                    category="Kalshi Specific",
                    severity="HIGH",
                    title="Missing sequence tracking",
                    description="No sequence tracking for gap detection",
                    file=str(self.ws_file),
                    recommendation="Add sequence tracking with gap detection",
                    code_snippet=""
                ))
        
        # Check 6: Environment-specific endpoints
        if ws_lines:
            if "demo" in "\n".join(ws_lines).lower() or "production" in "\n".join(ws_lines).lower():
                self.log("✓ Found environment-specific endpoint handling")
            else:
                self.report.add_finding(AuditFinding(
                    category="Kalshi Specific",
                    severity="MEDIUM",
                    title="Missing environment-specific endpoint handling",
                    description="No differentiation between demo and production endpoints",
                    file=str(self.ws_file),
                    recommendation="Add environment-specific endpoint selection",
                    code_snippet=""
                ))
    
    def audit_environment_configuration(self):
        """Audit environment configuration for WebSocket settings."""
        self.log("Auditing environment configuration...")
        
        if not self.env_file.exists():
            self.report.add_finding(AuditFinding(
                category="Configuration",
                severity="MEDIUM",
                title="Missing .env file",
                description="No .env file found - WebSocket configuration may be missing",
                file=str(self.env_file),
                recommendation="Create .env file with WebSocket configuration",
                code_snippet=""
            ))
            return
        
        env_lines = self.read_file_lines(self.env_file)
        if not env_lines:
            return
        
        # Check for relevant environment variables
        required_vars = [
            "KALSHI_API_KEY_ID",
            "KALSHI_PRIVATE_KEY_PATH",
            "KALSHI_ENV",
        ]
        
        optional_vars = [
            "MERID_KALSHI_MAX_WS_SUBS",
            "MERID_KALSHI_WS_CRITICAL",
            "KALSHI_WS_PRESSURE_SHUTDOWN_MAX",
            "KALSHI_WS_RECONNECT_CIRCUIT_THRESHOLD",
        ]
        
        for var in required_vars:
            if any(var in line for line in env_lines):
                self.log(f"✓ Found {var} in .env")
            else:
                self.report.add_finding(AuditFinding(
                    category="Configuration",
                    severity="CRITICAL",
                    title=f"Missing required environment variable: {var}",
                    description=f"Required environment variable {var} not set in .env",
                    file=str(self.env_file),
                    recommendation=f"Add {var} to .env file",
                    code_snippet=""
                ))
        
        for var in optional_vars:
            if any(var in line for line in env_lines):
                self.log(f"✓ Found optional {var} in .env")
    
    def run_full_audit(self) -> AuditReport:
        """Run all audit checks."""
        print("Starting WebSocket Health Audit...")
        print(f"Project root: {self.project_root}")
        print(f"Timestamp: {self.report.timestamp}")
        print("-" * 60)
        
        self.audit_connection_lifecycle()
        self.audit_heartbeat_dead_connection()
        self.audit_authentication_security()
        self.audit_message_queue_backpressure()
        self.audit_connection_metrics()
        self.audit_reconnection_storm_prevention()
        self.audit_kalshi_specific()
        self.audit_environment_configuration()
        
        print("-" * 60)
        print("Audit complete.")
        return self.report


def print_report(report: AuditReport, verbose: bool = False):
    """Print audit report to console."""
    print("\n" + "=" * 60)
    print("WEBSOCKET HEALTH AUDIT REPORT")
    print("=" * 60)
    print(f"Timestamp: {report.timestamp}")
    print(f"Total Findings: {len(report.findings)}")
    print("\nSummary:")
    for severity in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        count = report.summary.get(severity, 0)
        if count > 0:
            print(f"  {severity}: {count}")
    
    if verbose:
        print("\nDetailed Findings:")
        print("-" * 60)
        for finding in report.findings:
            print(f"\n[{finding.severity}] {finding.title}")
            print(f"Category: {finding.category}")
            print(f"File: {finding.file}")
            if finding.line:
                print(f"Line: {finding.line}")
            print(f"Description: {finding.description}")
            if finding.recommendation:
                print(f"Recommendation: {finding.recommendation}")
            if finding.code_snippet:
                print(f"Code: {finding.code_snippet}")
    else:
        # Print only CRITICAL and HIGH findings by default
        critical_high = [f for f in report.findings if f.severity in ["CRITICAL", "HIGH"]]
        if critical_high:
            print("\nCritical & High Findings:")
            print("-" * 60)
            for finding in critical_high:
                print(f"\n[{finding.severity}] {finding.title}")
                print(f"  File: {finding.file}")
                if finding.line:
                    print(f"  Line: {finding.line}")
                print(f"  {finding.description}")
        else:
            print("\n✓ No CRITICAL or HIGH findings.")
    
    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Audit WebSocket implementation for health and security")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed findings")
    parser.add_argument("--json", "-j", action="store_true", help="Output JSON report")
    parser.add_argument("--project-root", "-p", type=str, default=".", help="Project root directory")
    
    args = parser.parse_args()
    
    project_root = Path(args.project_root).resolve()
    if not project_root.exists():
        print(f"Error: Project root {project_root} does not exist")
        sys.exit(1)
    
    auditor = WebSocketAuditor(project_root, verbose=args.verbose)
    report = auditor.run_full_audit()
    
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_report(report, verbose=args.verbose)
    
    # Exit with error code if CRITICAL findings
    if report.summary.get("CRITICAL", 0) > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
