# MERID Zero-Trust Audit — Complete Task List

**Generated:** 2026-02-22
**Total Findings:** 72 actionable items
**Organized by:** Priority stage, then domain

---

## STAGE 0: GHOST INFRASTRUCTURE (Do First — Prevents Cascade Failures)

These are structural hazards that could undermine ALL other fixes.

### T-001: Remove duplicate execution engine
- **Priority:** STAGE 0 | **Domain:** Architecture | **Severity:** CRITICAL
- **Problem:** `merid_core/kalshi/execution_pipeline.py` is an ENTIRE parallel execution engine that consumes NATS OrderIntents directly. It is NOT integrated with MeridLoop, TaCo consensus, or the 9-gate execution path in `merid/execution/`. If anyone wires it up (or it gets activated by event bus misconfiguration), it bypasses ALL safety gates — kill switch, VenueGate, risk manager, deployment controller, execution guards.
- **Files:** `merid_core/kalshi/execution_pipeline.py` (entire file, ~500 lines)
- **Solution:** Delete or quarantine this file. If it's needed for future NATS-based execution, gate it behind a feature flag that defaults OFF and requires explicit `MERID_NATS_EXECUTION_ENABLED=true`. Add a startup warning log if the file is imported. Ensure no event bus subscriber references it.

### T-002: Consolidate to single consensus engine
- **Priority:** STAGE 0 | **Domain:** Swarm | **Severity:** CRITICAL
- **Problem:** Two consensus coordinators are instantiated: `EnhancedConsensusCoordinator` (quorum=3, 60% healthy agents) and `TaCoConsensusCoordinator` (quorum=2, simpler weighting). Both exist in memory. Code references both. Different quorum thresholds mean an opinion routed to TaCo needs fewer agents to approve a trade than Enhanced. Unclear which processes which symbols.
- **Files:** `consensus/consensus_coordinator.py`, `consensus/taco_consensus.py`, `merid/loop.py` (lines 618-656)
- **Solution:** Pick Enhanced as the production coordinator (stricter quorum). Remove TaCo instantiation from `loop.py`. Keep `taco_consensus.py` file but mark class as `@deprecated`. Audit all `TaCoConsensusCoordinator.get_instance()` calls and redirect to Enhanced. Add startup assertion that only one coordinator is active.

### T-003: Fix 35+ silent except-pass violations
- **Priority:** STAGE 0 | **Domain:** Data Integrity | **Severity:** CRITICAL
- **Problem:** Sprint 51 audit found 35+ `except: pass` or `except Exception: pass` blocks in production code paths. These actively swallow errors, hiding bugs. `edge_model.py` alone has 15 violations (L398-464). Also found in `consensus_aggregator.py`, `trading_agent.py` (L1239), `messages.py`, `sentiment.py`, `order_manager.py`.
- **Files:** `edge_model.py` (15 violations), `consensus_aggregator.py` (2), `trading_agent.py` (1), `messages.py`, `sentiment.py`, `order_manager.py` (multiple each)
- **Solution:** For each `except: pass` block: (1) Add `logger.exception()` at minimum, (2) Determine if the exception should propagate or be handled with a fallback value, (3) For trading-critical paths, convert to fail-closed (raise or return error). Use `grep -rn "except.*:.*pass" --include="*.py"` to find all instances. Wire Sprint 51 test into CI to prevent regression.

### T-004: Remove dead agent registry and manifest code
- **Priority:** STAGE 0 | **Domain:** Architecture | **Severity:** MEDIUM
- **Problem:** `agents/registry.py:load_agents()` defines 8 non-streaming agents that are never instantiated in production (the real swarm uses `agents/agent_mesh.py`). `agents/manifest.py` defines agent manifests used only for documentation. These create confusion about which agents are real.
- **Files:** `agents/registry.py`, `agents/manifest.py`
- **Solution:** Move `load_agents()` to a `_legacy` or `_reference` module. Add docstring to `agent_mesh.py` declaring it as the canonical production agent initialization. Add a startup log listing which agents are actually active.

---

## STAGE 1: STOP THE BLEEDING (24 hours — Prevents Immediate Financial Loss)

### T-005: Remove private key from repository
- **Priority:** STAGE 1 | **Domain:** Security | **Severity:** CRITICAL
- **Problem:** `kalshi_private_key.pem` (RSA-2048, 1,680 bytes) exists in the repo root. It is in `.gitignore` but may exist in git history. Anyone with repo access can impersonate the system on the Kalshi API and execute live trades.
- **Files:** `kalshi_private_key.pem` (repo root), `.kalshi/demo_private_key.pem`
- **Solution:** (1) Delete both PEM files from working directory. (2) Run `git filter-repo --path kalshi_private_key.pem --invert-paths` to purge from history. (3) Regenerate the Kalshi API key pair immediately (assume compromised). (4) Store keys in a secrets manager or encrypted vault, never in repo. (5) Add `*.pem` to `.gitignore` if not already present.

### T-006: Rotate all exposed credentials
- **Priority:** STAGE 1 | **Domain:** Security | **Severity:** CRITICAL
- **Problem:** `.env` file (277 lines) contains 50+ real API keys, database passwords, OAuth tokens, and exchange credentials in plaintext. `.env.backup` (429 lines) is a second copy with additional secrets. Both are in `.gitignore` but present on disk. Any machine compromise exposes everything.
- **Files:** `.env`, `.env.backup`
- **Solution:** Rotate ALL keys immediately — assume compromised. Specifically: (1) Kalshi API keys, (2) Exchange creds (Binance, Coinbase, Kraken, OKX, Alpaca), (3) LLM keys (Claude, OpenAI, DeepSeek), (4) Database passwords (Neo4j: `F@tc0ck42069`, MongoDB, Redis), (5) OAuth tokens (Twitter/X full OAuth flow), (6) Telegram bot token, (7) Supabase JWT. After rotation, move to a secrets manager (HashiCorp Vault, AWS Secrets Manager, or at minimum `python-dotenv` with encrypted `.env.enc`).

### T-007: Fix KillSwitchView.tsx — emergency controls are broken
- **Priority:** STAGE 1 | **Domain:** UI | **Severity:** CRITICAL
- **Problem:** Three safety-critical fetch calls use string literals instead of template literals. `fetch('API_ENDPOINTS.OPERATOR_EMERGENCY_STOP')` sends a request to the literal URL string `API_ENDPOINTS.OPERATOR_EMERGENCY_STOP` instead of resolving the variable. Emergency stop, kill switch reset, and category mode cycling are ALL non-functional.
- **Files:** `web/react/src/views/KillSwitchView.tsx` (lines 147, 168, 189)
- **Solution:** Replace all three lines:
  - L147: `fetch('API_ENDPOINTS.OPERATOR_EMERGENCY_STOP', ...)` → `` fetch(`${API_BASE_URL}${API_ENDPOINTS.OPERATOR_EMERGENCY_STOP}`, ...) ``
  - L168: `fetch('API_ENDPOINTS.OPERATOR_RESET_KILL_SWITCH', ...)` → `` fetch(`${API_BASE_URL}${API_ENDPOINTS.OPERATOR_RESET_KILL_SWITCH}`, ...) ``
  - L189: `fetch('API_ENDPOINTS.KALSHI_CATEGORIES', ...)` → `` fetch(`${API_BASE_URL}${API_ENDPOINTS.KALSHI_CATEGORIES}`, ...) ``
  - Add error retry logic (currently fetch failures are silent with no retry).
  - Add a frontend test that verifies the URL is not a string literal.

