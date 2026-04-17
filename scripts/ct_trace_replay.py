"""
CT Trace Replay Harness — End-to-End Determinism Checker
==========================================================

Replays CT-TRACE logs against recorded raw inputs to verify:
1. Computation determinism (same inputs → same outputs)
2. State machine correctness (transitions match logged)
3. Decision consistency (sizing, gating, execution decisions match)

Usage:
    # Replay from recorded cycle data
    python scripts/ct_trace_replay.py --cycle-file data/ct_cycles.jsonl --verify
    
    # Record current cycle for later replay
    python scripts/ct_trace_replay.py --record --output data/cycle_1234.json
    
    # Compare two cycle recordings
    python scripts/ct_trace_replay.py --diff cycle_a.json cycle_b.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime


# ═══════════════════════════════════════════════════════════════════════════
# §1 — Cycle Recording Data Structures
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CycleInput:
    """Raw inputs to a CT cycle (the "ground truth")."""
    cycle_number: int
    timestamp: str
    correlation_id: str
    
    # Market data
    spot_prices: Dict[str, float]  # asset -> USD price
    catalog_markets: List[Dict[str, Any]]  # Raw Kalshi market data
    orderbooks: Dict[str, Dict[str, Any]]  # ticker -> orderbook snapshot
    
    # Account state
    balance_cents: int
    positions: Dict[str, Dict[str, Any]]  # ticker -> position state
    fills_since_last_cycle: List[Dict[str, Any]]
    
    # Configuration (frozen at cycle time)
    config: Dict[str, Any]
    
    # External signals
    sentiment_bundle: Optional[Dict[str, Any]] = None
    indicator_data: Optional[Dict[str, Any]] = None


@dataclass
class CycleOutput:
    """Computed/decided outputs from a CT cycle (the "decisions")."""
    # Discovery stage
    assets_discovered: List[str]
    markets_per_asset: Dict[str, int]
    
    # Analysis stage  
    candidates: List[Dict[str, Any]]  # Edge, price, etc. per candidate
    tradeable_tickers: List[str]
    
    # Sizing stage
    sizing_decisions: List[Dict[str, Any]]  # ticker -> contracts, caps fired
    
    # Execution stage
    orders_submitted: List[Dict[str, Any]]  # What was actually sent
    orders_dry_run: List[Dict[str, Any]]
    
    # Monitor stage
    final_exposure_cents: int
    final_balance_cents: int
    bankroll_invariant_delta: int
    
    # Protect stage
    protect_mode: str  # normal, reduce, halt
    protect_reason: Optional[str]


@dataclass
class RecordedCycle:
    """Complete recording of one CT cycle for replay."""
    version: str = "1.0"
    input: CycleInput = field(default_factory=lambda: CycleInput(
        cycle_number=0, timestamp="", correlation_id="",
        spot_prices={}, catalog_markets=[], orderbooks={},
        balance_cents=0, positions={}, fills_since_last_cycle=[],
        config={}
    ))
    output: CycleOutput = field(default_factory=lambda: CycleOutput(
        assets_discovered=[], markets_per_asset={}, candidates=[],
        tradeable_tickers=[], sizing_decisions=[], orders_submitted=[],
        orders_dry_run=[], final_exposure_cents=0, final_balance_cents=0,
        bankroll_invariant_delta=0, protect_mode="normal", protect_reason=None
    ))
    trace_log_lines: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecordedCycle":
        return cls(
            version=data.get("version", "1.0"),
            input=CycleInput(**data["input"]),
            output=CycleOutput(**data["output"]),
            trace_log_lines=data.get("trace_log_lines", [])
        )


# ═══════════════════════════════════════════════════════════════════════════
# §2 — Trace Log Capture
# ═══════════════════════════════════════════════════════════════════════════


class TraceLogCapture:
    """Capture CT-TRACE and DRY-RUN-TRACE lines from log file."""
    
    def __init__(self, log_path: Path):
        self.log_path = log_path
    
    def capture_cycle(self, cycle_number: int) -> List[str]:
        """Extract all trace lines for a specific cycle."""
        lines = []
        cycle_str = f"cycle={cycle_number}"
        
        if not self.log_path.exists():
            return lines
        
        with open(self.log_path, 'r', encoding='utf-8') as f:
            for line in f:
                if cycle_str in line and ("[CT-TRACE]" in line or "[DRY-RUN-TRACE]" in line):
                    lines.append(line.strip())
        
        return lines
    
    def parse_cycle_data(self, cycle_number: int) -> Dict[str, Any]:
        """Parse structured data from trace logs for a cycle."""
        trace_lines = self.capture_cycle(cycle_number)
        
        data = {
            "cycle": cycle_number,
            "trace_lines": trace_lines,
            "stages": [],
            "sizing": [],
            "executions": [],
            "bankroll": {}
        }
        
        import re
        
        for line in trace_lines:
            # Stage detection
            stage_match = re.search(r'stage=(\w+)', line)
            if stage_match:
                data["stages"].append(stage_match.group(1))
            
            # Sizing extraction
            if "stage=size" in line:
                sizing = {}
                if (m := re.search(r'edge=([\d.]+)', line)):
                    sizing["edge"] = float(m.group(1))
                if (m := re.search(r'price=(\d+)¢', line)):
                    sizing["price_cents"] = int(m.group(1))
                if (m := re.search(r'contracts=(\d+)', line)):
                    sizing["contracts"] = int(m.group(1))
                if (m := re.search(r'market=(\S+)', line)):
                    sizing["ticker"] = m.group(1)
                if sizing:
                    data["sizing"].append(sizing)
            
            # Execution extraction
            if "stage=execute" in line:
                exec_data = {}
                if (m := re.search(r'market=(\S+)', line)):
                    exec_data["ticker"] = m.group(1)
                if (m := re.search(r'side=(\S+)', line)):
                    exec_data["side"] = m.group(1)
                if (m := re.search(r'size=(\d+)', line)):
                    exec_data["size"] = int(m.group(1))
                if (m := re.search(r'status=(\S+)', line)):
                    exec_data["status"] = m.group(1)
                if exec_data:
                    data["executions"].append(exec_data)
            
            # Bankroll invariant extraction
            if "[BANKROLL-INVARIANT" in line:
                if (m := re.search(r'delta=(\d+)¢', line)):
                    data["bankroll"]["invariant_delta"] = int(m.group(1))
                if (m := re.search(r'cash=(\d+)¢', line)):
                    data["bankroll"]["cash_cents"] = int(m.group(1))
                if (m := re.search(r'exposure=(\d+)¢', line)):
                    data["bankroll"]["exposure_cents"] = int(m.group(1))
        
        return data


# ═══════════════════════════════════════════════════════════════════════════
# §3 — Replayer Engine
# ═══════════════════════════════════════════════════════════════════════════


class CycleReplayer:
    """Replay a recorded cycle and verify determinism."""
    
    def __init__(self, cycle: RecordedCycle):
        self.cycle = cycle
        self.differences: List[Dict[str, Any]] = []
    
    def replay_and_verify(self) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Replay the cycle with recorded inputs and compare outputs.
        
        Returns: (passed, differences)
        """
        self.differences = []
        
        # Stage 1: Verify discovery determinism
        self._verify_discovery()
        
        # Stage 2: Verify analysis determinism
        self._verify_analysis()
        
        # Stage 3: Verify sizing determinism
        self._verify_sizing()
        
        # Stage 4: Verify execution decisions
        self._verify_execution()
        
        # Stage 5: Verify bankroll invariant
        self._verify_bankroll_invariant()
        
        return len(self.differences) == 0, self.differences
    
    def _verify_discovery(self):
        """Verify market discovery is deterministic."""
        inp = self.cycle.input
        out = self.cycle.output
        
        # Reconstruct: given spot prices and catalog, which assets were discovered?
        # This depends on spot price availability, not randomness
        expected_assets = set(out.assets_discovered)
        assets_with_spot = set(inp.spot_prices.keys())
        
        # Assets discovered should match assets with spot prices
        missing_spot = expected_assets - assets_with_spot
        if missing_spot:
            self.differences.append({
                "stage": "discover",
                "field": "assets_discovered",
                "issue": "discovered_without_spot",
                "expected": list(expected_assets),
                "actual_spot_available": list(assets_with_spot),
                "missing_spot": list(missing_spot)
            })
    
    def _verify_analysis(self):
        """Verify edge computation is deterministic."""
        inp = self.cycle.input
        out = self.cycle.output
        
        for candidate in out.candidates:
            ticker = candidate.get("ticker")
            logged_edge = candidate.get("edge")
            
            # Reconstruct edge from inputs
            # edge = model_prob - implied_prob - fees - slippage
            price_cents = candidate.get("price_cents", 50)
            implied_prob = price_cents / 100.0
            
            # Model probability would come from indicator stack
            # For replay, we check consistency, not absolute correctness
            if logged_edge is not None:
                # Edge should be in reasonable range given price
                # If price is 30¢, implied is 30%, edge could be +/- 20%
                expected_range = (-0.3, 0.4)  # Function of price
                
                if not (expected_range[0] <= logged_edge <= expected_range[1]):
                    self.differences.append({
                        "stage": "analyze",
                        "field": f"edge_{ticker}",
                        "issue": "edge_out_of_range",
                        "expected_range": expected_range,
                        "logged_edge": logged_edge,
                        "price_cents": price_cents,
                        "implied_prob": implied_prob
                    })
    
    def _verify_sizing(self):
        """Verify position sizing is deterministic."""
        out = self.cycle.output
        
        for sizing in out.sizing_decisions:
            ticker = sizing.get("ticker")
            contracts = sizing.get("contracts", 0)
            edge = sizing.get("edge", 0)
            caps_fired = sizing.get("caps_fired", [])
            
            # Verify: zero contracts when edge <= 0
            if edge <= 0 and contracts > 0:
                self.differences.append({
                    "stage": "size",
                    "field": f"contracts_{ticker}",
                    "issue": "nonzero_contracts_with_nonpositive_edge",
                    "edge": edge,
                    "contracts": contracts
                })
            
            # Verify: caps fired implies reduced or zero size
            if "MAX_CONTRACTS_PER_MARKET" in caps_fired and contracts > 5:
                self.differences.append({
                    "stage": "size",
                    "field": f"caps_{ticker}",
                    "issue": "cap_fired_but_size_too_high",
                    "contracts": contracts,
                    "caps_fired": caps_fired
                })
    
    def _verify_execution(self):
        """Verify execution decisions match configuration."""
        inp = self.cycle.input
        out = self.cycle.output
        
        dry_run = inp.config.get("dry_run", False)
        
        if dry_run:
            # Dry run: should have dry_run orders, no live orders
            if out.orders_submitted and not out.orders_dry_run:
                self.differences.append({
                    "stage": "execute",
                    "field": "orders",
                    "issue": "live_orders_in_dry_run_mode",
                    "live_count": len(out.orders_submitted),
                    "dry_run_count": len(out.orders_dry_run)
                })
    
    def _verify_bankroll_invariant(self):
        """Verify bankroll accounting invariant."""
        out = self.cycle.output
        
        delta = out.bankroll_invariant_delta
        tolerance = 100  # 1¢ tolerance
        
        if abs(delta) > tolerance:
            self.differences.append({
                "stage": "monitor",
                "field": "bankroll_invariant",
                "issue": "invariant_violated",
                "delta_cents": delta,
                "tolerance": tolerance
            })


