# MERID File Purge Recommendations

**Generated**: 2026-01-13  
**Purpose**: Identify files for removal to clean up codebase before port migration

---

## 🟢 KEEP - Production Files (DO NOT DELETE)

### Core Application

- `main.py` - Main entry point
- `startup.py` - System startup orchestration
- `requirements.txt` - Python dependencies
- `README.md` - Primary documentation
- `.env`, `.env.example`, `.env.template` - Configuration
- `.gitignore` - Git configuration

### Active Web Application

- `web/main.py` - Current FastAPI app (will be split, not deleted)
- `web/api/*.py` - All 41 API router files (KEEP ALL)
- `web/templates/unified_standalone.html` - **ACTIVE** main dashboard
- `web/templates/institutional.html` - **ACTIVE** institutional view
- `web/templates/simulation.html` - **ACTIVE** simulation monitor
- `web/templates/live_monitor.html` - **ACTIVE** live intelligence
- `web/templates/trading_perps.html` - **ACTIVE** perps trading
- `web/templates/trading_markets.html` - **ACTIVE** markets trading
- `web/templates/betting.html` - **ACTIVE** betting system
- `web/static/js/unified-standalone.js` - **ACTIVE** main JS
- `web/static/js/betting.js` - **ACTIVE** betting JS
- `web/static/js/trading_perps.js` - **ACTIVE** perps JS
- `web/static/js/trading_markets.js` - **ACTIVE** markets JS
- `web/static/js/unified-master.js` - **ACTIVE** (needs port update)
- `web/static/css/*.css` - All CSS files (KEEP)

### Core Systems

- `agents/` - All agent files (KEEP)
- `core/` - All core system files (KEEP)
- `config/` - Configuration files (KEEP)
- `data/` - Data files (KEEP)
- `utils/` - Utility files (KEEP)
- `swarm/` - Swarm coordination (KEEP)
- `cognitive_core/` - Cognitive systems (KEEP)
- `learning/` - Learning systems (KEEP)
- `memory/` - Memory systems (KEEP)

### Business Logic

- `trading/` - Trading logic (KEEP)
- `arbitrage/` - Arbitrage logic (KEEP)
- `prediction/` - Prediction markets (KEEP)
- `simulation/` - Simulation engine (KEEP)
- `backtesting/` - Backtesting (KEEP)
- `portfolio/` - Portfolio management (KEEP)
- `wallet/` - Wallet management (KEEP)
- `treasury/` - Treasury management (KEEP)

### Infrastructure

- `audit/` - Audit trail (KEEP)
- `monitoring/` - Monitoring (KEEP)
- `ops/` - Operations (KEEP)
- `compliance/` - Compliance (KEEP)
- `governance/` - Governance (KEEP)
- `backup/` - Backup systems (KEEP)
- `recovery/` - Recovery systems (KEEP)
- `ratelimit/` - Rate limiting (KEEP)
- `auth/` - Authentication (KEEP)
- `notifications/` - Notifications (KEEP)

### Testing

- `tests/` - All test files (KEEP)
- `pytest.ini` - Pytest config (KEEP)
- `run_tests.py` - Test runner (KEEP)

### Documentation (Current Architecture)

- `docs/REFLECTION_SYSTEM_V2.md` - **NEW** reflection system
- `docs/SWARM_ARCHITECTURE_REVIEW.md` - **NEW** swarm review
- `docs/PORT_MIGRATION_GUIDE.md` - **NEW** migration guide
- `docs/PORT_ASSIGNMENT_MAP.md` - **NEW** port mapping

---

## 🔴 REMOVE - Deprecated/Unused Files

### Obsolete Documentation (Root Level)

**Reason**: Historical debugging docs, no longer needed

