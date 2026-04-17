#!/usr/bin/env python3
"""
Script to remove all mock/fallback data from React view files.
Replaces mock data fallbacks with proper error logging.
"""

import re
from pathlib import Path

VIEW_FILES = [
    "web/react/src/views/Treasury.tsx",
    "web/react/src/views/Betting.tsx",
    "web/react/src/views/Mining.tsx",
    "web/react/src/views/Social.tsx",
    "web/react/src/views/Plugins.tsx",
    "web/react/src/views/Institutional.tsx",
]

def remove_mock_data_from_file(filepath: Path):
    """Remove mock data fallbacks from a single file."""
    print(f"Processing {filepath.name}...")
    
    content = filepath.read_text(encoding='utf-8')
    original_content = content
    
    # Pattern to match fallback mock data blocks
    # Matches from "// Fallback" comment to the closing of the set function
    pattern = r'(\s+)\/\/\s*Fallback.*?data\s*\n\s+set\w+\([^)]*?\{[\s\S]*?\}\);'
    
    def replace_mock_data(match):
        """Replace mock data with error logging."""
        indent = match.group(1)
        # Extract the setter function name
        setter_match = re.search(r'set(\w+)', match.group(0))
        if setter_match:
            var_name = setter_match.group(1)
            return f"{indent}console.error('Failed to load {var_name.lower()}:', err);"
        return f"{indent}console.error('Failed to load data:', err);"
    
    # Remove mock data blocks
    content = re.sub(pattern, replace_mock_data, content)
    
    # Also remove the "Using fallback data" warning displays
    warning_pattern = r'\s*<div className="bg-yellow-900/20 border border-yellow-600/50 rounded-lg p-4 flex items-center gap-3">\s*<AlertCircle className="w-5 h-5 text-yellow-500" />\s*<div>\s*<p className="text-yellow-500 font-medium">Using fallback data</p>\s*<p className="text-sm text-gray-400">\{error\}</p>\s*</div>\s*</div>'
    content = re.sub(warning_pattern, '', content, flags=re.MULTILINE)
    
    if content != original_content:
        filepath.write_text(content, encoding='utf-8')
        print(f"  ✓ Removed mock data from {filepath.name}")
        return True
    else:
        print(f"  - No changes needed for {filepath.name}")
        return False

def main():
    """Process all view files."""
    base_path = Path(__file__).parent
    changed_count = 0
    
    for file_path in VIEW_FILES:
        full_path = base_path / file_path
        if full_path.exists():
            if remove_mock_data_from_file(full_path):
                changed_count += 1
        else:
            print(f"  ✗ File not found: {file_path}")
    
    print(f"\n✓ Processed {len(VIEW_FILES)} files, modified {changed_count}")

if __name__ == "__main__":
    main()
