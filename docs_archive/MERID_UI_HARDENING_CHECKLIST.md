# MERID UI Hardening Checklist

**Canonical regression checklist for MERID UI system - run after any backend or agent change**

---

## 🎯 **Overview**

This checklist serves as:
- **Regression checklist** - Run after any backend or agent change
- **Specification** - Defines what each page must always render (no blank views)
- **Quality gate** - Ensures UI hardening standards are maintained

---

## 📋 **Target Pages**

Apply this checklist to all primary UI pages:

- `/` - Main Dashboard
- `/simple-dashboard` - Simple Dashboard  
- `/api-contracts` - API Contracts
- `/mode-management` - Mode Management
- `/observability` - Observability Dashboard
- `/ui-audit` - UI Audit Dashboard
- `/main-test` - Main Test Page
- `/debug-v2` - Debug Dashboard
- `/unified.html` - Unified Dashboard

---

## 🔧 **Universal Requirements (All Pages)**

### 1. **Dev Tools Validation**
- [ ] **HTML loads** - No 4xx/5xx status codes
- [ ] **Console clean** - No unhandled exceptions
- [ ] **Network healthy** - Expected APIs called, inspect for 4xx/5xx or 200 with empty payloads

### 2. **Fallback UI Standards**
- [ ] **Visible header** - Page shows clear title/header
- [ ] **Widget states** - Each widget has:
  - Loading state (spinner/skeleton)
  - Error state (error message, retry button)
  - "No data yet" state (empty state with helpful message)
- [ ] **No blank screens** - No route ever returns completely blank view

### 3. **API Base URL Debug Widget**
- [ ] **Debug widget** - Add to all dashboards showing:
  - `API_BASE_URL` in use
  - Current mode from `/api/v1/modes/current` or `/api/v1/trading/config`

---

## 📄 **Page-Specific Requirements**

### 🏠 **Main Dashboard `/`**

**Must show:**
- [ ] **Agent status** - Name, role, last heartbeat for all agents
- [ ] **Trading stats** - Recent orders, PnL, venue health
- [ ] **LLM/Explainability status** - Last success/error states

**If blank:**
- [ ] Check each widget's error/empty handling
- [ ] Never assume all APIs succeed
- [ ] Temporarily render static "Hello from Main Dashboard" card to verify routing

**Enhancement:**
- [ ] **System health strip** at top showing:
  - API / Neo4j / Redis / Ollama status
  - Global mode + spectator flag

---

### 📊 **Simple Dashboard `/simple-dashboard`**

**Purpose:** Safe fallback with minimal dependencies

**Must use robust endpoints:**
- [ ] `/api/v1/test/simple`
- [ ] `/api/v1/dashboard/portfolio/summary`
- [ ] `/api/v1/dashboard/execution/stats`

**Error handling:**
- [ ] Show small error per widget if any call fails
- [ ] Keep page usable even with partial failures

---

### 🔍 **API Contracts `/api-contracts`**

**Must:**
- [ ] **Fetch OpenAPI** - Get `/openapi.json` and schema endpoints
- [ ] **Render contract data:**
  - List of key endpoints
  - Schema snippets
  - Contract test status (✅/❌) for `/api/v1/dashboard/*`, `/api/v1/institutional/*`, etc.

**If blank:**
- [ ] Check OpenAPI parsing assumptions
- [ ] Verify schema matching reality

---

### ⚙️ **Mode Management `/mode-management`**

**Must read:**
- [ ] `/api/v1/trading/config` (global + spectator)
- [ ] `/api/v1/trading/venues/config`
- [ ] Optional traders config

**Must write:**
- [ ] POST/PATCH changes for mode toggles
- [ ] UI reflects updated values after round-trip

**Enhancements:**
- [ ] **Explicit labels** - "Global mode", "Spectator only", "Live trading allowed"
- [ ] **Audit metadata** - "Last changed at/by" information

---

### 📈 **Observability `/observability`**

**Must use:**
- [ ] `/api/v1/dashboard/execution/stats`
- [ ] `/api/v1/dashboard/portfolio/summary`
- [ ] Swarm/agent status endpoints

**If blank:**
- [ ] Inspect each widget's API call and fallback path
- [ ] Confirm websockets vs polling settings

