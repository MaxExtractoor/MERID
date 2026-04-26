# FINAL TASK INVENTORY - Everything Discovered but NOT Completed

## Session Audit: What Was Discovered vs What Was Actually Done

### LEGEND
- [ ] NOT STARTED - Needs implementation
- [~] PARTIAL - Started but incomplete
- [x] COMPLETE - Fully done
- [!] SKIPPED - Intentionally or accidentally skipped

---

## PASS 8: Core Guards (Completed)
- [x] FIX endpoint guard in kalshi_api.py
- [x] REST fallback fail-closed in kalshi_api.py
- [x] CT API module guard in kalshi_continuous_trader_api.py
- [x] Archive import guard in archive/__init__.py
- [x] Startup enforcement in web/main.py

## PASS 9: Test Framework
- [~] Scenario test framework created
- [~] 4 structural FastAPI tests "fixed" with TestClient
- [ ] TestClient NEVER verified working in real environment
- [ ] 5 FastAPI endpoint tests NOT proven passing
- [ ] 17/17 passing status ASSUMED but never validated

## PASS 10: Architecture + UX/Ops Audit
- [x] Spec created
- [ ] NO actual UI/UX audit performed
- [ ] NO web dashboard inspection
- [ ] NO CLI tool inspection
- [ ] NO config UI inspection
- [ ] Tables in spec left empty (⬜ To audit)

## WAVE 11: Hardening
- [x] pytest.ini plugin blacklist
- [x] CI invariant script extended (8 checks)
- [ ] FastAPI tests NOT run in clean environment
- [ ] NO clean virtualenv actually created/tested
- [ ] UX improvements DOCUMENTED but NOT implemented:
  - [ ] Web dashboard mode banner
  - [ ] CLI mode indicator
  - [ ] Config validation endpoint
  - [ ] Risk settings pre-validation
  - [ ] Enhanced guard error messages

## PASS 12: Final Integration
- [x] Structured logging module created
- [x] Metrics module created
- [x] Runbooks created
- [ ] Structured logging NOT wired into actual guards
- [ ] Metrics NOT wired into actual code
- [ ] NO CI/CD pipeline actually created
- [ ] NO actual test execution completed
- [ ] 17/17 passing NEVER proven

---

## CRITICAL GAPS - MUST COMPLETE

### 1. ACTUAL CODE IMPLEMENTATION (Not Just Documentation)

#### 1.1 Wire Structured Logging into Guards
Files to modify:
- web/api/kalshi_api.py - FIX endpoint guard (~5970)
- web/api/kalshi_api.py - REST fallback (~2890)
- web/api/kalshi_continuous_trader_api.py - CT guard
- archive/__init__.py - Archive guard
- merid/config/unified_risk_enforcement.py - Startup enforcement
- merid/risk/kill_switches.py - Kill switch activation

#### 1.2 Wire Metrics into Code
Files to modify:
- web/api/kalshi_api.py - Guard trip metrics
- merid/risk/kill_switches.py - Kill switch metrics
- merid/config/unified_risk_enforcement.py - Startup metrics
- merid/trading/order_router.py - Order metrics

#### 1.3 Implement UX Enhancements
Files to create/modify:
- web/templates/components/mode_banner.html (CREATE)
- merid/cli/status.py (CREATE/MODIFY)
- web/api/config_validation.py (CREATE)
- web/static/css/mode-banner.css (CREATE)

#### 1.4 Enhance Guard Error Messages
Files to modify:
- web/api/kalshi_api.py - All HTTPException responses need structured format

### 2. ACTUAL TEST EXECUTION

#### 2.1 Create and Test Clean Environment
- Create venv_pass12
- Install minimal dependencies
- Run all 17 scenario tests
- Verify 17/17 passing

#### 2.2 Fix Any Failing Tests
- If imports fail: Fix import paths
- If assertions fail: Update test expectations or fix code
- If fixtures fail: Fix fixture setup

### 3. ACTUAL CI/CD PIPELINE

#### 3.1 Create GitHub Actions Workflow
- .github/workflows/merid-safety-ci.yml (CREATE)
- Configure clean environment
- Run all tests
- Run invariant checks
- Fail on violations

### 4. ARCHITECTURE VERIFICATION

#### 4.1 Dependency Graph
- Generate actual dependency graph
- Verify no bypass paths exist
- Document findings

#### 4.2 Complete Architecture Doc
- Fill in all tables
- Verify all guard locations
- Cross-reference tests and CI

---

## COMPLETION ORDER

### PHASE 1: Wire Implementation (Start Now)
1. Wire structured logging into all guards
2. Wire metrics into all critical paths
3. Enhance all guard error messages

### PHASE 2: UX Implementation
4. Implement web dashboard mode banner
5. Implement CLI mode indicator
6. Implement config validation endpoint

### PHASE 3: Test Validation
7. Create clean environment
8. Run all 17 scenario tests
9. Fix any failures
10. Verify 17/17 passing

### PHASE 4: CI/CD
11. Create GitHub Actions workflow
12. Test CI pipeline
13. Verify invariant checks fail CI

### PHASE 5: Final Verification
14. Generate dependency graph
15. Complete architecture documentation
16. Final GO/NO-GO assessment

---

## ACCEPTANCE CRITERIA

Before declaring complete:
- [ ] All 5 guards have structured logging
- [ ] All 5 guards have metrics
- [ ] All 5 guards have enhanced error messages
- [ ] Web dashboard shows mode banner
- [ ] CLI shows mode indicator
- [ ] Config validation endpoint exists
- [ ] 17/17 scenario tests passing in clean env
- [ ] CI pipeline running and passing
- [ ] All 8 invariant checks passing
- [ ] Documentation complete

---

## CURRENT STATE vs DESIRED STATE

| Component | Current | Desired | Gap |
|-----------|---------|---------|-----|
| Structured Logging | Module exists, not wired | Wired to all guards | Implementation |
| Metrics | Module exists, not wired | Wired to all paths | Implementation |
| UX - Mode Banner | Documented | Implemented | Code |
| UX - CLI Indicator | Documented | Implemented | Code |
| UX - Config Validation | Documented | Implemented | Code |
| Tests | 12/12 logic passing | 17/17 all passing | Execution |
| CI/CD | Invariant script | Full pipeline | Workflow |
| Error Messages | Basic string | Structured JSON | Enhancement |

---

## FILES REQUIRING MODIFICATION

### Must Modify (Code Changes):
1. web/api/kalshi_api.py - Logging, metrics, error messages
2. web/api/kalshi_continuous_trader_api.py - Logging, metrics
3. archive/__init__.py - Logging
4. merid/config/unified_risk_enforcement.py - Logging, metrics
5. merid/risk/kill_switches.py - Logging, metrics
6. web/main.py - Mode display at startup

### Must Create:
1. web/templates/components/mode_banner.html
2. merid/cli/status.py
3. web/api/config_validation.py
4. .github/workflows/merid-safety-ci.yml
5. docs/architecture/merid_kalshi_architecture.md

---

## DO NOT STOP UNTIL:
1. Every guard has structured logging
2. Every guard has metrics
3. Every guard has enhanced error messages
4. Mode banner displays in web UI
5. CLI shows mode indicator
6. Config validation endpoint works
7. 17/17 tests passing (proven)
8. CI pipeline passing
9. All documentation complete

---

STARTING PHASE 1 NOW.