### T-008: Add margin/balance validation before order placement
- **Priority:** STAGE 1 | **Domain:** Kalshi | **Severity:** CRITICAL
- **Problem:** `execution_pipeline.py:_check_risk()` (lines 329-402) checks position limits, category permissions, daily loss, and total notional — but NEVER calls `get_balance()` to verify the account has sufficient funds. Orders can be submitted that exceed available balance, relying entirely on Kalshi's server-side rejection.
- **Files:** `merid/execution/executors/kalshi.py` (lines 84-235), `merid_core/kalshi/execution_pipeline.py` (lines 329-402)
- **Solution:** Before order submission in `KalshiExecutor.execute_trade()`, add: (1) `balance = await client.get_balance()`, (2) `order_cost = contracts * price_cents` (for limit) or `contracts * 99` (worst case for market), (3) `if balance.available < order_cost: return TradeResult(success=False, error="Insufficient balance")`. Cache balance with 30s TTL to avoid excessive API calls.

### T-009: Fix paper/live mode binding
- **Priority:** STAGE 1 | **Domain:** Kalshi | **Severity:** CRITICAL
- **Problem:** REST client URL (`api.kalshi.com` vs `demo-api.kalshi.co`) is set at KalshiRestClient initialization time, but PAPER/LIVE mode is checked at `execute_trade()` call time via VenueGate. If VenueGate module fails to import (exception caught as warning), mode check is bypassed and orders could hit live endpoint despite paper mode intent.
- **Files:** `merid/execution/executors/kalshi.py` (lines 115-132), `merid/prediction/venue_gate.py` (lines 153-155), `merid_core/kalshi/rest_client.py` (lines 72-77)
- **Solution:** (1) Make VenueGate check FAIL-CLOSED: if VenueGate import fails or `should_simulate_fill()` raises, BLOCK the order (not warn). (2) Bind mode at client initialization: if `KALSHI_ENV=demo`, reject any attempt to switch to live without reinitializing the client. (3) Add startup assertion: `assert client.base_url.contains("demo") == settings.is_paper_trading`.

### T-010: Enforce consensus quorum — no single-agent decisions
- **Priority:** STAGE 1 | **Domain:** Swarm | **Severity:** CRITICAL
- **Problem:** `unified_decision_layer.py` (lines 93-97): if only 1 agent submits a decision, it becomes the final decision with no quorum check. A single compromised agent can execute arbitrary trades.
- **Files:** `agents/unified_decision_layer.py` (lines 93-97)
- **Solution:** Replace single-agent passthrough with minimum quorum enforcement:
  ```python
  if len(contributions) < MIN_QUORUM:  # MIN_QUORUM = 3
      return UnifiedDecision(decision="NO_ACTION", reason="Insufficient quorum")
  ```
  Add configuration: `MERID_MIN_CONSENSUS_QUORUM=3` (env var). Log all cases where quorum is not met as WARNING.

### T-011: Require multi-agent veto confirmation
- **Priority:** STAGE 1 | **Domain:** Swarm | **Severity:** CRITICAL
- **Problem:** `consensus_coordinator.py` (lines 543-548): a single "veto" vote from ANY agent instantly sets `ConsensusState.VETOED` and blocks the trade. A compromised risk manager can block ALL trading indefinitely.
- **Files:** `consensus/consensus_coordinator.py` (lines 543-548)
- **Solution:** Require 2+ veto votes (or 1 veto + governance confirmation) before blocking. Change logic:
  ```python
  if vote == "veto":
      round.veto_votes.append(agent_id)
      if len(round.veto_votes) >= MIN_VETO_QUORUM:  # MIN_VETO_QUORUM = 2
          round.state = ConsensusState.VETOED
  ```
  If only 1 veto and it's from risk_manager, escalate to governance agent before finalizing veto. Log all veto attempts.

### T-012: Lock risk limit modification behind real approval
- **Priority:** STAGE 1 | **Domain:** Governance | **Severity:** CRITICAL
- **Problem:** `risk_guard.py` (lines 338-371): `update_limits()` has a `requires_dual_approval` parameter that is NEVER ENFORCED. It just calls `setattr()` directly. Any code path can zero out all risk limits (max_daily_loss, max_drawdown_pct, etc.) at runtime.
- **Files:** `risk/risk_guard.py` (lines 338-371)
- **Solution:** Implement actual dual-approval: (1) `update_limits()` writes proposed changes to a `PendingLimitChange` queue, (2) A second authorized caller must `approve_limit_change(change_id)`, (3) Only after 2 distinct approvers (different agent_id or operator_id) does `setattr()` execute. (4) All limit changes must be logged to audit trail with who proposed and who approved.

### T-013: Replace hardcoded kill switch reset code
- **Priority:** STAGE 1 | **Domain:** Governance | **Severity:** CRITICAL
- **Problem:** `risk_guard.py` (lines 277-300): kill switch reset requires `confirmation_code == "CONFIRM_RESET_TRADING"` — a hardcoded string visible in source code. No rate limiting on attempts.
- **Files:** `risk/risk_guard.py` (lines 277-300)
- **Solution:** Replace with: (1) Time-based OTP generated from a secret seed, (2) Rate limit reset attempts (max 3 per 5 minutes), (3) Require cooldown period (minimum 60s between kill switch activation and reset), (4) Log all reset attempts to audit trail. Alternatively, require operator to authenticate via the web API before reset is accepted.

### T-014: Add threading lock to risk exposure tracking
- **Priority:** STAGE 1 | **Domain:** Data Integrity | **Severity:** CRITICAL
- **Problem:** `merid/pipeline/risk_manager.py` (lines 137-162): `record_fill()` modifies `_exposures` dict (notional_usd, position_count, daily_trades) without any locking. Concurrent fills corrupt state — two simultaneous trades can cause lost updates, bypassing risk limits.
- **Files:** `merid/pipeline/risk_manager.py` (lines 137-162)
- **Solution:** Add `asyncio.Lock` (or `threading.Lock` if sync context):
  ```python
  async def record_fill(self, ...):
      async with self._lock:
          exp = self._get_exposure(venue, domain)
          exp.notional_usd += notional_usd
          exp.position_count += 1
  ```
  Also make `_get_exposure()` atomic (create-if-not-exists under same lock).