- `ALL_ERRORS_FIXED_FINAL.md` - Historical debug log
- `BOM_FIX_FINAL_REPORT.md` - Historical fix report
- `CLEAN_RESTART_PROCEDURE.md` - Obsolete procedure
- `COMPLETE_SYSTEM_AUDIT.md` - Historical audit
- `COMPREHENSIVE_ANALYSIS.md` - Historical analysis
- `COMPREHENSIVE_GAP_ANALYSIS.md` - Historical gap analysis
- `CONSOLE_ERRORS_FIXED.md` - Historical fix log
- `CRITICAL_AUDITS_COMPLETE.md` - Historical audit
- `CSS_JSON_HTML_AUDIT.md` - Historical audit
- `CURRENT_STATUS_AND_PRIORITIES.md` - Outdated status
- `DASHBOARD_FIX_SUMMARY.md` - Historical fix
- `DATA_FETCH_DIAGNOSIS.md` - Historical diagnosis
- `FILE_LISTING.md` - Obsolete listing
- `FINAL_AUDIT_SUMMARY.md` - Historical audit
- `FINAL_COMPLETION_REPORT.md` - Historical report
- `FRONTEND_HARDENING_COMPLETE.md` - Historical report
- `GAP_ANALYSIS_FINAL.md` - Historical analysis
- `INIT_FILES_AUDIT.md` - Historical audit
- `INSTITUTIONAL_GRADE_STATUS.md` - Outdated status
- `LIVE_DATA_STATUS.md` - Outdated status
- `PHASE_1_COMPLETE.md` - Historical milestone
- `PYTHON_FILES_FIX_REPORT.md` - Historical fix
- `QUICK_FIX.md` - Historical fix
- `SEMANTIC_VERIFICATION_REPORT.md` - Historical report
- `SPECIFICATION_VALIDATION.md` - Historical validation
- `STATE_MODEL_COMPLETE.md` - Historical milestone
- `UNDEFINED_FUNCTIONS_FIXED.md` - Historical fix
- `WIRING_VERIFICATION_COMPLETE.md` - Historical report

**Total**: 28 obsolete MD files (~250KB)

### Obsolete Templates

**Reason**: Not referenced in `web/main.py`, superseded by `unified_standalone.html`

- `web/templates/dashboard.html` - Superseded (26KB)
- `web/templates/dashboard_v2.html` - Superseded (8KB)
- `web/templates/dashboard_v2_full.html` - Superseded (13KB)
- `web/templates/index.html` - Superseded (18KB)
- `web/templates/unified.html` - Superseded (136KB)
- `web/templates/unified_clean.html` - Superseded (45KB)
- `web/templates/debug_state.html` - Debug only (5KB)
- `web/templates/test_predictions.html` - Test only (2KB)
- `web/templates/production_dashboard.html` - Superseded (12KB)

**Total**: 9 obsolete HTML files (~265KB)

### Obsolete JavaScript

**Reason**: Not referenced by any active template

- `web/static/js/institutional.js.backup` - Backup file (27KB)
- `web/static/js/production.js` - Not used (18KB)

**Total**: 2 obsolete JS files (~45KB)

### Obsolete Python Scripts (Root Level)

**Reason**: One-time debug/validation scripts

- `check_javascript.py` - One-time validation
- `check_merid_js.py` - One-time validation
- `check_syntax.py` - One-time validation
- `fix_bom.py` - One-time fix
- `inspect_institutional.py` - One-time debug
- `test_env.py` - One-time test
- `test_polymarket.py` - One-time test
- `verify_production_features.py` - One-time validation
- `verify_python_syntax.py` - One-time validation
- `validate_fresh_environment.py` - One-time validation

**Total**: 10 obsolete Python scripts (~35KB)

### Empty/Placeholder Files

**Reason**: Zero bytes or placeholder

- `pyproject.toml` - 0 bytes
- `state-model-events.md` - 0 bytes
- `state-model-events.EMPTY.claimed.md` - 2 bytes

**Total**: 3 empty files

### Obsolete Batch Files

**Reason**: Superseded by new startup system

- `merid.bat` - Obsolete (48 bytes)
- `MERID Control Center.bat` - Obsolete (209 bytes)

**Total**: 2 obsolete batch files

### Flutter/Mobile (If Not Used)

**Reason**: MERID is web-only, Flutter appears unused

