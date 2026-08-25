#!/usr/bin/env python3
"""High-leverage bug exposure audit for the MERID trading/execution stack.

This script is intentionally safe and read-only:
  * It does NOT place, modify, or cancel orders.
  * It does NOT mutate the ledger, cache, risk, or database.
  * It does NOT import merid modules (so it cannot start rogue singletons).
  * It masks secrets/tokens when printing environment data.

It audits:
  - Runtime state (duplicate uvicorn processes, live-trading env latches)
  - Git workspace drift and untracked order-placement scripts
  - Recent logs for high-leverage failure patterns
  - Static code heuristics in the trading/execution paths
  - Data files (kill switch, circuit-breaker watermark, audit chain)

Usage:
    .venv\Scripts\python.exe scripts\high_leverage_bug_exposure.py
    .venv\Scripts\python.exe scripts\high_leverage_bug_exposure.py --network --output-dir audit_output
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Optional deps; we fall back gracefully when they are missing.
try:
    import psutil
except Exception:  # noqa: BLE001
    psutil = None

try:
    import requests
except Exception:  # noqa: BLE001
    requests = None

try:
    from dotenv import dotenv_values
except Exception:  # noqa: BLE001
    dotenv_values = None

REPO_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = REPO_ROOT / "logs"
DATA_DIR = REPO_ROOT / "data"

CRITICAL_SOURCE_FILES = [
    "merid/event_venues/kalshi/order_router.py",
    "merid/event_venues/kalshi/order_intent_contract.py",
    "merid/event_venues/kalshi/fills_ledger.py",
    "merid/event_venues/kalshi/fills_poller.py",
    "merid/event_venues/kalshi/position_cache.py",
    "merid/event_venues/kalshi/binary_price_space.py",
    "merid/event_venues/kalshi/port_ledger_adapter.py",
    "merid/event_venues/kalshi/execution_risk_firewall.py",
    "merid/event_venues/kalshi/stop_candidate.py",
    "merid/event_venues/kalshi/resting_order_monitor.py",
    "merid/event_venues/kalshi/client_v2.py",
    "merid/prediction/trade_decision.py",
    "merid/prediction/agent_grid_15m.py",
    "merid/prediction/intent_contract.py",
    "merid/prediction/venue_gate.py",
    "merid/risk/unified_risk_manager.py",
    "merid/risk/unified_enforcement_gate.py",
    "merid/risk/profiles/kalshi_crypto_15m_risk_envelope.py",
    "merid/position_management/position_monitor.py",
    "merid/position_management/exit_policy.py",
    "merid/governance/trading_circuit_breaker.py",
    "merid/startup_validations.py",
    "merid/settings.py",
    "web/main_15m_lean.py",
]

LIVE_TRADING_ENV_VARS = [
    "MERID_ENV",
    "MERID_PROFILE",
    "MERID_PM_PROFILE",
    "MERID_PM_TRADING_MODE",
    "MERID_ALLOW_LIVE_TRADES",
    "MERID_PM_LIVE_ENABLED",
    "TRADING_ENABLED",
    "KALSHI_ENV",
    "MERID_KALSHI_ENV",
    "KALSHI_USE_DEMO",
    "MERID_RUNTIME_MODE",
    "MERID_KALSHI_WS_CLIENT",
    "MERID_DEV_ALLOW_WS",
]

SAFETY_ENV_VARS = [
    "MERID_CIRCUIT_BREAKER_DISABLED",
    "MERID_CIRCUIT_BREAKER_OBSERVE_ONLY",
    "MERID_EXIT_FIREWALL_OBSERVE_ONLY",
    "MERID_REQUIRE_EXIT_PARENTAGE",
    "MERID_ALLOW_UNPROTECTED_ENTRIES",
    "MERID_ENTRY_IDEMPOTENCY_ENABLED",
    "MERID_SINGLE_USER_OPERATOR",
    "DEBUG_ALLOW_MANUAL_ORDERS",
    "ALLOW_DIRECT_EXECUTION",
    "MERID_ALLOW_CT_SCRIPT_BYPASS",
    "PYTEST_CURRENT_TEST",
    "MERID_CFB_RTI_SHADOW_TELEMETRY",
]

SENSITIVE_NAME_RE = re.compile(r".*(TOKEN|KEY|SECRET|PASSWORD|CREDENTIAL|ANON|SERVICE_ROLE|APP_PASSWORD|API_SECRET|BREAKER_RELEASE|MANUAL_EMERGENCY|KALSHI_API|AUTH).*", re.I)

LOG_PATTERN_REGEXES: Dict[str, re.Pattern] = {
    "CRITICAL": re.compile(r"CRITICAL"),
    "TRADING_CIRCUIT_BREAKER_HALT": re.compile(r"TRADING_CIRCUIT_BREAKER_HALT"),
    "reconciliation_halted": re.compile(r"reconciliation_halted"),
    "reconciliation_status_mismatch": re.compile(r"reconciliation_status=mismatch"),
    "UNMATCHED_FILL": re.compile(r"UNMATCHED_FILL"),
    "firewall_rejection": re.compile(r"firewall:"),
    "STOP-CANDIDATE-NOT-SUBMITTED": re.compile(r"STOP-CANDIDATE-NOT-SUBMITTED"),
    "FILL-CANONICALIZATION_FAIL": re.compile(r"FILL-CANONICALIZATION.*FAIL"),
    "FILL-SIDE-CONFLICT": re.compile(r"(?:UNTRUSTED_SIDE_CONFLICT|FILL-SIDE-CONFLICT)"),
    "FILL-SIDE-FORM-MATCH": re.compile(r"FILL-SIDE-FORM-MATCH"),
    "WRONG-DIRECTION-POSITION-CHANGE": re.compile(r"WRONG-DIRECTION-POSITION-CHANGE"),
    "RESIDUAL-EXPOSURE-RISK": re.compile(r"RESIDUAL-EXPOSURE-RISK"),
    "POSITION-CACHE-CONTRACT-LIMIT-WARNING": re.compile(r"POSITION-CACHE-CONTRACT-LIMIT-WARNING"),
    "IS-EXIT-HINT-MISMATCH": re.compile(r"IS-EXIT-HINT-MISMATCH"),
    "ORDER-LIFECYCLE-INVARIANT": re.compile(r"ORDER-LIFECYCLE-INVARIANT"),
    "POSITION-CACHE-EDGE-FALLBACK": re.compile(r"POSITION-CACHE-EDGE-FALLBACK"),
    "unfilled_ioc": re.compile(r"unfilled_ioc|status=unfilled_ioc"),
    "final_minute_entry_disabled": re.compile(r"final_minute_entry_disabled"),
    "cfb_rti_failure": re.compile(r"cfb_rti_(?:unavailable|stale|nonmonotonic|invalid_value|symbol_mismatch)"),
    "lost_intent": re.compile(r"lost_intent"),
    "BRACKET_UNAVAILABLE": re.compile(r"BRACKET_UNAVAILABLE"),
    "PROTECTIVE_EXIT_DISABLED": re.compile(r"PROTECTIVE_EXIT_DISABLED"),
    "entry_with_open_position": re.compile(r"entry_with_open_position"),
    "MERID_ALLOW_UNPROTECTED_ENTRIES": re.compile(r"MERID_ALLOW_UNPROTECTED_ENTRIES"),
    "PositionCache.reset": re.compile(r"PositionCache\.reset|KalshiPositionCache\(\)\.clear"),
    "over_close_or_flip": re.compile(r"over-close|position flips|negative.*position"),
    "adverse_pnl": re.compile(r"adverse.*pnl|realized_pnl.*-|pnl=.*-"),
    "slippage": re.compile(r"slippage"),
    "fee_delta_unknown": re.compile(r"fee_delta_cents=unknown"),
    "edge_zero": re.compile(r"edge=0[\s\b]"),
}

STATIC_CODE_REGEXES: Dict[str, re.Pattern] = {
    "position_cache_reset": re.compile(r"PositionCache\.reset\(|KalshiPositionCache\(\)\.clear\("),
    "except_exception_pass": re.compile(r"except\s+Exception(?:\s+as\s+\w+)?\s*:\s*pass"),
    "float_for_money": re.compile(r"float\([^)]*(?:price|fee|pnl|notional|cost|usd|dollars)"),
    "int_fee_times_100": re.compile(r"int\(\s*(?:fee|cost)[^)]*\*\s*100\s*\)"),
    "round_decimal": re.compile(r"\.round\(|round\([^)]*Decimal"),
    "OrderResult.success": re.compile(r"\.success\b"),
    "apply_fill_not_once": re.compile(r"(?<!_)apply_fill\("),
    "reduce_only_false": re.compile(r"reduce_only\s*=\s*False"),
    "allow_short": re.compile(r"allow_short"),
    "manual_emergency_close": re.compile(r"is_manual_emergency_close"),
    "circuit_breaker_resume": re.compile(r"TradingCircuitBreaker\.resume\("),
    "direct_execution_bypass": re.compile(r"ALLOW_DIRECT_EXECUTION|DEBUG_ALLOW_MANUAL_ORDERS|MERID_ALLOW_CT_SCRIPT_BYPASS"),
    "unprotected_entries": re.compile(r"MERID_ALLOW_UNPROTECTED_ENTRIES"),
    "circuit_breaker_disabled": re.compile(r"MERID_CIRCUIT_BREAKER_DISABLED"),
    "dev_allow_ws": re.compile(r"MERID_DEV_ALLOW_WS"),
    "single_user_operator": re.compile(r"MERID_SINGLE_USER_OPERATOR"),
    "pytest_current_test": re.compile(r"PYTEST_CURRENT_TEST"),
    "while_true": re.compile(r"while\s+True\s*:"),
    "asyncio_gather_no_timeout": re.compile(r"asyncio\.gather\("),
    "sleep_in_async": re.compile(r"(?:await\s+)?asyncio\.sleep\(|time\.sleep\("),
    "raw_post_orders": re.compile(r"_request_with_resilience\([^)]*['\"]POST['\"][^)]*orders"),
    "observe_only_true": re.compile(r"MERID_EXIT_FIREWALL_OBSERVE_ONLY\s*=\s*(?:['\"]true['\"]|True|1)"),
    "require_exit_parentage_false": re.compile(r"MERID_REQUIRE_EXIT_PARENTAGE\s*=\s*(?:['\"]0['\"]|False|0)"),
}


def _is_sensitive_name(name: str) -> bool:
    return bool(SENSITIVE_NAME_RE.match(name))


def _mask_value(name: str, value: Any) -> Any:
    if value is None:
        return None
    s = str(value)
    if _is_sensitive_name(name) and s:
        if len(s) <= 4:
            return "***"
        return s[:2] + "***" + s[-2:]
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sh(cmd: List[str], cwd: Path = REPO_ROOT, timeout: int = 30) -> Tuple[int, str, str]:
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:  # noqa: BLE001
        return -1, "", str(e)


@dataclass
class Finding:
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW, INFO
    layer: str
    category: str
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    file: Optional[str] = None
    line: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "severity": self.severity,
            "layer": self.layer,
            "category": self.category,
            "description": self.description,
            "evidence": self.evidence,
        }
        if self.file:
            d["file"] = self.file
        if self.line:
            d["line"] = self.line
        return d


@dataclass
class Report:
    scan_timestamp: str = field(default_factory=_now)
    repo_root: str = str(REPO_ROOT)
    findings: List[Finding] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_timestamp": self.scan_timestamp,
            "repo_root": self.repo_root,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
        }

    def by_severity(self) -> Counter:
        return Counter(f.severity for f in self.findings)


class HighLeverageBugAuditor:
    def __init__(self, network: bool = False, run_tests: bool = False, log_tail: int = 200_000):
        self.network = network
        self.run_tests = run_tests
        self.log_tail = log_tail
        self.report = Report()

    # ----------------------------------------------------------------------
    # Public entry
    # ----------------------------------------------------------------------
    def run(self) -> Report:
        self._audit_runtime_environment()
        self._audit_processes()
        self._audit_git_workspace()
        self._audit_tmp_scripts()
        self._audit_data_files()
        self._audit_logs()
        self._audit_static_code()
        if self.network:
            self._audit_network_endpoints()
        if self.run_tests:
            self._run_targeted_tests()
        self._build_summary()
        return self.report

    # ----------------------------------------------------------------------
    # 1. Environment / runtime
    # ----------------------------------------------------------------------
    def _audit_runtime_environment(self) -> None:
        layer = "runtime_environment"

        env = {}
        for name in sorted(set(LIVE_TRADING_ENV_VARS + SAFETY_ENV_VARS)):
            value = os.environ.get(name)
            if value is not None:
                env[name] = _mask_value(name, value)

        self.report.add(
            Finding(
                severity="INFO",
                layer=layer,
                category="environment",
                description="Current process environment (sensitive values masked).",
                evidence=env,
            )
        )

        merid_allow_live = os.environ.get("MERID_ALLOW_LIVE_TRADES", "").lower()
        pm_mode = os.environ.get("MERID_PM_TRADING_MODE", "paper").lower()
        kalshi_env = os.environ.get("KALSHI_ENV", "demo").lower()
        merid_kalshi_env = os.environ.get("MERID_KALSHI_ENV", "").lower()
        merid_env = os.environ.get("MERID_ENV", "development").lower()

        if merid_allow_live in ("true", "1", "yes"):
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="live_trading_latch",
                    description="MERID_ALLOW_LIVE_TRADES is enabled in this process.",
                    evidence={"MERID_ALLOW_LIVE_TRADES": _mask_value("MERID_ALLOW_LIVE_TRADES", os.environ.get("MERID_ALLOW_LIVE_TRADES")), "MERID_PM_TRADING_MODE": pm_mode},
                )
            )
        if pm_mode == "live":
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="live_trading_latch",
                    description="MERID_PM_TRADING_MODE=live. Real-money order submission may be active.",
                    evidence={"MERID_PM_TRADING_MODE": "live"},
                )
            )
        if kalshi_env == "live" or merid_kalshi_env in ("live", "prod"):
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="live_trading_latch",
                    description="Kalshi environment is configured for live production venue.",
                    evidence={"KALSHI_ENV": kalshi_env, "MERID_KALSHI_ENV": merid_kalshi_env},
                )
            )
        if merid_env in ("prod", "production"):
            if os.environ.get("PYTEST_CURRENT_TEST"):
                self.report.add(
                    Finding(
                        severity="CRITICAL",
                        layer=layer,
                        category="production_startup_validation",
                        description="PYTEST_CURRENT_TEST is set in a production process. validate_production_startup should fail.",
                    )
                )
            for flag in ["DEBUG_ALLOW_MANUAL_ORDERS", "ALLOW_DIRECT_EXECUTION", "MERID_ALLOW_CT_SCRIPT_BYPASS"]:
                if os.environ.get(flag, "").lower() in ("1", "true", "yes"):
                    self.report.add(
                        Finding(
                            severity="CRITICAL",
                            layer=layer,
                            category="production_startup_validation",
                            description=f"{flag}=true in production; validate_production_startup should fail.",
                        )
                    )
            if os.environ.get("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "").lower() in ("1", "true", "yes"):
                self.report.add(
                    Finding(
                        severity="HIGH",
                        layer=layer,
                        category="firewall",
                        description="MERID_EXIT_FIREWALL_OBSERVE_ONLY=true in production. Exit parentage is NOT enforced.",
                    )
                )
            if os.environ.get("MERID_REQUIRE_EXIT_PARENTAGE", "0") not in ("1", "true", "yes"):
                self.report.add(
                    Finding(
                        severity="HIGH",
                        layer=layer,
                        category="firewall",
                        description="MERID_REQUIRE_EXIT_PARENTAGE is not set to 1 in production. Exit parentage unenforced.",
                    )
                )
            if os.environ.get("MERID_CIRCUIT_BREAKER_DISABLED", "").lower() in ("1", "true", "yes"):
                self.report.add(
                    Finding(
                        severity="CRITICAL",
                        layer=layer,
                        category="circuit_breaker",
                        description="MERID_CIRCUIT_BREAKER_DISABLED=true in production.",
                    )
                )

        if os.environ.get("MERID_SINGLE_USER_OPERATOR", "").lower() in ("1", "true", "yes"):
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="auth_bypass",
                    description="MERID_SINGLE_USER_OPERATOR=1 is a live-trading auth bypass. AGENTS.md says this is hard-blocked.",
                )
            )
        if os.environ.get("MERID_ALLOW_UNPROTECTED_ENTRIES", "").lower() in ("1", "true", "yes"):
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="protective_exit_gate",
                    description="MERID_ALLOW_UNPROTECTED_ENTRIES=1 allows entries without stop-candidate protection.",
                )
            )
        if os.environ.get("MERID_KALSHI_WS_CLIENT", "").lower() != "ws" and os.environ.get("MERID_DEV_ALLOW_WS", "").lower() in ("1", "true", "yes"):
            self.report.add(
                Finding(
                    severity="HIGH",
                    layer=layer,
                    category="websocket",
                    description="MERID_DEV_ALLOW_WS=true but MERID_KALSHI_WS_CLIENT is not 'ws'. Live production requires the real WebSocket client.",
                )
            )

        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            lines = env_file.read_text(encoding="utf-8").splitlines()
            dotenv_data = {}
            for line in lines:
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    dotenv_data[k.strip()] = _mask_value(k.strip(), v.strip().strip('"\''))
            self.report.add(
                Finding(
                    severity="INFO",
                    layer=layer,
                    category="dotenv",
                    description=".env file present (sensitive values masked).",
                    evidence=dotenv_data,
                )
            )

    # ----------------------------------------------------------------------
    # 2. Processes
    # ----------------------------------------------------------------------
    def _audit_processes(self) -> None:
        layer = "processes"
        uvicorn_pids: List[Dict[str, Any]] = []

        if psutil is not None:
            for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time"]):
                try:
                    cmd = " ".join(proc.info.get("cmdline") or [])
                    if "uvicorn" in proc.info.get("name", "").lower() or "main_15m_lean" in cmd:
                        uvicorn_pids.append(
                            {
                                "pid": proc.info["pid"],
                                "cmdline": cmd,
                                "create_time": datetime.fromtimestamp(proc.info["create_time"], tz=timezone.utc).isoformat(),
                                "connections": [],
                            }
                        )
                except Exception:  # noqa: BLE001
                    continue
            # Map port 8011 listeners to pids (best-effort, read-only).
            try:
                rc, out, _ = _sh(["powershell", "-Command", "Get-NetTCPConnection -LocalPort 8011 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,OwningProcess,State | ConvertTo-Json -Compress"])
                if rc == 0:
                    conns = json.loads(out) if out.strip().startswith("[") or out.strip().startswith("{") else []
                    if isinstance(conns, dict):
                        conns = [conns]
                    for up in uvicorn_pids:
                        for c in conns:
                            if c.get("OwningProcess") == up["pid"]:
                                up["connections"].append(c)
            except Exception:  # noqa: BLE001
                pass
        else:
            # Fallback: PowerShell + wmic
            rc, out, _ = _sh(["wmic", "process", "where", 'name="python.exe"', "get", "ProcessId,CommandLine", "/format:csv"])
            if rc == 0:
                for line in out.splitlines():
                    if "main_15m_lean" in line:
                        parts = line.split(",")
                        if parts:
                            uvicorn_pids.append({"pid": parts[-1].strip(), "cmdline": line, "connections": []})

        if len(uvicorn_pids) > 1:
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="duplicate_server",
                    description=f"Multiple uvicorn/main_15m_lean processes detected ({len(uvicorn_pids)}). This can cause duplicate orders and fill races.",
                    evidence={"processes": uvicorn_pids},
                )
            )
        elif not uvicorn_pids:
            self.report.add(
                Finding(
                    severity="INFO",
                    layer=layer,
                    category="server_process",
                    description="No uvicorn/main_15m_lean process found.",
                )
            )
        else:
            self.report.add(
                Finding(
                    severity="INFO",
                    layer=layer,
                    category="server_process",
                    description="One uvicorn/main_15m_lean process found.",
                    evidence={"processes": uvicorn_pids},
                )
            )

        listeners_8011 = [p for p in uvicorn_pids if any("8011" in str(c.get("laddr", "")) for c in p.get("connections", []))]
        if len(listeners_8011) > 1:
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="port_8011_race",
                    description="More than one process is listening on port 8011.",
                    evidence={"listeners": listeners_8011},
                )
            )

    # ----------------------------------------------------------------------
    # 3. Git workspace drift
    # ----------------------------------------------------------------------
    def _audit_git_workspace(self) -> None:
        layer = "git_workspace"
        rc, out, _ = _sh(["git", "status", "--porcelain"])
        if rc != 0:
            self.report.add(Finding("LOW", layer, "git", "Could not run git status.", {"error": out}))
            return

        modified: List[str] = []
        untracked: List[str] = []
        deleted: List[str] = []
        for line in out.splitlines():
            if not line:
                continue
            status = line[:2]
            path_ = line[3:].strip()
            if status.startswith("M") or status.endswith("M"):
                modified.append(path_)
            elif status.startswith("??"):
                untracked.append(path_)
            elif status.startswith("D"):
                deleted.append(path_)

        self.report.add(
            Finding(
                severity="INFO",
                layer=layer,
                category="git_status",
                description=f"Workspace has {len(modified)} modified, {len(untracked)} untracked, {len(deleted)} deleted files.",
                evidence={"modified_count": len(modified), "untracked_count": len(untracked), "deleted_count": len(deleted)},
            )
        )

        critical_modified = [p for p in modified if any(p.endswith(cf) or p.replace("\\", "/").endswith(cf) for cf in CRITICAL_SOURCE_FILES)]
        if critical_modified:
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="uncommitted_critical_source",
                    description="Critical trading/execution source files have uncommitted modifications.",
                    evidence={"files": critical_modified[:50]},
                )
            )

        if untracked:
            suspicious = [p for p in untracked if "/tmp" in p.replace("\\", "/") or p.startswith("tmp_") or p.endswith("_live.py") or "order" in p.lower()]
            if suspicious:
                self.report.add(
                    Finding(
                        severity="HIGH",
                        layer=layer,
                        category="untracked_suspicious_files",
                        description="Untracked temporary or order-related files present.",
                        evidence={"files": suspicious[:50]},
                    )
                )

    # ----------------------------------------------------------------------
    # 4. Temporary / ad-hoc scripts
    # ----------------------------------------------------------------------
    def _audit_tmp_scripts(self) -> None:
        layer = "tmp_scripts"
        order_placement_indicators = [
            re.compile(r"place-order|portfolio/events/orders|portfolio/orders", re.I),
            re.compile(r"client\._request_with_resilience.*orders|urllib\.request.*orders", re.I),
        ]

        risky: List[Dict[str, str]] = []
        for path in REPO_ROOT.glob("tmp_*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in order_placement_indicators:
                if pat.search(text):
                    risky.append({"file": str(path.relative_to(REPO_ROOT)), "size": path.stat().st_size})
                    break

        for path in (REPO_ROOT / "tmp").glob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pat in order_placement_indicators:
                if pat.search(text):
                    risky.append({"file": str(path.relative_to(REPO_ROOT)), "size": path.stat().st_size})
                    break

        if risky:
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="ad_hoc_order_scripts",
                    description="Ad-hoc Python scripts that can place orders are present and untracked.",
                    evidence={"scripts": risky},
                )
            )

    # ----------------------------------------------------------------------
    # 5. Data files (kill switch, watermark, audit chain)
    # ----------------------------------------------------------------------
    def _audit_data_files(self) -> None:
        layer = "data_files"

        kill_switch = DATA_DIR / "risk_kill_switch.json"
        if kill_switch.exists():
            try:
                data = json.loads(kill_switch.read_text(encoding="utf-8"))
                if data.get("active"):
                    self.report.add(
                        Finding(
                            severity="CRITICAL",
                            layer=layer,
                            category="kill_switch",
                            description="data/risk_kill_switch.json is active=true.",
                            evidence=data,
                        )
                    )
                else:
                    self.report.add(Finding("INFO", layer, "kill_switch", "risk_kill_switch.json is not active.", data))
            except Exception as e:  # noqa: BLE001
                self.report.add(Finding("LOW", layer, "kill_switch", f"Failed to parse risk_kill_switch.json: {e}"))

        watermark = DATA_DIR / "trading_circuit_breaker_http_watermark.json"
        if watermark.exists():
            try:
                data = json.loads(watermark.read_text(encoding="utf-8"))
                self.report.add(Finding("INFO", layer, "circuit_breaker_watermark", "Circuit breaker HTTP watermark present.", data))
            except Exception as e:  # noqa: BLE001
                self.report.add(Finding("LOW", layer, "circuit_breaker_watermark", f"Failed to parse watermark: {e}"))

        audit_chain = DATA_DIR / "risk_audit_chain.jsonl"
        if audit_chain.exists():
            recent_halt_reasons = []
            try:
                with audit_chain.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            rec = json.loads(line)
                        except Exception:
                            continue
                        if rec.get("type") in ("trading_halt", "trading_halt_released", "kill_switch_activated"):
                            recent_halt_reasons.append(rec)
                if recent_halt_reasons:
                    self.report.add(
                        Finding(
                            severity="HIGH" if not any(r.get("type") == "trading_halt_released" for r in recent_halt_reasons[-5:]) else "INFO",
                            layer=layer,
                            category="risk_audit_chain",
                            description=f"Found {len(recent_halt_reasons)} halt/kill events in risk_audit_chain.jsonl.",
                            evidence={"recent": recent_halt_reasons[-10:]},
                        )
                    )
            except Exception as e:  # noqa: BLE001
                self.report.add(Finding("LOW", layer, "risk_audit_chain", f"Failed to read risk_audit_chain.jsonl: {e}"))

    # ----------------------------------------------------------------------
    # 6. Log scan
    # ----------------------------------------------------------------------
    def _audit_logs(self) -> None:
        layer = "logs"
        if not LOG_DIR.exists():
            self.report.add(Finding("LOW", layer, "log_dir", f"Log directory not found: {LOG_DIR}"))
            return

        # Select log files modified in the last 48 hours, plus full.log*
        now = time.time()
        files: List[Path] = []
        for pattern in ["full.log*", "live_*.log*", "*.log"]:
            for path in LOG_DIR.glob(pattern):
                if path.is_file() and (now - path.stat().st_mtime < 48 * 3600 or "full.log" in path.name):
                    files.append(path)

        if not files:
            self.report.add(Finding("LOW", layer, "log_files", "No recent log files found."))
            return

        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        pattern_counts: Counter = Counter()
        pattern_examples: Dict[str, List[str]] = defaultdict(list)
        lifecycle_mismatches: List[Dict[str, Any]] = []
        reconciliation_mismatches: int = 0
        slippage_events: List[Dict[str, Any]] = []

        for log_path in files[:2]:  # scan the two most recent files to bound runtime
            try:
                # Read only the last self.log_tail lines to bound time/memory.
                from collections import deque

                tail: deque = deque(maxlen=self.log_tail)
                with log_path.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        tail.append(line)

                for line in tail:
                    for name, pat in LOG_PATTERN_REGEXES.items():
                        if pat.search(line):
                            pattern_counts[name] += 1
                            if len(pattern_examples[name]) < 3:
                                pattern_examples[name].append(line.strip()[:500])

                    # Order-lifecycle unit mismatch detection
                    if "[ORDER-LIFECYCLE]" in line:
                        self._parse_order_lifecycle(line, lifecycle_mismatches)

                    if "reconciliation_status=mismatch" in line:
                        reconciliation_mismatches += 1

                    if "slippage=" in line and "EXECUTION-FEEDBACK" in line:
                        self._parse_slippage(line, slippage_events)
            except Exception as e:  # noqa: BLE001
                self.report.add(Finding("LOW", layer, "log_read", f"Failed to read {log_path.name}: {e}"))

        # Surface the pattern scan
        for name, count in pattern_counts.most_common():
            sev = "CRITICAL" if name in ("TRADING_CIRCUIT_BREAKER_HALT", "reconciliation_halted", "UNMATCHED_FILL", "STOP-CANDIDATE-NOT-SUBMITTED", "PositionCache.reset") else "HIGH"
            if name in ("CRITICAL", "WRONG-DIRECTION-POSITION-CHANGE", "IS-EXIT-HINT-MISMATCH", "reconciliation_status_mismatch"):
                sev = "CRITICAL"
            if name in ("slippage", "FILL-SIDE-FORM-MATCH"):
                sev = "MEDIUM"
            self.report.add(
                Finding(
                    severity=sev,
                    layer=layer,
                    category=f"log_pattern:{name}",
                    description=f"Detected {count} occurrences of '{name}' in recent logs.",
                    evidence={"count": count, "examples": pattern_examples.get(name, [])},
                )
            )

        if lifecycle_mismatches:
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="order_lifecycle_unit_mismatch",
                    description=f"Found {len(lifecycle_mismatches)} ORDER-LIFECYCLE records where expected/actual position mismatch by 100x (contracts vs centi-contracts).",
                    evidence={"examples": lifecycle_mismatches[:10]},
                )
            )

        if reconciliation_mismatches:
            self.report.add(
                Finding(
                    severity="CRITICAL",
                    layer=layer,
                    category="exposure_reconciliation_mismatch",
                    description=f"Found {reconciliation_mismatches} exposure reconciliation_status=mismatch lines.",
                    evidence={"count": reconciliation_mismatches},
                )
            )

        if slippage_events:
            bad = [s for s in slippage_events if s.get("slippage_cents", 0) > 5]
            if bad:
                self.report.add(
                    Finding(
                        severity="HIGH",
                        layer=layer,
                        category="execution_slippage",
                        description=f"Found {len(bad)} fills with >5c slippage (may use wrong side price).",
                        evidence={"examples": bad[:10]},
                    )
                )

    def _parse_order_lifecycle(self, line: str, out: List[Dict[str, Any]]) -> None:
        try:
            marker = "[ORDER-LIFECYCLE] "
            idx = line.find(marker)
            if idx < 0:
                return
            # The log line is a JSON envelope; parse it and extract the message field.
            outer = json.loads(line)
            msg_text = outer.get("message", "")
            if not msg_text.startswith(marker):
                return
            payload = msg_text[len(marker) :].strip()
            if payload.startswith("["):
                # Some versions wrap the dict in a list; drop the list.
                payload = payload[1:-1] if payload.endswith("]") else payload
            rec = json.loads(payload)
            msg = rec[0] if isinstance(rec, list) else rec
            if not isinstance(msg, dict):
                return
            pre = msg.get("pre_position_yes")
            exp = msg.get("post_position_yes_expected")
            actual = msg.get("post_position_yes_actual")
            delta = msg.get("normalized_yes_delta")
            if pre is not None and exp is not None and actual is not None:
                # Convert all to Decimal for comparison
                from decimal import Decimal

                pre_d = Decimal(str(pre))
                delta_d = Decimal(str(delta)) if delta is not None else Decimal(0)
                exp_d = Decimal(str(exp))
                act_d = Decimal(str(actual))
                # A centi-contract vs contract mix is a 100x difference.
                if abs(exp_d) > 0 and abs(act_d) > 0 and (abs(exp_d) / abs(act_d) >= 10 or abs(act_d) / abs(exp_d) >= 10):
                    out.append({
                        "ticker": msg.get("ticker"),
                        "pre": pre,
                        "delta": delta,
                        "expected": exp,
                        "actual": actual,
                        "client_order_id": msg.get("client_order_id"),
                    })
        except Exception:  # noqa: BLE001
            return

    def _parse_slippage(self, line: str, out: List[Dict[str, Any]]) -> None:
        try:
            m = re.search(r"intended=(\d+)c\s+fill=(\d+)c\s+slippage=(\d+)c", line)
            if m:
                out.append({
                    "intended_cents": int(m.group(1)),
                    "fill_cents": int(m.group(2)),
                    "slippage_cents": int(m.group(3)),
                    "line": line.strip()[:300],
                })
        except Exception:  # noqa: BLE001
            return

    # ----------------------------------------------------------------------
    # 7. Static code heuristics
    # ----------------------------------------------------------------------
    def _audit_static_code(self) -> None:
        layer = "static_code"
        paths: List[Path] = []
        scan_roots = [
            REPO_ROOT / "merid" / "event_venues" / "kalshi",
            REPO_ROOT / "merid" / "prediction",
            REPO_ROOT / "merid" / "risk",
            REPO_ROOT / "merid" / "position_management",
            REPO_ROOT / "merid" / "governance",
            REPO_ROOT / "merid" / "data",
            REPO_ROOT / "merid" / "startup_validations.py",
            REPO_ROOT / "merid" / "settings.py",
            REPO_ROOT / "web" / "main_15m_lean.py",
            REPO_ROOT / "web" / "api",
        ]
        for root in scan_roots:
            if root.is_file():
                paths.append(root)
                continue
            if not root.exists():
                continue
            for p in root.rglob("*.py"):
                rel = p.relative_to(REPO_ROOT).as_posix()
                if "test" in p.parts or "tests" in p.parts or p.name.startswith("test_"):
                    continue
                if rel.startswith("scripts/"):
                    continue
                paths.append(p)

        # Always include the canonical critical files if we missed them.
        for cf in CRITICAL_SOURCE_FILES:
            cp = REPO_ROOT / cf
            if cp.exists() and cp not in paths:
                paths.append(cp)

        findings: Dict[str, List[Tuple[str, int, str]]] = defaultdict(list)
        for p in paths:
            rel = p.relative_to(REPO_ROOT).as_posix()
            try:
                with p.open("r", encoding="utf-8", errors="ignore") as f:
                    for lineno, line in enumerate(f, 1):
                        for name, pat in STATIC_CODE_REGEXES.items():
                            if pat.search(line):
                                if name == "float_for_money" and not any(k in line for k in ("price", "fee", "pnl", "notional", "cost", "usd", "dollars")):
                                    continue
                                findings[name].append((rel, lineno, line.strip()[:200]))
            except Exception:  # noqa: BLE001
                continue

        # Surface only the most dangerous patterns
        severity_map = {
            "position_cache_reset": "CRITICAL",
            "except_exception_pass": "HIGH",
            "float_for_money": "HIGH",
            "int_fee_times_100": "CRITICAL",
            "round_decimal": "MEDIUM",
            "OrderResult.success": "HIGH",
            "apply_fill_not_once": "CRITICAL",
            "reduce_only_false": "MEDIUM",
            "allow_short": "HIGH",
            "manual_emergency_close": "MEDIUM",
            "circuit_breaker_resume": "CRITICAL",
            "direct_execution_bypass": "HIGH",
            "unprotected_entries": "CRITICAL",
            "circuit_breaker_disabled": "CRITICAL",
            "dev_allow_ws": "MEDIUM",
            "single_user_operator": "CRITICAL",
            "pytest_current_test": "HIGH",
            "while_true": "LOW",
            "asyncio_gather_no_timeout": "MEDIUM",
            "sleep_in_async": "MEDIUM",
            "raw_post_orders": "HIGH",
            "observe_only_true": "HIGH",
            "require_exit_parentage_false": "HIGH",
        }

        for name, matches in findings.items():
            sev = severity_map.get(name, "MEDIUM")
            # Show up to 5 examples
            examples = [{"file": f, "line": ln, "snippet": snip} for f, ln, snip in matches[:5]]
            self.report.add(
                Finding(
                    severity=sev,
                    layer=layer,
                    category=f"static:{name}",
                    description=f"Detected {len(matches)} occurrences of '{name}' in source code.",
                    evidence={"count": len(matches), "examples": examples},
                )
            )

    # ----------------------------------------------------------------------
    # 8. Network endpoint checks (optional, GET-only)
    # ----------------------------------------------------------------------
    def _audit_network_endpoints(self) -> None:
        layer = "network"
        base = "http://127.0.0.1:8011"

        def get_json(endpoint: str) -> Optional[Dict[str, Any]]:
            url = base + endpoint
            try:
                if requests is not None:
                    r = requests.get(url, timeout=10)
                    if r.status_code == 200:
                        return r.json()
                    return {"status_code": r.status_code, "text": r.text[:500]}
                else:
                    import urllib.request

                    with urllib.request.urlopen(url, timeout=10) as resp:
                        return json.loads(resp.read().decode("utf-8"))
            except Exception as e:  # noqa: BLE001
                return {"error": str(e)}

        health = get_json("/api/v1/health")
        self.report.add(Finding("INFO", layer, "health", f"Health endpoint {base}/api/v1/health response.", health or {}))

        positions = get_json("/api/v1/positions")
        if isinstance(positions, dict):
            open_positions = positions.get("positions") or positions.get("data") or []
            self.report.add(
                Finding(
                    severity="INFO",
                    layer=layer,
                    category="positions",
                    description=f"Open positions snapshot returned {len(open_positions) if isinstance(open_positions, list) else '?'} entries.",
                    evidence=positions,
                )
            )

        orders = get_json("/api/v1/orders/open")
        if isinstance(orders, dict):
            open_orders = orders.get("orders") or orders.get("data") or []
            self.report.add(
                Finding(
                    severity="INFO",
                    layer=layer,
                    category="open_orders",
                    description=f"Open orders snapshot returned {len(open_orders) if isinstance(open_orders, list) else '?'} entries.",
                    evidence=orders,
                )
            )

    # ----------------------------------------------------------------------
    # 9. Targeted tests (optional)
    # ----------------------------------------------------------------------
    def _run_targeted_tests(self) -> None:
        layer = "tests"
        test_files = [
            "tests/test_order_router_ioc_tif_reconciliation.py",
            "tests/kalshi_alignment/test_order_router.py",
            "tests/event_venues/kalshi/test_port_ledger_adapter.py",
            "tests/event_venues/kalshi/test_kalshi_p0_partial_fill_reconciliation.py",
            "tests/event_venues/kalshi/test_kalshi_p0_maker_taker_simulator.py",
            "tests/event_venues/kalshi/test_kalshi_p0_exit_order_simulator.py",
            "tests/test_loop_15m_bugfixes.py",
            "tests/test_canonical_exposure_reconciliation.py",
            "tests/test_fills_ledger_v2_side_action_fix.py",
            "tests/test_fills_ledger_v2_fractional_replay.py",
            "tests/position_management/test_position_monitor.py",
            "tests/position_management/test_position_monitor_exit_audit.py",
            "tests/position_management/test_spread_stop_provenance.py",
            "tests/event_venues/kalshi/test_execution_risk_firewall.py",
            "tests/event_venues/kalshi/test_kalshi_order_manager.py",
            "tests/test_direct_venue_submission_guard.py",
            "tests/test_production_startup_validation.py",
            "tests/test_trade_decision_release_gates.py",
            "tests/test_cf_rti_adapter.py",
        ]
        cmd = ["python", "-m", "pytest"] + test_files + ["-q"]
        rc, out, err = _sh(cmd, cwd=REPO_ROOT, timeout=600)
        self.report.add(
            Finding(
                severity="INFO" if rc == 0 else "CRITICAL",
                layer=layer,
                category="targeted_tests",
                description=f"Targeted pytest suite exited {rc}.",
                evidence={"returncode": rc, "stdout": out[-2000:], "stderr": err[-2000:]},
            )
        )

    # ----------------------------------------------------------------------
    # 10. Summary
    # ----------------------------------------------------------------------
    def _build_summary(self) -> None:
        counts = self.report.by_severity()
        self.report.summary = {
            "total_findings": len(self.report.findings),
            "by_severity": dict(counts),
            "top_critical_layers": [
                {"layer": layer, "count": count}
                for layer, count in Counter(f.layer for f in self.report.findings if f.severity == "CRITICAL").most_common(10)
            ],
            "recommendations": self._recommendations(),
        }

    def _recommendations(self) -> List[str]:
        recs = []
        sev_set = {f.category for f in self.report.findings if f.severity == "CRITICAL"}
        if "duplicate_server" in sev_set or "port_8011_race" in sev_set:
            recs.append("Stop all but one uvicorn/main_15m_lean process immediately; duplicate server instances can place duplicate orders.")
        if "live_trading_latch" in sev_set:
            recs.append("Re-evaluate whether live trading should be enabled while debugging; set MERID_ALLOW_LIVE_TRADES=false and MERID_PM_TRADING_MODE=paper.")
        if "ad_hoc_order_scripts" in {f.category for f in self.report.findings}:
            recs.append("Delete or quarantine untracked order-placement scripts (tmp_*.py) before continuing.")
        if "uncommitted_critical_source" in {f.category for f in self.report.findings}:
            recs.append("Commit or revert unmodified critical trading source files; do not run live with uncommitted execution changes.")
        if "order_lifecycle_unit_mismatch" in {f.category for f in self.report.findings}:
            recs.append("Fix post_position_yes_actual in position_cache to use quantity_cc, not contracts; the invariant is failing silently.")
        if "exposure_reconciliation_mismatch" in {f.category for f in self.report.findings}:
            recs.append("Halt new entries and perform a three-way exchange/ledger/cache reconciliation before resuming trading.")
        if not recs:
            recs.append("No immediate CRITICAL findings. Continue monitoring and run canary paper cycles before scaling.")
        return recs


def _format_markdown(report: Report) -> str:
    lines = [
        "# MERID High-Leverage Bug Exposure Audit",
        f"**Scan time:** {report.scan_timestamp}",
        f"**Repo:** `{report.repo_root}`",
        "",
        "## Summary",
        "",
        f"- Total findings: {len(report.findings)}",
    ]
    counts = report.by_severity()
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        if counts[sev]:
            lines.append(f"- {sev}: {counts[sev]}")
    lines.append("")
    lines.append("## Immediate Recommendations")
    lines.append("")
    for rec in report.summary.get("recommendations", []):
        lines.append(f"- {rec}")
    lines.append("")
    lines.append("## Findings")
    lines.append("")
    for f in report.findings:
        file_tag = f" `{f.file}`" if f.file else ""
        line_tag = f" line {f.line}" if f.line else ""
        lines.append(f"### [{f.severity}] {f.layer} / {f.category}")
        lines.append(f"{f.description}{file_tag}{line_tag}")
        if f.evidence:
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(f.evidence, indent=2, default=str)[:1500])
            lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=REPO_ROOT, help="Directory for report files")
    parser.add_argument("--network", action="store_true", help="Query read-only localhost endpoints")
    parser.add_argument("--run-tests", action="store_true", help="Run targeted pytest suite (slow)")
    parser.add_argument("--log-tail", type=int, default=50_000, help="Max lines to tail from each log")
    args = parser.parse_args()

    auditor = HighLeverageBugAuditor(network=args.network, run_tests=args.run_tests, log_tail=args.log_tail)
    report = auditor.run()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"high_leverage_bug_exposure_{timestamp}.json"
    md_path = args.output_dir / f"high_leverage_bug_exposure_{timestamp}.md"

    json_path.write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    md_path.write_text(_format_markdown(report), encoding="utf-8")

    # Console summary (no secrets, no huge evidence dumps)
    counts = report.by_severity()
    print(f"MERID high-leverage audit complete: {json_path}")
    print(f"Total findings: {len(report.findings)}")
    for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
        if counts[sev]:
            print(f"  {sev}: {counts[sev]}")
    print("\nTop recommendations:")
    for rec in report.summary.get("recommendations", [])[:5]:
        print(f"  - {rec}")
    print(f"\nFull report: {md_path}")
    return 0 if counts["CRITICAL"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