---

## STAGE 2: STRUCTURAL INTEGRITY (1 week — Fixes Systemic Weaknesses)

### T-015: Implement proper auth — password hashing
- **Priority:** STAGE 2 | **Domain:** Security | **Severity:** CRITICAL
- **Problem:** `auth/user_manager.py` (lines 162-180): password authentication is a placeholder. Comment says "use bcrypt" but only simplified logic exists. `passlib[bcrypt]` is in requirements.txt but never called.
- **Files:** `auth/user_manager.py` (lines 162-180)
- **Solution:** Import `passlib.hash.bcrypt` and implement: `hashed = bcrypt.hash(password)` on registration, `bcrypt.verify(password, hashed)` on login. Add password complexity requirements (min 12 chars, mixed case, number, special).

### T-016: Implement proper auth — wallet signature verification
- **Priority:** STAGE 2 | **Domain:** Security | **Severity:** CRITICAL
- **Problem:** `auth/user_manager.py` (lines 137-160): wallet signature verification is COMMENTED OUT. Any wallet address auto-creates an account. Login requires only knowing a wallet address, no private key proof.
- **Files:** `auth/user_manager.py` (lines 137-160)
- **Solution:** Uncomment and implement `web3.eth.account.recover_message()` to cryptographically verify wallet signatures. Remove auto-create-on-login or gate it behind explicit registration flow.

### T-017: Fix CORS configuration
- **Priority:** STAGE 2 | **Domain:** Security | **Severity:** CRITICAL
- **Problem:** `web/main.py` (lines 316-322): CORS allows all origins (`["*"]` fallback), all methods (`["*"]`), all headers (`["*"]`) with `allow_credentials=True`. This enables CSRF attacks from any website.
- **Files:** `web/main.py` (lines 316-322)
- **Solution:** Restrict: `allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"]` (and prod domain). `allow_methods=["GET", "POST", "OPTIONS"]`. `allow_headers=["Content-Type", "Authorization", "X-Session-ID", "X-Correlation-ID"]`. Set `allow_credentials=False` unless session cookies are needed.

### T-018: Add auth decorators to API endpoints
- **Priority:** STAGE 2 | **Domain:** Security | **Severity:** HIGH
- **Problem:** `web/api/kalshi_api.py` (line 28+): endpoints like `/markets`, `/positions`, `/balance` are public with no authentication check. Any unauthenticated client can access trading data.
- **Files:** `web/api/kalshi_api.py`, `web/api/` (all route files)
- **Solution:** Create a FastAPI dependency `get_current_user = Depends(validate_session)` and add it to all non-public endpoints. Public endpoints (health check, docs) remain open. Trading endpoints require auth.

### T-019: Implement RBAC system
- **Priority:** STAGE 2 | **Domain:** Security | **Severity:** HIGH
- **Problem:** No role-based access control exists. All authenticated users have equal access. An operator and a viewer have the same permissions.
- **Files:** `auth/user_manager.py` (codebase-wide)
- **Solution:** Add `Role` enum (VIEWER, OPERATOR, ADMIN). Add `role` field to User model. Create `require_role(Role.OPERATOR)` dependency. Gate trading endpoints behind OPERATOR, kill switch behind ADMIN, view endpoints behind VIEWER.

### T-020: Handle order timeout with confirmation query
- **Priority:** STAGE 2 | **Domain:** Kalshi | **Severity:** HIGH
- **Problem:** `rest_client.py` (line 202): 10s timeout on POST to `/portfolio/orders`. If timeout occurs, order may exist on Kalshi's side but framework thinks it failed. Retry sends duplicate (mitigated by `client_order_id` dedup, but tracking is lost).
- **Files:** `merid_core/kalshi/rest_client.py` (lines 202, 250-264), `merid/event_venues/kalshi/client.py`
- **Solution:** On timeout during order placement: (1) Query `GET /portfolio/orders?client_order_id={id}` to check if order was placed, (2) If found, return success with the found order_id, (3) If not found after 3 attempts with 2s delay, return failure. Add `check_order_exists(client_order_id)` helper method.

### T-021: Add orderbook staleness detection
- **Priority:** STAGE 2 | **Domain:** Kalshi | **Severity:** HIGH
- **Problem:** `rest_client.py` (lines 458-470): `get_orderbook()` returns REST snapshot with no timestamp validation. Stale prices (30s+ old) can trigger trades. Kalshi REST API doesn't include server-side timestamp in orderbook response.
- **Files:** `merid_core/kalshi/rest_client.py` (lines 458-470), `merid/execution/executors/kalshi.py` (lines 61-82)
- **Solution:** Add client-side timestamp on fetch: `orderbook["_fetched_at"] = time.time()`. Before using orderbook data for trading, check: `if time.time() - orderbook["_fetched_at"] > MAX_ORDERBOOK_AGE_SECONDS: reject_trade("stale orderbook")`. Default `MAX_ORDERBOOK_AGE_SECONDS = 10`.

### T-022: Make kill switch check fail-closed on exception
- **Priority:** STAGE 2 | **Domain:** Kalshi | **Severity:** HIGH
- **Problem:** `merid/execution/executors/kalshi.py` (lines 97-113): kill switch check is wrapped in try-except. If `can_trade()` raises an exception (not just returns False), the exception handler logs a warning and returns failure — but the next call in a loop might succeed. Should halt permanently until explicitly cleared.
- **Files:** `merid/execution/executors/kalshi.py` (lines 97-113), `merid/execution/router.py` (lines 117-144)
- **Solution:** On kill switch exception: (1) Set a module-level `_kill_switch_error = True` flag, (2) All subsequent `execute_trade()` calls check this flag first and fail immediately, (3) Only clear via explicit `reset_kill_switch_error()` with proper auth. Log as CRITICAL, not WARNING.

### T-023: Sync positions from Kalshi on startup
- **Priority:** STAGE 2 | **Domain:** Kalshi | **Severity:** HIGH
- **Problem:** `execution_pipeline.py` (lines 226-229): `self.positions = {}` — position tracking starts empty on boot. After a restart, risk checks think no positions exist, allowing oversized orders until tracking catches up.
- **Files:** `merid_core/kalshi/execution_pipeline.py` (lines 226-229)
- **Solution:** In `start()` or init, call `positions = await client.get_positions()` and populate `self.positions` dict. Run reconciliation: compare local tracking vs Kalshi-reported positions, log discrepancies. Add periodic reconciliation (every 5 minutes).

### T-024: Add max opinion age check to consensus
- **Priority:** STAGE 2 | **Domain:** Swarm | **Severity:** HIGH
- **Problem:** `consensus_coordinator.py` (lines 283-333): `_handle_opinion_event()` accepts ANY pending opinions regardless of age. An opinion from 10 minutes ago on a rapidly moving market is treated equally to a fresh one.
- **Files:** `consensus/consensus_coordinator.py` (lines 283-333)
- **Solution:** Add age check when collecting opinions:
  ```python
  MAX_OPINION_AGE = 60  # seconds
  valid_opinions = [o for o in opinions if time.time() - o.timestamp < MAX_OPINION_AGE]
  ```
  Discard stale opinions before running consensus. Log discarded opinions count.