- `.dart_tool/` - Flutter tooling
- `.flutter-plugins-dependencies` - Flutter config
- `.metadata` - Flutter metadata
- `analysis_options.yaml` - Flutter analysis
- `android/` - Android build
- `ios/` - iOS build
- `linux/` - Linux build
- `macos/` - macOS build
- `windows/` - Windows build (Flutter, not Python)
- `build/` - Flutter build artifacts
- `flutter/` - Flutter SDK (14,011 items!)
- `lib/` - Flutter/Dart code (158 items)
- `test/` - Flutter tests
- `pubspec.yaml`, `pubspec.lock` - Flutter dependencies
- `pubspec.yaml.bak`, `pubspec.yaml.broken` - Flutter backups
- `devtools_options.yaml` - Flutter devtools

**Total**: ~14,500 Flutter files (~hundreds of MB)

**⚠️ CRITICAL**: Only delete if MERID is confirmed web-only

---

## 🟡 MAYBE - Review Before Deleting

### Documentation (Potentially Useful)

- `BUILD.md` - Build instructions (may still be useful)
- `QUICKSTART.md` - Quick start guide (may still be useful)
- `START_HERE.md` - Getting started (may still be useful)
- `MASTER_DOCUMENTATION.md` - Master docs (may still be useful)
- `MULTI_AGENT_ARCHITECTURE.md` - Architecture docs (may still be useful)
- `README_CURRENT.md` - Current readme (redundant with README.md?)
- `READY_FOR_TESTING.md` - Testing guide (may still be useful)

**Decision**: Keep if actively maintained, remove if outdated

### State Model Files (Root Level)

- `state-model-core.md` - State model design (11KB)
- `state-model-flow.md` - State flow design (20KB)

**Decision**: Keep if part of active architecture, move to `docs/` if keeping

### Alternative Entry Points

- `merid_app.py` - Alternative entry point? (2.7KB)
- `merid_bootstrap.py` - Bootstrap script? (762 bytes)
- `startup_minimal.py` - Minimal startup? (3.8KB)

**Decision**: Keep if used, remove if superseded by `startup.py`

### Test/Debug Scripts

- `autonomous_soak_test.py` - Soak testing (24KB)
- `tools.py` - Utility tools (2.5KB)

**Decision**: Keep if actively used for testing

### Backend/Frontend Alternatives

- `backend/` - Alternative backend? (3 items)
- `merid-api/` - Alternative API? (3 items)
- `merid-ui/` - Alternative UI? (26 items)
- `src/` - Alternative source? (23 items)

**Decision**: Investigate contents, remove if superseded

### Librex Integration

- `librex/` - External library? (135 items)

**Decision**: Keep if actively used, remove if unused dependency

### Archive Directory

- `docs_archive/` - Archived docs (65 items)

**Decision**: Keep as archive or purge entirely

### Node Modules

- `node_modules/` - NPM dependencies (0 items shown, but may exist)
- `package.json`, `package-lock.json` - NPM config

**Decision**: Keep if frontend uses NPM, remove if unused

---

## Summary

### Safe to Delete Immediately

| Category | Count | Estimated Size |
|----------|-------|----------------|
| Obsolete MD docs (root) | 28 files | ~250 KB |
| Obsolete HTML templates | 9 files | ~265 KB |
| Obsolete JS files | 2 files | ~45 KB |
| Obsolete Python scripts | 10 files | ~35 KB |
| Empty/placeholder files | 3 files | ~2 bytes |
| Obsolete batch files | 2 files | ~257 bytes |
| **TOTAL (Safe)** | **54 files** | **~595 KB** |

### Conditional Delete (Flutter - if web-only)

| Category | Count | Estimated Size |
|----------|-------|----------------|
| Flutter/Mobile files | ~14,500 files | ~hundreds of MB |

### Review Before Delete

| Category | Count | Notes |
|----------|-------|-------|
| Documentation (maybe useful) | 7 files | Review for current relevance |
| State model files | 2 files | Move to `docs/` if keeping |
| Alternative entry points | 3 files | Check if used |
| Test/debug scripts | 2 files | Check if actively used |
| Alternative dirs | 4 dirs | Investigate contents |
| Librex | 1 dir (135 items) | Check if dependency |
| Archive | 1 dir (65 items) | Keep or purge |

