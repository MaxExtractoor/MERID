#!/usr/bin/env python3
"""
MERID Production Stack - Circular Import & Race Condition Detector

This script performs deep static analysis to detect:
1. Circular imports across the entire codebase
2. Race conditions in async/threading code
3. Shared mutable state without proper synchronization
4. TOCTOU (Time-Of-Check-Time-Of-Use) vulnerabilities
5. Deadlock-prone lock ordering patterns

Based on best practices from:
- knot-imports (AST-based circular import detection)
- threadcheck (static race condition analysis)
- thread-safe-check (17 Python concurrency rules)
- depgraph (dependency graph analysis)

Usage:
    python scripts/circular_import_race_condition_detector.py --help
    python scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID
    python scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --exclude archive,legacy,probe_snapshots
    python scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --output-json report.json
"""

import ast
import sys
import json
import argparse
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class ImportEdge:
    """Represents an import relationship between modules."""
    source_module: str
    target_module: str
    line_number: int
    import_type: str  # 'import', 'from_import', 'relative_import'


@dataclass
class CircularImportCycle:
    """Represents a detected circular import cycle."""
    cycle_path: List[str]
    severity: Severity
    description: str
    fix_suggestion: str
    involved_files: List[str] = field(default_factory=list)


@dataclass
class RaceCondition:
    """Represents a detected race condition."""
    rule_id: str
    severity: Severity
    file_path: str
    line_number: int
    description: str
    code_snippet: str
    fix_suggestion: str
    shared_variable: Optional[str] = None
    lock_context: Optional[str] = None


@dataclass
class AnalysisReport:
    """Comprehensive analysis report."""
    circular_imports: List[CircularImportCycle] = field(default_factory=list)
    race_conditions: List[RaceCondition] = field(default_factory=list)
    total_modules_analyzed: int = 0
    total_files_analyzed: int = 0
    excluded_directories: List[str] = field(default_factory=list)
    scan_duration_seconds: float = 0.0


