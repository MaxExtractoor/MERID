#!/usr/bin/env python3
"""
MERID Agent Registry Scanner

Scans the codebase to discover all agents, extract metadata, and build a coverage matrix
for BTC/ETH/SOL/XRP/DOGE 15-minute Kalshi trading system.

Usage:
    python scripts/scan_agent_registry.py --output-json agents_inventory.json
    python scripts/scan_agent_registry.py --output-csv agents_inventory.csv
    python scripts/scan_agent_registry.py --coverage-matrix
"""

import argparse
import ast
import csv
import json
import logging
import os
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class AgentInfo:
    """Structured metadata for a discovered agent."""
    name: str
    type: str  # "canonical", "llm", "kalshi_trading", "kalshi_regime", "config"
    module: str
    file_path: str
    description: str = ""
    category: str = ""  # research, strategy, risk, coordination, ops
    markets: List[str] = field(default_factory=list)
    timeframes: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)
    enabled: bool = True
    status: str = "unknown"  # active, dormant, deprecated, experimental
    wired_where: List[str] = field(default_factory=list)
    series_tickers: List[str] = field(default_factory=list)
    archetype: str = ""
    base_class: str = ""
    role: str = ""  # feature, execution, risk, research
    feature_namespace: str = ""  # sentiment, microstructure, regime, macro, etc.
    
    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['markets'] = list(d['markets'])
        d['timeframes'] = list(d['timeframes'])
        d['assets'] = list(d['assets'])
        d['wired_where'] = list(d['wired_where'])
        d['series_tickers'] = list(d['series_tickers'])
        return d


