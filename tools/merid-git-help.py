#!/usr/bin/env python3
"""
MERID Git Conflict Resolution Helper
Provides quick reference for Git conflict resolution patterns.

Usage: python tools/merid-git-help.py
"""

import sys
import os

def print_help():
    """Print Git conflict resolution help for MERID."""
    
    print("""
🚀 MERID Git Conflict Resolution Helper
=========================================

When encountering merge conflicts in MERID, follow these patterns:

📋 PATTERN 1: Take Other Branch's Version
For files where one side is clearly authoritative:

    # Keep "theirs" (branch you're merging in)
    git checkout --theirs -- path/to/file.py
    git add path/to/file.py

    # Keep "ours" (your current branch)
    git checkout --ours -- path/to/file.py
    git add path/to/file.py

📋 PATTERN 2: Manual Merge for Composite Files
For files like agents/__init__.py that need custom merging:

    1. Open file and find conflict blocks:
       <<<<<<< HEAD
       # your branch content
       =======
       # other branch content
       >>>>>>> feature-branch

    2. Edit to desired final code

    3. Delete all conflict markers:
       - <<<<<<< HEAD
       - =======
       - >>>>>>> feature-branch

    4. Validate syntax:
       python -m py_compile path/to/file.py

    5. Stage as resolved:
       git add path/to/file.py

📋 PATTERN 3: Recovery from Wrong Choice
If you picked the wrong side and haven't staged yet:

    # Restore conflicted version
    git checkout -m -- path/to/file.py

If already staged:
    git reset HEAD path/to/file.py
    git checkout -m -- path/to/file.py

📋 PATTERN 4: Systematic Resolution

    1. Resolve one file at a time
    2. Validate after each fix (python -m py_compile)
    3. Stage immediately (git add)
    4. Test imports
    5. Verify system health (python meridctl_simple.py status)

📋 PATTERN 5: Final Verification

    git status  # Should show no "unmerged paths"
    python meridctl_simple.py status  # Verify system health
    git commit  # Complete the merge

🔍 COMMON MERID CONFLICT SCENARIOS

Import Files (__init__.py):
    • Use PATTERN 2 (Manual Merge)
    • Often need combined imports from both branches
    • Validate with python -m py_compile

Configuration Files:
    • Use PATTERN 1 (Take authoritative version)
    • Usually one branch has correct configuration

Core Implementation Files:
    • Use PATTERN 1 for clean files
    • Use PATTERN 2 for files with custom changes

🧪 TESTING & VALIDATION

    # Run tests before committing
    python -m pytest tests/ -v
    python -m py_compile merid_logging_config.py
    python meridctl_simple.py status

    # Health checks
    python meridctl_simple.py status --save
    cat merid_simple_health_*.json

🔍 DEBUGGING COMMANDS

    # Check for conflicts
    git status --porcelain=v1 | findstr "UU"
    git status

    # Validate syntax
    python -m py_compile path/to/problem_file.py

    # System health
    python meridctl_simple.py status --save

📚 ADDITIONAL RESOURCES

    Git Documentation:
    https://git-scm.com/docs/git-checkout
    https://git-scm.com/docs/git-merge

    MERID Documentation:
    docs/MERID_LOGGING_RULES_OF_THE_ROAD.md
    docs/MERID_SAFETY_ONE_PAGER.md
    MERID_IMPLEMENTATION_CHECKLIST.md

    Help Tools:
    python tools/merid-git-help.py  # This script
    python meridctl_simple.py --help

🤝 GETTING HELP

    1. Try the conflict resolution checklist above
    2. Use this script for quick reference
    3. Check existing issues for similar problems
    4. Create an issue with details about the conflict

💡 QUICK REFERENCE SUMMARY

    git checkout --theirs -- file.py    # Take their version
    git checkout --ours -- file.py      # Take your version
    git add file.py                     # Mark resolved
    python -m py_compile file.py        # Validate syntax
    git checkout -m -- file.py          # Restore conflicts
    meridctl_simple.py status           # Verify health

=========================================
🚀 MERID Git Conflict Resolution Helper
""")

def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] in ['-h', '--help', 'help']:
        print_help()
        return
    
    print_help()

if __name__ == "__main__":
    main()
