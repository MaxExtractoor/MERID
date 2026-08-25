"""
MERID Data Dependency Mapping Script

This script analyzes the MERID codebase to map upstream data sources and
downstream consumers for each component. This helps understand how changes
propagate through the system and identify high-leverage bottlenecks.

Usage:
    python scripts/map_data_dependencies.py --component agent_grid_15m
    python scripts/map_data_dependencies.py --all
    python scripts/map_data_dependencies.py --export dependencies.json
"""

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, asdict


@dataclass
class Component:
    """A component in the MERID system."""
    name: str
    file_path: str
    description: str
    upstream_sources: List[str]
    downstream_consumers: List[str]
    ssot_fields: List[str]
    high_leverage: bool


class DependencyMapper:
    """Maps data dependencies across the MERID codebase."""

    # Hardcoded component definitions based on MERID_DATA_DEPENDENCY_MAP.md
    COMPONENTS = {
        "kalshi_orderbook": Component(
            name="kalshi_orderbook",
            file_path="external:kalshi_api",
            description="Kalshi orderbook snapshots (YES/NO prices, liquidity)",
            upstream_sources=["external:kalshi_websocket", "external:kalshi_rest"],
            downstream_consumers=[
                "merid/prediction/agent_grid_15m.py",
                "merid/event_venues/kalshi/order_router.py",
                "merid/loop_15m.py"
            ],
            ssot_fields=[],
            high_leverage=True
        ),
        "kalshi_market_metadata": Component(
            name="kalshi_market_metadata",
            file_path="external:kalshi_catalog_api",
            description="Kalshi market metadata (strike, target, asset, expiry)",
            upstream_sources=["external:kalshi_catalog_api"],
            downstream_consumers=[
                "merid/prediction/agent_grid_15m.py",
                "merid/loop_15m.py"
            ],
            ssot_fields=[],
            high_leverage=True
        ),
        "profile_yaml": Component(
            name="profile_yaml",
            file_path="config/profiles/kalshi_crypto_15m_v2.yaml",
            description="Profile YAML (SSOT for signal_mode, enabled_features, price_range)",
            upstream_sources=["config:profile_yaml"],
            downstream_consumers=[
                "merid/risk/profiles/crypto_15m_profile.py",
                "merid/prediction/agent_grid_15m.py",
                "merid/event_venues/kalshi/order_router.py"
            ],
            ssot_fields=["signal_mode", "enabled_features", "disabled_features", "price_range", "strict_mode"],
            high_leverage=True
        ),
        "agent_grid_yaml": Component(
            name="agent_grid_yaml",
            file_path="config/kalshi_agent_grid.yaml",
            description="Agent grid YAML (per-agent configuration)",
            upstream_sources=["config:agent_grid_yaml"],
            downstream_consumers=[
                "merid/prediction/agent_grid_15m.py"
            ],
            ssot_fields=["signal_mode"],
            high_leverage=True
        ),
        "signal_generation": Component(
            name="signal_generation",
            file_path="merid/prediction/agent_grid_15m.py",
            description="Signal generation (momentum_fvg, price_based, hybrid, volatility_reversion)",
            upstream_sources=[
                "kalshi_orderbook",
                "profile_yaml",
                "external:spot_price_oracle"
            ],
            downstream_consumers=["intent_mapping"],
            ssot_fields=["signal_mode"],
            high_leverage=True
        ),
        "intent_mapping": Component(
            name="intent_mapping",
            file_path="merid/prediction/agent_grid_15m.py",
            description="Intent mapping (thesis_side, exposure_direction, price_side_alignment)",
            upstream_sources=["signal_generation", "profile_yaml"],
            downstream_consumers=["candidate_builder"],
            ssot_fields=["price_range", "strict_mode"],
            high_leverage=True
        ),
        "candidate_builder": Component(
            name="candidate_builder",
            file_path="merid/loop_15m.py",
            description="Candidate builder (side selection, strict mode, position limits)",
            upstream_sources=["intent_mapping", "profile_yaml", "position_cache"],
            downstream_consumers=["router"],
            ssot_fields=["price_range", "strict_mode"],
            high_leverage=True
        ),
        "router": Component(
            name="router",
            file_path="merid/event_venues/kalshi/order_router.py",
            description="Router (side/price reconciliation, risk enforcement, duplicate detection)",
            upstream_sources=["candidate_builder", "profile_yaml", "position_cache"],
            downstream_consumers=["kalshi_orders", "position_cache"],
            ssot_fields=["risk_limits", "price_range"],
            high_leverage=True
        ),
        "position_cache": Component(
            name="position_cache",
            file_path="merid/event_venues/kalshi/position_cache.py",
            description="Position cache (thesis_side preservation, exit reconciliation)",
            upstream_sources=["kalshi_fills", "position_state"],
            downstream_consumers=["router", "candidate_builder", "exit_logic"],
            ssot_fields=["thesis_side"],
            high_leverage=True
        ),
        "kalshi_orders": Component(
            name="kalshi_orders",
            file_path="external:kalshi_rest_api",
            description="Orders to Kalshi API",
            upstream_sources=["router"],
            downstream_consumers=["kalshi_fills"],
            ssot_fields=[],
            high_leverage=True
        ),
        "kalshi_fills": Component(
            name="kalshi_fills",
            file_path="external:kalshi_websocket",
            description="Kalshi fills (WebSocket/REST)",
            upstream_sources=["kalshi_orders"],
            downstream_consumers=["position_cache"],
            ssot_fields=[],
            high_leverage=True
        ),
    }

    def __init__(self):
        self.components = self.COMPONENTS

    def get_component(self, name: str) -> Optional[Component]:
        """Get a component by name."""
        return self.components.get(name)

    def get_upstream_chain(self, component_name: str) -> List[str]:
        """Get the full upstream chain for a component."""
        chain = []
        visited = set()
        
        def traverse(name: str):
            if name in visited:
                return
            visited.add(name)
            component = self.get_component(name)
            if component:
                for source in component.upstream_sources:
                    if source in self.components:
                        traverse(source)
                    else:
                        chain.append(source)
        
        traverse(component_name)
        return list(visited)

    def get_downstream_chain(self, component_name: str) -> List[str]:
        """Get the full downstream chain for a component."""
        chain = []
        visited = set()
        
        def traverse(name: str):
            if name in visited:
                return
            visited.add(name)
            component = self.get_component(name)
            if component:
                for consumer in component.downstream_consumers:
                    if consumer in self.components:
                        traverse(consumer)
                    else:
                        chain.append(consumer)
        
        traverse(component_name)
        return list(visited)

    def analyze_change_impact(self, component_name: str, field: str) -> Dict:
        """Analyze the impact of changing a field in a component."""
        component = self.get_component(component_name)
        if not component:
            return {"error": f"Component {component_name} not found"}
        
        if field not in component.ssot_fields and field not in ["all"]:
            return {"error": f"Field {field} not in SSOT fields for {component_name}"}
        
        downstream = self.get_downstream_chain(component_name)
        upstream = self.get_upstream_chain(component_name)
        
        return {
            "component": component_name,
            "field": field,
            "upstream_chain": upstream,
            "downstream_chain": downstream,
            "high_leverage": component.high_leverage,
            "ssot_fields": component.ssot_fields,
            "impact_risk": "HIGH" if component.high_leverage else "MEDIUM"
        }

    def export_to_json(self, output_path: str):
        """Export all components to JSON."""
        data = {
            "components": [asdict(comp) for comp in self.components.values()],
            "metadata": {
                "version": "1.0",
                "generated": "2026-07-24",
                "source": "MERID_DATA_DEPENDENCY_MAP.md"
            }
        }
        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Map MERID data dependencies")
    parser.add_argument("--component", help="Analyze a specific component")
    parser.add_argument("--field", help="Analyze impact of changing a specific field")
    parser.add_argument("--all", action="store_true", help="List all components")
    parser.add_argument("--export", help="Export to JSON file")
    parser.add_argument("--impact", action="store_true", help="Analyze change impact")
    
    args = parser.parse_args()
    
    mapper = DependencyMapper()
    
    if args.all:
        print("MERID Components:")
        print("=" * 80)
        for name, comp in mapper.components.items():
            print(f"\n{name}:")
            print(f"  File: {comp.file_path}")
            print(f"  Description: {comp.description}")
            print(f"  Upstream: {', '.join(comp.upstream_sources)}")
            print(f"  Downstream: {', '.join(comp.downstream_consumers)}")
            print(f"  SSOT Fields: {', '.join(comp.ssot_fields)}")
            print(f"  High Leverage: {comp.high_leverage}")
    
    elif args.component:
        if args.impact and args.field:
            result = mapper.analyze_change_impact(args.component, args.field)
            print(json.dumps(result, indent=2))
        else:
            comp = mapper.get_component(args.component)
            if comp:
                print(f"Component: {comp.name}")
                print(f"File: {comp.file_path}")
                print(f"Description: {comp.description}")
                print(f"\nUpstream Sources:")
                for source in comp.upstream_sources:
                    print(f"  - {source}")
                print(f"\nDownstream Consumers:")
                for consumer in comp.downstream_consumers:
                    print(f"  - {consumer}")
                print(f"\nSSOT Fields: {', '.join(comp.ssot_fields)}")
                print(f"High Leverage: {comp.high_leverage}")
            else:
                print(f"Component {args.component} not found")
    
    elif args.export:
        mapper.export_to_json(args.export)
        print(f"Exported dependencies to {args.export}")
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