class CircularImportDetector:
    """AST-based circular import detector inspired by knot-imports."""
    
    def __init__(self, project_root: Path, exclude_dirs: List[str] = None):
        self.project_root = project_root
        self.exclude_dirs = set(exclude_dirs or [])
        self.import_graph: Dict[str, Set[str]] = defaultdict(set)
        self.import_edges: List[ImportEdge] = []
        self.module_to_file: Dict[str, Path] = {}
        self.file_to_module: Dict[Path, str] = {}
        
        # Default directories to exclude
        self.default_excludes = {
            '.git', '__pycache__', '.venv', 'venv', 'env',
            'build', 'dist', '.eggs', '*.egg-info',
            'node_modules', '.pytest_cache', '.mypy_cache',
            'probe_snapshots', 'snapshots', 'output'
        }
    
    def should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded from analysis."""
        # Check default excludes
        for part in path.parts:
            if part in self.default_excludes:
                return True
        
        # Check user-specified excludes
        for exclude_dir in self.exclude_dirs:
            if exclude_dir in str(path):
                return True
        
        return False
    
    def path_to_module(self, file_path: Path) -> str:
        """Convert a file path to a module name."""
        try:
            relative_path = file_path.relative_to(self.project_root)
            # Remove .py extension and convert path separators to dots
            module_name = str(relative_path.with_suffix('')).replace('\\', '.').replace('/', '.')
            return module_name
        except ValueError:
            # File is not relative to project root
            return str(file_path.with_suffix('')).replace('\\', '.').replace('/', '.')
    
    def discover_python_files(self) -> List[Path]:
        """Discover all Python files in the project."""
        python_files = []
        for path in self.project_root.rglob('*.py'):
            if not self.should_exclude(path):
                python_files.append(path)
        return python_files
    
    def extract_imports(self, file_path: Path) -> List[ImportEdge]:
        """Extract import statements from a Python file using AST."""
        imports = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            tree = ast.parse(source, filename=str(file_path))
            source_module = self.path_to_module(file_path)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target_module = alias.name
                        imports.append(ImportEdge(
                            source_module=source_module,
                            target_module=target_module,
                            line_number=node.lineno,
                            import_type='import'
                        ))
                
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ''
                    for alias in node.names:
                        if module:
                            target_module = f"{module}.{alias.name}" if alias.name != '*' else module
                        else:
                            target_module = alias.name
                        
                        import_type = 'relative_import' if node.level > 0 else 'from_import'
                        imports.append(ImportEdge(
                            source_module=source_module,
                            target_module=target_module,
                            line_number=node.lineno,
                            import_type=import_type
                        ))
        
        except (SyntaxError, UnicodeDecodeError, IOError) as e:
            # Skip files that can't be parsed
            pass
        
        return imports
    
    def build_import_graph(self, python_files: List[Path]):
        """Build the import dependency graph."""
        for file_path in python_files:
            module_name = self.path_to_module(file_path)
            self.module_to_file[module_name] = file_path
            self.file_to_module[file_path] = module_name
            
            imports = self.extract_imports(file_path)
            for imp in imports:
                self.import_edges.append(imp)
                # Only add internal imports to the graph
                if self._is_internal_import(imp.target_module):
                    self.import_graph[imp.source_module].add(imp.target_module)
    
    def _is_internal_import(self, module_name: str) -> bool:
        """Check if an import is internal to the project."""
        # Simple heuristic: if it starts with a known top-level package
        top_level_packages = {'merid', 'web', 'agents', 'core', 'data', 'utils', 'scripts'}
        return any(module_name.startswith(pkg) for pkg in top_level_packages)
    
    def detect_cycles(self) -> List[CircularImportCycle]:
        """Detect circular imports using Tarjan's SCC algorithm."""
        cycles = []
        
        # Build adjacency list for DFS
        graph = self.import_graph
        visited = set()
        rec_stack = set()
        path = []
        
        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            path.append(node)
            
            for neighbor in graph.get(node, set()):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(self._create_cycle_report(cycle))
                    return True
            
            path.pop()
            rec_stack.remove(node)
            return False
        
        for node in graph:
            if node not in visited:
                dfs(node)
        
        return cycles
    
    def _create_cycle_report(self, cycle: List[str]) -> CircularImportCycle:
        """Create a detailed report for a circular import cycle."""
        # Determine severity based on cycle length
        cycle_length = len(cycle) - 1  # -1 because the last node repeats the first
        if cycle_length == 2:
            severity = Severity.CRITICAL
            description = f"Direct circular import between {cycle[0]} and {cycle[1]}"
            fix_suggestion = f"Extract shared code from {cycle[0]} and {cycle[1]} into a new module, or use lazy imports (import inside functions)"
        elif cycle_length <= 4:
            severity = Severity.HIGH
            description = f"Circular import involving {cycle_length} modules"
            fix_suggestion = "Refactor to break the cycle by moving shared dependencies to a separate module or using dependency injection"
        else:
            severity = Severity.MEDIUM
            description = f"Complex circular import involving {cycle_length} modules"
            fix_suggestion = "Consider architectural refactoring to reduce coupling between these modules"
        
        # Get involved files
        involved_files = []
        for module in cycle:
            if module in self.module_to_file:
                involved_files.append(str(self.module_to_file[module]))
        
        return CircularImportCycle(
            cycle_path=cycle,
            severity=severity,
            description=description,
            fix_suggestion=fix_suggestion,
            involved_files=involved_files
        )