### T-025: Add consensus timeout escalation
- **Priority:** STAGE 2 | **Domain:** Swarm | **Severity:** HIGH
- **Problem:** `consensus_coordinator.py` (lines 660-694): after 120s + 2 retries, consensus times out with NO_ACTION safe default. No escalation to governance. No alert to operator. System just silently moves on.
- **Files:** `consensus/consensus_coordinator.py` (lines 660-694)
- **Solution:** On timeout: (1) Publish `consensus.timeout` event to event bus, (2) Alert operator via notification system, (3) If 3 consecutive timeouts for same symbol, escalate to governor agent, (4) If governor unavailable, trigger defensive mode (reduce-only for that symbol).

### T-026: Add signal source authentication
- **Priority:** STAGE 2 | **Domain:** Swarm | **Severity:** HIGH
- **Problem:** `agents/signal_fusion_agent.py` (lines 49-56): external signals accepted from ANY source with no verification. An attacker could spoof orderflow, social sentiment, or onchain data to manipulate consensus.
- **Files:** `agents/signal_fusion_agent.py` (lines 49-56)
- **Solution:** Add source validation: (1) Each signal source must register with a `source_id`, (2) Signals must include `source_id` that matches a registered source, (3) Add rate limiting per source (max N signals per minute), (4) Add anomaly detection (flag signals with scores > 3 standard deviations from recent history).

### T-027: Wire governor agent to execution veto
- **Priority:** STAGE 2 | **Domain:** Governance | **Severity:** HIGH
- **Problem:** `agents/governor_agent.py` (lines 369-610): the governor can recommend PAUSE or RETIRE other agents but has NO veto power over trade execution. It's advisory only — governance has no teeth.
- **Files:** `agents/governor_agent.py` (lines 369-610), `merid/execution/router.py`
- **Solution:** Add governance gate in `ExecutionRouter.execute()`: before final execution, check `governor.approve_trade(intent)`. Governor can return APPROVE, DELAY (queue for review), or BLOCK. If governor is unavailable, default to APPROVE (fail-open to prevent governor crash from halting all trading). Log all governor decisions.

### T-028: Wire intent review to execution pipeline
- **Priority:** STAGE 2 | **Domain:** Governance | **Severity:** HIGH
- **Problem:** `governance/intent_review.py` (lines 115-150): defines quorum requirements for trade approval but is NOT connected to the execution pipeline. It's dead code.
- **Files:** `governance/intent_review.py` (lines 115-150)
- **Solution:** Either: (A) Wire `IntentReviewEngine.review(intent)` into `ExecutionRouter` before executor call, with configurable thresholds for which trades need review (e.g., > $1000, new markets, first trade of day). Or (B) Delete the module if it's not needed and the 9-gate path is sufficient. Don't keep dead governance code.

### T-029: Add write-ahead log for audit trail
- **Priority:** STAGE 2 | **Domain:** Governance | **Severity:** HIGH
- **Problem:** `compliance/audit_logger.py` (line 150-152): in-memory buffer is `clear()`ed before flush to disk. If system crashes between clear and flush, buffer contents are lost. No write-ahead log.
- **Files:** `compliance/audit_logger.py` (lines 150-152)
- **Solution:** Implement write-ahead pattern: (1) Write events to WAL file first (append-only), (2) Flush to primary storage, (3) Only truncate WAL after successful flush confirmed. Use `fsync()` after WAL write for durability. Alternatively, use SQLite in WAL mode for atomic writes.

### T-030: Add recovery reconciliation with Kalshi
- **Priority:** STAGE 2 | **Domain:** Governance | **Severity:** HIGH
- **Problem:** `recovery/disaster_recovery.py`: disaster recovery does NOT include reconciliation with Kalshi. After a crash, the system can't verify that local position tracking matches exchange records. Could recover into an insolvent state.
- **Files:** `recovery/disaster_recovery.py`
- **Solution:** Add `reconcile_with_venue()` to recovery sequence: (1) Fetch all open positions from Kalshi API, (2) Compare with local state, (3) If mismatch: log CRITICAL, enter reduce-only mode, alert operator. Run reconciliation before any new orders are allowed after recovery.

### T-031: Guard float() conversions in data ingestion
- **Priority:** STAGE 2 | **Domain:** Data Integrity | **Severity:** HIGH
- **Problem:** `data/ingestion/data_ingestion.py` (lines 221-454): 15+ unguarded `float(raw.get(...))` calls. If any external API returns malformed data (e.g., `"N/A"`, `null`, `""`), the entire ingestion pipeline crashes.
- **Files:** `data/ingestion/data_ingestion.py` (lines 221-454)
- **Solution:** Create a safe conversion helper:
  ```python
  def safe_float(value, default=0.0):
      try:
          result = float(value)
          if math.isnan(result) or math.isinf(result):
              return default
          return result
      except (TypeError, ValueError):
          return default
  ```
  Replace all `float(raw.get(...))` with `safe_float(raw.get(...))`. Log conversion failures at DEBUG level.

### T-032: Change news agent default-on-error to fail-closed
- **Priority:** STAGE 2 | **Domain:** Data Integrity | **Severity:** HIGH
- **Problem:** `agents/news_monitor_agent.py` (lines 298-307, 378-385): both simulation and consensus validation DEFAULT TO APPROVAL on exception. Broken validation = auto-publish to Twitter/Telegram.
- **Files:** `agents/news_monitor_agent.py` (lines 298-307, 378-385)
- **Solution:** Change `except Exception` blocks to return `{"proceed": False, "approved": False, "reason": "validation_error"}`. Never auto-approve on error. Log the exception. Add alerting if error rate exceeds threshold.

### T-033: Add per-view error boundaries in React
- **Priority:** STAGE 2 | **Domain:** UI | **Severity:** HIGH
- **Problem:** `App.tsx` (line 103): single `ErrorBoundary` wraps ALL views. One component crash takes down the entire dashboard. Operator loses visibility into all systems.
- **Files:** `web/react/src/App.tsx` (line 103)
- **Solution:** Wrap each `<Route>` component in its own `<ErrorBoundary>`:
  ```tsx
  <Route path="/kalshi" element={
    <ErrorBoundary fallback={<ViewError view="kalshi" />}>
      <KalshiDashboardView />
    </ErrorBoundary>
  } />
  ```
  The view-level error boundary shows an error for that view only, while other views remain operational.

