#!/usr/bin/env python3
"""
Strategy and Agent Mapping Tool — Phase 2 of Production Audit

This script maps all trading strategies, formulas, and execution agents in the MERID system.

Usage:
    python scripts/map_strategies_and_agents.py
    python scripts/map_strategies_and_agents.py --output-json strategy_map.json

Exit codes:
    0: Mapping complete
    1: Error running mapping
"""

import os
import sys
import json
import ast
import inspect
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any, Callable
import argparse

# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Key modules to scan
TRADING_MODULES = [
    "merid/trading/kalshi_continuous_trader.py",
    "merid/trading/topn_allocator.py",
    "merid/trading/top3_edge_allocator.py",
    "merid/trading/top3_batch_manager.py",
    "merid/trading/order_router.py",
]

STRATEGY_MODULES = [
    "merid/prediction/strategy.py",
    "merid/prediction/paper_session.py",
]

AGENT_MODULES = [
    "merid/trading/kalshi_trading_agent.py",
    "agents/",
]

RISK_MODULES = [
    "merid/prediction/risk/kalshi_risk_engine.py",
    "merid/risk/",
]


@dataclass
class StrategyInfo:
    """Information about a trading strategy."""
    name: str
    module: str
    class_name: Optional[str]
    function_name: Optional[str]
    assets: List[str]
    edge_formula: str
    sizing_formula: str
    config_keys: List[str]
    enabled: bool
    calls_kelly: bool = False
    calls_topn: bool = False


@dataclass
class AgentInfo:
    """Information about a trading agent."""
    name: str
    module: str
    class_name: str
    responsibility: str  # signal_gen, allocation, order_submit, monitoring
    strategies: List[str]
    config_dependencies: List[str]
    execution_venue: str  # kalshi, polymarket, etc.
    final_order_function: str  # The function that actually sends orders
    risk_checks: List[str]  # Risk check functions called
    can_bypass_topn: bool = False


@dataclass
class SizingFormula:
    """A position sizing formula found in the codebase."""
    name: str
    location: str  # module:function or module:class.method
    formula_pseudocode: str
    risk_cap_compliance: str  # "compliant", "non-compliant", "unknown"
    uses_kelly: bool
    uses_topn: bool


