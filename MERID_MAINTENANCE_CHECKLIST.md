# MERID Maintenance Checklist
**For releases, iterations, and Git pattern updates**

---

## 🔧 Git Conflict Resolution Maintenance

### **When Git Patterns Change**
- [ ] Update `meridctl_simple.py git-help` (CLI help first)
- [ ] Re-sync `MERID_OPERATOR_QUICK_SHEET.md` from CLI
- [ ] Update `CONTRIBUTING.md` conflict checklist from CLI
- [ ] Verify alignment: `python meridctl_simple.py git-help` matches quick sheet
- [ ] Test all commands: `python meridctl_simple.py status`, `git-help`, `pre-merge-checklist`

### **When Pre-Merge Checks Change**
- [ ] Update `meridctl_simple.py pre-merge-checklist` (CLI first)
- [ ] Re-sync `MERID_OPERATOR_QUICK_SHEET.md` from CLI
- [ ] Update `CONTRIBUTING.md` pre-merge section from CLI
- [ ] Verify alignment: `python meridctl_simple.py pre-merge-checklist` matches quick sheet
- [ ] Test validation: `python meridctl_simple.py pre-merge-checklist`

### **When Health Monitoring Changes**
- [ ] Update `meridctl_simple.py status` (CLI first)
- [ ] Re-sync `MERID_OPERATOR_QUICK_SHEET.md` from CLI
- [ ] Update related documentation from CLI
- [ ] Verify health check: `python meridctl_simple.py status`
- [ ] Test health snapshot: `python meridctl_simple.py status --save`

---

## 🚀 Release Checklist

### **Before Release**
- [ ] Run `python meridctl_simple.py status` - ensure healthy
- [ ] Run `python meridctl_simple.py pre-merge-checklist` - ensure validation passes
- [ ] Verify CLI help: `python meridctl_simple.py git-help`
- [ ] Check quick sheet alignment with CLI
- [ ] Test all Git conflict patterns on sample files
- [ ] Validate documentation matches CLI output

### **After Release**
- [ ] Update CHANGELOG.md with any CLI changes
- [ ] Tag release with version number
- [ ] Update any related documentation if patterns changed

---

## 📋 Quick Validation Commands

```bash
# Health check
python meridctl_simple.py status

# Git conflict help
python meridctl_simple.py git-help

# Pre-merge validation
python meridctl_simple.py pre-merge-checklist

# Quick sheet alignment check
head -20 MERID_OPERATOR_QUICK_SHEET.md

# Documentation sync check
grep -A 10 "Conflict Resolution" CONTRIBUTING.md
```

---

## 🎯 Key Principle

**CLI First, Then Sync:**
1. **CLI help** (`meridctl_simple.py`) is authoritative source
2. **Quick sheet** (`MERID_OPERATOR_QUICK_SHEET.md`) is derived from CLI
3. **Documentation** (`CONTRIBUTING.md`) is synced from CLI
4. **Guardrail note** in quick sheet reminds maintainers of workflow

---

## 🔍 Alignment Verification

### **Commands to Verify Alignment**
```bash
# Test all CLI commands work
python meridctl_simple.py status
python meridctl_simple.py git-help
python meridctl_simple.py pre-merge-checklist

# Verify quick sheet matches CLI
python meridctl_simple.py git-help | grep "PATTERN 1"
python meridctl_simple.py git-help | grep "PATTERN 2"
python meridctl_simple.py git-help | grep "PATTERN 3"
python meridctl_simple.py git-help | grep "PATTERN 4"
python meridctl_simple.py git-help | grep "PATTERN 5"

# Check guardrail note exists
head -1 MERID_OPERATOR_QUICK_SHEET.md
```

---

## 📚 Related Files

- **`meridctl_simple.py`** - CLI implementation (authoritative)
- **`MERID_OPERATOR_QUICK_SHEET.md`** - Quick reference (derived)
- **`CONTRIBUTING.md`** - Development guide (synced)
- **`tools/merid-git-help.py`** - Interactive helper (aligned)
- **`tools/pre-commit-hook.sh`** - Automation script (aligned)

---

**Status:** ✅ **MAINTENANCE PROCESS DOCUMENTED**  
**Workflow:** 🔧 **CLI-FIRST APPROACH**  
**Alignment:** 📋 **VERIFICATION CHECKLIST**  
**Quality:** 🔍 **DRIFT PREVENTION**  
**Future-Proofing:** 🔮 **SCALABLE PROCESS**  
**Team:** 👥 **SELF-SERVICE ENABLED**  
**Gold Standard:** 🏅 **INSTITUTIONALIZED**