### T-034: Validate API_BASE_URL on app startup
- **Priority:** STAGE 2 | **Domain:** UI | **Severity:** HIGH
- **Problem:** `web/react/src/config/constants.ts` (line 13): `API_BASE_URL = getEnv('VITE_API_BASE', "")` defaults to empty string. If env var not set, all fetch calls become relative URLs, which may silently fail in production.
- **Files:** `web/react/src/config/constants.ts` (line 13)
- **Solution:** Add startup validation:
  ```typescript
  if (!API_BASE_URL && import.meta.env.PROD) {
    console.error("CRITICAL: VITE_API_BASE not set in production!");
  }
  ```
  Consider making this a build-time check in Vite config.

### T-035: Block trading on stale data
- **Priority:** STAGE 2 | **Domain:** UI | **Severity:** HIGH
- **Problem:** `KalshiTradeTicket.tsx` (lines 76-79): checks execution gate but NOT data freshness. Operator could place orders based on 30s+ stale price data after a WebSocket disconnect.
- **Files:** `web/react/src/components/KalshiTradeTicket.tsx` (lines 76-79)
- **Solution:** Add staleness check to submit handler:
  ```typescript
  const dataAge = Date.now() - lastPriceUpdate.getTime();
  if (dataAge > 30_000) {
    setError("Market data is stale. Refresh before trading.");
    return;
  }
  ```
  Also disable the submit button when data is stale (red `DataAgeBadge` visible).

---

## STAGE 3: HARDENING (2-4 weeks — Production Readiness)

### T-036: Add agent weight reset/decay
- **Priority:** STAGE 3 | **Domain:** Swarm | **Severity:** HIGH
- **Problem:** `consensus_coordinator.py` (lines 464-478): agent reliability weights are static once initialized. A compromised agent with historical high performance keeps permanent elevated weight.
- **Files:** `consensus/consensus_coordinator.py` (lines 464-478)
- **Solution:** Implement weight decay: `weight *= 0.95` daily (exponential decay to baseline). Require minimum N recent decisions to maintain weight above 1.0. Add reset trigger: if agent has 3 consecutive bad outcomes, reset weight to 0.5.

### T-037: Enable collusion detection
- **Priority:** STAGE 3 | **Domain:** Swarm | **Severity:** HIGH
- **Problem:** `agents/governor_agent.py` (lines 236-257): `_calculate_pairwise_correlation()` function exists but is NEVER CALLED during consensus. Colluding agents can vote identically without detection.
- **Files:** `agents/governor_agent.py` (lines 236-257)
- **Solution:** Call correlation analysis on every consensus round. If any agent pair has correlation > 0.95 over last 20 decisions, flag as potential collusion. Governor should investigate: reduce weight of correlated agents, require independent research sources. Log correlation matrix periodically.

### T-038: Raise minimum confidence threshold
- **Priority:** STAGE 3 | **Domain:** Swarm | **Severity:** MEDIUM
- **Problem:** `ai_signals/signal_validation.py` (lines 272-274): signals accepted with 50% confidence (0.5) — barely above a coin flip for real money trades.
- **Files:** `ai_signals/signal_validation.py` (lines 272-274)
- **Solution:** Raise minimum confidence to 0.65 for trade signals. Add tiered thresholds: 0.5 for opinion submission, 0.65 for trade plan creation, 0.75 for orders > $500. Log signals rejected for low confidence.

### T-039: Fix freshness default inversion
- **Priority:** STAGE 3 | **Domain:** Swarm | **Severity:** HIGH
- **Problem:** `consensus/taco_consensus.py` (line 357): `freshness = getattr(opinion, "signal_freshness", 1.0)` — missing freshness attribute defaults to 1.0 (maximally fresh). Inverted trust model: unknown = maximally trusted.
- **Files:** `consensus/taco_consensus.py` (line 357)
- **Solution:** Invert default: `freshness = getattr(opinion, "signal_freshness", 0.5)` — unknown freshness gets 50% weight. Better: require `signal_freshness` field (raise if missing). Log opinions with missing freshness.

### T-040: Add partial fill detection
- **Priority:** STAGE 3 | **Domain:** Kalshi | **Severity:** HIGH
- **Problem:** `rest_client.py` (lines 271-278): framework assumes atomic fill-or-fail. Kalshi orders can rest and partially fill over time. Framework returns "submitted" without detecting partial fills.
- **Files:** `merid_core/kalshi/rest_client.py` (lines 271-278), `merid/execution/executors/kalshi.py` (lines 217-235)
- **Solution:** After order submission: (1) If order status = "resting", start polling `GET /portfolio/orders/{order_id}` every 5s, (2) Track fill progress (filled_count vs total_count), (3) After 60s or full fill, update position tracking and return final result. (4) If still resting after timeout, return partial fill result with `remaining_count`.

### T-041: Persist idempotency tracking
- **Priority:** STAGE 3 | **Domain:** Kalshi | **Severity:** MEDIUM-HIGH
- **Problem:** `execution_pipeline.py` (line 229): `self.processed_intents: set = set()` — in-memory only. Lost on restart. After crash, duplicate orders possible despite `client_order_id` (Kalshi deduplicates but framework loses tracking).
- **Files:** `merid_core/kalshi/execution_pipeline.py` (line 229)
- **Solution:** Persist to SQLite: `CREATE TABLE processed_intents (client_order_id TEXT PRIMARY KEY, timestamp REAL, market TEXT)`. On startup, load last 24h of intents into memory set. On process, write to DB before submitting to Kalshi. TTL: purge entries > 7 days.

### T-042: Fix daily loss reset timezone
- **Priority:** STAGE 3 | **Domain:** Kalshi | **Severity:** MEDIUM-HIGH
- **Problem:** `execution_pipeline.py` (lines 426-434): daily loss reset uses `time.time()` (local epoch) with hardcoded 24h window. Daylight savings or timezone changes could desync.
- **Files:** `merid_core/kalshi/execution_pipeline.py` (lines 426-434)
- **Solution:** Use UTC datetime: `from datetime import datetime, timezone`. Reset at UTC midnight: `if datetime.now(timezone.utc).date() > self._last_reset_date`. Store `_last_reset_date` as `datetime.date` not float.

### T-043: Fix circuit breaker threshold
- **Priority:** STAGE 3 | **Domain:** Kalshi | **Severity:** HIGH
- **Problem:** `merid/event_venues/kalshi/client.py` (line 78): circuit opens after 5 failures. With 3 retries per request, a single transient issue causes 3 failures, a second request adds 2 more = circuit opens. Too sensitive.
- **Files:** `merid/event_venues/kalshi/client.py` (line 78)
- **Solution:** Increase threshold to 10 failures OR use a sliding window (5 failures in 60s). Add half-open state: after recovery timeout, allow 1 test request before fully closing. Log circuit state transitions.

