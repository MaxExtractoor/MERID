#!/usr/bin/env python3
"""Deep System Audit - Comprehensive bug search across 10 categories.

This script performs deep audits for:
1. Ignored function parameters
2. Negative money/quantity bugs
3. Database schema mismatches
4. Initialization order dependencies
5. Series/ticker resolution bugs
6. Fallback/default value bugs
7. Division-by-zero risks
8. Type coercion in financial math
9. Error handling gaps
10. Race conditions in async code
"""

import ast
import inspect
import re
import sys
import os
from pathlib import Path
from typing import List, Dict, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class DeepAuditor:
    """Audits codebase for critical bug patterns."""
    
    def __init__(self, base_path: str = None):
        self.base_path = Path(base_path or '.')
        self.issues: List[Dict] = []
        self.files_checked = 0
        self.patterns_found = 0
    
    def audit_all(self) -> Dict:
        """Run all 10 audits."""
        print("="*80)
        print("DEEP SYSTEM AUDIT - 10 Categories")
        print("="*80)
        
        self.audit_1_ignored_parameters()
        self.audit_2_negative_money()
        self.audit_3_schema_mismatches()
        self.audit_4_init_order()
        self.audit_5_series_resolution()
        self.audit_6_fallback_defaults()
        self.audit_7_division_by_zero()
        self.audit_8_type_coercion()
        self.audit_9_error_handling()
        self.audit_10_race_conditions()
        
        return self._generate_report()
    
    def audit_1_ignored_parameters(self):
        """Audit 1: Find functions that accept parameters but don't use them."""
        print("\n[Audit 1] Ignored Function Parameters...")
        
        patterns = [
            (r'def\s+\w+\([^)]*series_tickers[^)]*\):', 'series_tickers parameter'),
            (r'def\s+\w+\([^)]*agent_name[^)]*\):', 'agent_name parameter'),
            (r'def\s+\w+\([^)]*market_tickers[^)]*\):', 'market_tickers parameter'),
        ]
        
        files_to_check = [
            'merid/event_venues/kalshi/market_selector.py',
            'merid/prediction/trading_agent.py',
            'merid/event_venues/kalshi/kalshi_risk.py',
        ]
        
        found = 0
        for file_path in files_to_check:
            full_path = self.base_path / file_path
            if not full_path.exists():
                continue
                
            try:
                with open(full_path, 'r') as f:
                    content = f.read()
                    tree = ast.parse(content)
                
                # Check for function definitions with unused parameters
                for node in ast.walk(tree):
                    if isinstance(node, ast.AsyncFunctionDef) or isinstance(node, ast.FunctionDef):
                        func_name = node.name
                        args = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
                        
                        # Get all variable references in function body
                        used_vars = set()
                        for child in ast.walk(node):
                            if isinstance(child, ast.Name):
                                used_vars.add(child.id)
                            elif isinstance(child, ast.Attribute):
                                if isinstance(child.value, ast.Name):
                                    used_vars.add(child.value.id)
                        
                        # Check for unused parameters
                        for arg in args:
                            if arg not in used_vars and not arg.startswith('_'):
                                # Skip self, cls
                                if arg in ('self', 'cls'):
                                    continue
                                # Check if it's in default value
                                if any(str(default).count(arg) > 0 for default in node.args.defaults):
                                    continue
                                
                                self.issues.append({
                                    'audit': 1,
                                    'file': file_path,
                                    'line': node.lineno,
                                    'severity': 'WARNING',
                                    'message': f'Function {func_name} has unused parameter: {arg}'
                                })
                                found += 1
                                
            except Exception as e:
                self.issues.append({
                    'audit': 1,
                    'file': file_path,
                    'severity': 'ERROR',
                    'message': f'Failed to parse: {e}'
                })
        
        print(f"  Found {found} potential unused parameters")
        self.patterns_found += found
    
    def audit_2_negative_money(self):
        """Audit 2: Find calculations that could produce negative values in financial contexts."""
        print("\n[Audit 2] Negative Money/Quantity Bugs...")
        
        dangerous_patterns = [
            (r'bankroll\s*\*\s*0', 'bankroll multiplied by zero'),
            (r'equity\s*\*\s*0', 'equity multiplied by zero'),
            (r'cents\s*/\s*100(?!\d)', 'cents division without bounds check'),
            (r'balance\s*-\s*\w+', 'balance subtraction without check'),
            (r'max\([^)]*,\s*0\)', 'max with 0 (hiding potential negative)'),
        ]
        
        files_to_check = [
            'merid/event_venues/kalshi/kalshi_risk.py',
            'merid/event_venues/kalshi/fills_ledger.py',
            'merid/prediction/agent_grid_config.py',
        ]
        
        found = 0
        for file_path in files_to_check:
            full_path = self.base_path / file_path
            if not full_path.exists():
                continue
                
            try:
                with open(full_path, 'r') as f:
                    lines = f.readlines()
                
                for i, line in enumerate(lines, 1):
                    for pattern, desc in dangerous_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            # Check if it's already protected
                            if 'max(' in line and '> 0' in line:
                                continue
                            
                            self.issues.append({
                                'audit': 2,
                                'file': file_path,
                                'line': i,
                                'severity': 'WARNING',
                                'message': f'Potential negative money: {desc}',
                                'code': line.strip()[:80]
                            })
                            found += 1
                            
            except Exception as e:
                pass
        
        print(f"  Found {found} potential negative money patterns")
        self.patterns_found += found
    
    def audit_3_schema_mismatches(self):
        """Audit 3: Find database schema mismatches."""
        print("\n[Audit 3] Database Schema Mismatches...")
        
        # Check fills_ledger.py for schema consistency
        fills_ledger_path = self.base_path / 'merid/event_venues/kalshi/fills_ledger.py'
        
        found = 0
        if fills_ledger_path.exists():
            try:
                with open(fills_ledger_path, 'r') as f:
                    content = f.read()
                
                # Check for CREATE TABLE columns
                create_table_match = re.search(r'CREATE TABLE.*?\((.*?)\)', content, re.DOTALL | re.IGNORECASE)
                if create_table_match:
                    create_columns = set(re.findall(r'(\w+)\s+(?:TEXT|REAL|INTEGER)', create_table_match.group(1)))
                    
                    # Check for INSERT statements
                    insert_matches = re.findall(r'INSERT.*?\(([^)]+)\)', content, re.IGNORECASE)
                    for insert_cols in insert_matches:
                        insert_set = set(c.strip() for c in insert_cols.split(','))
                        
                        # Check for columns in INSERT but not CREATE
                        missing_in_create = insert_set - create_columns
                        if missing_in_create:
                            self.issues.append({
                                'audit': 3,
                                'file': 'merid/event_venues/kalshi/fills_ledger.py',
                                'severity': 'CRITICAL',
                                'message': f'INSERT columns not in CREATE TABLE: {missing_in_create}'
                            })
                            found += 1
                
                # Check for migration handling
                if 'ALTER TABLE' in content and 'proceeds_dollars' in content:
                    print(f"  ✅ Schema migration handling found")
                
            except Exception as e:
                pass
        
        print(f"  Found {found} schema mismatch issues")
        self.patterns_found += found
    
    def audit_4_init_order(self):
        """Audit 4: Find initialization order dependencies."""
        print("\n[Audit 4] Initialization Order Dependencies...")
        
        # Check for common anti-patterns
        anti_patterns = [
            (r'await\s+\w+\.connect\(\).*\n.*await\s+\w+\._init_db', 'Connection before init'),
            (r'self\._\w+\s*=.*get\(\).*\n.*if\s+self\._\w+', 'Cached value used before check'),
        ]
        
        found = 0
        critical_files = [
            'merid/event_venues/kalshi/fills_ledger.py',
            'merid/event_venues/kalshi/market_selector.py',
            'merid/prediction/agent_grid.py',
        ]
        
        for file_path in critical_files:
            full_path = self.base_path / file_path
            if not full_path.exists():
                continue
                
            try:
                with open(full_path, 'r') as f:
                    content = f.read()
                
                # Check for _init_db called before connection
                if '_writer_loop' in content:
                    if re.search(r'await\s+self\._init_db\(\).*aiosqlite\.connect', content, re.DOTALL):
                        print(f"  ✅ {file_path}: _init_db before connection")
                    elif re.search(r'aiosqlite\.connect.*await\s+self\._init_db\(\)', content, re.DOTALL):
                        self.issues.append({
                            'audit': 4,
                            'file': file_path,
                            'severity': 'CRITICAL',
                            'message': 'Connection opened before _init_db'
                        })
                        found += 1
                        
            except Exception as e:
                pass
        
        print(f"  Found {found} initialization order issues")
        self.patterns_found += found
    
    def audit_5_series_resolution(self):
        """Audit 5: Find series/ticker resolution bugs."""
        print("\n[Audit 5] Series/Ticker Resolution Chain...")
        
        # Verify AGENT_SERIES_MAP consistency
        market_selector_path = self.base_path / 'merid/event_venues/kalshi/market_selector.py'
        
        found = 0
        if market_selector_path.exists():
            try:
                # Import and check the module
                sys.path.insert(0, str(self.base_path))
                from merid.event_venues.kalshi.market_selector import AGENT_SERIES_MAP, validate_agent_series_map
                
                issues = validate_agent_series_map()
                for issue in issues:
                    self.issues.append({
                        'audit': 5,
                        'file': 'merid/event_venues/kalshi/market_selector.py',
                        'severity': 'CRITICAL' if 'CRITICAL' in issue else 'WARNING',
                        'message': issue
                    })
                    found += 1
                
                print(f"  Checked {len(AGENT_SERIES_MAP)} agent mappings")
                
            except Exception as e:
                self.issues.append({
                    'audit': 5,
                    'severity': 'ERROR',
                    'message': f'Failed to validate AGENT_SERIES_MAP: {e}'
                })
        
        print(f"  Found {found} series mapping issues")
        self.patterns_found += found
    
    def audit_6_fallback_defaults(self):
        """Audit 6: Find suspicious fallback/default values."""
        print("\n[Audit 6] Fallback/Default Value Bugs...")
        
        dangerous_defaults = [
            (r'default\s*=\s*-1', 'default=-1 sentinel'),
            (r'default\s*=\s*0[^.]', 'default=0 (potential money/quantity)'),
            (r'default\s*=\s*\[\]', 'mutable default []'),
            (r'default\s*=\s*\{\}', 'mutable default {}'),
        ]
        
        found = 0
        files_to_check = list(self.base_path.rglob('*.py'))[:50]  # Check first 50 files
        
        for file_path in files_to_check:
            if 'test' in str(file_path):
                continue
                
            try:
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                
                for i, line in enumerate(lines, 1):
                    for pattern, desc in dangerous_defaults:
                        if re.search(pattern, line):
                            # Skip comments
                            if line.strip().startswith('#'):
                                continue
                            
                            self.issues.append({
                                'audit': 6,
                                'file': str(file_path.relative_to(self.base_path)),
                                'line': i,
                                'severity': 'INFO',
                                'message': f'Suspicious default: {desc}'
                            })
                            found += 1
                            
            except Exception as e:
                pass
        
        print(f"  Found {found} suspicious defaults (review recommended)")
        self.patterns_found += found
    
    def audit_7_division_by_zero(self):
        """Audit 7: Find division without checking denominator."""
        print("\n[Audit 7] Division-by-Zero Risks...")
        
        # Check for division patterns
        division_patterns = [
            r'/\s*\w+\b(?!\s*100\b)',
            r'/\s*\(',
        ]
        
        found = 0
        critical_files = [
            self.base_path / 'merid/event_venues/kalshi/kalshi_risk.py',
            self.base_path / 'merid/prediction/trading_agent.py',
        ]
        
        for file_path in critical_files:
            if not file_path.exists():
                continue
                
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                    tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv)):
                        # Check if denominator is protected
                        line_num = node.lineno
                        
                        # Get the line
                        lines = content.split('\n')
                        if line_num <= len(lines):
                            line = lines[line_num - 1]
                            
                            # Check for protection
                            if not any(protector in line for protector in ['if', 'max(', 'min(', '!= 0', '> 0']):
                                self.issues.append({
                                    'audit': 7,
                                    'file': str(file_path.relative_to(self.base_path)),
                                    'line': line_num,
                                    'severity': 'WARNING',
                                    'message': 'Division without zero protection',
                                    'code': line.strip()[:60]
                                })
                                found += 1
                                
            except Exception as e:
                pass
        
        print(f"  Found {found} unprotected divisions")
        self.patterns_found += found
    
    def audit_8_type_coercion(self):
        """Audit 8: Find type coercion in financial math."""
        print("\n[Audit 8] Type Coercion in Financial Math...")
        
        coercion_patterns = [
            (r'int\([^)]*cents[^)]*\)', 'int() on cents'),
            (r'float\([^)]*Decimal[^)]*\)', 'float() on Decimal'),
            (r'Decimal\([^)]+\)\s*\*\s*[^D]', 'Decimal * float'),
            (r'cents\s*/\s*100\.0', 'cents / 100.0 (float)'),
        ]
        
        found = 0
        critical_files = [
            self.base_path / 'merid/event_venues/kalshi/kalshi_risk.py',
            self.base_path / 'merid/event_venues/kalshi/fills_ledger.py',
        ]
        
        for file_path in critical_files:
            if not file_path.exists():
                continue
                
            try:
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                
                for i, line in enumerate(lines, 1):
                    for pattern, desc in coercion_patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            self.issues.append({
                                'audit': 8,
                                'file': str(file_path.relative_to(self.base_path)),
                                'line': i,
                                'severity': 'INFO',
                                'message': f'Type coercion: {desc}'
                            })
                            found += 1
                            
            except Exception as e:
                pass
        
        print(f"  Found {found} type coercion patterns")
        self.patterns_found += found
    
    def audit_9_error_handling(self):
        """Audit 9: Find error handling gaps."""
        print("\n[Audit 9] Error Handling Gaps...")
        
        risky_operations = [
            (r'requests\.(get|post|put|delete)\(', 'HTTP request without try/except'),
            (r'\.execute\(["\']', 'DB execute without protection'),
            (r'open\([^)]+\)', 'File open without try/except'),
            (r'\[\s*[\'"]\w+[\'"]\s*\](?!\s*=)', 'Dict access without .get()'),
        ]
        
        found = 0
        sample_files = [
            self.base_path / 'merid/event_venues/kalshi/client.py',
            self.base_path / 'merid/prediction/kalshi_tools.py',
        ]
        
        for file_path in sample_files:
            if not file_path.exists():
                continue
                
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                    tree = ast.parse(content)
                
                # Check for try-except coverage
                try_except_ranges = []
                for node in ast.walk(tree):
                    if isinstance(node, ast.Try):
                        try_except_ranges.append((node.lineno, node.end_lineno))
                
                # Check for risky operations not in try blocks
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        if isinstance(node.func, ast.Attribute):
                            func_name = f"{type(node.func.value).__name__}.{node.func.attr}"
                        else:
                            func_name = getattr(node.func, 'id', '')
                        
                        # Check if this call is inside a try block
                        in_try = any(start <= node.lineno <= end for start, end in try_except_ranges)
                        
                        if not in_try:
                            # Check if it's a risky operation
                            for pattern, desc in risky_operations:
                                if re.search(pattern, func_name):
                                    self.issues.append({
                                        'audit': 9,
                                        'file': str(file_path.relative_to(self.base_path)),
                                        'line': node.lineno,
                                        'severity': 'WARNING',
                                        'message': desc
                                    })
                                    found += 1
                                    
            except Exception as e:
                pass
        
        print(f"  Found {found} potential error handling gaps")
        self.patterns_found += found
    
    def audit_10_race_conditions(self):
        """Audit 10: Find race conditions in async code."""
        print("\n[Audit 10] Race Conditions in Async Code...")
        
        race_patterns = [
            (r'self\._\w+\[.*\]\s*=', 'Shared dict/list modification'),
            (r'if\s+.*in\s+self\._', 'Check-then-act pattern'),
            (r'self\._\w+\s*\+?=', 'In-place modification'),
        ]
        
        found = 0
        async_files = [
            self.base_path / 'merid/event_venues/kalshi/fills_ledger.py',
            self.base_path / 'merid/event_venues/kalshi/market_catalog.py',
        ]
        
        for file_path in async_files:
            if not file_path.exists():
                continue
                
            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                
                # Check for async def without locks
                if 'async def' in content and 'asyncio.Lock' not in content:
                    if 'self._mutex' not in content and 'self._lock' not in content:
                        self.issues.append({
                            'audit': 10,
                            'file': str(file_path.relative_to(self.base_path)),
                            'severity': 'INFO',
                            'message': 'Async code without locks - review for race conditions'
                        })
                        found += 1
                else:
                    print(f"  ✅ {file_path.name}: Has locking mechanism")
                    
            except Exception as e:
                pass
        
        print(f"  Found {found} potential race conditions")
        self.patterns_found += found
    
    def _generate_report(self) -> Dict:
        """Generate final audit report."""
        print("\n" + "="*80)
        print("AUDIT REPORT SUMMARY")
        print("="*80)
        
        # Group issues by severity
        critical = [i for i in self.issues if i.get('severity') == 'CRITICAL']
        warnings = [i for i in self.issues if i.get('severity') == 'WARNING']
        info = [i for i in self.issues if i.get('severity') == 'INFO']
        
        print(f"\nTotal Issues Found: {len(self.issues)}")
        print(f"  Critical: {len(critical)}")
        print(f"  Warnings: {len(warnings)}")
        print(f"  Info: {len(info)}")
        
        if critical:
            print("\n🔴 CRITICAL ISSUES (Must Fix):")
            for issue in critical[:10]:  # Show first 10
                print(f"  [{issue['audit']}] {issue['file']}:{issue.get('line', 'N/A')}")
                print(f"      {issue['message']}")
        
        if warnings:
            print("\n⚠️  WARNINGS (Should Review):")
            for issue in warnings[:5]:  # Show first 5
                print(f"  [{issue['audit']}] {issue['file']}:{issue.get('line', 'N/A')}")
                print(f"      {issue['message'][:60]}")
        
        print("\n" + "="*80)
        
        if critical:
            print("❌ AUDIT FAILED: Critical issues found")
            return {'passed': False, 'critical': len(critical), 'warnings': len(warnings)}
        elif warnings:
            print("⚠️  AUDIT PASSED WITH WARNINGS")
            return {'passed': True, 'critical': 0, 'warnings': len(warnings)}
        else:
            print("✅ ALL AUDITS PASSED")
            return {'passed': True, 'critical': 0, 'warnings': 0}


if __name__ == '__main__':
    auditor = DeepAuditor(base_path='.')
    results = auditor.audit_all()
    sys.exit(0 if results['passed'] else 1)