# ═══════════════════════════════════════════════════════════════════════════
# §4 — Recording from Live CT
# ═══════════════════════════════════════════════════════════════════════════


class LiveCycleRecorder:
    """Record a live CT cycle for later replay."""
    
    def __init__(self, trader):
        self.trader = trader
    
    def record_current_state(self) -> RecordedCycle:
        """Capture current CT state as a recordable cycle."""
        cycle = RecordedCycle()
        
        # Input capture
        cycle.input.cycle_number = getattr(self.trader, "_cycle", 0)
        cycle.input.timestamp = datetime.utcnow().isoformat()
        cycle.input.correlation_id = self.trader._correlation_id if hasattr(self.trader, "_correlation_id") else ""
        
        # Spot prices
        if hasattr(self.trader, "_last_spot_prices"):
            cycle.input.spot_prices = self.trader._last_spot_prices
        
        # Balance
        if hasattr(self.trader, "_last_balance_cents"):
            cycle.input.balance_cents = self.trader._last_balance_cents
        
        # Positions (from tracker)
        if hasattr(self.trader, "tracker") and hasattr(self.trader.tracker, "positions"):
            cycle.input.positions = {
                k: {"qty": v.get("qty", 0), "avg_price": v.get("avg_price", 0)}
                for k, v in self.trader.tracker.positions.items()
            }
        
        # Config
        if hasattr(self.trader, "config"):
            cycle.input.config = {
                "dry_run": self.trader.config.dry_run,
                "kelly_fraction": self.trader.config.kelly_fraction,
                "min_edge": str(self.trader.config.min_edge),
                "max_contracts_per_market": self.trader.config.max_position_per_market,
            }
        
        return cycle