### T-044: Fix duplicate detection thread safety
- **Priority:** STAGE 3 | **Domain:** Data Integrity | **Severity:** HIGH
- **Problem:** `data/ingestion/data_ingestion.py` (lines 368-376): `_is_duplicate()` uses non-atomic check-then-set on a regular `set()`. Two threads checking the same hash simultaneously both pass.
- **Files:** `data/ingestion/data_ingestion.py` (lines 368-376)
- **Solution:** Use `threading.Lock`:
  ```python
  def _is_duplicate(self, content_hash: str) -> bool:
      with self._dedup_lock:
          if content_hash in self._seen_hashes:
              return True
          self._seen_hashes.add(content_hash)
          return False
  ```

### T-045: Make schema validation required
- **Priority:** STAGE 3 | **Domain:** Data Integrity | **Severity:** HIGH
- **Problem:** `schemas/validator.py` (lines 104-106): if `jsonschema` package is not installed, validation silently returns `True` for all data. Missing dependency = no validation.
- **Files:** `schemas/validator.py` (lines 104-106)
- **Solution:** Make `jsonschema` a required dependency (move from optional to required in `requirements.txt`). If package missing, raise `ImportError` on startup, not silently pass. Add `jsonschema>=4.0.0` to requirements.txt.

### T-046: Guard config port parsing
- **Priority:** STAGE 3 | **Domain:** Data Integrity | **Severity:** MEDIUM-HIGH
- **Problem:** `config/ports.py` (lines 17-22): 6x `int(os.getenv(...))` with no try/except. Invalid env var = application crash on import.
- **Files:** `config/ports.py` (lines 17-22)
- **Solution:** Wrap each in try/except with sane defaults:
  ```python
  def _safe_port(env_var, default):
      try:
          port = int(os.getenv(env_var, str(default)))
          if 1 <= port <= 65535:
              return port
      except (TypeError, ValueError):
          pass
      return default
  BACKEND_PORT = _safe_port("MERID_BACKEND_PORT", 8000)
  ```

### T-047: Encrypt SQLite databases at rest
- **Priority:** STAGE 3 | **Domain:** Data Integrity | **Severity:** MEDIUM
- **Problem:** 13 SQLite databases in `data/` directory contain trading history, consensus decisions, agent traces, betting data, calibration data — all unencrypted.
- **Files:** `assertions.db`, `brier_metrics.db`, `data/agent_traces.db`, `data/betting.db`, `data/calibration.db`, `data/consensus.db`, `data/flow.db`, `data/llm_governance.db`, `data/notifications.db`, `data/prediction_consensus.db`, `data/realized_edge.db`, `data/reward_engine.db`, `data/signals.db`
- **Solution:** Use `sqlcipher` (encrypted SQLite) for sensitive databases (trading, consensus, agent traces). Others (notifications, brier metrics) can remain unencrypted. Add encryption key from env var `MERID_DB_ENCRYPTION_KEY`.

### T-048: Add WebSocket message schema validation
- **Priority:** STAGE 3 | **Domain:** UI | **Severity:** MEDIUM
- **Problem:** `useMeridSocket.ts` (lines 43-52): parses JSON messages but tries 3 different payload formats without validation. Malformed data accepted silently.
- **Files:** `web/react/src/hooks/useMeridSocket.ts` (lines 43-52)
- **Solution:** Add zod or yup schema validation for known event types. Unknown event types logged at DEBUG level. Malformed data for known types logged at WARNING level and discarded.

### T-049: Prevent mode switch during active orders
- **Priority:** STAGE 3 | **Domain:** UI | **Severity:** MEDIUM
- **Problem:** `ModeControlPanel.tsx`: mode can be switched while orders are being submitted. No lock during order submission across `BatchOrderPanel` and `KalshiTradeTicket`.
- **Files:** `web/react/src/components/ModeControlPanel.tsx`, `web/react/src/components/KalshiTradeTicket.tsx`
- **Solution:** Add global `isSubmitting` context. When any trading component sets `submitting=true`, disable mode switching in `ModeControlPanel`. Re-enable after all submissions complete.

### T-050: Add token refresh handling
- **Priority:** STAGE 3 | **Domain:** UI | **Severity:** MEDIUM
- **Problem:** `KalshiTradeTicket.tsx` (line 160): `localStorage.getItem('merid-access')` — token never refreshes. If token expires, subsequent requests silently fail with 401.
- **Files:** `web/react/src/components/KalshiTradeTicket.tsx` (line 160)
- **Solution:** Add token refresh interceptor in `useApiData`: if response is 401, attempt refresh via `/api/v1/auth/refresh`. If refresh fails, redirect to login. Store token expiry time and proactively refresh 5 minutes before expiry.

### T-051: Wire rate limiting middleware
- **Priority:** STAGE 3 | **Domain:** Security | **Severity:** HIGH
- **Problem:** `slowapi==0.1.9` is in requirements.txt but no rate limiting middleware is applied to the FastAPI app. All endpoints accept unlimited requests.
- **Files:** `web/main.py`, `requirements.txt`
- **Solution:** Add slowapi middleware:
  ```python
  from slowapi import Limiter, _rate_limit_exceeded_handler
  limiter = Limiter(key_func=get_remote_address)
  app.state.limiter = limiter
  app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
  ```
  Rate limits: 100/min for read endpoints, 10/min for trading endpoints, 3/min for auth endpoints.

### T-052: Pin all dependency versions
- **Priority:** STAGE 3 | **Domain:** Security | **Severity:** MEDIUM
- **Problem:** `requirements.txt`: some dependencies use `>=` constraints instead of pinned `==` versions. Allows untested newer versions to install.
- **Files:** `requirements.txt`
- **Solution:** Run `pip freeze > requirements.lock` for exact versions. Use `requirements.txt` for direct dependencies with `==` pins, `requirements.lock` for full transitive dependency tree. Add `pip-audit` to CI for vulnerability scanning.

### T-053: Add secrets rotation mechanism
- **Priority:** STAGE 3 | **Domain:** Security | **Severity:** MEDIUM
- **Problem:** All API keys, database passwords, and tokens are static environment variables. No rotation mechanism, no versioning, no audit trail of secret access.
- **Files:** Codebase-wide
- **Solution:** Implement secret rotation interface: (1) Each secret has a `version` and `expires_at`, (2) On startup, check if any secrets are expired and log WARNING, (3) Provide `make rotate-keys` Makefile target that generates new keys and updates vault. (4) For Kalshi: generate new API key pair, update env, verify with test request.

### T-054: Persist drawdown state to disk
- **Priority:** STAGE 3 | **Domain:** Governance | **Severity:** MEDIUM
- **Problem:** `risk_guard.py` (lines 143-144): drawdown tracking (`current_drawdown_pct`, `high_water_mark_usd`) is in-memory only. Lost on crash or restart. System forgets how much it's lost.
- **Files:** `risk/risk_guard.py` (lines 143-144)
- **Solution:** Persist to `data/risk_state.json` on every update: `{"high_water_mark": 10000.0, "current_drawdown_pct": 3.5, "daily_loss": 150.0, "last_updated": "2026-02-22T..."}`. Load on startup. If file missing, start conservatively (0 drawdown, require manual high-water-mark confirmation).

