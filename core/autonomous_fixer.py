"""Autonomous Coverage Fixer Agent for MERID.

This agent automatically identifies coverage gaps and generates
fixing tests to achieve target coverage thresholds.
"""

import subprocess
import json
import os
import re
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class CoverageGap:
    """Represents a coverage gap in a file."""
    file_path: str
    line_number: int
    line_content: str
    context: str  # function/class context
    gap_type: str  # branch, statement, missing


@dataclass
class FixResult:
    """Result of a coverage fix attempt."""
    file_path: str
    test_file_path: str
    lines_added: int
    tests_added: int
    coverage_before: float
    coverage_after: float
    success: bool
    error_message: str = ""


class CoverageAnalyzer:
    """Analyzes coverage reports to identify gaps."""
    
    def __init__(self):
        self.logger = logger.bind(component="CoverageAnalyzer")
    
    def get_coverage_report(self, source_path: str = None) -> Dict[str, Any]:
        """Get JSON coverage report for analysis."""
        try:
            # Generate JSON coverage report
            cmd = ["coverage", "json", "-o", "-"]
            if source_path:
                cmd.extend(["--include", f"{source_path}/*"])
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=os.getcwd()
            )
            
            if result.returncode == 0:
                return json.loads(result.stdout)
            else:
                self.logger.error("coverage_report_failed", stderr=result.stderr)
                return {}
        except Exception as e:
            self.logger.error("coverage_analysis_error", error=str(e))
            return {}
    
    def identify_coverage_gaps(self, file_path: str, min_coverage: float = 85.0) -> List[CoverageGap]:
        """Identify specific coverage gaps in a file."""
        gaps = []
        
        # Get missing lines
        try:
            result = subprocess.run(
                ["coverage", "report", "--show-missing", "--include", file_path],
                capture_output=True,
                text=True
            )
            
            # Parse missing lines from output
            missing_lines = self._parse_missing_lines(result.stdout)
            
            # Read source file to get context
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    lines = f.readlines()
                
                for line_num in missing_lines:
                    if line_num <= len(lines):
                        line_content = lines[line_num - 1].strip()
                        context = self._get_context(lines, line_num)
                        
                        gap = CoverageGap(
                            file_path=file_path,
                            line_number=line_num,
                            line_content=line_content,
                            context=context,
                            gap_type=self._classify_gap(line_content)
                        )
                        gaps.append(gap)
            
            self.logger.info(
                "gaps_identified",
                file=file_path,
                gap_count=len(gaps),
                min_coverage=min_coverage
            )
            
        except Exception as e:
            self.logger.error("gap_identification_failed", error=str(e))
        
        return gaps
    
    def _parse_missing_lines(self, coverage_output: str) -> List[int]:
        """Parse missing line numbers from coverage report."""
        missing_lines = []
        
        # Look for lines like "Missing: 45-50, 67, 89-92"
        for line in coverage_output.split('\n'):
            if 'Missing:' in line:
                parts = line.split('Missing:')
                if len(parts) > 1:
                    ranges = parts[1].strip()
                    for range_str in ranges.split(','):
                        range_str = range_str.strip()
                        if '-' in range_str:
                            start, end = map(int, range_str.split('-'))
                            missing_lines.extend(range(start, end + 1))
                        else:
                            try:
                                missing_lines.append(int(range_str))
                            except ValueError:
                                pass
        
        return missing_lines
    
    def _get_context(self, lines: List[str], line_num: int) -> str:
        """Get the function/class context for a line."""
        # Look backwards to find function/class definition
        for i in range(line_num - 1, -1, -1):
            line = lines[i]
            if line.strip().startswith('def ') or line.strip().startswith('class '):
                return line.strip()
        return "unknown"
    
    def _classify_gap(self, line_content: str) -> str:
        """Classify the type of coverage gap."""
        line = line_content.strip()
        
        if line.startswith('if ') or line.startswith('elif ') or line.startswith('else:'):
            return "branch"
        elif line.startswith('except') or line.startswith('finally:'):
            return "exception"
        elif line.startswith('return') or line.startswith('raise'):
            return "statement"
        elif 'assert' in line:
            return "assertion"
        else:
            return "statement"