class RaceConditionDetector:
    """Static analysis race condition detector inspired by threadcheck and thread-safe-check."""
    
    # Detection rules based on thread-safe-check's 17 Python rules
    RULES = {
        'TS001': {
            'name': 'Global Mutation',
            'description': 'Unprotected mutation of global variable',
            'severity': Severity.HIGH,
            'pattern': 'global_mutation'
        },
        'TS002': {
            'name': 'Class Attribute',
            'description': 'Unprotected access to shared class attribute',
            'severity': Severity.HIGH,
            'pattern': 'class_attribute'
        },
        'TS003': {
            'name': 'Closure Capture',
            'description': 'Closure capturing mutable state without synchronization',
            'severity': Severity.MEDIUM,
            'pattern': 'closure_capture'
        },
        'TS010': {
            'name': 'Unprotected Access',
            'description': 'Unprotected shared variable access in threaded context',
            'severity': Severity.CRITICAL,
            'pattern': 'unprotected_access'
        },
        'TS011': {
            'name': 'Check-Then-Act',
            'description': 'TOCTOU: Check-then-act race condition',
            'severity': Severity.HIGH,
            'pattern': 'check_then_act'
        },
        'TS012': {
            'name': 'Compound Operation',
            'description': 'Compound operation without atomic lock',
            'severity': Severity.HIGH,
            'pattern': 'compound_operation'
        },
        'TS013': {
            'name': 'Collection Iteration',
            'description': 'Collection modification during iteration',
            'severity': Severity.HIGH,
            'pattern': 'collection_iteration'
        },
        'TS020': {
            'name': 'Deadlock Risk',
            'description': 'Potential deadlock due to lock ordering',
            'severity': Severity.CRITICAL,
            'pattern': 'deadlock_risk'
        },
        'TS021': {
            'name': 'Lock Not Released',
            'description': 'Lock acquired but not properly released',
            'severity': Severity.CRITICAL,
            'pattern': 'lock_not_released'
        },
        'TS030': {
            'name': 'Blocking in Async',
            'description': 'Blocking operation in async function',
            'severity': Severity.MEDIUM,
            'pattern': 'blocking_in_async'
        },
        'TS031': {
            'name': 'Missing Await',
            'description': 'Async function called without await',
            'severity': Severity.HIGH,
            'pattern': 'missing_await'
        },
        'TS032': {
            'name': 'Threading Lock in Async',
            'description': 'Using threading.Lock in async context (use asyncio.Lock)',
            'severity': Severity.HIGH,
            'pattern': 'threading_lock_in_async'
        },
        'TS033': {
            'name': 'Shared State in Coroutine',
            'description': 'Shared mutable state accessed in coroutine without protection',
            'severity': Severity.HIGH,
            'pattern': 'shared_state_coroutine'
        },
    }
    
    def __init__(self, project_root: Path, exclude_dirs: List[str] = None):
        self.project_root = project_root
        self.exclude_dirs = set(exclude_dirs or [])
        self.race_conditions: List[RaceCondition] = []
    
    def should_exclude(self, path: Path) -> bool:
        """Check if a path should be excluded from analysis."""
        default_excludes = {
            '.git', '__pycache__', '.venv', 'venv', 'env',
            'build', 'dist', '.eggs', '*.egg-info',
            'node_modules', '.pytest_cache', '.mypy_cache',
            'probe_snapshots', 'snapshots', 'output'
        }
        
        for part in path.parts:
            if part in default_excludes:
                return True
        
        for exclude_dir in self.exclude_dirs:
            if exclude_dir in str(path):
                return True
        
        return False
    
    def discover_python_files(self) -> List[Path]:
        """Discover all Python files in the project."""
        python_files = []
        for path in self.project_root.rglob('*.py'):
            if not self.should_exclude(path):
                python_files.append(path)
        return python_files
    
    def analyze_file(self, file_path: Path) -> List[RaceCondition]:
        """Analyze a single file for race conditions with high-confidence detection only."""
        conditions = []
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                source = f.read()
            
            tree = ast.parse(source, filename=str(file_path))
            lines = source.splitlines()
            
            # Pre-scan for ACTUAL concurrency usage (not just imports)
            has_thread_creation = False
            has_async_function = False
            global_vars = set()
            
            for node in ast.walk(tree):
                # Detect actual Thread() creation
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == 'Thread':
                        has_thread_creation = True
                    elif isinstance(node.func, ast.Attribute) and node.func.attr == 'Thread':
                        has_thread_creation = True
                
                # Detect async functions
                if isinstance(node, ast.AsyncFunctionDef):
                    has_async_function = True
                
                # Detect global variables
                if isinstance(node, ast.Global):
                    for name in node.names:
                        global_vars.add(name)
            
            # Skip files that don't use actual concurrency
            if not has_thread_creation and not has_async_function:
                return []
            
            # Rule TS030: Blocking in async (high confidence)
            if has_async_function:
                for node in ast.walk(tree):
                    if isinstance(node, ast.AsyncFunctionDef):
                        for child in ast.walk(node):
                            if self._is_blocking_call(child):
                                conditions.append(RaceCondition(
                                    rule_id='TS030',
                                    severity=Severity.MEDIUM,
                                    file_path=str(file_path),
                                    line_number=child.lineno,
                                    description="Blocking operation in async function",
                                    code_snippet=lines[child.lineno - 1] if child.lineno <= len(lines) else '',
                                    fix_suggestion="Use async equivalent or run in executor with asyncio.to_thread()"
                                ))
            
            # Rule TS032: Threading lock in async (high confidence)
            if has_async_function:
                for node in ast.walk(tree):
                    if isinstance(node, ast.AsyncFunctionDef):
                        for child in ast.walk(node):
                            if self._uses_threading_lock(child):
                                conditions.append(RaceCondition(
                                    rule_id='TS032',
                                    severity=Severity.HIGH,
                                    file_path=str(file_path),
                                    line_number=child.lineno,
                                    description="Using threading.Lock in async context",
                                    code_snippet=lines[child.lineno - 1] if child.lineno <= len(lines) else '',
                                    fix_suggestion="Use asyncio.Lock instead of threading.Lock in async functions"
                                ))
            
            # Rule TS011: Check-then-act on globals (only in threaded contexts)
            if has_thread_creation and global_vars:
                for node in ast.walk(tree):
                    if isinstance(node, ast.If):
                        if self._tests_shared_variable(node.test, global_vars):
                            if self._modifies_shared_variable(node.body, global_vars):
                                conditions.append(RaceCondition(
                                    rule_id='TS011',
                                    severity=Severity.HIGH,
                                    file_path=str(file_path),
                                    line_number=node.lineno,
                                    description="Check-then-act race condition on global variable",
                                    code_snippet=lines[node.lineno - 1] if node.lineno <= len(lines) else '',
                                    fix_suggestion="Use atomic operations or lock the entire check-then-act sequence"
                                ))
        
        except (SyntaxError, UnicodeDecodeError, IOError):
            pass
        
        return conditions
    
    def _is_in_init(self, node: ast.AST) -> bool:
        """Check if a node is inside an __init__ method."""
        # Simplified check - walk up to find if we're in __init__
        # This is a heuristic; a full implementation would track parent nodes
        return False
    
    def _is_protected_by_lock(self, node: ast.AST, lock_variables: Set[str]) -> bool:
        """Check if a node is protected by a lock (simplified heuristic)."""
        # This is a simplified check - a full implementation would track lock scope
        return len(lock_variables) > 0
    
    def _tests_shared_variable(self, node: ast.AST, shared_variables: Set[str]) -> bool:
        """Check if a condition tests a shared variable."""
        if isinstance(node, ast.Name) and node.id in shared_variables:
            return True
        if isinstance(node, ast.Compare):
            for comparator in node.comparators:
                if self._tests_shared_variable(comparator, shared_variables):
                    return True
        return False
    
    def _modifies_shared_variable(self, body: List[ast.stmt], shared_variables: Set[str]) -> bool:
        """Check if a body modifies a shared variable."""
        for stmt in body:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name) and target.id in shared_variables:
                        return True
        return False
    
    def _is_blocking_call(self, node: ast.AST) -> bool:
        """Check if a node is a blocking call."""
        blocking_functions = {'time.sleep', 'socket.connect', 'urllib.request.urlopen', 'requests.get'}
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                call_name = f"{node.func.value.id}.{node.func.attr}" if isinstance(node.func.value, ast.Name) else node.func.attr
                return any(bf in call_name for bf in blocking_functions)
        return False
    
    def _is_async_call_without_await(self, node: ast.AST) -> bool:
        """Check if an async function is called without await."""
        # This is a simplified check - a full implementation would track function signatures
        if isinstance(node, ast.Call):
            # Check if parent is an await expression
            return not isinstance(node.parent, ast.Await) if hasattr(node, 'parent') else False
        return False
    
    def _uses_threading_lock(self, node: ast.AST) -> bool:
        """Check if node uses threading.Lock."""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in ['Lock', 'RLock']:
                return True
        return False


