#!/usr/bin/env python3
"""
Extract all icon imports from src/ directory to identify which icons are actually used.
"""

import os
import re
from pathlib import Path

def extract_icon_imports():
    """Extract all icon names from import statements."""
    src_dir = Path("src")
    used_icons = set()
    
    # Pattern to match icon imports from '../ui/icons'
    pattern = r'import\s*\{([^}]+)\}\s*from\s*[\'"]\.\./ui/icons[\'"]'
    
    for file_path in src_dir.rglob("*.tsx"):
        if file_path.is_file():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Find all import statements from ui/icons
                matches = re.findall(pattern, content)
                
                for match in matches:
                    # Split by comma and clean up
                    icons = [icon.strip() for icon in match.split(',')]
                    for icon in icons:
                        # Handle aliases like "Settings as SettingsIcon"
                        if ' as ' in icon:
                            icon = icon.split(' as ')[0].strip()
                        # Remove any remaining whitespace
                        icon = icon.strip()
                        if icon:
                            used_icons.add(icon)
                            
            except Exception as e:
                print(f"Error processing {file_path}: {e}")
    
    return sorted(used_icons)

def main():
    used_icons = extract_icon_imports()
    
    print("Icons actually used in the codebase:")
    print("=" * 50)
    for icon in used_icons:
        print(f"  {icon}")
    
    print(f"\nTotal unique icons used: {len(used_icons)}")
    
    # Write to file for easy reference
    with open("used_icons.txt", "w") as f:
        f.write("Icons actually used:\n")
        f.write("=" * 30 + "\n")
        for icon in used_icons:
            f.write(f"{icon}\n")
        f.write(f"\nTotal: {len(used_icons)}\n")
    
    print("\nWritten to used_icons.txt")

if __name__ == "__main__":
    main()
