# MERID Pre-UI Technical + UX Audit Prompt Package

A comprehensive audit prompt and guidance set for reviewing MERID's architecture, safety, observability, agent readiness, accessibility, and security before any UI/UX development begins.

---

## Master Audit Prompt (Paste into AI Assistant)

```
You are an expert crypto/DeFi platform architect, SRE, security engineer, and accessibility-focused UX reviewer.
Audit the MERID monorepo (c:\Dev\MERID) before any UI/UX work begins. Focus on architecture, wiring, capital safety,
observability, autonomous agent readiness, and WCAG-aligned surfaces for the future UI.

REPO STRUCTURE HIGHLIGHTS:
- Contracts: contracts/*.sol
- Backend/infra: web/api, web/services, core/, infra/, observability/, swarm/, security/, integration/
- Agent + swarm logic: collaborative/, swarm/, prompts/, qa/
- Docs/specs: docs/, master_roadmap_checklist.txt
- IaC/CI: deployment/, infra/, workflows/, k8s manifests (if present)

AUDIT CHECKLIST:

1. MENTAL MODEL
   - Produce a concise architecture diagram (text) of services, queues, DBs, chains, external deps.
   - Map data flow: user → API → strategies → chains → storage/observability.
   - Component inventory table: name, type (service/contract/agent), language, dependencies, responsibilities.
   - Flag single points of failure, tight couplings, and missing obvious components (config, feature flags, secrets).

2. VAULTS, STRATEGIES, CAPITAL SAFETY
   - Enumerate all vaults/strategies/contracts, their params, risk assumptions.
   - Confirm caps, pause/kill, withdraw safety, governance/upgrade paths.
   - Prioritized must-fix list (reentrancy, unchecked calls, unsafe upgrades, oracle assumptions, stuck capital) 
     with file refs and concrete fixes.

3. BACKEND SERVICES & WIRING
   - For each API/worker: inputs/outputs/dependencies; how they talk to chains/other services.
   - Identify hard-coded wiring, scattered config, duplicated logic.
   - Evaluate separation of concerns (trading vs risk vs orchestration vs agents).
   - Recommend minimal refactors to expose clean, stable endpoints for UI (/status, /vaults, /positions, /risk, /incidents).

4. AGENT FRAMEWORK & AUTONOMY
   - Document current/planned roles (observer, dev, remediator, deploy-intent, tool-scout) and permissions.
   - Describe tool access paths (repo, CI, metrics, logs, configs) and gateways.
   - Verify separation of powers between orchestrators, auditors/verifiers, humans/governance; note policy/veto gaps.
   - Propose minimal v0.1 agent architecture: read-only + PR creation only, with required interfaces/logging/auth hooks.

5. CI/CD, IaC, ENVIRONMENTS
   - Inspect GitHub Actions (/.github/workflows), deployment scripts (deployment/, infra/, k8s/) for build/test/deploy flow.
   - Are dev/stage/prod environments defined? Repeatable builds/tests/rollbacks? Proper secrets handling?
   - Recommend a minimal safe pipeline: PR → build/tests/security lint; main → build/tests → dev deploy; 
     approval-gated staging/prod.

6. OBSERVABILITY & INCIDENT READINESS
   - Audit current metrics/logs/traces (Prometheus/OpenTelemetry instrumentation, observability/ folder).
   - Do we have latency, error rate, throughput, resource usage, PnL/exposure metrics?
   - Provide a minimal v0.1 metrics + alert spec for API, strategy, infra, capital safety 
     (with Prometheus/Grafana snippets if needed).

7. SECURITY, AUTH, RBAC FOR AGENTS/SERVICES
   - Evaluate current auth (JWT, OAuth2 client-credentials, mTLS) and RBAC scopes.
   - Design minimal OAuth2 client-credentials flow for agents: short-lived access tokens, no refresh tokens.
   - Define scopes (metrics.read, logs.read, repo.read, repo.write:dev, ci.trigger:dev, config.read).
   - Note least-privilege violations and fixes (per-agent identities, env separation, policy engine).

8. UI/UX READINESS
   - List backend/contracts/infra that must be fixed/stabilized before UI.
   - Identify safe surfaces already usable for UI (APIs, models, metrics).
   - Specify minimal additional wiring for first UI modules: vault list/status, portfolio view, 
     risk/limits + alerts, activity/incident timeline.
   - Include WCAG 2.2 priorities for connect wallet + deposit/withdraw: focus order/visibility/not obscured, 
     target size, dragging alternatives, redundant entry, accessible authentication, error prevention/identification.

9. SECURITY & PRIVACY CHECKLIST
   - Verify data minimization, encryption in transit/at rest, anonymization for analytics.
   - Confirm wallet flows keep secrets client-side; admin surfaces gated w/ MFA + governance.
   - Ensure RBAC for internal tools; sensitive actions require governance approval.
   - Check compliance readiness (GDPR-style consent/export/delete) and privacy disclosures.
   - Ensure logs avoid leaking secrets; audit events include actor + timestamp.

10. OUTPUT FORMAT
   - Start with a one-page executive summary: key risks, key strengths, top 5 blockers before UI/UX.
   - Detailed sections 1-9 with severity (High/Med/Low), area (contract/backend/infra/agent/observability/security), 
     file references, and actionable fixes (not just descriptions).
```

