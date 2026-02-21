# MERID Repository Cleanup Audit
**Generated:** 2026-02-16  
**Purpose:** Identify orphaned modules, redundant code, and technical debt for cleanup

---

## 🔴 CRITICAL BLOAT - IMMEDIATE REVIEW NEEDED

### 1. **Entire Flutter SDK Embedded (14,000+ files)**
**Location:** `c:\Dev\MERID\flutter/`  
**Size:** Massive (complete Flutter framework source)  
**Issue:** Full Flutter SDK checked into repo instead of being a dependency  
**Impact:** Repository bloat, slower clones, unnecessary storage  
**Recommendation:** Remove entirely - Flutter should be installed via system package manager  
**Evidence:** No imports found in Python codebase (`from flutter` or `import flutter`)

### 2. **librex PHP Search Engine (135+ files)**
**Location:** `c:\Dev\MERID\librex/`  
**Type:** Complete PHP web application (search engine fork)  
**Issue:** Unrelated PHP application embedded in Python/TypeScript project  
**Files:** PHP scripts, Docker configs, static assets, entire subproject  
**Recommendation:** Remove - appears to be accidentally included dependency  
**Evidence:** No Python imports, separate technology stack

### 3. **merid-api Node.js Stub (3 files)**
**Location:** `c:\Dev\MERID\merid-api/`  
**Files:** `index.js`, `package.json`, `package-lock.json`  
**Issue:** Minimal Node.js API stub, appears unused  
**Recommendation:** Remove or consolidate into main web API  
**Evidence:** No references in Python codebase

---

## 🟡 ROOT DIRECTORY POLLUTION

### 4. **83 Test Files in Root Directory**
**Pattern:** `test_*.py` files scattered in project root  
**Issue:** Tests should be in `tests/` directory, not root  
**Impact:** Cluttered root, poor organization  
**Examples:**
- `test_advanced_analytics.py`
- `test_ai_signals.py`
- `test_assertion_framework.py`
- `test_blockchain_v2.py`
- `test_brier_metrics.py`
- `test_complete_system.py`
- `test_dashboard.py`
- `test_ml_integration.py`
- `test_multi_asset.py`
- `test_predictive_analytics.py`
- `test_scalability.py`
- `test_system_integration.py`
- `test_trading_system.py`
- `test_web3_integration.py`
- ... and 69 more

**Recommendation:** Move to `tests/` directory or archive if superseded

### 5. **37 Run Scripts in Root Directory**
**Pattern:** `run_*.py` files in project root  
**Impact:** Cluttered root, unclear organization  
**Examples:**
- `run_baseline.py`
- `run_batch_2_scaling.py`
- `run_config_refactor_pilot.py`
- `run_fault_injection.py`
- `run_feature_flag_experiment.py`
- `run_hardening_sprint.py`
- `run_phase*.py` (13 phase-specific scripts)
- `run_stress_tests.py`
- `run_tests.py`
- `run_tiny_experiments.py`
- `run_week*.py` (7 weekly review scripts)

**Recommendation:** Consolidate into `scripts/` or document which are still active

### 6. **19 Report Generation Scripts in Root**
**Pattern:** `generate_*.py` files  
**Examples:**
- `generate_phase2_completion_report.py`
- `generate_phase2_completion_report_ascii.py`
- `generate_phase2_completion_report_demo.py`
- `generate_phase2_completion_report_fixed.py`
- `generate_phase2_completion_report_simple.py`
- `generate_phase3_completion_report.py`
- `generate_phase4_completion_report.py`
- `generate_phase5_completion_report.py`
- `generate_phase5b_completion_report.py`
- `generate_phase6_completion_report.py`
- `generate_phase7_completion_report.py`
- `generate_risk_shadow_report.py`
- `generate_risk_shadow_report_simple.py`
- ... and more

**Recommendation:** Archive historical reports, move active scripts to `scripts/reports/`

---

## 🟠 DUPLICATE & VARIANT FILES

