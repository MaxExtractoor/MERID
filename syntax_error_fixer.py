#!/usr/bin/env python3
"""
MERID Syntax Error Fixer
Automatically fixes common syntax errors found by the scanner
"""

import os
import re
from pathlib import Path

class SyntaxErrorFixer:
    def __init__(self, root_dir: str = "."):
        self.root_dir = Path(root_dir).resolve()
        self.fixes_applied = 0
        
    def fix_git_conflict_markers(self, file_path: Path) -> bool:
        """Fix Git conflict markers in a file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Remove Git conflict markers and keep the "theirs" version (after =======)
            lines = content.split('\n')
            fixed_lines = []
            in_conflict = False
            skip_until_marker = False
            
            for line in lines:
                if line.startswith('<<<<<<<'):
                    in_conflict = True
                    skip_until_marker = True
                    continue
                elif line.startswith('=======') and skip_until_marker:
                    skip_until_marker = False
                    continue
                elif line.startswith('>>>>>>>') and in_conflict:
                    in_conflict = False
                    skip_until_marker = False
                    continue
                
                if not skip_until_marker:
                    fixed_lines.append(line)
            
            fixed_content = '\n'.join(fixed_lines)
            
            if fixed_content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
                print(f"✅ Fixed Git conflicts in {file_path}")
                return True
                
        except Exception as e:
            print(f"❌ Error fixing {file_path}: {e}")
        
        return False
    
    def fix_f_string_backslash(self, file_path: Path) -> bool:
        """Fix f-string backslash issues"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Fix f-string with backslash by breaking it into multiple parts
            # Pattern: f"text\{expression}" -> f"text" + "\\" + str(expression)
            pattern = r'f"([^"]*?)\\([^"]*?{[^}]+}[^"]*?)"'
            
            def replace_fstring(match):
                prefix = match.group(1)
                suffix = match.group(2)
                return f'f"{prefix}" + "\\\\" + f"{suffix}"'
            
            fixed_content = re.sub(pattern, replace_fstring, content)
            
            if fixed_content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
                print(f"✅ Fixed f-string backslash in {file_path}")
                return True
                
        except Exception as e:
            print(f"❌ Error fixing {file_path}: {e}")
        
        return False
    
    def fix_unmatched_brackets(self, file_path: Path) -> bool:
        """Fix unmatched brackets in JavaScript/TypeScript files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Basic bracket balancing
            lines = content.split('\n')
            fixed_lines = []
            
            for line in lines:
                # Skip comments
                if '//' in line:
                    line = line[:line.index('//')]
                
                # Count brackets
                open_braces = line.count('{')
                close_braces = line.count('}')
                open_parens = line.count('(')
                close_parens = line.count(')')
                open_brackets = line.count('[')
                close_brackets = line.count(']')
                
                # Simple fix: add missing closing brackets at end of line
                if open_braces > close_braces:
                    line += '}' * (open_braces - close_braces)
                if open_parens > close_parens:
                    line += ')' * (open_parens - close_parens)
                if open_brackets > close_brackets:
                    line += ']' * (open_brackets - close_brackets)
                
                fixed_lines.append(line)
            
            fixed_content = '\n'.join(fixed_lines)
            
            if fixed_content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
                print(f"✅ Fixed unmatched brackets in {file_path}")
                return True
                
        except Exception as e:
            print(f"❌ Error fixing {file_path}: {e}")
        
        return False
    
    def fix_json_comments(self, file_path: Path) -> bool:
        """Remove comments from JSON files"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Remove single-line comments
            lines = content.split('\n')
            fixed_lines = []
            
            for line in lines:
                # Remove inline comments
                if '/*' in line:
                    line = line[:line.index('/*')]
                # Remove lines that are just comments
                if line.strip().startswith('/*') or line.strip().startswith('*') or line.strip().startswith('*/'):
                    continue
                fixed_lines.append(line)
            
            fixed_content = '\n'.join(fixed_lines)
            
            if fixed_content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
                print(f"✅ Fixed JSON comments in {file_path}")
                return True
                
        except Exception as e:
            print(f"❌ Error fixing {file_path}: {e}")
        
        return False
    
    def fix_yaml_multiple_docs(self, file_path: Path) -> bool:
        """Fix YAML multiple document issues"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            original_content = content
            
            # Remove extra document separators
            lines = content.split('\n')
            fixed_lines = []
            doc_count = 0
            
            for line in lines:
                if line.strip() == '---':
                    doc_count += 1
                    if doc_count > 1:  # Skip additional document separators
                        continue
                fixed_lines.append(line)
            
            fixed_content = '\n'.join(fixed_lines)
            
            if fixed_content != original_content:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(fixed_content)
                print(f"✅ Fixed YAML multiple docs in {file_path}")
                return True
                
        except Exception as e:
            print(f"❌ Error fixing {file_path}: {e}")
        
        return False
    
    def fix_bom_character(self, file_path: Path) -> bool:
        """Remove BOM character from file"""
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()
            
            original_content = content
            
            # Write back without BOM
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            if content != original_content:
                print(f"✅ Fixed BOM character in {file_path}")
                return True
                
        except Exception as e:
            print(f"❌ Error fixing {file_path}: {e}")
        
        return False
    
    def fix_all_critical_errors(self):
        """Fix all critical syntax errors automatically"""
        print("🔧 MERID Syntax Error Fixer")
        print("=" * 50)
        print()
        
        # Files with known issues from the scan
        critical_files = [
            "monitoring/real_prediction_markets.py",
            "scripts/setup_paper_trading.py", 
            "web/api/predictions.py",
            "generate_phase2_completion_report.py",
            "generate_phase2_completion_report_ascii.py",
            "test_final_validation.py",
            "web3/onchain_verifier.py",
            "merid-ui/tsconfig.app.json",
            "merid-ui/tsconfig.node.json",
            "monitoring/elasticsearch-index-template.json",
            "infra/rbac-config.yml",
            "infra/tls-config.yml",
            "tmp/env_scan.py",
            "neo4j_writer.py",
            "robustness_validation_test.py",
            "test_assertion_framework.py"
        ]
        
        for file_path_str in critical_files:
            file_path = self.root_dir / file_path_str
            
            if not file_path.exists():
                print(f"⚠️  File not found: {file_path}")
                continue
            
            print(f"🔧 Fixing: {file_path}")
            
            # Apply fixes based on file type and known issues
            if file_path.suffix == '.py':
                if self.fix_git_conflict_markers(file_path):
                    self.fixes_applied += 1
                if self.fix_f_string_backslash(file_path):
                    self.fixes_applied += 1
                    
            elif file_path.suffix in {'.json'}:
                if self.fix_json_comments(file_path):
                    self.fixes_applied += 1
                    
            elif file_path.suffix in {'.yml', '.yaml'}:
                if self.fix_yaml_multiple_docs(file_path):
                    self.fixes_applied += 1
                    
            # Special fixes for specific files
            if 'env_scan.py' in str(file_path):
                if self.fix_bom_character(file_path):
                    self.fixes_applied += 1
        
        print(f"\n📊 SUMMARY")
        print("=" * 50)
        print(f"🔧 Fixes applied: {self.fixes_applied}")
        
        if self.fixes_applied > 0:
            print("✅ Some syntax errors have been automatically fixed")
            print("🔄 Run the critical syntax scanner again to verify")
        else:
            print("ℹ️  No automatic fixes applied")
            print("🔍 Manual fixes may be required for remaining errors")

def main():
    """Main entry point"""
    fixer = SyntaxErrorFixer()
    fixer.fix_all_critical_errors()

if __name__ == "__main__":
    main()
