# Contributing to MERID

This document provides guidelines for contributing to the MERID project, including development setup, coding standards, and conflict resolution procedures.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.11.x (64-bit)
- Git
- Virtual environment (recommended)

### Setup
```bash
git clone <repository-url>
cd MERID
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

## 🔧 Development Workflow

### 1. Create a Feature Branch
```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes
- Follow existing code style
- Add tests for new functionality
- Update documentation as needed

### 3. Test Your Changes
```bash
make golden-path          # 490-test golden path suite
make preflight            # Tests + readiness + drift + RiskContext
```

### 4. Commit and Push
```bash
git add .
git commit -m "feat: add your feature description"
git push origin feature/your-feature-name
```

### 5. Create Pull Request
- Describe your changes clearly
- Link to relevant issues
- Ensure CI checks pass

---

## 🛠️ MERID Conflict Resolution Checklist

When encountering merge conflicts in MERID, follow these exact patterns:

### **Pattern 1: Take Other Branch's Version**
For files where one side is clearly authoritative:

```bash
# Keep "theirs" (branch you're merging in)
git checkout --theirs -- path/to/file.py
git add path/to/file.py
```

Or keep your version:
```bash
# Keep "ours" (your current branch)
git checkout --ours -- path/to/file.py
git add path/to/file.py
```

### **Pattern 2: Manual Merge for Composite Files**
For files like `agents/__init__.py` that need custom merging:

1. Open the file and find conflict blocks:
   ```
   <<<<<<< HEAD
   # your branch content
   =======
   # other branch content
   >>>>>>> feature-branch
   ```

2. Edit to desired final code

3. **Delete all conflict markers:**
   - `<<<<<<< HEAD`
   - `=======` 
   - >>>>>>> feature-branch`

4. **Validate syntax:**
   ```bash
   python -m py_compile path/to/file.py
   ```

5. **Stage as resolved:**
   ```bash
   git add path/to/file.py
   ```

### **Pattern 3: Recovery from Wrong Choice**
If you picked the wrong side and haven't staged yet:

```bash
# Restore conflicted version
git checkout -m -- path/to/file.py
```

If already staged:
```bash
git reset HEAD path/to/file.py
git checkout -m -- path/to/file.py
```

### **Pattern 4: Systematic Resolution**

1. **Resolve one file at a time** - Prevents cascading issues
2. **Validate after each fix** - Use `python -m py_compile`
3. **Stage immediately** - `git add` marks conflict resolved
4. **Test imports** - Ensure import chain works
5. **Verify system health** - Run `make preflight`

### **Pattern 5: Final Verification**

After resolving all conflicts:
```bash
git status  # Should show no "unmerged paths"
make golden-path  # Verify no regressions
git commit  # Complete the merge
```

---

## 📋 Common Conflict Scenarios in MERID

### **Import Files (`__init__.py`)**
- Use **Pattern 2** (Manual Merge)
- These files often need combined imports from both branches
- Validate with `python -m py_compile`

### **Configuration Files**
- Use **Pattern 1** (Take authoritative version)
- Usually one branch has the correct configuration

### **Core Implementation Files**
- Use **Pattern 1** for clean files
- Use **Pattern 2** for files with custom changes

---

## 🧪 Testing Guidelines

### **Run Tests Before Committing**
```bash
make golden-path           # 490-test golden path suite
make preflight             # Full preflight (tests + readiness + drift + risk context)
```

### **Health Checks**
```bash
# Risk context snapshot
make risk-context

# Readiness auditor
make readiness

# Codebase drift audit
make codebase-drift-audit
```

---

## 📝 Code Style

### **Python Standards**
- Follow PEP 8
- Use type hints where appropriate
- Add docstrings for public functions
- Keep lines under 100 characters

### **MERID Specific**
- Use `utils.logger.get_logger()` for all logging (f-string format, not structlog kwargs)
- Follow existing import patterns
- Maintain backward compatibility
- Add health checks for new components
- No new `# type: ignore` without a justifying comment (e.g. `# type: ignore[arg-type]  # reason`)
- No new bare `except: pass` — log with `logger.debug`

---

## 🔍 Debugging Tips

### **Import Issues**
```bash
python -m py_compile path/to/problem_file.py
```

### **Health Monitoring**
```bash
make risk-context           # Print live RiskContext
make readiness              # Run readiness auditor
```

### **Git Status**
```bash
git status --porcelain=v1 | findstr "UU"  # Show conflicts
git status  # Show overall status
```

---

## 📚 Additional Resources

### **Git Documentation**
- [Git checkout](https://git-scm.com/docs/git-checkout)
- [Git merge](https://git-scm.com/docs/git-merge)

### **MERID Documentation**
- [Getting Started](docs/GETTING_STARTED.md)
- [Go-Live Checklist](docs/GO_LIVE_CHECKLIST.md)
- [Readiness Scorecard](docs/SWARM_TRADING_READINESS.md)

### **Help Tools**
```bash
# Quick conflict resolution help
python tools/merid-git-help.py

# Health monitoring
make preflight
```

---

## 🤝 Getting Help

### **For Code Conflicts**
1. Try the conflict resolution checklist above
2. Use `python tools/merid-git-help.py` for quick reference
3. Check existing issues for similar problems
4. Create an issue with details about the conflict

### **For System Issues**
1. Run `make preflight` for full health check
2. Run `make risk-context` for risk state
3. Check API docs at http://localhost:8000/docs

---

## 📋 Review Process

### **Before Submitting PR**
- [ ] All tests pass
- [ ] No merge conflicts
- [ ] Health check passes (`make preflight`)
- [ ] Documentation updated
- [ ] Code follows style guidelines
- [ ] No new `# type: ignore` without a justifying comment

### **Pre-Merge/Pre-Push Checklist**
Run these checks before merging or pushing to ensure system integrity:

```bash
# Quick validation
make golden-path

# Or full preflight:
make preflight
```

**Automation Tip:** Add to your pre-commit hook:
```bash
#!/bin/bash
make golden-path
```

### **PR Review Checklist**
- [ ] Code quality and style
- [ ] Test coverage
- [ ] Documentation accuracy
- [ ] System health impact
- [ ] Backward compatibility

---

**Thank you for contributing to MERID!** 🚀