### 7. **Fixed/Working/Final Variants (15+ files)**
**Pattern:** Files with suffixes indicating iterations  
**Issue:** Multiple versions of same script, unclear which is canonical  

**Fixed variants (7 files):**
- `weekly_review_fixed.py`
- `generate_phase2_completion_report_fixed.py`
- `run_phase4a_governance_fixed.py`
- `run_phase6_combined_strategy_execution_fixed.py`
- `test_agent_fixed.py`
- `tests/integration/test_contracts_fixed.py`
- `tests/merid/event_venues/test_kalshi_client_batch66_fixed.py`

**Working variants (3 files):**
- `run_phase4a_governance_working_final.py`
- `run_phase4a_governance_working.py`
- `test_stream_working.py`

**Simple variants (8 files):**
- `generate_risk_shadow_report_simple.py`
- `generate_phase2_completion_report_simple.py`
- `meridctl_simple.py`
- `streams/market_data_stream_simple.py`
- `test_bootstrap_simple.py`
- `test_phase2_2_simple.py`
- `tests/trading/test_execution_simple.py`
- `test_stream_simple.py`

**Demo variants (3 files):**
- `generate_phase2_completion_report_demo.py`
- `scripts/run_paper_demo.py`
- `swarm/demo/resilience_demo.py`

**V2 variants (2 files):**
- `run_phase6_combined_strategy_execution_v2.py`
- `tests/test_blockchain_v2.py`

**Recommendation:** Archive non-canonical versions, establish naming convention

### 8. **Debug Scripts (7 files)**
**Pattern:** `debug_*.py` in root  
**Issue:** Temporary debugging scripts left in codebase  
**Files:**
- `debug_assertion_pipeline.py`
- `debug_basic.py`
- `debug_bootstrap.py`
- `debug_case.py`
- `debug_policy.py`
- `debug_test.py`
- `observability/debug_infrastructure.py`

**Recommendation:** Move to `tools/debug/` or remove if obsolete

### 9. **Temporary Files (4 files)**
**Pattern:** `tmp_*.py`, `tmp_*.txt` in root  
**Issue:** Temporary/scratch files in version control  
**Files:**
- `tmp_np.py` (dataclass test)
- `tmp_test_dataclass.py`
- `tmp_swarm.txt`
- `tmp_swarm_results.txt`

**Recommendation:** Add to `.gitignore`, remove from repo

### 10. **Implementation Option Files (2 files)**
**Files:**
- `IMPLEMENTATION-OPTION-A-AGGREGATOR.py`
- `IMPLEMENTATION-OPTION-B-SERVICE.py`

**Issue:** Design alternatives that should have been archived after decision  
**Recommendation:** Move to `docs/archive/design_options/` or remove

---

## 📁 MASSIVE DOCUMENTATION ARCHIVE

### 11. **318 Archived Documentation Files**
**Location:** `docs/archive/`  
**Size:** Hundreds of markdown files from past sprints  
**Issue:** Valuable history but clutters active docs  
**Content:**
- Phase 0-4 sprint reports (100+ files)
- Week 1-6 status reports (50+ files)
- UTF8 logging pattern iterations (20+ variants)
- Multiple "FINAL" versions of same docs
- Audit reports from different dates
- Implementation summaries (10+ versions)

**Examples of duplicates/iterations:**
- `FINAL_UTF8_PATTERNS_SUMMARY.md`
- `ULTIMATE_UTF8_PATTERNS_SUMMARY.md`
- `COMPLETE_UTF8_PATTERNS_SUMMARY.md`
- `MINIMAL_UTF8_PATTERNS_FINAL.md`
- `PRODUCTION_UTF8_PATTERNS_FINAL.md`
- `RELIABLE_CAPTURE_UTF8_PATTERNS_FINAL.md`
- `GUNICORN_UTF8_PATTERNS_FINAL.md`
- ... 15+ UTF8 pattern variants

**Recommendation:** 
- Keep archive but compress/tar older sprints
- Create index document for historical reference
- Consider moving to external wiki/documentation system

---

## 🔧 ORPHANED/UNUSED MODULES

