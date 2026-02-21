#!/usr/bin/env python3
"""
MERID Codebase Syntax Scanner
Comprehensive syntax error detection across all Python, JavaScript, and configuration files
"""

import os
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Set
import re

class SyntaxScanner:
    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir).resolve()
        self.errors = []
        self.warnings = []
        self.scanned_files = 0
        self.passed_files = 0
        
        # File extensions to scan
        self.python_extensions = {'.py'}
        self.javascript_extensions = {'.js', '.jsx', '.ts', '.tsx'}
        self.json_extensions = {'.json'}
        self.config_extensions = {'.env', '.yaml', '.yml', '.toml', '.ini', '.cfg'}
        
        # Directories to exclude
        self.exclude_dirs = {
            '__pycache__', '.git', '.vscode', '.idea', 'node_modules',
            'venv', 'env', '.venv', 'dist', 'build', '.pytest_cache',
            'coverage', 'htmlcov', '.mypy_cache', '.tox'
        }
        
        # Files to exclude
        self.exclude_files = {
            '.DS_Store', 'Thumbs.db', '*.pyc', '*.pyo', '*.pyd'
        }

    def scan_file(self, file_path: Path) -> List[Dict]:
        """Scan a single file for syntax errors"""
        errors = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            errors.append({
                'file': str(file_path),
                'type': 'READ_ERROR',
                'line': 0,
                'message': f"Could not read file: {e}",
                'severity': 'ERROR'
            })
            return errors
        
        # Skip empty files
        if not content.strip():
            return errors
        
        # Scan based on file extension
        if file_path.suffix in self.python_extensions:
            return self._scan_python_file(file_path, content)
        elif file_path.suffix in self.javascript_extensions:
            return self._scan_javascript_file(file_path, content)
        elif file_path.suffix in self.json_extensions:
            return self._scan_json_file(file_path, content)
        elif file_path.suffix in self.config_extensions:
            return self._scan_config_file(file_path, content)
        else:
            return []

    def _scan_python_file(self, file_path: Path, content: str) -> List[Dict]:
        """Scan Python file for syntax errors"""
        errors = []
        
        try:
            # Parse AST to check for syntax errors
            ast.parse(content, filename=str(file_path))
        except SyntaxError as e:
            errors.append({
                'file': str(file_path),
                'type': 'PYTHON_SYNTAX_ERROR',
                'line': e.lineno or 0,
                'column': e.offset or 0,
                'message': f"Syntax error: {e.msg}",
                'severity': 'ERROR',
                'code_snippet': self._get_code_snippet(content, e.lineno or 0)
            })
        except Exception as e:
            errors.append({
                'file': str(file_path),
                'type': 'PYTHON_PARSE_ERROR',
                'line': 0,
                'message': f"Parse error: {e}",
                'severity': 'ERROR'
            })
        
        # Additional Python-specific checks
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            # Check for common issues
            if '\t' in line and not line.strip().startswith('#'):
                errors.append({
                    'file': str(file_path),
                    'type': 'TABS_IN_CODE',
                    'line': i,
                    'message': "Tab character found in code (use spaces instead)",
                    'severity': 'WARNING',
                    'code_snippet': line.strip()
                })
            
            # Check for trailing whitespace
            if line.endswith(' ') or line.endswith('\t'):
                errors.append({
                    'file': str(file_path),
                    'type': 'TRAILING_WHITESPACE',
                    'line': i,
                    'message': "Trailing whitespace found",
                    'severity': 'WARNING',
                    'code_snippet': repr(line)
                })
        
        return errors

    def _scan_javascript_file(self, file_path: Path, content: str) -> List[Dict]:
        """Scan JavaScript/TypeScript file for syntax errors"""
        errors = []
        
        # Try to use Node.js for syntax checking if available
        try:
            result = subprocess.run(
                ['node', '--check', str(file_path)],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                # Parse Node.js error output
                error_lines = result.stderr.strip().split('\n')
                for error_line in error_lines:
                    if ':' in error_line and 'SyntaxError' in error_line:
                        errors.append({
                            'file': str(file_path),
                            'type': 'JAVASCRIPT_SYNTAX_ERROR',
                            'line': 0,
                            'message': f"JavaScript syntax error: {error_line}",
                            'severity': 'ERROR'
                        })
        except (subprocess.TimeoutExpired, FileNotFoundError):
            # Fallback to basic regex checks
            errors.extend(self._basic_javascript_checks(file_path, content))
        
        return errors

    def _basic_javascript_checks(self, file_path: Path, content: str) -> List[Dict]:
        """Basic JavaScript syntax checks without Node.js"""
        errors = []
        lines = content.split('\n')
        
        # Basic bracket matching
        brace_stack = []
        paren_stack = []
        bracket_stack = []
        
        for i, line in enumerate(lines, 1):
            # Skip comments and strings for bracket checking
            cleaned = line
            if '//' in line:
                cleaned = line[:line.index('//')]
            
            for char in cleaned:
                if char == '{':
                    brace_stack.append(i)
                elif char == '}':
                    if not brace_stack:
                        errors.append({
                            'file': str(file_path),
                            'type': 'UNMATCHED_BRACE',
                            'line': i,
                            'message': "Unmatched closing brace '}'",
                            'severity': 'ERROR',
                            'code_snippet': line.strip()
                        })
                    else:
                        brace_stack.pop()
                elif char == '(':
                    paren_stack.append(i)
                elif char == ')':
                    if not paren_stack:
                        errors.append({
                            'file': str(file_path),
                            'type': 'UNMATCHED_PAREN',
                            'line': i,
                            'message': "Unmatched closing parenthesis ')'",
                            'severity': 'ERROR',
                            'code_snippet': line.strip()
                        })
                    else:
                        paren_stack.pop()
                elif char == '[':
                    bracket_stack.append(i)
                elif char == ']':
                    if not bracket_stack:
                        errors.append({
                            'file': str(file_path),
                            'type': 'UNMATCHED_BRACKET',
                            'line': i,
                            'message': "Unmatched closing bracket ']'",
                            'severity': 'ERROR',
                            'code_snippet': line.strip()
                        })
                    else:
                        bracket_stack.pop()
        
        # Check for unclosed brackets
        if brace_stack:
            errors.append({
                'file': str(file_path),
                'type': 'UNCLOSED_BRACE',
                'line': brace_stack[-1],
                'message': f"Unclosed brace '{{' at line {brace_stack[-1]}",
                'severity': 'ERROR'
            })
        
        if paren_stack:
            errors.append({
                'file': str(file_path),
                'type': 'UNCLOSED_PAREN',
                'line': paren_stack[-1],
                'message': f"Unclosed parenthesis '(' at line {paren_stack[-1]}",
                'severity': 'ERROR'
            })
        
        if bracket_stack:
            errors.append({
                'file': str(file_path),
                'type': 'UNCLOSED_BRACKET',
                'line': bracket_stack[-1],
                'message': f"Unclosed bracket '[' at line {bracket_stack[-1]}",
                'severity': 'ERROR'
            })
        
        return errors

    def _scan_json_file(self, file_path: Path, content: str) -> List[Dict]:
        """Scan JSON file for syntax errors"""
        errors = []
        
        try:
            json.loads(content)
        except json.JSONDecodeError as e:
            errors.append({
                'file': str(file_path),
                'type': 'JSON_SYNTAX_ERROR',
                'line': e.lineno,
                'column': e.colno,
                'message': f"JSON syntax error: {e.msg}",
                'severity': 'ERROR',
                'code_snippet': self._get_code_snippet(content, e.lineno)
            })
        except Exception as e:
            errors.append({
                'file': str(file_path),
                'type': 'JSON_PARSE_ERROR',
                'line': 0,
                'message': f"JSON parse error: {e}",
                'severity': 'ERROR'
            })
        
        return errors

    def _scan_config_file(self, file_path: Path, content: str) -> List[Dict]:
        """Scan configuration file for syntax errors"""
        errors = []
        
        if file_path.suffix == '.env':
            # Check dotenv syntax
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                line = line.strip()
                
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                
                # Check for valid KEY=VALUE format
                if '=' not in line:
                    errors.append({
                        'file': str(file_path),
                        'type': 'DOTENV_SYNTAX_ERROR',
                        'line': i,
                        'message': f"Invalid dotenv syntax (missing '='): {line[:50]}",
                        'severity': 'ERROR',
                        'code_snippet': line
                    })
                    continue
                
                key, value = line.split('=', 1)
                
                # Check for invalid characters in key
                if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', key):
                    errors.append({
                        'file': str(file_path),
                        'type': 'DOTENV_INVALID_KEY',
                        'line': i,
                        'message': f"Invalid dotenv key format: {key}",
                        'severity': 'ERROR',
                        'code_snippet': line
                    })
        
        elif file_path.suffix in {'.yaml', '.yml'}:
            # Basic YAML syntax checks
            try:
                import yaml
                yaml.safe_load(content)
            except ImportError:
                errors.append({
                    'file': str(file_path),
                    'type': 'YAML_CHECK_SKIPPED',
                    'line': 0,
                    'message': "PyYAML not installed, skipping YAML syntax check",
                    'severity': 'WARNING'
                })
            except yaml.YAMLError as e:
                line_num = 0
                if hasattr(e, 'problem_mark') and e.problem_mark:
                    line_num = e.problem_mark.line + 1
                
                errors.append({
                    'file': str(file_path),
                    'type': 'YAML_SYNTAX_ERROR',
                    'line': line_num,
                    'message': f"YAML syntax error: {e}",
                    'severity': 'ERROR'
                })
        
        return errors

    def _get_code_snippet(self, content: str, line_num: int, context: int = 2) -> str:
        """Get code snippet around error line"""
        lines = content.split('\n')
        start = max(0, line_num - context - 1)
        end = min(len(lines), line_num + context)
        
        snippet_lines = []
        for i in range(start, end):
            prefix = ">>> " if i == line_num - 1 else "    "
            snippet_lines.append(f"{prefix}{i+1:4d}: {lines[i]}")
        
        return '\n'.join(snippet_lines)

    def scan_directory(self) -> Dict:
        """Scan entire directory recursively"""
        print(f"🔍 Scanning directory: {self.root_dir}")
        print("=" * 60)
        
        all_files = []
        
        # Find all files to scan
        for root, dirs, files in os.walk(self.root_dir):
            # Remove excluded directories
            dirs[:] = [d for d in dirs if d not in self.exclude_dirs]
            
            for file in files:
                file_path = Path(root) / file
                
                # Check if file should be scanned
                if self._should_scan_file(file_path):
                    all_files.append(file_path)
        
        print(f"📁 Found {len(all_files)} files to scan")
        print()
        
        # Scan each file
        for file_path in sorted(all_files):
            self.scanned_files += 1
            file_errors = self.scan_file(file_path)
            
            if file_errors:
                self.errors.extend(file_errors)
            else:
                self.passed_files += 1
            
            # Progress indicator
            if self.scanned_files % 50 == 0:
                print(f"📊 Scanned {self.scanned_files}/{len(all_files)} files...")
        
        return self._generate_report()

    def _should_scan_file(self, file_path: Path) -> bool:
        """Check if file should be scanned"""
        # Check extension
        if (file_path.suffix not in self.python_extensions and
            file_path.suffix not in self.javascript_extensions and
            file_path.suffix not in self.json_extensions and
            file_path.suffix not in self.config_extensions):
            return False
        
        # Check if file is in excluded directory
        for part in file_path.parts:
            if part in self.exclude_dirs:
                return False
        
        # Check if file name is excluded
        if file_path.name in self.exclude_files:
            return False
        
        return True

    def _generate_report(self) -> Dict:
        """Generate comprehensive scan report"""
        # Group errors by type and severity
        error_counts = {}
        warning_counts = {}
        files_with_errors = set()
        
        for error in self.errors:
            files_with_errors.add(error['file'])
            
            error_type = error['type']
            severity = error['severity']
            
            if severity == 'ERROR':
                error_counts[error_type] = error_counts.get(error_type, 0) + 1
            else:
                warning_counts[error_type] = warning_counts.get(error_type, 0) + 1
        
        return {
            'summary': {
                'total_files_scanned': self.scanned_files,
                'files_passed': self.passed_files,
                'files_with_errors': len(files_with_errors),
                'total_errors': len([e for e in self.errors if e['severity'] == 'ERROR']),
                'total_warnings': len([e for e in self.errors if e['severity'] == 'WARNING']),
                'success_rate': (self.passed_files / self.scanned_files * 100) if self.scanned_files > 0 else 0
            },
            'error_breakdown': error_counts,
            'warning_breakdown': warning_counts,
            'files_with_errors': sorted(list(files_with_errors)),
            'all_errors': sorted(self.errors, key=lambda x: (x['file'], x['line']))
        }

def main():
    """Main entry point"""
    scanner = SyntaxScanner()
    
    print("🔍 MERID Codebase Syntax Scanner")
    print("=" * 60)
    print()
    
    # Scan the codebase
    report = scanner.scan_directory()
    
    # Print summary
    summary = report['summary']
    print(f"\n📊 SCAN SUMMARY")
    print("=" * 60)
    print(f"📁 Total files scanned: {summary['total_files_scanned']}")
    print(f"✅ Files passed: {summary['files_passed']}")
    print(f"❌ Files with errors: {summary['files_with_errors']}")
    print(f"🚨 Total errors: {summary['total_errors']}")
    print(f"⚠️  Total warnings: {summary['total_warnings']}")
    print(f"📈 Success rate: {summary['success_rate']:.1f}%")
    
    # Print error breakdown
    if report['error_breakdown']:
        print(f"\n🚨 ERROR BREAKDOWN")
        print("=" * 60)
        for error_type, count in sorted(report['error_breakdown'].items()):
            print(f"❌ {error_type}: {count}")
    
    # Print warning breakdown
    if report['warning_breakdown']:
        print(f"\n⚠️  WARNING BREAKDOWN")
        print("=" * 60)
        for warning_type, count in sorted(report['warning_breakdown'].items()):
            print(f"⚠️  {warning_type}: {count}")
    
    # Print detailed errors
    if report['all_errors']:
        print(f"\n🔍 DETAILED ERRORS")
        print("=" * 60)
        
        current_file = None
        for error in report['all_errors']:
            if error['file'] != current_file:
                current_file = error['file']
                print(f"\n📁 {current_file}")
                print("-" * 40)
            
            severity_icon = "🚨" if error['severity'] == 'ERROR' else "⚠️"
            line_info = f"Line {error['line']}" if error['line'] > 0 else "Global"
            
            print(f"{severity_icon} {line_info}: {error['message']}")
            
            if 'code_snippet' in error and error['code_snippet']:
                print(f"   Code: {error['code_snippet']}")
    
    # Print conclusion
    print(f"\n🎯 CONCLUSION")
    print("=" * 60)
    
    if summary['total_errors'] == 0:
        print("✅ NO SYNTAX ERRORS FOUND!")
        print("🎉 The codebase is syntactically clean!")
        
        if summary['total_warnings'] > 0:
            print(f"⚠️  {summary['total_warnings']} warnings found - consider addressing them")
    else:
        print(f"❌ {summary['total_errors']} syntax errors found!")
        print(f"🔧 Please fix these errors before proceeding")
        
        if summary['files_with_errors'] > 0:
            print(f"📁 Errors in {summary['files_with_errors']} files")
    
    # Return exit code
    return 1 if summary['total_errors'] > 0 else 0

if __name__ == "__main__":
    sys.exit(main())
