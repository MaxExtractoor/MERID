# MERID Phase 21e – Telegram Bot Console Specification

_Status: Draft v0.1 (2026-01-15)_

This document defines the requirements for Phase 21e. Objective: provide a dual-console Telegram bot (ops + user) acting as a secure, read-only + limited-control surface with strong authentication, RBAC, safe controls, and auditability.

---

## 1. Objectives

1. Give MERID operators a secure Telegram console for status/risk/incident visibility with safe controls (pause/resume/reduce risk/emergency stop).
2. Provide power users/investors with read-only portfolio + performance summaries via Telegram.
3. Ensure strict RBAC, session management, MFA hooks, and breach detection integration.
4. Log every command with correlation IDs; support escalations into incident workflows.

---

## 2. Agent Roles & Flow

```
Telegram Update (command / inline button / DM)
        ↓
[Auth Layer]
  - Allowlist (user_id → role)
  - Session tokens + expiry
  - MFA or out-of-band challenge hooks (future)
        ↓
[Rate Limiter + Breach Check]
  - per-user command quotas
  - `BreachDetectionSystem` context
        ↓
[Command Router]
  - map to handler (status/risk/etc.)
  - enforce role + approval
        ↓
[Backend Client]
  - call internal `/x/*` or new `/telegram/*` endpoints
  - gather telemetry
        ↓
[Formatter]
  - build user or ops console response
  - add advisory disclaimers / runbook suggestions
        ↓
[Safe Control Execution]
  - queue limited commands (pause/resume/etc.)
  - require approval flows if configured
        ↓
[Audit + Event Bus]
  - log command, response, latency, anomalies
  - publish to `event_stream`
```

---

## 3. Command Surface

### User Console (default role `viewer`)
- `/help` – list commands + disclaimers
- `/status` – high-level MERID state (uptime, incidents count)
- `/portfolio` – summarised PnL/allocation with redactions
- `/risk` – risk usage + kill switch state (read-only)
- `/intel` – social/market summary (advisory only)

### Ops Console (roles `operator`, `admin`)
- `/ops status` – same as `/status` plus agent-level stats
- `/ops incidents` – incident summaries + quick links
- `/ops alerts` – outstanding alerts + recommended actions
- `/ops pause` – queue pause command (requires confirmation)
- `/ops resume` – resume trading (requires confirmation)
- `/ops reduce_risk` – set temporary exposure cap (bounded)
- `/ops emergency_stop` – admin-only, requires dual approval

Each command mapped to internal REST endpoints (reuse `/x/*` where possible, add `/telegram/*` for ops-specific data).

---

## 4. Authentication & Sessions

- Maintain `TelegramBotConsole` allowlist: user_id → role + auth_token.
- `start_session(user_id, auth_token)` verifies secret (e.g., OTP) and issues session with 4h timeout.
- Require DM-based confirmations for limited-control commands.
- Integrate with `BreachDetectionSystem.check_permission()` per command (resource `telegram.<command>`).
- Log auth failures via `detect_auth_failure`.

---

## 5. Rate Limiting & Safety

- Per-user command quotas (default 60/hour for read-only, 10/hour for ops commands).
- Global cool-down when breach scores spike.
- Safe controls: `pause/resume/reduce_risk/emergency_stop` demand confirmation + optional multi-approver flow (persist pending commands).
- All commands run through approval queue before execution when risk level ≥ high.

---

## 6. Logging & Monitoring

- For each command:
  - record user_id, command, role, session_id, message link, timestamp.
  - log backend latency, status_code, success flag, error text.
  - append to central `telegram_bot` log stream + publish to `event_stream` (`telegram_command`).
- Metrics dashboard: command volume, ops vs user usage, auth failures, rate-limit hits.
- Alerts on emergency_stop usage, repeated auth failures, high breach scores.

---

## 7. Backend Integration

- Reuse `/x/status`, `/x/portfolio`, `/x/risk`, `/x/incidents`, `/x/social-intel` for read-only responses.
- Add `/ops/actions` and `/ops/approval` endpoints to queue safe controls.
- Add `/telegram/sessions` endpoints for session management (create/refresh/revoke).

---

## 8. Testing Requirements

1. **Auth tests** – sessions, token mismatch, expired session denial.
2. **RBAC tests** – viewer cannot run ops commands; admin can run emergency stop only with confirmation path.
3. **Rate limit tests** – exceeding quotas returns friendly message + logs incident.
4. **Safe control tests** – pause/emergency workflows require confirmation + audit entry.
5. **Logging tests** – ensure telemetry events emitted with latency/status.

---

## 9. Open Questions / Follow-ups

- Decide on OTP delivery mechanism for `auth_token` (manual secret vs. integration).
- Confirm whether ops commands should require dual approval (two distinct admins) or single admin + reason.
- Determine message formatting (Markdown vs HTML) and localization needs.
- Align new `/telegram/*` endpoints with existing RBAC scopes.

---

Once approved, implementation steps:
1. Build Telegram bot service (handlers, auth, rate limits, approval queues).
2. Add backend endpoints/tests for ops commands and session management.
3. Integrate with monitoring/logging dashboards.