class AutonomousCoverageFixer:
    """Automatically fixes coverage gaps by generating tests."""
    
    def __init__(self, llm_client=None):
        self.analyzer = CoverageAnalyzer()
        self.llm_client = llm_client
        self.logger = logger.bind(component="AutonomousCoverageFixer")
    
    async def fix_module_coverage(
        self,
        module_path: str,
        target_coverage: float = 85.0
    ) -> FixResult:
        """Automatically fix coverage for a module."""
        
        self.logger.info(
            "fix_started",
            module=module_path,
            target=target_coverage
        )
        
        # Get current coverage
        coverage_before = self._get_file_coverage(module_path)
        
        if coverage_before >= target_coverage:
            self.logger.info("coverage_already_met", current=coverage_before)
            return FixResult(
                file_path=module_path,
                test_file_path="",
                lines_added=0,
                tests_added=0,
                coverage_before=coverage_before,
                coverage_after=coverage_before,
                success=True,
                error_message="Coverage already meets target"
            )
        
        # Identify gaps
        gaps = self.analyzer.identify_coverage_gaps(module_path, target_coverage)
        
        if not gaps:
            self.logger.warning("no_gaps_identified", module=module_path)
            return FixResult(
                file_path=module_path,
                test_file_path="",
                lines_added=0,
                tests_added=0,
                coverage_before=coverage_before,
                coverage_after=coverage_before,
                success=False,
                error_message="Could not identify coverage gaps"
            )
        
        # Generate tests for gaps
        test_file_path = self._get_test_file_path(module_path)
        tests_added = await self._generate_tests_for_gaps(gaps, test_file_path)
        
        # Run tests and verify coverage
        test_success = self._run_tests(test_file_path)
        
        if test_success:
            coverage_after = self._get_file_coverage(module_path)
        else:
            coverage_after = coverage_before
        
        success = coverage_after >= target_coverage
        
        result = FixResult(
            file_path=module_path,
            test_file_path=test_file_path,
            lines_added=tests_added * 10,  # Estimate
            tests_added=tests_added,
            coverage_before=coverage_before,
            coverage_after=coverage_after,
            success=success
        )
        
        self.logger.info(
            "fix_completed",
            module=module_path,
            before=coverage_before,
            after=coverage_after,
            success=success
        )
        
        return result
    
    def _get_file_coverage(self, file_path: str) -> float:
        """Get current coverage percentage for a file."""
        try:
            result = subprocess.run(
                ["coverage", "report", "--include", file_path],
                capture_output=True,
                text=True
            )
            
            # Parse percentage from output
            for line in result.stdout.split('\n'):
                if file_path in line or os.path.basename(file_path) in line:
                    # Look for percentage pattern like "85%"
                    match = re.search(r'(\d+)%', line)
                    if match:
                        return float(match.group(1))
            
            return 0.0
        except Exception as e:
            self.logger.error("coverage_check_failed", error=str(e))
            return 0.0
    
    def _get_test_file_path(self, module_path: str) -> str:
        """Determine the test file path for a module."""
        # Convert src/path/module.py to tests/path/test_module.py
        if module_path.startswith('src/'):
            relative = module_path[4:]  # Remove 'src/'
        else:
            relative = module_path
        
        dir_name = os.path.dirname(relative)
        file_name = os.path.basename(relative)
        test_name = f"test_{file_name}"
        
        return f"tests/{dir_name}/{test_name}"
    
    async def _generate_tests_for_gaps(self, gaps: List[CoverageGap], test_file_path: str) -> int:
        """Generate tests to cover the identified gaps."""
        
        # Group gaps by context (function/class)
        grouped_gaps = {}
        for gap in gaps:
            context = gap.context
            if context not in grouped_gaps:
                grouped_gaps[context] = []
            grouped_gaps[context].append(gap)
        
        tests_generated = 0
        
        for context, context_gaps in grouped_gaps.items():
            # Generate test for this context
            test_code = self._generate_test_code(context, context_gaps)
            
            # Append to test file
            self._append_test_to_file(test_file_path, test_code)
            tests_generated += 1
        
        return tests_generated
    
    def _generate_test_code(self, context: str, gaps: List[CoverageGap]) -> str:
        """Generate test code for a specific context and gaps."""
        # Extract function name from context
        func_name = context.split('(')[0].replace('def ', '').replace('class ', '').strip()
        
        test_lines = [
            "",
            f"\ndef test_{func_name}_coverage_fix():",
            f'    """Auto-generated test to cover {len(gaps)} gaps in {func_name}."""',
            "    # TODO: Implement test based on gaps:",
        ]
        
        for gap in gaps:
            test_lines.append(f"    # Line {gap.line_number}: {gap.gap_type} - {gap.line_content[:50]}")
        
        test_lines.extend([
            "    pass  # Replace with actual test implementation",
            "",
        ])
        
        return '\n'.join(test_lines)
    
    def _append_test_to_file(self, test_file_path: str, test_code: str):
        """Append generated test code to the test file."""
        os.makedirs(os.path.dirname(test_file_path), exist_ok=True)
        
        # Create file if doesn't exist with imports
        if not os.path.exists(test_file_path):
            with open(test_file_path, 'w') as f:
                f.write("import pytest\n")
                f.write("from unittest.mock import Mock, patch\n\n")
        
        # Append test code
        with open(test_file_path, 'a') as f:
            f.write(test_code)
    
    def _run_tests(self, test_file_path: str) -> bool:
        """Run the generated tests."""
        try:
            result = subprocess.run(
                ["pytest", test_file_path, "-v", "--tb=short"],
                capture_output=True,
                text=True,
                timeout=60
            )
            return result.returncode == 0
        except subprocess.TimeoutExpired:
            self.logger.error("test_timeout", file=test_file_path)
            return False
        except Exception as e:
            self.logger.error("test_run_failed", error=str(e))
            return False


