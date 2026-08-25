"""
Legacy Path Inventory and Tagging Script

This script scans the codebase for deprecated strategies, old APIs, and DB-dependent
tests, tagging them for cleanup (remove, refactor, or quarantine).

Usage::

    python scripts/inventory_legacy_paths.py --output docs/legacy_inventory.md
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from enum import Enum
import re

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class LegacyTag(str, Enum):
    """Tags for legacy code."""
    REMOVE = "REMOVE"  # Truly dead code and tests; delete
    REFACTOR = "REFACTOR"  # Keep behavior but migrate to current abstractions
    QUARANTINE = "QUARANTINE"  # Move to legacy module behind feature flag


@dataclass
class LegacyPath:
    """Represents a legacy code path."""
    file_path: str
    line_number: int
    tag: LegacyTag
    reason: str
    pattern_matched: str
    suggested_action: str = ""
    
    def to_markdown(self) -> str:
        """Convert to markdown format for documentation."""
        return f"""
### {self.file_path}:{self.line_number}

- **Tag**: {self.tag.value}
- **Reason**: {self.reason}
- **Pattern**: `{self.pattern_matched}`
- **Suggested Action**: {self.suggested_action}
"""


class LegacyPathInventory:
    """Scans codebase for legacy paths."""
    
    # Patterns to search for
    PATTERNS = {
        # Deprecated strategies
        "deprecated_strategy": [
            r"legacy.*agent",
            r"old.*strategy",
            r"deprecated.*strategy",
            r".*legacy.*grid",
        ],
        # Old APIs
        "old_api": [
            r"from.*legacy.*import",
            r"import.*legacy",
            r"KalshiVenueClient.*legacy",
            r"KalshiMarketCatalog.*legacy",
        ],
        # DB-dependent tests
        "db_dependent_test": [
            r"def test_.*\(.*db\)",
            r"def test_.*\(.*database\)",
            r"pytest.*mark.*db",
            r"@pytest\.mark\.database",
            r"\.db\.session",
            r"Session\(\)",
            r"engine\.connect\(\)",
        ],
        # Hard-coded paths
        "hardcoded_path": [
            r"/legacy/",
            r"/archive/",
            r"/disabled/",
        ],
        # Old contract schemas
        "old_contract_schema": [
            r"ContractSchema.*v1",
            r"OldContract",
            r"LegacyContract",
        ],
        # Deprecated imports
        "deprecated_import": [
            r"from merid\.kalshi",
            r"from merid\.event_venues\.kalshi\.legacy",
        ],
    }
    
    def __init__(self, root_dir: str = str(project_root)):
        self.root_dir = Path(root_dir)
        self.legacy_paths: List[LegacyPath] = []
        self.scanned_files: Set[str] = set()
    
    def scan_file(self, file_path: Path) -> List[LegacyPath]:
        """Scan a single file for legacy patterns."""
        legacy_paths = []
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            for line_num, line in enumerate(lines, 1):
                for pattern_category, patterns in self.PATTERNS.items():
                    for pattern in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            # Determine tag based on pattern category
                            tag = self._determine_tag(pattern_category, line)
                            reason = self._determine_reason(pattern_category)
                            suggested_action = self._determine_suggested_action(tag, pattern_category)
                            
                            legacy_path = LegacyPath(
                                file_path=str(file_path.relative_to(self.root_dir)),
                                line_number=line_num,
                                tag=tag,
                                reason=reason,
                                pattern_matched=pattern,
                                suggested_action=suggested_action,
                            )
                            legacy_paths.append(legacy_path)
        
        except Exception as e:
            print(f"Error scanning {file_path}: {e}")
        
        return legacy_paths
    
    def _determine_tag(self, pattern_category: str, line: str) -> LegacyTag:
        """Determine tag based on pattern category and line content."""
        if pattern_category in ["deprecated_strategy", "old_contract_schema"]:
            return LegacyTag.REMOVE
        elif pattern_category == "old_api":
            if "legacy" in line.lower() and "import" in line.lower():
                return LegacyTag.REFACTOR
            return LegacyTag.QUARANTINE
        elif pattern_category == "db_dependent_test":
            return LegacyTag.REFACTOR
        elif pattern_category == "hardcoded_path":
            return LegacyTag.REMOVE
        elif pattern_category == "deprecated_import":
            return LegacyTag.REFACTOR
        else:
            return LegacyTag.QUARANTINE
    
    def _determine_reason(self, pattern_category: str) -> str:
        """Determine reason based on pattern category."""
        reasons = {
            "deprecated_strategy": "Deprecated strategy implementation",
            "old_api": "Old API usage that should be migrated",
            "db_dependent_test": "Test depends on database connection",
            "hardcoded_path": "Hard-coded legacy path reference",
            "old_contract_schema": "Old contract schema definition",
            "deprecated_import": "Deprecated import statement",
        }
        return reasons.get(pattern_category, "Legacy pattern detected")
    
    def _determine_suggested_action(self, tag: LegacyTag, pattern_category: str) -> str:
        """Determine suggested action based on tag and pattern category."""
        if tag == LegacyTag.REMOVE:
            return "Delete this code/test as it is no longer used"
        elif tag == LegacyTag.REFACTOR:
            return "Migrate to current abstractions (e.g., use simulated data instead of DB)"
        elif tag == LegacyTag.QUARANTINE:
            return "Move to legacy module behind feature flag with invariant check"
        return "Review and update"
    
    def scan_directory(self, directory: Path, extensions: Tuple[str, ...] = ('.py',)) -> List[LegacyPath]:
        """Scan a directory for legacy patterns."""
        legacy_paths = []
        
        for file_path in directory.rglob('*'):
            if file_path.is_file() and file_path.suffix in extensions:
                # Skip certain directories
                if any(skip in str(file_path) for skip in ['.git', '__pycache__', 'node_modules', '.venv']):
                    continue
                
                file_legacy_paths = self.scan_file(file_path)
                legacy_paths.extend(file_legacy_paths)
                self.scanned_files.add(str(file_path))
        
        return legacy_paths
    
    def generate_inventory_report(self) -> str:
        """Generate markdown inventory report."""
        report = "# Legacy Path Inventory Report\n\n"
        report += f"Generated: {self._get_timestamp()}\n\n"
        report += f"Scanned {len(self.scanned_files)} files\n"
        report += f"Found {len(self.legacy_paths)} legacy paths\n\n"
        
        # Group by tag
        by_tag: Dict[LegacyTag, List[LegacyPath]] = {}
        for path in self.legacy_paths:
            if path.tag not in by_tag:
                by_tag[path.tag] = []
            by_tag[path.tag].append(path)
        
        # Report by tag
        for tag in LegacyTag:
            if tag in by_tag:
                report += f"## {tag.value} ({len(by_tag[tag])} items)\n\n"
                for path in by_tag[tag]:
                    report += path.to_markdown()
        
        # Summary statistics
        report += "\n## Summary Statistics\n\n"
        report += "| Tag | Count |\n"
        report += "|-----|-------|\n"
        for tag in LegacyTag:
            count = len(by_tag.get(tag, []))
            report += f"| {tag.value} | {count} |\n"
        
        return report
    
    def _get_timestamp(self) -> str:
        """Get current timestamp."""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def run(self, output_file: Optional[str] = None) -> str:
        """Run the inventory scan."""
        print(f"Scanning {self.root_dir} for legacy paths...")
        
        self.legacy_paths = self.scan_directory(self.root_dir)
        
        report = self.generate_inventory_report()
        
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                f.write(report)
            print(f"Report written to {output_file}")
        
        return report


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Inventory legacy paths in MERID codebase")
    parser.add_argument(
        "--output",
        "-o",
        default="docs/legacy_inventory.md",
        help="Output file for inventory report (default: docs/legacy_inventory.md)"
    )
    parser.add_argument(
        "--root",
        "-r",
        default=str(project_root),
        help="Root directory to scan (default: project root)"
    )
    
    args = parser.parse_args()
    
    inventory = LegacyPathInventory(root_dir=args.root)
    report = inventory.run(output_file=args.output)
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Scanned files: {len(inventory.scanned_files)}")
    print(f"Legacy paths found: {len(inventory.legacy_paths)}")
    print(f"Report written to: {args.output}")


if __name__ == "__main__":
    main()