### T-055: Fix capability gating enforcement
- **Priority:** STAGE 3 | **Domain:** Governance | **Severity:** MEDIUM
- **Problem:** `governance/capability_gating.py` (lines 43-127): `request_capability()` always returns True — it's logging-only, not enforcement.
- **Files:** `governance/capability_gating.py` (lines 43-127)
- **Solution:** Change return logic: check `reliability_score >= required_threshold` and return `False` if below. Wire into agent decision pipeline: before an agent can execute a capability, check `gating_service.has_capability(agent_id, capability)`. If not granted, reject with explanation.

### T-056: Wire all test files into CI or mark explicitly
- **Priority:** STAGE 3 | **Domain:** Testing | **Severity:** HIGH
- **Problem:** 641 test files exist but CI only runs 12. 629 test files are not executed in CI. Unknown how many pass. 17 test files are not even wired into the Makefile.
- **Files:** `.github/workflows/ci.yml`, `Makefile`, `tests/`
- **Solution:** (1) Run `pytest tests/ --co -q` to count discoverable tests. (2) Add `make test-all` target that runs everything. (3) In CI, add a step that runs all tests (allow failures initially but report). (4) Triage: mark broken tests with `@pytest.mark.skip(reason="needs_fix")` rather than silently not running them. (5) Target: 0 test files outside CI within 2 weeks.

### T-057: Reduce mock dependency in tests
- **Priority:** STAGE 3 | **Domain:** Testing | **Severity:** MEDIUM
- **Problem:** 7,953+ lines of test code use Mock/MagicMock (>15% of all test code). Many tests mock so aggressively they test mock behavior, not real code. Kill switch tests mock all dependencies. Consensus tests mock the coordinator itself.
- **Files:** `tests/` (codebase-wide)
- **Solution:** For critical paths (kill switch, consensus, execution), create integration tests that use real objects with test configurations (not mocks). Use `pytest.fixture` to create real `RiskGuard` with test limits, real `ConsensusCoordinator` with in-memory state. Keep unit tests with mocks for edge cases only.

### T-058: Add swarm integration tests
- **Priority:** STAGE 3 | **Domain:** Testing | **Severity:** HIGH
- **Problem:** `merid/swarm/` has 7 files with ZERO test coverage. Swarm behavior (agent coordination, consensus formation, opinion routing) is completely untested.
- **Files:** `merid/swarm/`, `tests/swarm/`
- **Solution:** Create `tests/swarm/test_swarm_integration.py`: (1) Boot a minimal swarm (3 agents), (2) Inject a market signal, (3) Verify all agents produce opinions, (4) Verify consensus forms within timeout, (5) Verify trade plan has correct direction. (6) Test failure modes: agent crash, timeout, conflicting opinions.

### T-059: Add chaos/network partition tests
- **Priority:** STAGE 3 | **Domain:** Testing | **Severity:** MEDIUM
- **Problem:** No tests for: WebSocket disconnection during active trade, agent crash mid-vote, Kalshi API timeout during order placement, network partition between services.
- **Files:** `tests/chaos/` (mostly empty)
- **Solution:** Create chaos test suite: (1) Kill WebSocket mid-trade, verify frontend recovery. (2) Kill an agent mid-consensus, verify quorum still forms. (3) Inject 10s delay in Kalshi mock, verify timeout handling. (4) Kill Redis mid-operation, verify in-memory fallback. Run in CI with `@pytest.mark.chaos` marker.

### T-060: Delete legacy settings module
- **Priority:** STAGE 3 | **Domain:** Architecture | **Severity:** LOW
- **Problem:** Two settings modules: `merid/settings.py` (primary, Pydantic, 484 lines) and `config/settings.py` (legacy, dataclass, 109 lines). Both load from `.env`. `config/settings.py` uses different env var names (e.g., `SERVER_PORT` vs `MERID_BACKEND_PORT`).
- **Files:** `config/settings.py`
- **Solution:** Audit all imports of `config.settings` — redirect to `merid.settings`. Delete `config/settings.py`. Update any tests that depend on it. Keep `core/settings.py` (constants, non-conflicting).

### T-061: Clean up _legacy directories
- **Priority:** STAGE 3 | **Domain:** Architecture | **Severity:** LOW
- **Problem:** ~100 files in `_legacy/` folders across `web/react/src/components/_legacy/`, `web/react/src/hooks/_legacy/`, `web/react/src/views/_legacy/`. Dead code not imported by active components.
- **Files:** `web/react/src/components/_legacy/`, `web/react/src/hooks/_legacy/`, `web/react/src/views/_legacy/`
- **Solution:** Delete all `_legacy/` directories. If any are needed for reference, they're in git history. Run `npm run build` after deletion to verify nothing breaks.

### T-062: Add WebSocket event replay endpoint
- **Priority:** STAGE 3 | **Domain:** Real-time | **Severity:** MEDIUM
- **Problem:** If a client disconnects and >20 trade events fire during disconnect, those events are lost. No replay endpoint exists. Client reconnects with stale view.
- **Files:** `web/api/ws_trade_events.py`
- **Solution:** Add REST endpoint: `GET /api/v1/events/replay?since={timestamp}&type={event_type}`. Returns events from in-memory buffer (last 100) or from persistent event store if available. Client calls this on WebSocket reconnect before processing live events.

### T-063: Add automatic circuit breaker for kill switch
- **Priority:** STAGE 3 | **Domain:** Governance | **Severity:** MEDIUM
- **Problem:** Kill switches are manual-only (`emergency_stop()` requires human trigger). No automatic circuit breaker for: venue outage, market volatility spike, correlation breakdown.
- **Files:** `merid/risk/kill_switches.py` (lines 36-49)
- **Solution:** Add automatic triggers: (1) If 5 consecutive order rejections from Kalshi → auto-halt for 5 minutes, (2) If portfolio drawdown exceeds `max_drawdown_pct` → auto-halt, (3) If consensus timeout rate > 50% in last 10 rounds → auto-halt. All auto-halts log the trigger and send operator alert. Auto-recovery after cooldown period (configurable, default 5 min).

### T-064: Add limp mode enforcement
- **Priority:** STAGE 3 | **Domain:** Swarm | **Severity:** MEDIUM
- **Problem:** `consensus_coordinator.py` (lines 741-759): limp mode POLICY is defined (blocked_actions: long/short, max_new_position_usd: 0) but there's NO ENFORCEMENT mechanism checking this policy before execution.
- **Files:** `consensus/consensus_coordinator.py` (lines 741-759)
- **Solution:** In `Loop._execute_plans()`, check `if coordinator.is_limp_mode()` before executing any plan. If limp mode active, filter plans to only allow `reduce`, `close`, `flat` directions. Block any plan with `direction in (LONG, SHORT)`. Log blocked plans.