class AgentRegistryScanner:
    """Scans MERID codebase for agent definitions and wiring."""
    
    def __init__(self, repo_root: str):
        self.repo_root = Path(repo_root)
        self.agents: List[AgentInfo] = []
        
        # Agent discovery patterns
        self.agent_patterns = {
            'canonical': re.compile(r'class\s+(\w+Agent)\s*\(\s*CanonicalAgent\s*\)'),
            'base_kalshi': re.compile(r'class\s+(\w+Agent)\s*\(\s*BaseKalshiAgent\s*\)'),
            'kalshi_trading': re.compile(r'class\s+(\w+TradingAgent)\s*\('),
            'llm_base': re.compile(r'class\s+(\w+Agent)\s*\(\s*BaseAgent\s*\)'),
            'agent_interface': re.compile(r'class\s+(\w+Agent)\s*\(\s*AgentInterface\s*\)'),
        }
        
        # Directories to scan
        self.scan_dirs = [
            self.repo_root / "agents",
            self.repo_root / "merid" / "agents",
            self.repo_root / "merid" / "prediction",
        ]
        
        # Config files to parse
        self.config_files = [
            self.repo_root / "config" / "agent_manifest.yml",
            self.repo_root / "config" / "kalshi_agent_grid.yaml",
        ]
    
    def scan_all(self) -> List[AgentInfo]:
        """Run full scan: code + configs."""
        print(f"Scanning MERID agent registry from {self.repo_root}")
        
        # Scan Python files for agent classes
        self._scan_python_agents()
        
        # Parse YAML configs
        self._parse_yaml_configs()
        
        # Detect wiring patterns
        self._detect_wiring()
        
        # Classify status
        self._classify_status()
        
        # Classify roles and feature namespaces
        self._classify_roles()
        
        print(f"Discovered {len(self.agents)} agents total")
        return self.agents
    
    def _scan_python_agents(self):
        """Scan Python files for agent class definitions."""
        for scan_dir in self.scan_dirs:
            if not scan_dir.exists():
                continue
            
            for py_file in scan_dir.rglob("*.py"):
                if "__pycache__" in str(py_file):
                    continue
                
                self._scan_python_file(py_file)
    
    def _scan_python_file(self, file_path: Path):
        """Extract agent classes from a single Python file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse AST for docstrings
            tree = ast.parse(content)
            docstrings = self._extract_docstrings(tree)
            
            # Find agent classes
            for agent_type, pattern in self.agent_patterns.items():
                for match in pattern.finditer(content):
                    class_name = match.group(1)
                    
                    # Get docstring
                    docstring = docstrings.get(class_name, "")
                    
                    # Extract module path
                    rel_path = file_path.relative_to(self.repo_root)
                    module = str(rel_path.with_suffix('')).replace(os.sep, '.')
                    
                    # Determine markets/timeframes from docstring or class name
                    markets, timeframes, assets = self._extract_scope(class_name, docstring, content)
                    
                    agent = AgentInfo(
                        name=class_name,
                        type=agent_type,
                        module=module,
                        file_path=str(rel_path),
                        description=docstring.split('\n')[0] if docstring else "",
                        markets=markets,
                        timeframes=timeframes,
                        assets=assets,
                        base_class=self._get_base_class(content, class_name),
                    )
                    
                    self.agents.append(agent)
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
    
    def _extract_docstrings(self, tree: ast.AST) -> Dict[str, str]:
        """Extract class docstrings from AST."""
        docstrings = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                docstring = ast.get_docstring(node)
                if docstring:
                    docstrings[node.name] = docstring
        return docstrings
    
    def _extract_scope(self, class_name: str, docstring: str, content: str) -> tuple:
        """Extract markets, timeframes, assets from class name and docstring."""
        markets = []
        timeframes = []
        assets = []
        
        # Parse class name for patterns
        name_lower = class_name.lower()
        
        # Asset detection
        for asset in ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']:
            if asset.lower() in name_lower:
                assets.append(asset)
        
        # Timeframe detection
        tf_patterns = {
            '15m': '15m', '15min': '15m', 'fifteen_min': '15m',
            '1h': '1h', 'hourly': '1h', 'hour': '1h',
            'daily': 'daily', '1d': 'daily',
            'weekly': 'weekly', '1w': 'weekly',
        }
        for pattern, tf in tf_patterns.items():
            if pattern in name_lower or pattern in docstring.lower():
                timeframes.append(tf)
        
        # Market detection
        if 'kalshi' in name_lower or 'kalshi' in docstring.lower():
            markets.append('kalshi')
        if 'crypto' in name_lower or 'crypto' in docstring.lower():
            markets.append('crypto')
        
        return markets, timeframes, assets
    
    def _get_base_class(self, content: str, class_name: str) -> str:
        """Extract base class from class definition."""
        pattern = rf'class\s+{class_name}\s*\(\s*([^)]+)\)'
        match = re.search(pattern, content)
        if match:
            return match.group(1).strip()
        return ""
    
    def _parse_yaml_configs(self):
        """Parse YAML config files for agent definitions."""
        try:
            import yaml
        except ImportError:
            print("Warning: PyYAML not installed, skipping YAML config parsing")
            return
        
        for config_file in self.config_files:
            if not config_file.exists():
                continue
            
            try:
                with open(config_file, 'r') as f:
                    config = yaml.safe_load(f)
                
                if config_file.name == "agent_manifest.yml":
                    self._parse_agent_manifest(config, config_file)
                elif config_file.name == "kalshi_agent_grid.yaml":
                    self._parse_kalshi_grid(config, config_file)
            
            except Exception as e:
                print(f"Error parsing {config_file}: {e}")
    
    def _parse_agent_manifest(self, config: Dict, config_file: Path):
        """Parse agent_manifest.yml for canonical agents."""
        agents = config.get('agents', {})
        for role, agent_config in agents.items():
            module = agent_config.get('module', '')
            description = agent_config.get('description', '')
            category = agent_config.get('category', '')
            
            # Extract class name from module
            class_name = module.split('.')[-1] if module else role
            
            # Extract data_access for markets
            data_access = agent_config.get('data_access', [])
            markets = [da for da in data_access if da in ['kalshi', 'binance', 'coinbase']]
            
            agent = AgentInfo(
                name=class_name,
                type="config",
                module=module,
                file_path=str(config_file.relative_to(self.repo_root)),
                description=description,
                category=category,
                markets=markets,
                enabled=True,
                status="active",
            )
            
            self.agents.append(agent)
    
    def _parse_kalshi_grid(self, config: Dict, config_file: Path):
        """Parse kalshi_agent_grid.yaml for Kalshi trading agents."""
        agents = config.get('agents', [])
        for agent_config in agents:
            name = agent_config.get('name', '')
            enabled = agent_config.get('enabled', True)
            assets = agent_config.get('assets', [])
            timeframes = agent_config.get('timeframes', [])
            series_tickers = agent_config.get('series_tickers', [])
            archetype = agent_config.get('archetype', '')
            category = agent_config.get('category', 'crypto')
            
            # Build description from config
            description = f"Kalshi {name} agent ({archetype})"
            
            agent = AgentInfo(
                name=name,
                type="kalshi_grid",
                module=f"config.kalshi_agent_grid.{name.lower()}",
                file_path=str(config_file.relative_to(self.repo_root)),
                description=description,
                category=category,
                assets=assets,
                timeframes=timeframes,
                markets=['kalshi'] if 'kalshi' in str(config_file).lower() else [],
                enabled=enabled,
                status="active" if enabled else "dormant",
                series_tickers=series_tickers,
                archetype=archetype,
                wired_where=["kalshi_agent_grid"],
            )
            
            self.agents.append(agent)
    
    def _detect_wiring(self):
        """Detect where agents are wired into the system."""
        # Simple heuristic: check for imports and references
        for agent in self.agents:
            if agent.type in ["kalshi_grid", "config"]:
                continue
            
            # Check if agent is referenced in key files
            key_files = [
                self.repo_root / "merid" / "agents" / "wiring.py",
                self.repo_root / "merid" / "prediction" / "agent_grid.py",
                self.repo_root / "web" / "startup_agents.py",
            ]
            
            for key_file in key_files:
                if not key_file.exists():
                    continue
                
                try:
                    with open(key_file, 'r') as f:
                        content = f.read()
                    
                    if agent.name in content or agent.module in content:
                        agent.wired_where.append(key_file.name)
                except:
                    pass
    
    def _classify_status(self):
        """Classify agent status based on enabled flag and wiring."""
        for agent in self.agents:
            if agent.status != "unknown":
                continue
            
            if not agent.enabled:
                agent.status = "dormant"
            elif agent.wired_where:
                agent.status = "active"
            else:
                agent.status = "experimental"
    
    def _classify_roles(self):
        """Classify agents into roles (feature/execution/risk/research) and feature namespaces."""
        target_assets = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
        target_timeframe = '15m'
        
        for agent in self.agents:
            # Skip if already classified
            if agent.role:
                continue
            
            # Execution agents: Only 15m Kalshi grid agents with _15M suffix for target assets
            # More strict: name must end with _15M to be execution
            is_15m_crypto = (
                agent.type == 'kalshi_grid' and
                agent.name.endswith('_15M') and
                target_timeframe in agent.timeframes and
                any(asset in agent.assets for asset in target_assets) and
                agent.enabled
            )
            
            if is_15m_crypto:
                agent.role = "execution"
                logger.debug(f"Classified {agent.name} as execution (15m Kalshi grid)")
                continue
            
            # Risk agents: Category = risk or type indicates risk management
            if agent.category == 'risk' or 'risk' in agent.name.lower():
                agent.role = "risk"
                continue
            
            # Research agents: Category = research or type = config with research role
            if agent.category == 'research' or agent.type == 'config':
                agent.role = "research"
                continue
            
            # Feature agents: Everything else
            agent.role = "feature"
            
            # Determine feature namespace based on agent characteristics
            if 'sentiment' in agent.name.lower() or 'news' in agent.name.lower() or 'social' in agent.name.lower():
                agent.feature_namespace = "sentiment"
            elif 'microstructure' in agent.name.lower() or '1m' in agent.name.lower() or '5m' in agent.name.lower():
                agent.feature_namespace = "microstructure"
            elif 'regime' in agent.name.lower() or 'trend' in agent.name.lower() or '1h' in agent.timeframes or 'daily' in agent.timeframes:
                agent.feature_namespace = "regime"
            elif 'macro' in agent.name.lower() or 'fundamental' in agent.name.lower():
                agent.feature_namespace = "macro"
            elif 'vol' in agent.name.lower() or 'volatility' in agent.name.lower():
                agent.feature_namespace = "volatility"
            else:
                agent.feature_namespace = "general"
    
    def filter_15m_crypto(self) -> List[AgentInfo]:
        """Filter to BTC/ETH/SOL/XRP/DOGE 15m agents."""
        target_assets = {'BTC', 'ETH', 'SOL', 'XRP', 'DOGE'}
        target_timeframe = '15m'
        
        filtered = []
        for agent in self.agents:
            # Check if agent matches target assets and timeframe
            asset_match = any(asset in agent.assets for asset in target_assets)
            tf_match = target_timeframe in agent.timeframes
            
            # Also check series tickers (e.g., KXBTC, KXETH)
            series_match = any(
                any(asset in ticker for asset in target_assets)
                for ticker in agent.series_tickers
            )
            
            # Check name patterns
            name_match = any(
                f"{asset}_15M" in agent.name.upper() or f"{asset}15M" in agent.name.upper()
                for asset in target_assets
            )
            
            if asset_match or tf_match or series_match or name_match:
                filtered.append(agent)
        
        return filtered
    
    def build_coverage_matrix(self) -> Dict[str, Any]:
        """Build coverage matrix for BTC/ETH/SOL/XRP/DOGE 15m."""
        target_assets = ['BTC', 'ETH', 'SOL', 'XRP', 'DOGE']
        target_timeframe = '15m'
        
        matrix = {
            'target_assets': target_assets,
            'target_timeframe': target_timeframe,
            'coverage': {},
            'summary': {
                'total_assets': len(target_assets),
                'covered_assets': 0,
                'total_agents': 0,
                'active_agents': 0,
                'gaps': []
            }
        }
        
        for asset in target_assets:
            asset_agents = []
            
            for agent in self.agents:
                # Check if agent covers this asset at 15m
                asset_match = asset in agent.assets
                tf_match = target_timeframe in agent.timeframes
                series_match = any(asset in ticker for ticker in agent.series_tickers)
                name_match = f"{asset}_15M" in agent.name.upper() or f"{asset}15M" in agent.name.upper()
                
                if asset_match or (tf_match and series_match) or name_match:
                    asset_agents.append({
                        'name': agent.name,
                        'type': agent.type,
                        'status': agent.status,
                        'enabled': agent.enabled,
                        'archetype': agent.archetype,
                    })
            
            matrix['coverage'][asset] = {
                'has_signal_agent': any(a['type'] in ['canonical', 'kalshi_regime'] for a in asset_agents),
                'has_execution_agent': any(a['type'] == 'kalshi_trading' for a in asset_agents),
                'has_grid_agent': any(a['type'] == 'kalshi_grid' for a in asset_agents),
                'agents': asset_agents,
                'is_covered': len(asset_agents) > 0,
            }
            
            if matrix['coverage'][asset]['is_covered']:
                matrix['summary']['covered_assets'] += 1
            
            matrix['summary']['total_agents'] += len(asset_agents)
            matrix['summary']['active_agents'] += sum(1 for a in asset_agents if a['enabled'])
        
        # Identify gaps
        for asset, coverage in matrix['coverage'].items():
            if not coverage['is_covered']:
                matrix['summary']['gaps'].append(f"{asset}: No agents found")
            elif not coverage['has_grid_agent']:
                matrix['summary']['gaps'].append(f"{asset}: Missing Kalshi grid agent")
        
        return matrix
    
    def export_json(self, output_path: str):
        """Export agent inventory to JSON."""
        data = {
            'scan_timestamp': datetime.utcnow().isoformat(),
            'repo_root': str(self.repo_root),
            'total_agents': len(self.agents),
            'agents': [a.to_dict() for a in self.agents],
        }
        
        with open(output_path, 'w') as f:
            json.dump(data, f, indent=2)
        
        print(f"Exported {len(self.agents)} agents to {output_path}")
    
    def export_csv(self, output_path: str):
        """Export agent inventory to CSV."""
        fieldnames = [
            'name', 'type', 'module', 'file_path', 'description', 'category',
            'markets', 'timeframes', 'assets', 'enabled', 'status',
            'archetype', 'series_tickers', 'wired_where', 'base_class',
            'role', 'feature_namespace'
        ]
        
        with open(output_path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for agent in self.agents:
                row = agent.to_dict()
                # Convert lists to strings for CSV
                row['markets'] = ','.join(row['markets'])
                row['timeframes'] = ','.join(row['timeframes'])
                row['assets'] = ','.join(row['assets'])
                row['series_tickers'] = ','.join(row['series_tickers'])
                row['wired_where'] = ','.join(row['wired_where'])
                writer.writerow(row)
        
        print(f"Exported {len(self.agents)} agents to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Scan MERID agent registry')
    parser.add_argument('--repo-root', default='.', help='Repository root path')
    parser.add_argument('--output-json', help='Export to JSON file')
    parser.add_argument('--output-csv', help='Export to CSV file')
    parser.add_argument('--coverage-matrix', action='store_true', help='Print coverage matrix')
    parser.add_argument('--filter-15m', action='store_true', help='Filter to 15m crypto agents')
    
    args = parser.parse_args()
    
    scanner = AgentRegistryScanner(args.repo_root)
    scanner.scan_all()
    
    if args.filter_15m:
        filtered = scanner.filter_15m_crypto()
        print(f"\n=== 15m Crypto Agents ({len(filtered)}) ===")
        for agent in filtered:
            print(f"  {agent.name}: {agent.description}")
            print(f"    Assets: {agent.assets}, Timeframes: {agent.timeframes}")
            print(f"    Status: {agent.status}, Enabled: {agent.enabled}")
            print()
        scanner.agents = filtered
    
    if args.coverage_matrix:
        matrix = scanner.build_coverage_matrix()
        print("\n=== BTC/ETH/SOL/XRP/DOGE 15m Coverage Matrix ===")
        print(json.dumps(matrix, indent=2))
    
    if args.output_json:
        scanner.export_json(args.output_json)
    
    if args.output_csv:
        scanner.export_csv(args.output_csv)
    
    if not any([args.output_json, args.output_csv, args.coverage_matrix, args.filter_15m]):
        # Default: print summary
        print(f"\n=== Agent Registry Summary ===")
        print(f"Total agents: {len(scanner.agents)}")
        
        by_type = {}
        for agent in scanner.agents:
            by_type[agent.type] = by_type.get(agent.type, 0) + 1
        
        print("\nBy type:")
        for agent_type, count in sorted(by_type.items()):
            print(f"  {agent_type}: {count}")
        
        by_status = {}
        for agent in scanner.agents:
            by_status[agent.status] = by_status.get(agent.status, 0) + 1
        
        print("\nBy status:")
        for status, count in sorted(by_status.items()):
            print(f"  {status}: {count}")
        
        by_role = {}
        for agent in scanner.agents:
            by_role[agent.role] = by_role.get(agent.role, 0) + 1
        
        print("\nBy role:")
        for role, count in sorted(by_role.items()):
            print(f"  {role}: {count}")
        
        # 15m execution agents (the only ones allowed to trade)
        execution_15m = [a for a in scanner.agents if a.role == "execution"]
        print(f"\n15m Execution Agents (allowed to trade): {len(execution_15m)}")
        for agent in execution_15m:
            print(f"  - {agent.name}: assets={agent.assets}, tf={agent.timeframes}")


if __name__ == '__main__':
    main()
