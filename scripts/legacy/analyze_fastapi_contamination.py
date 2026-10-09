#!/usr/bin/env python3
"""
Script to analyze FastAPI app for legacy contamination and gaps.

This script:
1. Scans main_15m_lean.py for all router includes
2. Traces each router to its source file
3. Analyzes imports and dependencies
4. Identifies legacy vs production code paths
5. Exposes gaps and contamination
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple
import re

# Known legacy modules to flag
LEGACY_MODULES = {
    'merid.prediction.agent_grid',  # Legacy agent grid (use agent_grid_15m)
    'merid.lanes',  # Legacy lane system
    'merid.prediction.paper_session',  # Legacy paper session
    'agents.reflection',  # Legacy reflection system
    'agents.agent_mesh',  # Legacy agent mesh
    'merid.prediction.social_broadcaster',  # Legacy social broadcaster
    'core.learning',  # Legacy learning system
    'core.price_feed',  # Legacy price feed (use unified_spot_service)
    'merid.publishing',  # Legacy publishing system
}

# Known production modules
PRODUCTION_MODULES = {
    'merid.loop_15m',
    'merid.prediction.agent_grid_15m',
    'merid.event_venues.kalshi.ws_bridge',
    'merid.event_venues.kalshi.market_catalog',
    'merid.event_venues.kalshi.market_state',
    'merid.event_venues.kalshi.bankroll_service_v2',
    'merid.event_venues.kalshi.order_router',
    'data.unified_spot_service',
    'merid.risk.kill_switches',
    'merid.risk.global_risk_guard',
}

class RouterAnalyzer(ast.NodeVisitor):
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.routers: List[Dict] = []
        self.imports: List[Dict] = []
        self.app_creation = None
        
    def visit_ImportFrom(self, node):
        module = node.module or ''
        for alias in node.names:
            self.imports.append({
                'type': 'from',
                'module': module,
                'name': alias.name,
                'asname': alias.asname,
                'line': node.lineno
            })
        self.generic_visit(node)
        
    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append({
                'type': 'import',
                'module': alias.name,
                'asname': alias.asname,
                'line': node.lineno
            })
        self.generic_visit(node)
        
    def visit_Call(self, node):
        # Look for app.include_router() calls
        if isinstance(node.func, ast.Attribute):
            if node.func.attr == 'include_router':
                if isinstance(node.func.value, ast.Name) and node.func.value.id == 'app':
                    if node.args:
                        router_name = None
                        if isinstance(node.args[0], ast.Name):
                            router_name = node.args[0].id
                        elif isinstance(node.args[0], ast.Attribute):
                            router_name = node.args[0].attr
                        
                        self.routers.append({
                            'name': router_name,
                            'line': node.lineno,
                            'args': len(node.args),
                            'keywords': [kw.arg for kw in node.keywords if kw.arg]
                        })
        
        # Look for FastAPI() app creation
        if isinstance(node.func, ast.Name) and node.func.id == 'FastAPI':
            self.app_creation = {
                'line': node.lineno,
                'has_lifespan': any(kw.arg == 'lifespan' for kw in node.keywords)
            }
            
        self.generic_visit(node)

def analyze_file(file_path: Path) -> Dict:
    """Analyze a Python file for imports and router usage."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        tree = ast.parse(content, filename=str(file_path))
    except Exception as e:
        return {'error': str(e)}
    
    analyzer = RouterAnalyzer(file_path)
    analyzer.visit(tree)
    
    return {
        'file': str(file_path),
        'routers': analyzer.routers,
        'imports': analyzer.imports,
        'app_creation': analyzer.app_creation
    }

def trace_router_source(router_name: str, web_dir: Path, main_imports: List[Dict]) -> Tuple[Path, Dict]:
    """Find the source file for a router by tracing imports."""
    # First, check if we can find the import in main file
    router_import = None
    for imp in main_imports:
        imp_name = imp.get('name', '')
        imp_asname = imp.get('asname', '')
        if imp_asname == router_name or imp_name == router_name:
            router_import = imp
            break
    
    if router_import:
        # Try to find the file based on the import module
        module_path = router_import['module'].replace('.', '/')
        
        # Try common patterns
        patterns = [
            f"{module_path}.py",
            f"{module_path}/__init__.py",
            f"api/{router_name}.py",
            f"routers/{router_name}.py",
            f"{router_name}.py",
        ]
        
        for pattern in patterns:
            for file_path in web_dir.parent.rglob(pattern):
                result = analyze_file(file_path)
                return file_path, result
    
    # Fallback: search for router name in all Python files
    for file_path in web_dir.parent.rglob("*.py"):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            if f"router = APIRouter()" in content or f"{router_name} = APIRouter()" in content:
                result = analyze_file(file_path)
                return file_path, result
        except:
            continue
    
    return None, {'error': 'Router source not found'}

def classify_import(module: str) -> str:
    """Classify an import as legacy, production, or unknown."""
    # Check production first (more specific)
    for prod in PRODUCTION_MODULES:
        if module.startswith(prod):
            return 'PRODUCTION'
    
    # Check for exact legacy match (not prefix)
    if module in LEGACY_MODULES:
        return 'LEGACY'
    
    # Check for known legacy patterns
    if 'agents.' in module and module != 'agents.telegram_agent':
        return 'LEGACY'
    if 'core.' in module and module not in ['core.cache']:
        return 'LEGACY'
    if 'merid.lanes' in module:
        return 'LEGACY'
    if module == 'merid.prediction.agent_grid':  # Exact match only
        return 'LEGACY'
    
    return 'UNKNOWN'