### T-065: Improve retry jitter distribution
- **Priority:** STAGE 3 | **Domain:** Kalshi | **Severity:** MEDIUM
- **Problem:** `rest_client.py` (lines 220-224): jitter is only 0-25% of delay. 100 concurrent requests retrying simultaneously create near-synchronized waves (thundering herd).
- **Files:** `merid_core/kalshi/rest_client.py` (lines 220-224)
- **Solution:** Use full jitter: `wait = random.uniform(0, delay)` instead of `delay + random.uniform(0, delay * 0.25)`. This distributes retries uniformly across the backoff window. Reference: AWS Architecture Blog "Exponential Backoff and Jitter".

### T-066: Add sanitization for external data before social posts
- **Priority:** STAGE 3 | **Domain:** Data Integrity | **Severity:** MEDIUM
- **Problem:** `agents/news_monitor_agent.py` (lines 180-184): external news headlines posted directly to Twitter/Telegram without sanitization. Malicious news source could inject misleading content.
- **Files:** `agents/news_monitor_agent.py` (lines 180-184)
- **Solution:** Add content sanitization: (1) Strip HTML/markdown from headlines, (2) Truncate to max 280 chars, (3) Blocklist for manipulation keywords ("BUY NOW", "guaranteed", "insider"), (4) Require consensus score > 0.7 before auto-posting any external content.

### T-067: Add heartbeat dead-man's switch for consensus
- **Priority:** STAGE 3 | **Domain:** Swarm | **Severity:** MEDIUM
- **Problem:** No dead-man's switch. If the consensus coordinator crashes or hangs, all trading stops with no recovery mechanism. Positions remain open with no governance override.
- **Files:** `consensus/consensus_coordinator.py`
- **Solution:** Add watchdog: (1) Consensus coordinator publishes heartbeat every 30s, (2) Watchdog checks heartbeat age, (3) If heartbeat > 120s old, watchdog triggers defensive mode (reduce-only), (4) If heartbeat > 300s old, watchdog triggers kill switch, (5) Alert operator at both thresholds.

### T-068: Add replay attack protection for opinions
- **Priority:** STAGE 3 | **Domain:** Swarm | **Severity:** MEDIUM
- **Problem:** `agents/swarm_mixin.py` (lines 191-206): state version is 8 chars of MD5, never checked during consensus. Opinions with different state versions (different market conditions) can be mixed.
- **Files:** `agents/swarm_mixin.py` (lines 191-206)
- **Solution:** (1) Upgrade hash to SHA-256 (full length), (2) Include state_version in opinion object, (3) During consensus, reject opinions whose state_version doesn't match current market state, (4) Add nonce to prevent exact replays.

### T-069: Fix .env.example typo and missing fields
- **Priority:** STAGE 3 | **Domain:** Config | **Severity:** LOW
- **Problem:** `.env.example` has typo: `KRAKE_PRIVATE_KEY` should be `KRAKEN_PRIVATE_KEY`. Missing 5 fields that code references: `POLYGON_ACCESS_KEY_ID`, `POLYGON_SECRET_ACCESS_KEY`, `FINNHUB_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SECRET_KEY`.
- **Files:** `.env.example`
- **Solution:** Fix typo, add missing fields with `change_me` placeholders.

### T-070: Add request timeout to useApiData
- **Priority:** STAGE 3 | **Domain:** UI | **Severity:** MEDIUM
- **Problem:** `useApiData.ts` (line 74): `fetch()` calls have no AbortSignal timeout. Slow API responses could hang indefinitely, freezing the UI polling loop.
- **Files:** `web/react/src/hooks/useApiData.ts` (line 74)
- **Solution:** Add AbortController with timeout:
  ```typescript
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10_000);
  const res = await fetch(url, { signal: controller.signal, ...options });
  clearTimeout(timeout);
  ```

### T-071: Add event listener cleanup to useMeridSocket
- **Priority:** STAGE 3 | **Domain:** UI | **Severity:** MEDIUM
- **Problem:** `useMeridSocket.ts`: listeners added to `eventListenersRef` Map. No automatic cleanup if same handler added multiple times. Listeners can accumulate on component remount.
- **Files:** `web/react/src/hooks/useMeridSocket.ts`
- **Solution:** Return cleanup function from `.on()`:
  ```typescript
  const off = socket.on('event', handler);
  // In useEffect cleanup:
  return () => off();
  ```
  Add deduplication: if same handler reference already registered for an event, skip.

### T-072: Remove orphan test result files from repo root
- **Priority:** STAGE 3 | **Domain:** Hygiene | **Severity:** LOW
- **Problem:** 11 `test_results_*.txt` files and multiple `_fix_*.py` scripts in repo root. These are temporary artifacts that clutter the workspace.
- **Files:** `test_results_5051.txt`, `test_results_batch.txt`, `test_results_constants.txt`, `test_results_early.txt`, `test_results_fixedsprints.txt`, `test_results_h.txt`, `test_results_hi.txt`, `test_results_m.txt`, `test_results_noqur.txt`, `test_results_recent.txt`, `test_results_s47.txt`, `_fix_any.py`, `_fix_apibase_auth.py`, `_fix_buttons.py`, `_fix_displayname.py`, `_fix_duplicates.py`, `_fix_memo.py`, `_fix_timeouts.py`
- **Solution:** Delete all `test_results_*.txt` and `_fix_*.py` from repo root. Add `test_results_*.txt` and `_fix_*.py` to `.gitignore`.

---

## SUMMARY BY STAGE

| Stage | Tasks | Critical | High | Medium | Timeline |
|-------|-------|----------|------|--------|----------|
| **Stage 0** | T-001 to T-004 | 3 | 0 | 1 | Do first |
| **Stage 1** | T-005 to T-014 | 10 | 0 | 0 | 24 hours |
| **Stage 2** | T-015 to T-035 | 4 | 17 | 0 | 1 week |
| **Stage 3** | T-036 to T-072 | 0 | 8 | 29 | 2-4 weeks |
| **TOTAL** | **72 tasks** | **17** | **25** | **30** | |

## SUMMARY BY DOMAIN

| Domain | Tasks | Most Critical |
|--------|-------|---------------|
| Security & Auth | 12 | T-005, T-006, T-015, T-016, T-017 |
| Swarm & Consensus | 13 | T-002, T-010, T-011, T-024, T-025 |
| Kalshi Integration | 11 | T-008, T-009, T-020, T-021, T-023 |
| Governance & Risk | 11 | T-012, T-013, T-027, T-028, T-029 |
| Data Integrity | 9 | T-003, T-014, T-031, T-032, T-044 |
| UI/UX | 10 | T-007, T-033, T-034, T-035 |
| Architecture | 3 | T-001, T-004, T-060 |
| Testing | 3 | T-056, T-057, T-058 |
