# 15m Execution Plan

Production-ready start plan to coordinate parallel work across all tracks without stepping on each other or re-introducing mistakes.

---

## 0. Execution Mode

- All work happens in **short‑lived feature branches**, grouped by phase.
- Every branch:
  - Targets one clearly scoped area.
  - Must keep tests passing for its scope.
  - Must not touch legacy/`legacy/` except to move/delete.

Suggested branch naming:

- `feature/15m-phase01-legacy-removal` 
- `feature/15m-phase04-ui-rewrite` 
- `feature/15m-phase09-config-flags` 
- etc.

---

## 1. Immediate Day‑1 Parallel Tracks

These can all start now without blocking each other.

### Track A: Legacy Removal Core (Backend)

**Owner:** Backend lead  
**Branch:** `feature/15m-phase01-legacy-removal` 

Scope:

- Execute Phases 1–2–3 (module deletion, integration rewrites, tests) end‑to‑end:
  - Delete consensus/sentiment/opinion/debate modules.
  - Rewrite `merid/loop.py`, `merid/prediction/agent_grid.py`, `merid/prediction/trading_agent.py`.
  - Remove/adjust tests that enforce legacy behavior.
- Get to:
  - All imports clean for 15m path.
  - 15m app starts, runs loop, and trades without legacy code.

Success criteria:

- 15m profile boots and runs a tick without errors.
- `pytest` passes for loop, agent grid, trading agent, and venue tests.
- "No consensus/sentiment/opinion/debate imports in 15m path" tests pass.

---

### Track B: Config & Non‑Negotiables Wiring

**Owner:** Backend + Ops  
**Branch:** `feature/15m-phase09-config-and-constitution` 

Scope:

- Implement non‑negotiables in config and code:
  - Single canonical asset list: BTC, ETH, SOL, XRP, DOGE for 15m.
  - 15m‑only timeframe enforcement.
  - Single risk calculator and bankroll source.
- Wire the **15m Operating Constitution** into:
  - `docs/15m/ARCHITECTURE_CURRENT.md`.
  - CI scripts for:
    - Legacy concept grep.
    - Config key budget.
    - Approved canonical paths.

Success criteria:

- Config files for 15m contain only the five assets and 15m contracts.
- CI fails if non‑negotiable violations appear.
- Architecture doc lists active modules and banned concepts accurately.

---

### Track C: UI/UX Rewrite for 15m

**Owner:** Frontend lead  
**Branch:** `feature/15m-phase04-ui-rewrite` 

Scope:

- Execute Phases 4–5–6:
  - Remove legacy screens, routes, and components:
    - `/consensus`, `/debate`, `/sentiment`, `/opinion`, `/mood`.
    - Sentiment meter, mood index, consensus widgets, debate panels.
  - Build the 15m‑centric dashboard:
    - Market list (BTC/ETH/SOL/XRP/DOGE 15m only).
    - Market state/health.
    - Orders, fills, bankroll, risk.
    - Loop/agent status and connectivity.
  - Align labels and state with Kalshi's contract semantics.

Success criteria:

- UI has only the new 15m navigation tree.
- No legacy concepts rendered.
- UI snapshot tests for dashboard and market details pass.

---

### Track D: Repo & Git Hygiene

**Owner:** Repo maintainer  
**Branch:** `feature/15m-phase19-repo-sweep` 

Scope:

- Execute Phase 19–20 partially in parallel:
  - Classify directories and move legacy code into `legacy/` or delete.
  - Clean docs/markdown files:
    - Delete or move any docs that describe behavior you no longer have.
    - Rewrite root README for the 15m stack as mainline.
  - Tag key points:
    - `legacy-pre-15m-sweep` 
    - `kalshi-15m-v1` once all core phases are merged.

Success criteria:

- Root layout is clean and matches the new product.
- No active paths import `legacy/`.
- README and GitHub description accurately describe the new 15m product.

---

### Track E: Observability & Kill‑Switch

**Owner:** Backend/infra  
**Branch:** `feature/15m-phase10-observability` 

Scope:

- Implement metrics and logging for:
  - Loop tick duration.
  - Bankroll freshness.
  - WS bridge health and market state age.
  - Fills ledger and settlement.
