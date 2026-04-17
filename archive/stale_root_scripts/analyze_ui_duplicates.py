#!/usr/bin/env python3
"""
Analyze UI codebase for duplicates and dead code
"""
import os
import re
from pathlib import Path
from collections import defaultdict

def find_ui_duplicates(root_dir):
    """Find duplicate component names and patterns in UI codebase"""
    
    # Find all TSX/TS files
    ui_files = []
    for path in Path(root_dir).rglob("*.tsx"):
        if "node_modules" not in str(path) and "_legacy" not in str(path):
            ui_files.append(path)
    
    for path in Path(root_dir).rglob("*.ts"):
        if "node_modules" not in str(path) and "_legacy" not in str(path):
            ui_files.append(path)
    
    print(f"Found {len(ui_files)} UI files")
    
    # Analyze component definitions
    component_defs = defaultdict(list)
    duplicate_components = defaultdict(list)
    
    # Analyze imports
    imports = defaultdict(list)
    duplicate_imports = defaultdict(list)
    
    # Analyze constants
    constants = defaultdict(list)
    duplicate_constants = defaultdict(list)
    
    # Analyze functions
    functions = defaultdict(list)
    duplicate_functions = defaultdict(list)
    
    for file_path in ui_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                rel_path = str(file_path.relative_to(root_dir))
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            continue
        
        # Find React component definitions
        component_matches = re.findall(r'(?:const|function|class)\s+(\w+)(?:\s*=\s*React\.)?(?:\s*\(|\s*:|\s+extends)', content)
        for comp in component_matches:
            if comp.startswith('React') or comp in ['useState', 'useEffect', 'useCallback', 'useMemo']:
                continue
            component_defs[comp].append(rel_path)
            if len(component_defs[comp]) > 1:
                duplicate_components[comp] = component_defs[comp]
        
        # Find imports
        import_matches = re.findall(r'import.*from\s+[\'"]([^\'"]+)[\'"]', content)
        for imp in import_matches:
            imports[imp].append(rel_path)
            if len(imports[imp]) > 5:  # Only flag heavily used imports
                duplicate_imports[imp] = imports[imp]
        
        # Find constants (UPPER_CASE)
        constant_matches = re.findall(r'(?:const|let|var)\s+([A-Z][A-Z_0-9]*)\s*=', content)
        for const in constant_matches:
            constants[const].append(rel_path)
            if len(constants[const]) > 1:
                duplicate_constants[const] = constants[const]
        
        # Find functions
        function_matches = re.findall(r'(?:const|function)\s+(\w+)\s*\(', content)
        for func in function_matches:
            if func.startswith('use') or func.startswith('handle') or func in ['render', 'component']:
                continue
            functions[func].append(rel_path)
            if len(functions[func]) > 1:
                duplicate_functions[func] = functions[func]
    
    return {
        'total_files': len(ui_files),
        'duplicate_components': dict(duplicate_components),
        'duplicate_imports': dict(duplicate_imports),
        'duplicate_constants': dict(duplicate_constants),
        'duplicate_functions': dict(duplicate_functions),
        'component_counts': {k: len(v) for k, v in component_defs.items() if len(v) > 1}
    }

def find_dead_code_patterns(root_dir):
    """Find potential dead code patterns"""
    
    dead_code_indicators = []
    
    for file_path in Path(root_dir).rglob("*.tsx"):
        if "node_modules" in str(file_path) or "_legacy" in str(file_path):
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                rel_path = str(file_path.relative_to(root_dir))
        except:
            continue
        
        # Check for commented out code blocks
        if content.count('/*') > 5 or content.count('// TODO') > 3:
            dead_code_indicators.append({
                'file': rel_path,
                'type': 'commented_code',
                'details': f"Comment blocks: {content.count('/*')}, TODOs: {content.count('// TODO')}"
            })
        
        # Check for unused imports (basic heuristic)
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'import' in line and ('React' in line or '{' in line):
                import_name = line.split('from')[0].replace('import', '').strip()
                if import_name and content.count(import_name.split('{')[1].split('}')[0] if '{' in import_name else import_name) == 1:
                    dead_code_indicators.append({
                        'file': rel_path,
                        'type': 'potentially_unused_import',
                        'line': i + 1,
                        'details': line.strip()
                    })
    
    return dead_code_indicators

if __name__ == "__main__":
    root_dir = Path("c:/Dev/MERID/web/react/src")
    
    print("🔍 Analyzing UI codebase for duplicates and dead code...")
    print("=" * 60)
    
    # Find duplicates
    duplicates = find_ui_duplicates(root_dir)
    
    print(f"\n📊 UI Analysis Summary:")
    print(f"  Total UI files: {duplicates['total_files']}")
    print(f"  Duplicate components: {len(duplicates['duplicate_components'])}")
    print(f"  Duplicate constants: {len(duplicates['duplicate_constants'])}")
    print(f"  Duplicate functions: {len(duplicates['duplicate_functions'])}")
    
    print(f"\n🔄 DUPLICATE COMPONENTS:")
    for comp, files in sorted(duplicates['duplicate_components'].items(), key=lambda x: -len(x[1])):
        print(f"\n  {comp} ({len(files)} files):")
        for f in files[:3]:  # Show first 3 files
            print(f"    - {f}")
        if len(files) > 3:
            print(f"    ... and {len(files) - 3} more")
    
    print(f"\n📦 HEAVILY USED IMPORTS (>5 files):")
    for imp, files in sorted(duplicates['duplicate_imports'].items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {imp} ({len(files)} files)")
    
    print(f"\n🔢 DUPLICATE CONSTANTS:")
    for const, files in sorted(duplicates['duplicate_constants'].items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {const} ({len(files)} files):")
        for f in files[:2]:
            print(f"    - {f}")
        if len(files) > 2:
            print(f"    ... and {len(files) - 2} more")
    
    print(f"\n⚡ DUPLICATE FUNCTIONS:")
    for func, files in sorted(duplicates['duplicate_functions'].items(), key=lambda x: -len(x[1]))[:10]:
        print(f"  {func} ({len(files)} files):")
        for f in files[:2]:
            print(f"    - {f}")
        if len(files) > 2:
            print(f"    ... and {len(files) - 2} more")
    
    # Find dead code
    dead_code = find_dead_code_patterns(root_dir)
    
    print(f"\n💀 DEAD CODE INDICATORS:")
    for indicator in dead_code[:15]:  # Show first 15
        print(f"  {indicator['file']}: {indicator['type']}")
        if 'details' in indicator:
            print(f"    {indicator['details']}")
    
    if len(dead_code) > 15:
        print(f"  ... and {len(dead_code) - 15} more files with potential dead code")