class BatchCoverageFixer:
    """Fix coverage for multiple modules in batch."""
    
    def __init__(self, fixer: AutonomousCoverageFixer = None):
        self.fixer = fixer or AutonomousCoverageFixer()
        self.logger = logger.bind(component="BatchCoverageFixer")
    
    async def fix_tier2_coverage(
        self,
        modules: List[str],
        target_coverage: float = 85.0
    ) -> List[FixResult]:
        """Fix coverage for all Tier 2 modules."""
        
        self.logger.info(
            "batch_fix_started",
            module_count=len(modules),
            target=target_coverage
        )
        
        results = []
        for module in modules:
            result = await self.fixer.fix_module_coverage(module, target_coverage)
            results.append(result)
        
        # Summary
        successful = sum(1 for r in results if r.success)
        total_tests = sum(r.tests_added for r in results)
        
        self.logger.info(
            "batch_fix_completed",
            successful=successful,
            total=len(modules),
            tests_added=total_tests
        )
        
        return results
    
    def generate_report(self, results: List[FixResult]) -> str:
        """Generate a markdown report of coverage fixes."""
        lines = [
            "# Autonomous Coverage Fix Report",
            "",
            "| Module | Before | After | Tests Added | Status |",
            "|--------|--------|-------|-------------|--------|",
        ]
        
        for result in results:
            status = "✅" if result.success else "❌"
            lines.append(
                f"| {os.path.basename(result.file_path)} | "
                f"{result.coverage_before:.1f}% | "
                f"{result.coverage_after:.1f}% | "
                f"{result.tests_added} | {status} |"
            )
        
        lines.append("")
        lines.append(f"**Summary**: {sum(1 for r in results if r.success)}/{len(results)} modules fixed")
        
        return '\n'.join(lines)