- Implement kill‑switch conditions:
  - WS down too long.
  - Bankroll stale.
  - Market catalog empty/bad.
  - Risk engine failure.

Success criteria:

- Metrics exposed for 15m profile.
- Kill‑switch toggles trading to safe mode under failure conditions.
- Tests simulate kill conditions and confirm behavior.

---

### Track F: Strategy Documentation & Backtest Harness

**Owner:** Quant / research  
**Branch:** `feature/15m-phase21-quant-docs-and-backtest` 

Scope:

- Implement Phase 21:
  - `docs/15m_quant_kalshi/whitepaper.md` with strategy and evaluation sections.
  - Minimal backtest harness for 15m crypto contracts.
  - Gap map table (ideal vs current system).
  - Reference agents in `strategies/kalshi_15m_reference/`.

Success criteria:

- Whitepaper present and filled out at least at skeleton level.
- Backtest harness runs on mock data and has tests.
- Gap map clearly identifies modeling and evaluation TODOs.

---

## 2. Coordination and Merge Strategy

### 2.1 Order of merges

To avoid conflicts:

1. Merge **Track A (Legacy Removal Core)** first – it defines the new backend truth.
2. Merge **Track B (Config & Constitution)** next – it locks in rules.
3. Merge **Track C (UI/UX 15m Rewrite)** once backend APIs are stable.
4. Merge **Track E (Observability & Kill‑Switch)** once 15m loop is stable.
5. Merge **Track D (Repo & Git Hygiene)** to solidify structure.
6. Merge **Track F (Quant Docs & Backtest)** when basic harness is ready.

Each merge should:

- Pass all 15m CI jobs.
- Update `docs/15m/ARCHITECTURE_CURRENT.md` if architecture changed.
- Update the success criteria checklist.

### 2.2 PR template

Use a strict PR template for everything:

- Scope: What part of 15m stack does this change?
- Non‑negotiables: Which non‑negotiables are touched? Any at risk?
- Canonical paths: Does this change introduce new paths for existing concepts?
- Legacy interaction: Does this touch any `legacy/` code? If yes, justify.
- Tests: Which tests were added/updated?
- Drift gate:
  - New abstraction? Why?
  - Any duplicated concepts?
  - Any second source of truth?

---

## 3. Daily Workflow to Avoid Mistakes

### 3.1 Standup artifact

Every day, maintain a short `DAILY_15M_STATUS.md` (or internal doc) with:

- What branches are active.
- Which phases are in progress.
- What's blocked.
- Any new risks or drift concerns.

### 3.2 "Red flag" checklist for reviewers

During code review, always check:

- Did this PR add a new module/class? Is it necessary?
- Did it add new config keys? Are they documented and non‑overlapping?
- Did it change the 15m entrypoint, loop, or risk? Are we still aligned with the constitution?
- Did it touch UI semantics? Do labels still match backend and Kalshi?
- Are there any new references to legacy concepts in active paths?

If any answer is uncomfortable, block the PR.

---

## 4. Release Path to a Clean 15m Product

Once all major tracks are merged:

1. Run full 15m CI suite.
2. Run manual smoke test:
   - Start 15m stack.
   - Confirm all five assets (BTC, ETH, SOL, XRP, DOGE) show live 15m markets.
   - Place small test trades, confirm fills and settlement.
   - Confirm kill‑switch under a simulated failure.
3. Tag `kalshi-15m-v1`.
4. Freeze any new structural changes until you've:
   - Fixed any bugs that show up.
   - Updated docs and whitepaper with anything learned post‑launch.

---

## 5. How this keeps mistakes out

This start plan avoids mistakes because:

- Work is split by concern (backend, UI, infra, docs) but unified by the same constitution.
- Every branch has a narrow, testable goal.
- CI enforces non‑negotiables and bans legacy concepts.
- Reviews use a drift‑focused checklist.
- Docs are living and updated with each merge.

If you drop this into the repo and actually use it, you can keep shaping the full production code and logic while trimming and keeping strict separation from legacy, without letting the old architecture leak back in.