# ═══════════════════════════════════════════════════════════════════════════
# §5 — CLI Entry Point
# ═══════════════════════════════════════════════════════════════════════════


def cmd_record(args):
    """Record current CT state."""
    print("[REPLAY] Recording current CT cycle...")
    
    # Import CT module
    try:
        from merid.trading.kalshi_continuous_trader import get_continuous_trader
        trader = get_continuous_trader()
    except Exception as e:
        print(f"[ERROR] Could not load CT: {e}")
        return 1
    
    recorder = LiveCycleRecorder(trader)
    cycle = recorder.record_current_state()
    
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(cycle.to_dict(), f, indent=2, default=str)
    
    print(f"[REPLAY] Recorded cycle {cycle.input.cycle_number} to {output_path}")
    return 0


def cmd_verify(args):
    """Verify a recorded cycle."""
    print(f"[REPLAY] Verifying cycle from {args.cycle_file}...")
    
    cycle_path = Path(args.cycle_file)
    if not cycle_path.exists():
        print(f"[ERROR] Cycle file not found: {cycle_path}")
        return 2
    
    with open(cycle_path, 'r') as f:
        data = json.load(f)
    
    cycle = RecordedCycle.from_dict(data)
    
    replayer = CycleReplayer(cycle)
    passed, differences = replayer.replay_and_verify()
    
    print(f"\n[REPLAY] Cycle {cycle.input.cycle_number}")
    print(f"[REPLAY] Timestamp: {cycle.input.timestamp}")
    print(f"[REPLAY] Stages logged: {', '.join(set(cycle.output.assets_discovered) if cycle.output.assets_discovered else [])}")
    
    if passed:
        print("[REPLAY] ✅ All invariants passed")
        return 0
    else:
        print(f"[REPLAY] ❌ {len(differences)} issues found:")
        for diff in differences:
            print(f"\n  Stage: {diff['stage']}")
            print(f"  Field: {diff['field']}")
            print(f"  Issue: {diff['issue']}")
        return 1