---

## Recommended Action Plan

### Phase 1: Safe Cleanup (Immediate)
```bash
# Delete obsolete documentation
rm ALL_ERRORS_FIXED_FINAL.md BOM_FIX_FINAL_REPORT.md CLEAN_RESTART_PROCEDURE.md
rm COMPLETE_SYSTEM_AUDIT.md COMPREHENSIVE_ANALYSIS.md COMPREHENSIVE_GAP_ANALYSIS.md
rm CONSOLE_ERRORS_FIXED.md CRITICAL_AUDITS_COMPLETE.md CSS_JSON_HTML_AUDIT.md
rm CURRENT_STATUS_AND_PRIORITIES.md DASHBOARD_FIX_SUMMARY.md DATA_FETCH_DIAGNOSIS.md
rm FILE_LISTING.md FINAL_AUDIT_SUMMARY.md FINAL_COMPLETION_REPORT.md
rm FRONTEND_HARDENING_COMPLETE.md GAP_ANALYSIS_FINAL.md INIT_FILES_AUDIT.md
rm INSTITUTIONAL_GRADE_STATUS.md LIVE_DATA_STATUS.md PHASE_1_COMPLETE.md
rm PYTHON_FILES_FIX_REPORT.md QUICK_FIX.md SEMANTIC_VERIFICATION_REPORT.md
rm SPECIFICATION_VALIDATION.md STATE_MODEL_COMPLETE.md UNDEFINED_FUNCTIONS_FIXED.md
rm WIRING_VERIFICATION_COMPLETE.md

# Delete obsolete templates
rm web/templates/dashboard.html web/templates/dashboard_v2.html
rm web/templates/dashboard_v2_full.html web/templates/index.html
rm web/templates/unified.html web/templates/unified_clean.html
rm web/templates/debug_state.html web/templates/test_predictions.html
rm web/templates/production_dashboard.html

# Delete obsolete JS
rm web/static/js/institutional.js.backup web/static/js/production.js

# Delete obsolete scripts
rm check_javascript.py check_merid_js.py check_syntax.py fix_bom.py
rm inspect_institutional.py test_env.py test_polymarket.py
rm verify_production_features.py verify_python_syntax.py validate_fresh_environment.py

# Delete empty files
rm pyproject.toml state-model-events.md state-model-events.EMPTY.claimed.md

# Delete obsolete batch files
rm merid.bat "MERID Control Center.bat"
```

**Savings**: ~595 KB + clutter reduction

### Phase 2: Flutter Cleanup (If Web-Only)
```bash
# ONLY if MERID is confirmed web-only (no mobile app)
rm -rf .dart_tool android ios linux macos windows build flutter lib test
rm .flutter-plugins-dependencies .metadata analysis_options.yaml
rm pubspec.yaml pubspec.lock pubspec.yaml.bak pubspec.yaml.broken devtools_options.yaml
```

**Savings**: Hundreds of MB

### Phase 3: Review & Decide
1. Review `BUILD.md`, `QUICKSTART.md`, `START_HERE.md` - Keep if current
2. Check if `merid_app.py`, `merid_bootstrap.py`, `startup_minimal.py` are used
3. Investigate `backend/`, `merid-api/`, `merid-ui/`, `src/` directories
4. Check if `librex/` is an active dependency
5. Decide on `docs_archive/` - keep or purge

---

## Post-Purge Actions

1. **Update `.gitignore`** - Add patterns for build artifacts
2. **Update `README.md`** - Remove references to deleted files
3. **Test startup** - Ensure `python startup.py` still works
4. **Test web app** - Ensure `python -m web.main` still works
5. **Run tests** - Ensure `pytest` still passes

---

## Estimated Total Savings

- **Immediate (Phase 1)**: ~595 KB + reduced clutter
- **Conditional (Phase 2)**: ~hundreds of MB (if Flutter removed)
- **Total files removed**: 54-14,500+ files depending on Flutter decision

**Recommendation**: Execute Phase 1 immediately, investigate Flutter usage before Phase 2.