**Enhancements:**
- [ ] **Events log** - Recent system events (agent failures, LLM timeouts, risk breaches)

---

### 🔎 **UI Audit `/ui-audit`**

**Must run quality checks:**
- [ ] **Data binding validation** - Against schemas
- [ ] **State completeness** - Missing loading/error/empty states
- [ ] **Navigation testing** - All main routes accessible

**If empty:**
- [ ] Always render "Tests run" list with placeholders

**Enhancements:**
- [ ] **"Run all UI checks" button** that:
  - Calls backend test endpoints for each main page
  - Shows pass/fail per page:
    - "Main Dashboard – data OK"
    - "Mode Management – config OK"
    - "Observability – metrics OK"

---

### 🧪 **Main Test `/main-test` & Debug `/debug-v2`**

**Purpose:** Scratchpads for debugging

**`/main-test`:**
- [ ] **API test buttons** - Call key APIs and display raw JSON
- [ ] **Minimal layout** - Never goes blank

**`/debug-v2`:**
- [ ] **Internal state display:**
  - Mode config
  - Last errors
  - Pending energies
- [ ] **Agent self-test buttons**:
  - `GET /api/v1/agents/analyst-gemma-01/selftest`
  - `GET /api/v1/agents/strategy-agent-01/selftest`

---

### 🔄 **Unified Dashboard `/unified.html`**

**Must verify:**
- [ ] **JS bundle loading** - Correct bundle and API base URL
- [ ] **Static fallback** - If this loads and talks to API correctly, issues likely in SPA routing/components

---

## 🤖 **LLM + UI End-to-End Checks**

**On `/` and `/observability`:**
- [ ] **Per-agent LLM status** - Last success, last error

**On `/debug-v2`:**
- [ ] **LLM validation buttons**:
  - Agent self-test endpoints
  - Clear error messages for failures (timeout, connection refused, JSON parse failure)

**Expected behavior:**
- [ ] **Ollama + env correct** → "OK" with latency
- [ ] **Issues** → Clear error message

---

## 📝 **Implementation TODO List**

**Copy-paste this into issues for SWE-1.5:**

1. **[HIGH]** Implement `API_BASE_URL + mode` debug widget on main dashboards
2. **[HIGH]** Add loading/error/empty states to all main pages and widgets (no blank screens)
3. **[MEDIUM]** Wire `/api-contracts` to `/openapi.json` and show contract test status per main endpoint
4. **[MEDIUM]** Ensure `/mode-management` reads/writes global/venue/trader modes and displays clearly
5. **[MEDIUM]** Enhance `/observability` with events log and basic LLM status
6. **[MEDIUM]** Build `/ui-audit` test runner with per-page pass/fail summary and "Run all checks" button
7. **[LOW]** Turn `/main-test` and `/debug-v2` into simple JSON/debug consoles for APIs and internal state
8. **[LOW]** Expose agent self-test endpoints and hook them into `/debug-v2` for LLM validation

---

## 🚀 **Usage Instructions**

### **For Regression Testing:**
1. Run through this checklist after any backend/agent changes
2. Verify all universal requirements first
3. Check page-specific requirements
4. Run LLM end-to-end checks
5. Document any failures in issues

### **For Development:**
1. Use this as specification when building new UI components
2. Ensure all new pages meet universal requirements
3. Add page-specific requirements for new pages
4. Update this checklist when adding new features

### **For Quality Assurance:**
1. Use as acceptance criteria for UI changes
2. Run before deploying to production
3. Use as basis for automated UI tests
4. Maintain as living document

---

## 📊 **Quality Metrics**

**Success criteria:**
- ✅ All pages load without 4xx/5xx errors
- ✅ No unhandled console exceptions
- ✅ All widgets have loading/error/empty states
- ✅ No completely blank screens
- ✅ API debug widgets present on dashboards
- ✅ Page-specific requirements met
- ✅ LLM end-to-end checks pass

**Failure handling:**
- ❌ Document specific failures
- ❌ Create issues for each failure
- ❌ Prioritize by impact (blank screens > missing states > missing enhancements)
- ❌ Track until resolved

---

**This checklist is the canonical specification for MERID UI hardening. Use it consistently across all development and testing activities.**
