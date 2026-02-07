"""
MERID Demo Runner — scripted walkthrough for new operators.

Runs a guided simulation scenario with commentary, demonstrating:
1. System startup and health checks
2. Agent registration and capability discovery
3. Market data ingestion with contract validation
4. Trade proposal generation and risk gating
5. Consensus voting and decision explanation
6. Circuit breaker and kill switch demonstration
7. Audit trail verification

Usage:
    python -m core.demo_runner
    python -m core.demo_runner --fast   # skip delays
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Optional

from utils.logger import get_logger

logger = get_logger("core.demo_runner")

# ANSI colors for terminal output
_CYAN = "\033[96m"
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _banner(text: str) -> None:
    width = max(len(text) + 4, 60)
    print(f"\n{_CYAN}{'═' * width}")
    print(f"  {_BOLD}{text}{_RESET}{_CYAN}")
    print(f"{'═' * width}{_RESET}\n")


def _step(num: int, title: str) -> None:
    print(f"{_GREEN}[Step {num}]{_RESET} {_BOLD}{title}{_RESET}")


def _info(msg: str) -> None:
    print(f"  {msg}")


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠{_RESET} {msg}")


def _pause(seconds: float, fast: bool) -> None:
    if not fast:
        time.sleep(seconds)


def run_demo(fast: bool = False) -> None:
    """Run the full MERID demo scenario."""

    _banner("MERID Trading System — Guided Demo")
    _info("This demo walks through a simulated trading cycle.")
    _info("All actions run in SIMULATION mode — no real orders are placed.\n")
    _pause(1.5, fast)

    # ── Step 1: System Health ──────────────────────────────────────
    _step(1, "System Health Check")
    try:
        from core.health_monitor import get_health_monitor
        monitor = get_health_monitor()
        _ok(f"Health monitor initialized — {len(getattr(monitor, '_components', {}))} components tracked")
    except Exception as exc:
        _warn(f"Health monitor not available: {exc}")
    _pause(1, fast)

    # ── Step 2: Agent Registry ─────────────────────────────────────
    _step(2, "Agent Capability Discovery")
    try:
        import yaml
        from pathlib import Path
        manifest_path = Path(__file__).parent.parent / "config" / "agent_manifest.yml"
        if manifest_path.exists():
            with open(manifest_path) as f:
                manifest = yaml.safe_load(f)
            agents = manifest.get("agents", {})
            _ok(f"Loaded {len(agents)} agents from agent_manifest.yml")
            for name, cfg in list(agents.items())[:5]:
                caps = ", ".join(cfg.get("capabilities", [])[:3])
                _info(f"  • {name} ({cfg.get('role', '?')}) — {caps}")
            if len(agents) > 5:
                _info(f"  … and {len(agents) - 5} more")
        else:
            _warn("agent_manifest.yml not found")
    except Exception as exc:
        _warn(f"Agent manifest load error: {exc}")
    _pause(1, fast)

    # ── Step 3: Data Contract Validation ───────────────────────────
    _step(3, "Market Data Ingestion + Contract Validation")
    try:
        from core.data_contracts import get_data_contract_registry
        registry = get_data_contract_registry()
        contracts = registry.list_contracts()
        _ok(f"{len(contracts)} data contracts registered")

        # Simulate a valid tick
        sample = {"price": 50123.45, "volume": 1234.5, "timestamp": time.time(), "symbol": "BTC/USDT"}
        result = registry.validate("binance", sample)
        if result.valid:
            _ok("Sample BTC/USDT tick passed binance contract validation")
        else:
            _warn(f"Validation failed: {result.errors}")

        # Simulate a bad tick
        bad = {"volume": -1.0, "timestamp": time.time()}
        bad_result = registry.validate("binance", bad)
        if not bad_result.valid:
            _ok(f"Bad tick correctly rejected: {bad_result.errors[0]}")
    except Exception as exc:
        _warn(f"Data contract error: {exc}")
    _pause(1, fast)

    # ── Step 4: Risk Gating ────────────────────────────────────────
    _step(4, "Risk Limit Enforcement")
    try:
        from core.order_sanity_check import get_order_sanity_checker
        checker = get_order_sanity_checker()
        # Good order
        good = checker.check(symbol="BTC/USDT", quantity=0.01, price=50000, portfolio_value=100000, side="buy")
        if good.passed:
            _ok("Small BTC order (0.01 @ $50K) passed sanity check")
        # Oversized order
        big = checker.check(symbol="BTC/USDT", quantity=100, price=50000, portfolio_value=100000, side="buy")
        if not big.passed:
            _ok(f"Oversized order correctly blocked: {big.violations[0]['message']}")
    except Exception as exc:
        _warn(f"Sanity checker error: {exc}")
    _pause(1, fast)

    # ── Step 5: Trading Halt ───────────────────────────────────────
    _step(5, "Circuit Breaker & Trading Halt")
    try:
        from core.automated_risk_controls import TradingHaltManager
        halt_mgr = TradingHaltManager()
        _ok(f"Trading halt manager: halted={halt_mgr.is_halted}")

        halt_mgr.halt("demo: simulated drawdown breach")
        _ok(f"Halt triggered — is_halted={halt_mgr.is_halted}")

        halt_mgr.resume("demo: breach cleared")
        _ok(f"Resumed — is_halted={halt_mgr.is_halted}")
    except Exception as exc:
        _warn(f"Halt manager error: {exc}")
    _pause(1, fast)

    # ── Step 6: Audit Trail ────────────────────────────────────────
    _step(6, "Audit Trail Integrity")
    try:
        from core.audit_trail import AuditTrail
        trail = AuditTrail(storage_path="data/demo_audit")
        _ok(f"Audit trail: {len(trail.entries)} entries, chain valid={trail.verify_chain()}")
        _ok(f"Order index keys: {len(trail._order_index)}")
    except Exception as exc:
        _warn(f"Audit trail error: {exc}")
    _pause(1, fast)

    # ── Step 7: Readiness Score ────────────────────────────────────
    _step(7, "Readiness Score")
    try:
        from core.merid_readiness_score import aggregate_scores, readiness_level
        total, maximum = aggregate_scores()
        pct = total / maximum * 100 if maximum else 0
        level = readiness_level()
        _ok(f"Readiness: {total}/{maximum} ({pct:.0f}%) — {level}")
    except Exception as exc:
        _warn(f"Readiness score error: {exc}")

    # ── Done ───────────────────────────────────────────────────────
    _banner("Demo Complete")
    _info("All steps ran in SIMULATION mode. No real orders were placed.")
    _info("Next steps:")
    _info("  • Run full test suite:  make test")
    _info("  • Start API server:     make run")
    _info("  • View operator dashboard: http://localhost:8000/dashboard")
    _info("  • Read onboarding guide:   docs/GETTING_STARTED.md\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="MERID Demo Runner")
    parser.add_argument("--fast", action="store_true", help="Skip delays between steps")
    args = parser.parse_args()
    run_demo(fast=args.fast)


if __name__ == "__main__":
    main()