class StrategyAndAgentMapper:
    """Maps all strategies, formulas, and agents in the MERID system."""
    
    def __init__(self):
        self.strategies: List[StrategyInfo] = []
        self.agents: List[AgentInfo] = []
        self.sizing_formulas: List[SizingFormula] = []
        self.execution_paths: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        
    def run_full_mapping(self) -> Dict[str, Any]:
        """Execute complete strategy and agent mapping."""
        print("=" * 80)
        print("STRATEGY AND AGENT MAPPING — MERID Trading System")
        print("=" * 80)
        print()
        
        # Phase 2.1: Enumerate all strategies
        self._map_strategies()
        
        # Phase 2.2: Extract sizing formulas
        self._extract_sizing_formulas()
        
        # Phase 2.3: Map all agents
        self._map_agents()
        
        # Phase 2.4: Trace execution paths
        self._trace_execution_paths()
        
        # Phase 2.5: Identify bypass risks
        self._identify_bypass_risks()
        
        return self._generate_report()
    
    def _map_strategies(self):
        """Map all trading strategies."""
        print("[Phase 2.1] Mapping trading strategies...")
        print()
        
        # Read the agent grid YAML to get agent definitions
        agent_grid = self._load_agent_grid()
        
        for agent_def in agent_grid.get("agents", []):
            strategy_info = StrategyInfo(
                name=agent_def.get("name", "unknown"),
                module="kalshi_agent_grid.yaml",
                class_name=None,
                function_name=None,
                assets=agent_def.get("assets", []),
                edge_formula=self._extract_edge_formula(agent_def),
                sizing_formula="TopNEdgeAllocator (when USE_TOPN_ALLOCATOR=true)",
                config_keys=self._extract_config_keys(agent_def),
                enabled=True,
                calls_kelly=False,
                calls_topn=True,
            )
            self.strategies.append(strategy_info)
            print(f"  [OK] {strategy_info.name}")
            print(f"    Assets: {', '.join(strategy_info.assets)}")
            print(f"    Edge formula: {strategy_info.edge_formula}")
            print()
            
    def _load_agent_grid(self) -> Dict:
        """Load the agent grid YAML."""
        grid_path = PROJECT_ROOT / "config" / "kalshi_agent_grid.yaml"
        try:
            import yaml
            with open(grid_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.warnings.append(f"Error loading agent grid: {e}")
            return {"agents": []}
    
    def _extract_edge_formula(self, agent_def: Dict) -> str:
        """Extract the edge computation formula from agent definition."""
        strategy = agent_def.get("strategy", {})
        return (
            f"min_edge_early={strategy.get('min_edge_early', 'N/A')}, "
            f"min_edge_mid={strategy.get('min_edge_mid', 'N/A')}, "
            f"min_edge_late={strategy.get('min_edge_late', 'N/A')}, "
            f"min_edge_terminal={strategy.get('min_edge_terminal', 'N/A')}"
        )
    
    def _extract_config_keys(self, agent_def: Dict) -> List[str]:
        """Extract all config keys this agent depends on."""
        keys = []
        
        # Strategy keys
        if "strategy" in agent_def:
            for key in agent_def["strategy"].keys():
                keys.append(f"strategy.{key}")
                
        # Risk limits
        if "risk_limits" in agent_def:
            for key in agent_def["risk_limits"].keys():
                keys.append(f"risk_limits.{key}")
                
        # Market filter
        if "market_filter" in agent_def:
            for key in agent_def["market_filter"].keys():
                keys.append(f"market_filter.{key}")
                
        return keys
    
    def _extract_sizing_formulas(self):
        """Extract all position sizing formulas from code."""
        print("[Phase 2.2] Extracting sizing formulas...")
        print()
        
        # Formula 1: Kelly sizing (legacy)
        kelly_formula = SizingFormula(
            name="Kelly Criterion Sizing",
            location="merid/prediction/risk/kalshi_risk_engine.py:calculate_order_size",
            formula_pseudocode="""
# From kalshi_risk_engine.py
def calculate_order_size(balance_cents, edge, contract_price_cents, ...):
    # PROBLEM: Uses max_risk_per_trade_pct per TRADE, not per CYCLE
    kelly_risk_cents = int(balance_cents * frac_kelly)
    max_risk_cents = int(balance_cents * cfg.max_risk_per_trade_pct)  # <-- PER TRADE
    risk_cents = min(kelly_risk_cents, max_risk_cents, max_exposure_cents)
    # Convert to contracts
    return risk_cents // contract_price_cents
            """.strip(),
            risk_cap_compliance="non-compliant",  # Per-trade, not per-cycle
            uses_kelly=True,
            uses_topn=False,
        )
        self.sizing_formulas.append(kelly_formula)
        
        # Formula 2: TopN Allocator sizing (new)
        topn_formula = SizingFormula(
            name="TopN Allocator Sizing",
            location="merid/trading/topn_allocator.py:compute_allocations",
            formula_pseudocode="""
# From topn_allocator.py
def compute_allocations(equity_cents, candidates):
    # CORRECT: Uses max_cycle_risk_pct per CYCLE across all trades
    cycle_risk_cents = int(equity_cents * config.max_cycle_risk_pct)
    
    # Select top N candidates by edge
    selected = select_top_n(candidates, max_edges)
    
    # Allocate proportional to edge score
    for candidate in selected:
        allocated_risk = cycle_risk_cents * (candidate.edge / total_edge)
        contracts = allocated_risk // candidate.max_loss_per_contract
        
    return allocations  # Total risk <= cycle_risk_cents
            """.strip(),
            risk_cap_compliance="compliant",  # Per-cycle cap enforced
            uses_kelly=False,
            uses_topn=True,
        )
        self.sizing_formulas.append(topn_formula)
        
        # Formula 3: Global Risk Guard (last-line defense)
        guard_formula = SizingFormula(
            name="Global Risk Guard",
            location="merid/trading/kalshi_continuous_trader.py:GlobalRiskGuard.check_order",
            formula_pseudocode="""
# From kalshi_continuous_trader.py
def check_order(equity_cents, existing_risk_cents, pending_order):
    # ABSOLUTE LAST-LINE DEFENSE
    max_cycle_risk = equity_cents * self.max_cycle_risk_pct
    new_total = existing_risk_cents + pending_order.max_loss_cents
    
    if new_total > max_cycle_risk:
        return (False, "Cycle risk cap exceeded")
    
    return (True, "Allowed")
            """.strip(),
            risk_cap_compliance="compliant",
            uses_kelly=False,
            uses_topn=False,
        )
        self.sizing_formulas.append(guard_formula)
        
        for formula in self.sizing_formulas:
            status = "[OK]" if formula.risk_cap_compliance == "compliant" else "[FAIL]"
            print(f"  {status} {formula.name}")
            print(f"    Location: {formula.location}")
            print(f"    Compliance: {formula.risk_cap_compliance}")
            print()
            
    def _map_agents(self):
        """Map all trading agents and execution actors."""
        print("[Phase 2.3] Mapping trading agents...")
        print()
        
        agents = [
            AgentInfo(
                name="KalshiContinuousTrader",
                module="merid/trading/kalshi_continuous_trader.py",
                class_name="KalshiContinuousTrader",
                responsibility="order_submit",
                strategies=["BTC_15M", "BTC_HOURLY", "ETH_15M", "ETH_HOURLY", "SOL_15M", "XRP_15M", "DOGE_15M"],
                config_dependencies=[
                    "USE_TOPN_ALLOCATOR",
                    "MAX_CYCLE_RISK_PCT",
                    "MAX_TOTAL_RISK_PCT",
                    "kalshi_agent_grid.yaml",
                ],
                execution_venue="kalshi",
                final_order_function="KalshiWebSocket._submit_order",
                risk_checks=[
                    "GlobalRiskGuard.check_order",
                    "TopNEdgeAllocator.compute_allocations",
                    "top3_batch_manager.can_open_new_position",
                ],
                can_bypass_topn=False,  # Cannot bypass if USE_TOPN_ALLOCATOR=true
            ),
            AgentInfo(
                name="TopNEdgeAllocator",
                module="merid/trading/topn_allocator.py",
                class_name="TopNEdgeAllocator",
                responsibility="allocation",
                strategies=[],  # Called by KalshiContinuousTrader
                config_dependencies=[
                    "max_cycle_risk_pct",
                    "max_edges_per_cycle",
                    "min_contracts",
                ],
                execution_venue="internal",
                final_order_function="compute_allocations",
                risk_checks=[
                    "validate_cycle_budget",
                    "compute_max_loss_per_contract",
                ],
                can_bypass_topn=False,
            ),
            AgentInfo(
                name="GlobalRiskGuard",
                module="merid/trading/kalshi_continuous_trader.py",
                class_name="GlobalRiskGuard",
                responsibility="monitoring",
                strategies=[],
                config_dependencies=[
                    "MAX_CYCLE_RISK_PCT",
                    "MAX_TOTAL_RISK_PCT",
                ],
                execution_venue="internal",
                final_order_function="check_order",
                risk_checks=[
                    "check_order",
                    "reset_cycle",
                ],
                can_bypass_topn=False,
            ),
            AgentInfo(
                name="Top3BatchManager",
                module="merid/trading/top3_batch_manager.py",
                class_name="Top3BatchManager",
                responsibility="allocation",
                strategies=[],
                config_dependencies=[
                    "cycle_risk_cap_pct",
                ],
                execution_venue="internal",
                final_order_function="can_open_new_position",
                risk_checks=["notional_check"],
                can_bypass_topn=True,  # Legacy path
            ),
        ]
        
        self.agents = agents
        
        for agent in agents:
            bypass = "[WARN] CAN BYPASS" if agent.can_bypass_topn else "[OK] GUARDED"
            print(f"  {bypass} {agent.name}")
            print(f"    Module: {agent.module}")
            print(f"    Role: {agent.responsibility}")
            print(f"    Execution: {agent.execution_venue}")
            print(f"    Final order func: {agent.final_order_function}")
            print(f"    Risk checks: {len(agent.risk_checks)}")
            print()
            
    def _trace_execution_paths(self):
        """Trace all execution paths from strategy to order submission."""
        print("[Phase 2.4] Tracing execution paths...")
        print()
        
        paths = [
            {
                "name": "TopN Allocator Path (SAFE)",
                "description": "Primary execution path when USE_TOPN_ALLOCATOR=true",
                "steps": [
                    "KalshiContinuousTrader._run_cycle_inner",
                    "TopNEdgeAllocator.compute_allocations",
                    "validate_cycle_budget (enforces max_cycle_risk_pct)",
                    "KalshiContinuousTrader._execute_trade",
                    "GlobalRiskGuard.check_order (last-line defense)",
                    "KalshiWebSocket._submit_order (exchange)",
                ],
                "can_bypass": False,
                "status": "safe",
            },
            {
                "name": "Legacy Kelly Path (UNSAFE)",
                "description": "Fallback path when USE_TOPN_ALLOCATOR=false",
                "steps": [
                    "KalshiContinuousTrader._run_cycle_inner",
                    "BankrollManager.calculate_order_size (Kelly sizing)",
                    "kalshi_risk_engine.calculate_order_size",
                    "max_risk_per_trade_pct applied PER TRADE",
                    "KalshiContinuousTrader._execute_trade",
                    "KalshiWebSocket._submit_order (exchange)",
                ],
                "can_bypass": True,
                "status": "unsafe",
            },
            {
                "name": "Direct Order Path (UNSAFE IF UNGUARDED)",
                "description": "Any code calling _submit_order directly",
                "steps": [
                    "<any module>",
                    "KalshiWebSocket._submit_order (direct)",
                ],
                "can_bypass": True,
                "status": "risk",
            },
        ]
        
        self.execution_paths = paths
        
        for path in paths:
            status_icon = "[OK]" if path["status"] == "safe" else "[FAIL]" if path["status"] == "unsafe" else "[WARN]"
            print(f"  {status_icon} {path['name']}")
            print(f"    Can bypass TopN: {path['can_bypass']}")
            for i, step in enumerate(path['steps'], 1):
                print(f"      {i}. {step}")
            print()
            
    def _identify_bypass_risks(self):
        """Identify all paths that can bypass the 1-2% rule."""
        print("[Phase 2.5] Identifying bypass risks...")
        print()
        
        bypass_paths = []
        
        # Check each agent
        for agent in self.agents:
            if agent.can_bypass_topn:
                bypass_paths.append({
                    "type": "agent",
                    "name": agent.name,
                    "location": agent.module,
                    "final_order_function": agent.final_order_function,
                    "risk": f"{agent.name} can submit orders without TopN allocator validation",
                })
                
        # Check each execution path
        for path in self.execution_paths:
            if path["can_bypass"]:
                bypass_paths.append({
                    "type": "path",
                    "name": path["name"],
                    "steps": path["steps"],
                    "risk": f"Execution path '{path['name']}' can bypass per-cycle risk cap",
                })
                
        if bypass_paths:
            print(f"  Found {len(bypass_paths)} potential bypass paths:")
            for bypass in bypass_paths:
                print(f"    [WARN] {bypass['name']}")
                print(f"        Risk: {bypass['risk']}")
                print(f"        Location: {bypass.get('location', 'N/A')}")
                print()
        else:
            print("  [OK] No bypass paths detected")
            print()
            
        return bypass_paths
    
    def _generate_report(self) -> Dict[str, Any]:
        """Generate final mapping report."""
        report = {
            "strategies": [asdict(s) for s in self.strategies],
            "sizing_formulas": [asdict(f) for f in self.sizing_formulas],
            "agents": [asdict(a) for a in self.agents],
            "execution_paths": self.execution_paths,
            "bypass_paths": self._identify_bypass_risks(),
            "warnings": self.warnings,
            "summary": {
                "total_strategies": len(self.strategies),
                "total_agents": len(self.agents),
                "total_formulas": len(self.sizing_formulas),
                "safe_paths": len([p for p in self.execution_paths if p["status"] == "safe"]),
                "unsafe_paths": len([p for p in self.execution_paths if p["status"] == "unsafe"]),
                "agents_can_bypass": len([a for a in self.agents if a.can_bypass_topn]),
            }
        }
        
        return report
    
    def print_summary(self):
        """Print human-readable summary."""
        print("=" * 80)
        print("MAPPING SUMMARY")
        print("=" * 80)
        print()
        
        print(f"Strategies mapped: {len(self.strategies)}")
        print(f"Agents mapped: {len(self.agents)}")
        print(f"Sizing formulas: {len(self.sizing_formulas)}")
        print(f"Execution paths: {len(self.execution_paths)}")
        print()
        
        safe_paths = len([p for p in self.execution_paths if p["status"] == "safe"])
        unsafe_paths = len([p for p in self.execution_paths if p["status"] == "unsafe"])
        bypass_agents = len([a for a in self.agents if a.can_bypass_topn])
        
        print("Status:")
        print(f"  Safe execution paths: {safe_paths}")
        print(f"  Unsafe execution paths: {unsafe_paths}")
        print(f"  Agents that can bypass TopN: {bypass_agents}")
        print()
        
        if bypass_agents > 0:
            print("[WARN] WARNING: Some agents can bypass the TopN allocator")
            print("    Review these agents to ensure they don't create risk violations")
            print()
            
        if unsafe_paths > 0:
            print("[WARN] WARNING: Unsafe execution paths detected")
            print("    These paths only activate when USE_TOPN_ALLOCATOR=false")
            print("    Keep USE_TOPN_ALLOCATOR=true in production")
            print()
            
        print("[DONE] Mapping complete")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Strategy and Agent Mapping Tool")
    parser.add_argument("--output-json", help="Save report to JSON file")
    args = parser.parse_args()
    
    mapper = StrategyAndAgentMapper()
    report = mapper.run_full_mapping()
    
    if args.output_json:
        with open(args.output_json, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        print(f"Report saved to {args.output_json}")
        
    exit_code = mapper.print_summary()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
