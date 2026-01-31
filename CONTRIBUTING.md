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
python -m pytest tests/
python meridctl_simple.py status
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
5. **Verify system health** - Run `meridctl_simple.py status`

### **Pattern 5: Final Verification**

After resolving all conflicts:
```bash
git status  # Should show no "unmerged paths"
python meridctl_simple.py status  # Verify system health
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
python -m pytest tests/ -v
python -m py_compile merid_logging_config.py
python meridctl_simple.py status
```

### **Health Checks**
```bash
# Basic health check
python meridctl_simple.py status

# Save health snapshot
python meridctl_simple.py status --save

# Custom output path
python meridctl_simple.py status --output /tmp/health.json
```

---

## 📝 Code Style

### **Python Standards**
- Follow PEP 8
- Use type hints where appropriate
- Add docstrings for public functions
- Keep lines under 100 characters

### **MERID Specific**
- Use `merid_logging_config` for all logging
- Follow existing import patterns
- Maintain backward compatibility
- Add health checks for new components

---

## 🔍 Debugging Tips

### **Import Issues**
```bash
python -m py_compile path/to/problem_file.py
```

### **Health Monitoring**
```bash
python meridctl_simple.py status --save
cat merid_simple_health_*.json
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
- [MERID Logging Rules of the Road](docs/MERID_LOGGING_RULES_OF_THE_ROAD.md)
- [MERID Safety One-Pager](docs/MERID_SAFETY_ONE_PAGER.md)
- [MERID Implementation Checklist](MERID_IMPLEMENTATION_CHECKLIST.md)

### **Help Tools**
```bash
# Quick conflict resolution help
python tools/merid-git-help.py

# Health monitoring
python meridctl_simple.py --help
```

---

## 🤝 Getting Help

### **For Code Conflicts**
1. Try the conflict resolution checklist above
2. Use `python tools/merid-git-help.py` for quick reference
3. Check existing issues for similar problems
4. Create an issue with details about the conflict

### **For System Issues**
1. Run `python meridctl_simple.py status` for health check
2. Check the logs in the `logs/` directory
3. Review the implementation checklist

---

## 📋 Review Process

### **Before Submitting PR**
- [ ] All tests pass
- [ ] No merge conflicts
- [ ] Health check passes (`meridctl_simple.py status`)
- [ ] Documentation updated
- [ ] Code follows style guidelines

### **Pre-Merge/Pre-Push Checklist**
Run these checks before merging or pushing to ensure system integrity:

```bash
# Quick validation
python meridctl_simple.py pre-merge-checklist

# Or run manually:
python -m py_compile agents/__init__.py
python -m py_compile core/settings.py
python -m py_compile db/neo4j.py
python -m py_compile merid_logging_config.py
python meridctl_simple.py status
```

**Automation Tip:** Add to your pre-commit hook:
```bash
#!/bin/bash
python -m py_compile agents/__init__.py core/settings.py db/neo4j.py merid_logging_config.py
python meridctl_simple.py status
python -m pytest tests/smoke -q
```

### **PR Review Checklist**
- [ ] Code quality and style
- [ ] Test coverage
- [ ] Documentation accuracy
- [ ] System health impact
- [ ] Backward compatibility

---

**Thank you for contributing to MERID!** 🚀