---

## UI/UX Audit Goals & Success Metrics

### Goals (Pre-Build)
- **Confidence & clarity**: users understand funds, yield, and risk at all times.
- **Frictionless flows**: connect wallet, deposit, withdraw, view positions without friction.
- **Transparency**: surface what autonomous agents do and what governance controls exist.

### Success Metrics (For Later Measurement)
- **Task success rate**: % of users completing connect/deposit/withdraw/view PnL without assistance.
- **Time on task**: median time for first deposit and first withdrawal.
- **Drop-off points**: % abandonment at each funnel step (connect, deposit, withdraw, onboarding).
- **Error/help signals**: support tickets or "help" clicks per 100 active users for core tasks.
- **Perceived trust**: post-task ratings ("I understand what MERID is doing with my funds") in moderated tests.

---

## Wiring Diagram Scope

### User Flows (Front-to-Back)
- Connect wallet / auth → state sync → risk/eligibility checks
- View portfolio summary → positions → detailed vault/strategy view
- Deposit flow: select vault → preview risk/yield → confirm tx → pending → success/failure states
- Withdraw flow: same, including partial withdraws and pending queues
- Notifications/alerts: how users see incidents, pauses, or strategy changes
- "What MERID is doing now": surfacing agent actions and system status

### Technical Flows
- Frontend → API gateway → backend services → on-chain (RPC/provider) → back
- Backend → metrics/logging/tracing → Prometheus/Grafana/log store
- Agent framework → tools (repo, CI, metrics, logs) → CI/CD → environments
- Config/governance path: UI → backend → governance contracts/multisig for parameter or upgrade requests

The diagram should clearly show where UI reads data, where it writes/initiates actions, and which components must be stable for the first UI version.

---

## Accessibility Standards & WCAG 2.2 Focus

### Target Standard
**WCAG 2.2 Level AA** for DeFi/fintech web application.

### High-Priority WCAG 2.2 Criteria for MERID Forms

#### New in 2.2 (AA)
- **2.4.11 Focus Not Obscured (Minimum)**: keyboard focus indicators must not be hidden behind sticky headers/panels/modals.
- **2.5.7 Dragging Movements**: any drag interactions (sliders, graph scrubbing) must have non-drag alternatives (numeric inputs, arrow keys).
- **2.5.8 Target Size (Minimum)**: click/tap targets (buttons, icons, tabs) must meet minimum size/spacing (~24×24 CSS px or equivalent spacing).
- **3.2.6 Consistent Help**: help/docs/tooltips must appear in consistent locations across flows.
- **3.3.7 Redundant Entry**: don't force users to re-type same data in multi-step flows.
- **3.3.8 Accessible Authentication (Minimum)**: auth must not rely solely on remembering/copying complex strings; support password managers and wallet flows.

#### Core 2.0/2.1 AA Criteria (Critical for MERID)
- **1.1.1 Non-text Content (A)**: all icons/charts used as controls need meaningful text alternatives.
- **1.4.3 Contrast (Minimum) (AA) & 1.4.11 Non-text Contrast (AA)**: sufficient contrast for text and UI elements.
- **2.1.1 Keyboard (A) & 2.1.2 No Keyboard Trap (A)**: every step fully keyboard-operable, no traps.
- **2.4.3 Focus Order (A) & 2.4.7 Focus Visible (AA)**: logical focus order, always clearly visible.
- **3.2.1 On Focus (A) & 3.2.2 On Input (A)**: no unexpected context changes on focus/input.
- **3.3.1 Error Identification (A) & 3.3.3 Error Suggestion (AA)**: clear error messages with guidance.
- **3.3.4 Error Prevention (Legal, Financial, Data) (AA)**: confirmation step for financial transactions.