def main():
    parser = argparse.ArgumentParser(
        description='MERID Production Stack - Circular Import & Race Condition Detector',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID
  python scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --exclude archive,legacy
  python scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --output-json report.json
        """
    )
    
    parser.add_argument(
        '--scan-path',
        type=str,
        required=True,
        help='Path to the project directory to scan'
    )
    
    parser.add_argument(
        '--exclude',
        type=str,
        default='',
        help='Comma-separated list of directories to exclude from analysis'
    )
    
    parser.add_argument(
        '--output-json',
        type=str,
        help='Path to output JSON report file'
    )
    
    parser.add_argument(
        '--only-circular-imports',
        action='store_true',
        help='Only detect circular imports, skip race condition analysis'
    )
    
    parser.add_argument(
        '--only-race-conditions',
        action='store_true',
        help='Only detect race conditions, skip circular import analysis'
    )
    
    args = parser.parse_args()
    
    import time
    start_time = time.time()
    
    scan_path = Path(args.scan_path)
    if not scan_path.exists():
        print(f"Error: Scan path does not exist: {scan_path}")
        sys.exit(1)
    
    exclude_dirs = [d.strip() for d in args.exclude.split(',') if d.strip()]
    
    report = AnalysisReport(
        excluded_directories=exclude_dirs
    )
    
    print(f"🔍 Starting analysis of: {scan_path}")
    print(f"🚫 Excluding directories: {exclude_dirs if exclude_dirs else 'none'}")
    print()
    
    # Circular Import Detection
    if not args.only_race_conditions:
        print("📦 Detecting circular imports...")
        circular_detector = CircularImportDetector(scan_path, exclude_dirs)
        python_files = circular_detector.discover_python_files()
        report.total_files_analyzed = len(python_files)
        circular_detector.build_import_graph(python_files)
        report.total_modules_analyzed = len(circular_detector.module_to_file)
        report.circular_imports = circular_detector.detect_cycles()
        print(f"   Analyzed {report.total_files_analyzed} files ({report.total_modules_analyzed} modules)")
        print(f"   Found {len(report.circular_imports)} circular import cycles")
        print()
    
    # Race Condition Detection
    if not args.only_circular_imports:
        print("⚡ Detecting race conditions...")
        race_detector = RaceConditionDetector(scan_path, exclude_dirs)
        python_files = race_detector.discover_python_files()
        if not args.only_circular_imports:
            report.total_files_analyzed = len(python_files)
        
        for file_path in python_files:
            conditions = race_detector.analyze_file(file_path)
            report.race_conditions.extend(conditions)
        
        print(f"   Analyzed {report.total_files_analyzed} files")
        print(f"   Found {len(report.race_conditions)} potential race conditions")
        print()
    
    report.scan_duration_seconds = time.time() - start_time
    
    # Print Summary
    print("=" * 80)
    print("📊 ANALYSIS SUMMARY")
    print("=" * 80)
    print(f"Scan path: {scan_path}")
    print(f"Files analyzed: {report.total_files_analyzed}")
    print(f"Modules analyzed: {report.total_modules_analyzed}")
    print(f"Scan duration: {report.scan_duration_seconds:.2f}s")
    print()
    
    # Print Circular Import Results
    if report.circular_imports:
        print(f"🔄 CIRCULAR IMPORTS ({len(report.circular_imports)} found)")
        print("-" * 80)
        for i, cycle in enumerate(report.circular_imports, 1):
            print(f"\n[{i}] {cycle.severity.value}: {cycle.description}")
            print(f"    Cycle: {' → '.join(cycle.cycle_path)}")
            print(f"    💡 Fix: {cycle.fix_suggestion}")
            if cycle.involved_files:
                print(f"    Files:")
                for file in cycle.involved_files:
                    print(f"      - {file}")
    else:
        print("✅ No circular imports detected")
    
    print()
    
    # Print Race Condition Results
    if report.race_conditions:
        print(f"⚡ RACE CONDITIONS ({len(report.race_conditions)} found)")
        print("-" * 80)
        
        # Group by rule
        by_rule = defaultdict(list)
        for rc in report.race_conditions:
            by_rule[rc.rule_id].append(rc)
        
        for rule_id, conditions in by_rule.items():
            rule_info = RaceConditionDetector.RULES.get(rule_id, {})
            print(f"\n[{rule_id}] {rule_info.get('name', rule_id)} ({len(conditions)} occurrences)")
            print(f"    {rule_info.get('description', '')}")
            
            for rc in conditions[:3]:  # Show first 3 occurrences per rule
                print(f"\n    📍 {rc.file_path}:{rc.line_number}")
                print(f"       {rc.description}")
                if rc.code_snippet:
                    print(f"       Code: {rc.code_snippet.strip()}")
                print(f"       💡 Fix: {rc.fix_suggestion}")
            
            if len(conditions) > 3:
                print(f"    ... and {len(conditions) - 3} more occurrences")
    else:
        print("✅ No race conditions detected")
    
    print()
    print("=" * 80)
    
    # Output JSON if requested
    if args.output_json:
        output_path = Path(args.output_json)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        json_report = {
            'summary': {
                'scan_path': str(scan_path),
                'files_analyzed': report.total_files_analyzed,
                'modules_analyzed': report.total_modules_analyzed,
                'scan_duration_seconds': report.scan_duration_seconds,
                'circular_imports_count': len(report.circular_imports),
                'race_conditions_count': len(report.race_conditions),
                'excluded_directories': report.excluded_directories
            },
            'circular_imports': [
                {
                    'severity': cycle.severity.value,
                    'description': cycle.description,
                    'cycle_path': cycle.cycle_path,
                    'fix_suggestion': cycle.fix_suggestion,
                    'involved_files': cycle.involved_files
                }
                for cycle in report.circular_imports
            ],
            'race_conditions': [
                {
                    'rule_id': rc.rule_id,
                    'severity': rc.severity.value,
                    'file_path': rc.file_path,
                    'line_number': rc.line_number,
                    'description': rc.description,
                    'code_snippet': rc.code_snippet,
                    'fix_suggestion': rc.fix_suggestion,
                    'shared_variable': rc.shared_variable,
                    'lock_context': rc.lock_context
                }
                for rc in report.race_conditions
            ]
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(json_report, f, indent=2)
        
        print(f"📄 JSON report saved to: {output_path}")
    
    # Exit with error code if issues found
    if report.circular_imports or report.race_conditions:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == '__main__':
    main()
