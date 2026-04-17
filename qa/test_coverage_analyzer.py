"""
Test Coverage Analyzer for MERID.

Analyzes test coverage by mapping test files to source files and identifying
untested modules and functions.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ModuleCoverage:
    module_path: str
    has_tests: bool
    test_files: List[str]
    functions: List[str]
    tested_functions: Set[str]
    coverage_percentage: float


class TestCoverageAnalyzer:
    """
    Analyzes test coverage across codebase.
    
    Features:
    - Maps test files to source modules
    - Identifies untested modules
    - Calculates function-level coverage
    - Generates coverage report
    """
    
    def __init__(self, root_path: str):
        self.root_path = Path(root_path)
        self._source_modules: Dict[str, List[str]] = {}
        self._test_files: Dict[str, Set[str]] = {}
        self._coverage: Dict[str, ModuleCoverage] = {}
    
    def analyze(self) -> None:
        """Run coverage analysis."""
        logger.info("Starting test coverage analysis")
        
        self._scan_source_modules()
        self._scan_test_files()
        self._calculate_coverage()
        
        logger.info(f"Analysis complete: {len(self._coverage)} modules analyzed")
    
    def _scan_source_modules(self) -> None:
        """Scan source modules and extract functions."""
        for file_path in self.root_path.rglob("*.py"):
            if self._should_skip_file(file_path):
                continue
            
            if "test" in file_path.parts:
                continue
            
            functions = self._extract_functions(file_path)
            if functions:
                rel_path = str(file_path.relative_to(self.root_path))
                self._source_modules[rel_path] = functions
    
    def _scan_test_files(self) -> None:
        """Scan test files and identify tested modules."""
        test_dir = self.root_path / "tests"
        if not test_dir.exists():
            logger.warning("No tests directory found")
            return
        
        for test_file in test_dir.rglob("test_*.py"):
            tested_modules = self._extract_tested_modules(test_file)
            rel_path = str(test_file.relative_to(self.root_path))
            self._test_files[rel_path] = tested_modules
    
    def _extract_functions(self, file_path: Path) -> List[str]:
        """Extract function names from source file."""
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                tree = ast.parse(f.read())
            
            functions = []
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    if not node.name.startswith('_'):
                        functions.append(node.name)
            
            return functions
        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
            return []
    
    def _extract_tested_modules(self, test_file: Path) -> Set[str]:
        """Extract modules being tested from test file."""
        try:
            with open(test_file, 'r', encoding='utf-8-sig') as f:
                content = f.read()
                tree = ast.parse(content)
            
            tested = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.module:
                        tested.add(node.module)
            
            return tested
        except Exception as e:
            logger.error(f"Error parsing test file {test_file}: {e}")
            return set()
    
    def _calculate_coverage(self) -> None:
        """Calculate coverage for each module."""
        for module_path, functions in self._source_modules.items():
            module_name = self._path_to_module(module_path)
            
            test_files = []
            tested_functions = set()
            
            for test_file, tested_modules in self._test_files.items():
                if any(module_name.startswith(tm) for tm in tested_modules):
                    test_files.append(test_file)
            
            has_tests = len(test_files) > 0
            coverage_pct = 0.0
            
            if has_tests and functions:
                coverage_pct = (len(tested_functions) / len(functions)) * 100
            
            self._coverage[module_path] = ModuleCoverage(
                module_path=module_path,
                has_tests=has_tests,
                test_files=test_files,
                functions=functions,
                tested_functions=tested_functions,
                coverage_percentage=coverage_pct,
            )
    
    def _path_to_module(self, file_path: str) -> str:
        """Convert file path to module name."""
        return file_path.replace('\\', '.').replace('/', '.').replace('.py', '')
    
    def _should_skip_file(self, file_path: Path) -> bool:
        """Check if file should be skipped."""
        skip_dirs = {
            "__pycache__",
            ".git",
            ".venv",
            "venv",
            "node_modules",
            ".pytest_cache",
            "merid-ui",
            "flutter",
        }
        
        for part in file_path.parts:
            if part in skip_dirs:
                return True
        
        return False
    
    def get_untested_modules(self) -> List[ModuleCoverage]:
        """Get modules without tests."""
        return [
            cov for cov in self._coverage.values()
            if not cov.has_tests
        ]
    
    def get_critical_untested_modules(self) -> List[ModuleCoverage]:
        """Get critical modules without tests."""
        critical_paths = [
            "core/",
            "trading/",
            "governance/",
            "security/",
            "wallet/",
        ]
        
        return [
            cov for cov in self._coverage.values()
            if not cov.has_tests and any(cov.module_path.startswith(cp) for cp in critical_paths)
        ]
    
    def get_summary(self) -> Dict[str, object]:
        """Get coverage summary."""
        total_modules = len(self._coverage)
        tested_modules = len([c for c in self._coverage.values() if c.has_tests])
        untested_modules = total_modules - tested_modules
        
        critical_untested = len(self.get_critical_untested_modules())
        
        return {
            "total_modules": total_modules,
            "tested_modules": tested_modules,
            "untested_modules": untested_modules,
            "coverage_percentage": (tested_modules / total_modules * 100) if total_modules > 0 else 0,
            "critical_untested": critical_untested,
            "total_test_files": len(self._test_files),
        }
    
    def generate_report(self, output_path: str) -> None:
        """Generate coverage report."""
        summary = self.get_summary()
        untested = self.get_untested_modules()
        critical_untested = self.get_critical_untested_modules()
        
        with open(output_path, 'w') as f:
            f.write("# MERID Test Coverage Report\n\n")
            f.write(f"**Generated**: {Path(output_path).stat().st_mtime}\n\n")
            
            f.write("## Summary\n\n")
            f.write(f"- **Total Modules**: {summary['total_modules']}\n")
            f.write(f"- **Tested Modules**: {summary['tested_modules']}\n")
            f.write(f"- **Untested Modules**: {summary['untested_modules']}\n")
            f.write(f"- **Coverage**: {summary['coverage_percentage']:.1f}%\n")
            f.write(f"- **Critical Untested**: {summary['critical_untested']}\n")
            f.write(f"- **Total Test Files**: {summary['total_test_files']}\n\n")
            
            if critical_untested:
                f.write("## Critical Untested Modules\n\n")
                for cov in critical_untested[:50]:
                    f.write(f"### {cov.module_path}\n\n")
                    f.write(f"- **Functions**: {len(cov.functions)}\n")
                    f.write(f"- **Function List**: {', '.join(cov.functions[:10])}\n\n")
            
            f.write("## All Untested Modules\n\n")
            for cov in untested[:100]:
                f.write(f"- `{cov.module_path}` ({len(cov.functions)} functions)\n")
        
        logger.info(f"Coverage report generated: {output_path}")


def run_coverage_analysis(root_path: str, output_path: str) -> Dict[str, object]:
    """Run test coverage analysis."""
    analyzer = TestCoverageAnalyzer(root_path)
    
    logger.info(f"Starting coverage analysis: {root_path}")
    analyzer.analyze()
    
    summary = analyzer.get_summary()
    logger.info(f"Coverage: {summary['coverage_percentage']:.1f}%")
    
    analyzer.generate_report(output_path)
    
    return summary