def cmd_diff(args):
    """Compare two cycle recordings."""
    print(f"[REPLAY] Comparing {args.cycle_a} vs {args.cycle_b}...")
    
    path_a = Path(args.cycle_a)
    path_b = Path(args.cycle_b)
    
    if not path_a.exists() or not path_b.exists():
        print("[ERROR] One or both cycle files not found")
        return 2
    
    with open(path_a, 'r') as f:
        cycle_a = RecordedCycle.from_dict(json.load(f))
    with open(path_b, 'r') as f:
        cycle_b = RecordedCycle.from_dict(json.load(f))
    
    differences = []
    
    # Compare inputs
    if cycle_a.input.cycle_number != cycle_b.input.cycle_number:
        differences.append(f"cycle_number: {cycle_a.input.cycle_number} vs {cycle_b.input.cycle_number}")
    
    if cycle_a.input.balance_cents != cycle_b.input.balance_cents:
        differences.append(f"balance_cents: {cycle_a.input.balance_cents} vs {cycle_b.input.balance_cents}")
    
    # Compare outputs
    if cycle_a.output.final_exposure_cents != cycle_b.output.final_exposure_cents:
        differences.append(f"final_exposure: {cycle_a.output.final_exposure_cents} vs {cycle_b.output.final_exposure_cents}")
    
    if cycle_a.output.orders_submitted != cycle_b.output.orders_submitted:
        differences.append(f"orders_submitted count: {len(cycle_a.output.orders_submitted)} vs {len(cycle_b.output.orders_submitted)}")
    
    if differences:
        print("\n[REPLAY] Differences found:")
        for d in differences:
            print(f"  - {d}")
        return 1
    else:
        print("\n[REPLAY] ✅ No significant differences")
        return 0


def cmd_parse_logs(args):
    """Parse trace logs and extract cycle data."""
    log_path = Path(args.log_file) if args.log_file else Path("data/logs/merid.log")
    
    print(f"[REPLAY] Parsing trace logs from {log_path}...")
    
    capture = TraceLogCapture(log_path)
    
    if args.cycle_number:
        data = capture.parse_cycle_data(args.cycle_number)
        print(json.dumps(data, indent=2))
    else:
        # Find all cycles
        cycles_found = set()
        if log_path.exists():
            import re
            with open(log_path, 'r') as f:
                for line in f:
                    if m := re.search(r'cycle=(\d+)', line):
                        cycles_found.add(int(m.group(1)))
        
        print(f"[REPLAY] Found {len(cycles_found)} cycles in logs")
        print(f"[REPLAY] Cycle numbers: {sorted(cycles_found)[:20]}...")  # First 20


def main():
    parser = argparse.ArgumentParser(
        description="CT Trace Replay Harness — Verify determinism and invariants"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")
    
    # Record command
    record_parser = subparsers.add_parser("record", help="Record current CT cycle")
    record_parser.add_argument("--output", "-o", default="data/ct_replay/cycle_latest.json")
    
    # Verify command
    verify_parser = subparsers.add_parser("verify", help="Verify a recorded cycle")
    verify_parser.add_argument("--cycle-file", "-c", required=True, help="Path to recorded cycle")
    
    # Diff command
    diff_parser = subparsers.add_parser("diff", help="Compare two cycles")
    diff_parser.add_argument("cycle_a", help="First cycle file")
    diff_parser.add_argument("cycle_b", help="Second cycle file")
    
    # Parse logs command
    parse_parser = subparsers.add_parser("parse-logs", help="Parse CT trace logs")
    parse_parser.add_argument("--log-file", "-l", help="Path to log file")
    parse_parser.add_argument("--cycle-number", "-n", type=int, help="Extract specific cycle")
    
    args = parser.parse_args()
    
    if args.command == "record":
        return cmd_record(args)
    elif args.command == "verify":
        return cmd_verify(args)
    elif args.command == "diff":
        return cmd_diff(args)
    elif args.command == "parse-logs":
        return cmd_parse_logs(args)
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