def analyze_contamination():
    """Main analysis function."""
    web_dir = Path('c:/Dev/MERID/web')
    main_file = web_dir / 'main_15m_lean.py'
    
    print("=" * 80)
    print("FASTAPI CONTAMINATION ANALYSIS")
    print("=" * 80)
    print()
    
    # Analyze main file
    print("1. ANALYZING MAIN FILE: main_15m_lean.py")
    print("-" * 80)
    main_analysis = analyze_file(main_file)
    
    if 'error' in main_analysis:
        print(f"ERROR: {main_analysis['error']}")
        return
    
    print(f"App creation at line {main_analysis['app_creation']['line']}")
    print(f"Has lifespan: {main_analysis['app_creation']['has_lifespan']}")
    print()
    
    # Analyze imports
    print("2. IMPORT ANALYSIS")
    print("-" * 80)
    legacy_imports = []
    production_imports = []
    unknown_imports = []
    
    for imp in main_analysis['imports']:
        classification = classify_import(imp['module'])
        imp['classification'] = classification
        
        if classification == 'LEGACY':
            legacy_imports.append(imp)
        elif classification == 'PRODUCTION':
            production_imports.append(imp)
        else:
            unknown_imports.append(imp)
    
    print(f"Total imports: {len(main_analysis['imports'])}")
    print(f"  LEGACY: {len(legacy_imports)}")
    print(f"  PRODUCTION: {len(production_imports)}")
    print(f"  UNKNOWN: {len(unknown_imports)}")
    print()
    
    if legacy_imports:
        print("[WARNING] LEGACY IMPORTS FOUND:")
        for imp in legacy_imports:
            print(f"  Line {imp['line']}: from {imp['module']} import {imp['name']}")
        print()
    
    # Analyze routers
    print("3. ROUTER ANALYSIS")
    print("-" * 80)
    print(f"Total routers included: {len(main_analysis['routers'])}")
    print()
    
    router_details = []
    for router in main_analysis['routers']:
        print(f"Router: {router['name']} (line {router['line']})")
        print(f"  Args: {router['args']}, Keywords: {router['keywords']}")
        
        # Trace router source
        source_file, source_analysis = trace_router_source(router['name'], web_dir, main_analysis['imports'])
        if source_file:
            print(f"  Source: {source_file.relative_to(web_dir.parent)}")
            
            # Analyze router imports
            router_legacy = []
            router_production = []
            for imp in source_analysis.get('imports', []):
                classification = classify_import(imp['module'])
                if classification == 'LEGACY':
                    router_legacy.append(imp)
                elif classification == 'PRODUCTION':
                    router_production.append(imp)
            
            if router_legacy:
                print(f"  [WARNING] LEGACY IMPORTS IN ROUTER: {len(router_legacy)}")
                for imp in router_legacy[:5]:  # Show first 5
                    print(f"    from {imp['module']} import {imp['name']}")
            
            router_details.append({
                'name': router['name'],
                'source': str(source_file),
                'legacy_count': len(router_legacy),
                'production_count': len(router_production),
                'legacy_imports': router_legacy
            })
        else:
            print(f"  [WARNING] Source not found")
        print()
    
    # Summary
    print("=" * 80)
    print("CONTAMINATION SUMMARY")
    print("=" * 80)
    
    total_legacy = len(legacy_imports) + sum(r['legacy_count'] for r in router_details)
    total_production = len(production_imports) + sum(r['production_count'] for r in router_details)
    
    print(f"Main file legacy imports: {len(legacy_imports)}")
    print(f"Router legacy imports: {sum(r['legacy_count'] for r in router_details)}")
    print(f"Total legacy imports: {total_legacy}")
    print()
    print(f"Main file production imports: {len(production_imports)}")
    print(f"Router production imports: {sum(r['production_count'] for r in router_details)}")
    print(f"Total production imports: {total_production}")
    print()
    
    if total_legacy > 0:
        print("[WARNING] CONTAMINATION DETECTED")
        print("   Legacy code is present in the FastAPI app.")
        print("   This should be removed to prevent conflicts with the production stack.")
    else:
        print("[OK] NO LEGACY CONTAMINATION DETECTED")
    
    print()
    print("=" * 80)
    print("GAPS ANALYSIS")
    print("=" * 80)
    
    # Check for expected production components
    expected_production = {
        'merid.loop_15m': False,
        'merid.prediction.agent_grid_15m': False,
        'merid.event_venues.kalshi.ws_bridge': False,
        'data.unified_spot_service': False,
    }
    
    for imp in main_analysis['imports']:
        for expected in expected_production:
            if imp['module'].startswith(expected):
                expected_production[expected] = True
    
    print("Expected production components:")
    for component, present in expected_production.items():
        status = "[OK]" if present else "[MISSING]"
        print(f"  {status} {component}")
    
    print()
    print("=" * 80)

if __name__ == '__main__':
    analyze_contamination()
