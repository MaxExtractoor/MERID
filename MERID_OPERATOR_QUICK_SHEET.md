# MERID Operator Quick Sheet
> This quick sheet is derived from `python meridctl_simple.py git-help`. Update CLI help first, then sync this file.

# Core health
python meridctl_simple.py status

# Git conflict help
python meridctl_simple.py git-help

# Pre-merge validation (recommended)
python meridctl_simple.py pre-merge-checklist

# Essential Git conflict patterns
# 1) Take side:   git checkout --theirs/--ours -- path && python -m py_compile path && git add path
# 2) Manual fix:  edit file, remove <<<<<<</=======/>>>>>>> markers, python -m py_compile, git add
# 3) Recover:     git checkout -m -- path
# 4) Go file by file, validate after each
# 5) Final check: git status && python meridctl_simple.py status

# More help
python tools/merid-git-help.py
cat CONTRIBUTING.md | grep -A 10 "Conflict Resolution"