### Pre-Build Testing
- **Keyboard-only navigation**: all flows (connect, deposit, withdraw, view) fully usable with keyboard; no traps, visible focus.
- **Screen reader smoke test**: basic labels, landmarks, announcements for balances/PnL/errors.
- **Color/contrast checks**: automated + manual review for contrast ratios; don't encode state only by color.
- **Zoom/responsive tests**: at 200-400% zoom, key flows remain usable without horizontal scrolling.

### Practical Implementation Notes

#### Focus Not Obscured (2.4.11)
- Tab through connect → vault → amount → confirm flows with mouse disabled.
- Ensure focused elements never hidden under sticky headers, bottom sheets, or toasts.
- Use `element.scrollIntoView({block: 'center'})` when elements receive focus.

#### Target Size (2.5.8)
- Key CTAs (connect, deposit, withdraw, confirm) sized/padded generously for mouse and touch.
- Small icons (info, settings, filters) wrapped in clickable areas meeting minimum target size.
- Test on mobile breakpoints; measure hit areas in inspector, not just visual icon size.

#### Dragging Movements (2.5.7)
- Pair sliders with numeric input fields and stepper buttons (+/-).
- Allow keyboard adjustment via arrow keys, Page Up/Down, or exact number entry.
- For charts/scrubbing, add start/end date inputs or predefined range buttons (1D, 1W, 1M).

#### Accessible Authentication (3.3.8)
- No CAPTCHAs or cognitive puzzles in front of wallet connect.
- Allow password paste and autofill; don't block password managers.
- Clear, labeled form fields; avoid complex visual puzzles.
- Error feedback states what went wrong in text with guidance.

---

## Security & Privacy Audit Checklist

### Data Handling & Privacy
- [ ] Identify all user data types (wallet addresses, emails, KYC fields if any, logs with identifiers).
- [ ] Confirm data minimization: only collect what MERID truly needs.
- [ ] Check PII (if any) encrypted at rest (AES-256) and in transit (TLS 1.2+/1.3).
- [ ] Verify anonymization or pseudonymization for analytics where possible.

### Auth & Session
- [ ] Confirm secure wallet connect flows; no secret keys handled by MERID UI.
- [ ] Enforce MFA for admin/operator interfaces where relevant.
- [ ] Ensure session/token storage avoids XSS-prone patterns and uses short lifetimes.

### Access Control
- [ ] RBAC for internal tools: UI surfaces only data/actions a given role should see (user, support, admin).
- [ ] Sensitive admin actions (changing risk limits, pausing vaults) always gated behind governance and multi-factor protections.

### Compliance Awareness
- [ ] Acknowledge GDPR-style requirements if touching EU users: consent, data export, deletion paths.
- [ ] Clear privacy and data-use disclosures linked in the UI.

### Logging & Observability
- [ ] Ensure logs and error messages do NOT leak secrets or sensitive user data.
- [ ] Security-relevant events (login, role changes, governance actions) audited with user/agent identity and timestamp.

---

## User Research Methods Before Design

### Recommended Approach
Prioritize **small, deep** research over broad surveys for specialized DeFi product.

1. **Stakeholder interviews**: clarify business goals, risk appetite, non-negotiables for capital safety and autonomy messaging.
2. **Expert/target user interviews**: short sessions with crypto-native users, quant traders, DeFi power users to understand mental models and existing tooling pain points.
3. **Task-based usability tests on wireframes**: test connect wallet, deposit, see risk, withdraw, interpret incident/alert flows even with low-fidelity prototypes.
4. **Heuristic evaluation**: apply fintech-focused UX heuristics (clarity of money state, error prevention, transparency of fees/risk) before high-fidelity design.

---

## Next Steps

1. Run this audit prompt against the full MERID codebase (c:\Dev\MERID).
2. Generate executive summary + detailed findings with severity ratings and file references.
3. Prioritize High-severity blockers for immediate remediation before UI work.
4. Use findings to inform:
   - Backend API stabilization roadmap
   - Agent framework v0.1 scope (read-only + PR creation)
   - Observability baseline (metrics/alerts/dashboards)
   - Security/auth hardening (OAuth2 scopes, RBAC policies)
5. Create WCAG 2.2 checklist specifically for connect/deposit/withdraw flows to hand to designers and QA.
6. Document wiring diagram showing stable surfaces for UI integration.

This package serves as the canonical pre-UI audit specification, ensuring every technical review, UX planning session, and AI assistant run checks the same architecture, safety, observability, accessibility, and privacy constraints before visual design begins.