### 12. **Unused Utility Scripts in Root (20+ files)**
**Examples:**
- `analyze_results.py` (9KB)
- `autonomous_soak_test.py` (24KB)
- `backfill_phase*.py` (3 files)
- `check_actual_status.py`
- `check_analytics.py`
- `clean_test.py`
- `complete_40h_target.py`
- `complete_brier_analysis.py`
- `create_fast_agent.py`
- `create_favicon.py`
- `create_scaling_plan.py`
- `critical_syntax_scanner.py`
- `define_official_roadmap.py`
- `demo_experiment_workflow.py`
- `demo_merid_metrics.py`
- `design_per_task_roi_schema.py`
- `diagnose_slo_breach.py`
- `ensure_strategy_policy_accuracy_column.py`
- `extend_phase7_production_roi_schema.py`
- `monitor_production_dashboard.py`

**Recommendation:** Move to `scripts/maintenance/` or `tools/`, audit for usage

### 13. **Multiple Startup Scripts (6 files)**
**Files in root:**
- `main.py`
- `merid_api.py`
- `merid_app.py`
- `merid_bootstrap.py`
- `meridctl.py`
- `meridctl_logging_only.py`
- `meridctl_simple.py`
- `startup.py`
- `startup_minimal.py`
- `start_merid.py`

**Issue:** 10 different entry points, unclear which is canonical  
**Recommendation:** Consolidate to 1-2 entry points, document others or archive

### 14. **Multiple Completion Trial Scripts**
**Pattern:** Various trial/test completion scripts  
**Files:**
- `complete_trial.ps1`
- `complete_trial.sh`
- `PHASE0B-ACCEPTANCE-TEST.ps1`
- `PHASE0B-ENHANCED-ACCEPTANCE-TEST.ps1`
- `PHASE0B-SIMPLE-ACCEPTANCE-TEST.ps1`
- `PHASE0B-TEST-EXECUTOR.ps1`
- `PHASE0B-TEST.ps1`

**Recommendation:** Consolidate or move to `scripts/testing/phase0/`

---

## 🗄️ POTENTIALLY ORPHANED DIRECTORIES

### 15. **bots/ Directory**
**Contents:** 1 item (not expanded)  
**Evidence:** No imports found (`from bots.` or `import bots.`)  
**Status:** ⚠️ Needs investigation - may be orphaned

### 16. **marketing_swarm/ Directory**
**Contents:** 2 items  
**Evidence:** No imports found  
**Status:** ⚠️ Needs investigation - may be orphaned

### 17. **flink/ Directory**
**Contents:** 6 items (Apache Flink streaming)  
**Evidence:** No Python imports found  
**Status:** ⚠️ Needs investigation - may be unused streaming infrastructure

### 18. **merid-ui/ Directory**
**Contents:** 0 items (empty)  
**Recommendation:** Remove empty directory

### 19. **skills/ Directory**
**Contents:** 0 items (empty)  
**Recommendation:** Remove empty directory

### 20. **node_modules/ Directory**
**Status:** Should be in `.gitignore`, not tracked  
**Recommendation:** Add to `.gitignore`, remove from repo

### 21. **build/ Directory**
**Contents:** 0 items (empty, likely build artifacts)  
**Recommendation:** Ensure in `.gitignore`

---

## 📊 LARGE GENERATED/DATA FILES IN REPO

### 22. **Large Log/Coverage Files (100MB+)**
**Files:**
- `MERID_REPO_TREE.txt` (2.8MB)
- `_merid-directories.txt` (573KB)
- `coverage.xml` (180KB)
- `coverage.json` (8.8MB!)
- `coverage_current.xml` (1MB)
- `coverage_final.xml` (1MB)
- `vite.log` (4.4MB!)
- `master_roadmap_checklist.txt` (172KB)

**Recommendation:** Add to `.gitignore`, regenerate as needed

### 23. **Database Files in Repo**
**Files:**
- `assertions.db` (36KB)
- `brier_metrics.db` (122KB)

**Recommendation:** Add to `.gitignore`, use migrations instead

---

## 🔄 DUPLICATE IMPLEMENTATIONS

### 24. **Multiple Logging Configurations**
**Files:**
- `merid_logging.py`
- `merid_logging_config.py`
- `merid_logging_queue.py`
- `my_gunicorn_logger.py`
- `sitecustomize.py` (logging setup)

**Issue:** Multiple logging configuration approaches  
**Recommendation:** Consolidate to single canonical logging setup

### 25. **Multiple Phase PowerShell Scripts**
**Pattern:** 14 `.ps1` scripts in root for phase testing  
**Recommendation:** Move to `scripts/phases/` directory

### 26. **Multiple Weekly Review Scripts (7+ files)**
**Pattern:** `run_week*.py`, `weekly_*.py`  
**Files:**
- `run_week1_review.py`
- `run_week2_test_expansion.py`
- `run_week3_review.py`
- `run_week5_hardening.py`
- `run_week6_execution.py`
- `run_week6_scaling.py`
- `run_weekly_strict_review.py`
- `weekly_review_basic.py`
- `weekly_review_fixed.py`
- `weekly_review_roi.py`
- `weekly_review_roi_ascii.py`
- `weekly_review_ascii_only.py`

**Recommendation:** Consolidate to single review script with parameters

---

## 🎯 SUMMARY STATISTICS

| Category | Count | Recommendation |
|----------|-------|----------------|
| **Flutter SDK files** | 14,000+ | Remove entire directory |
| **librex PHP files** | 135+ | Remove entire directory |
| **Root test files** | 83 | Move to tests/ |
| **Root run scripts** | 37 | Consolidate to scripts/ |
| **Root generate scripts** | 19 | Move to scripts/reports/ |
| **Archived docs** | 318 | Compress/index |
| **Variant files (_fixed, _v2, etc)** | 23+ | Archive non-canonical |
| **Debug scripts** | 7 | Move to tools/debug/ |
| **Temp files** | 4 | Remove, add to .gitignore |
| **Large log/data files** | 8 | Add to .gitignore |
| **Empty directories** | 3 | Remove |
| **Duplicate entry points** | 10 | Consolidate to 1-2 |

**Estimated Cleanup Impact:**
- **Files to review:** 15,000+ 
- **Storage savings:** 500MB+ (Flutter + librex + logs)
- **Organization improvement:** High (cleaner root, better structure)

---

## 🎬 RECOMMENDED ACTIONS

### Immediate (High Priority)
1. ✅ Remove `flutter/` directory entirely
2. ✅ Remove `librex/` directory entirely  
3. ✅ Move 83 root test files to `tests/` directory
4. ✅ Add large logs/coverage files to `.gitignore`
5. ✅ Remove empty directories (`skills/`, `merid-ui/`, `build/`)

### Short-term (Medium Priority)
6. 📦 Archive variant files (*_fixed, *_working, *_simple) to `archive/variants/`
7. 📦 Move debug scripts to `tools/debug/`
8. 📦 Remove temp files, add `tmp_*` to `.gitignore`
9. 📦 Consolidate run scripts into `scripts/` with subdirectories
10. 📦 Consolidate generate scripts into `scripts/reports/`

### Long-term (Low Priority)
11. 📚 Compress/index docs/archive/ (tar older sprints)
12. 🔍 Audit potentially orphaned directories (bots, marketing_swarm, flink)
13. 🔧 Consolidate startup scripts to canonical entry point
14. 🔧 Consolidate logging configuration
15. 🔧 Remove database files from repo, use migrations

---

## ⚠️ BEFORE REMOVING - VERIFY

For each item marked for removal, verify:
- [ ] No active imports in codebase
- [ ] Not referenced in documentation
- [ ] Not required by CI/CD pipelines
- [ ] Not used in production deployments
- [ ] Has been backed up to archive if historical value

---

**Last Updated:** 2026-02-16  
**Auditor:** Master Architect Review  
**Next Review:** After cleanup implementation
