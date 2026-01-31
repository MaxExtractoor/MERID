# MERID Phase 21d – X Bot Capabilities & Safety Spec

_Status: Draft v0.1 (2026-01-15)_

This document captures the must-have requirements for Phase 21d before any implementation. It focuses on a safe, read-only X interface that feeds social intelligence into the swarm while enforcing strict authentication, auditing, and risk workflows.

---

## 1. Core Goals

1. Treat X as both **intel** and **control surface** with safety-first design.
2. Build a **social-intel swarm path** that classifies and scores mentions before strategies or alerts act on them.
3. Deploy a **protective perimeter** around MERID’s reputation (incident detection, phishing detection, crisis workflows).
4. Provide a **read-only ops console** via X (status, risk, incidents) with strong auth and logging.
5. Lay groundwork for later content/engagement agents without granting posting power in v0.1.

---

## 2. Agent Roles & Flow

```
X Mentions/DMs/Webhooks
        ↓
[Ingress Worker]
  - rate limit-aware polling
  - handles API errors/backoff
        ↓
[Command & Event Parser]
  - detect commands vs intel mentions
  - attach correlation IDs
        ↓
[Social Intel Swarm]
  - classifiers (alerts/complaints/praise/questions/signals)
  - sentiment + topic + spam/bot filters (per-task agents)
  - regime detectors (fear/euphoria spikes, exploit chatter)
  - authenticity scoring + network/actor mapping
        ↓
[Protective Agents]
  - incident/bug chatter detection
  - phishing/impersonation monitor
  - crisis workflow launcher (opens incident, drafts internal notices)
        ↓
[Ops Command Router]
  - authZ via mapping + breach detection score
  - command-level rate limits & approval
  - forwards to backend endpoints (/x/status, /x/risk, …)
        ↓
[Response Builder]
  - summarizes backend data
  - advisory tone, no auto-posting without approval
  - logs every step
```

**NB:** No agent can place trades or publish tweets without a separate human approval workflow.

---

## 3. Internal REST Endpoints (bot → backend)

| Endpoint | Purpose | Notes |
| --- | --- | --- |
| `GET /x/status` | Overall uptime, incidents count, health summary | safe for public read |
| `GET /x/portfolio` | Aggregated PnL, exposure, strategy states | ops role only, DM surface |
| `GET /x/risk` | Risk limits vs usage, drawdowns, kill switches | ops role only |
| `GET /x/incidents` | Recent incidents (incl. social-triggered) | ops role only |
| `GET /x/social-intel` | Advisory sentiment/regime summary | internal use by swarm |
| `GET /x/vaults` | Optional: vault list + basic yields | low-risk |
| `GET /x/help` | Command catalog, disclaimers | public |

All endpoints require bot service authentication (client credentials / signed token) plus per-command RBAC enforced inside the backend.

---

## 4. Authentication & Authorization

### Bot → MERID
- Use OAuth2 client-credentials or mTLS service token scoped to `xbot.read_status`, `xbot.read_ops`, etc.
- Rotate secrets via existing secrets manager; key reload without downtime.

### X User → Bot
- Maintain mapping of X user ID → MERID profile (public/user/ops/admin).
- Allowlist required for ops-grade commands; default unknown users to `public`.
- Commands declare required role + risk level; deny-by-default.

### Breach Detection Integration
- Each request builds `AuthContext` (user, command, IP/X metadata) and calls `security.breach_detection.check_permission(...)` with internal resource keys.
- Log anomaly score + decision; escalate to safe mode on repeated failures.

---

## 5. Rate Limiting & Backoff

### External (X APIs)
- Track `x-rate-limit-*` headers and sleep until reset on 429.
- Token-bucket per endpoint + per API key; operate at ~70–80% of published limits.
- Add jitter to polling intervals; implement exponential backoff + circuit breaker on repeated failures.

### Internal (Commands)
- Per-user command quotas (e.g., 30/hour for read-only, 5/hour for ops commands).
- Global flood control per command type.
- Automatic cooldown when breach detection flags anomalies.

---

## 6. Logging & Monitoring

Log every stage with correlation IDs:
- **Ingress:** user ID, text, raw metadata, rate-limit status.
- **Processing:** auth decision, breach score, command classification, backend endpoints called, swarm advisory path.
- **Response:** high-level summary, success/failure, latency metrics.

Send to dedicated `xbot` log stream (Loki/ELK). Consider hashing batches for tamper evidence. Build dashboards for:
- Command volume by role/type
- Error/429 rates
- Auth failures & breach scores
- Incident triggers from social intel

Alerts on spikes in risky commands, repeated auth failures, or high anomaly scores.

---

## 7. Safety & Incident Workflows

- Social chatter tagged `incident` auto-creates an internal incident stub (no public post) and links on-chain/PnL telemetry.
- Phishing detector monitors impersonation and scam keywords; send to human review queue.
- Crisis workflow agent compiles threads & metrics, proposes human-reviewed statements.
- All memecoin/social-driven signals must pass through `core/memecoin_safety` + market confirmations before strategies see them.

---

## 8. Testing Requirements

1. **Command auth tests** – ensure each command enforces role + breach detection path.
2. **Rate limit/backoff tests** – simulate 429s and verify sleep/backoff + logging.
3. **Social classification tests** – fixtures for alerts, praise, exploit chatter; assert correct tagging.
4. **Incident triggering tests** – ensure exploit chatter + negative PnL triggers incident creation but no auto-post.
5. **Logging/audit tests** – confirm logs emitted with IDs for requests/responses.
6. **Memecoin safety regression** – reuse existing tests ensuring social hype cannot bypass `memecoin_safety` rules.

---

## 9. Open Questions / Next Steps

- Finalize exact list of curated accounts/keywords for v0.1.
- Decide on storage layer for social intel context (RAG/MCP) shared across agents.
- Define DM vs mention command surfaces (DM-only for ops commands?).
- Align `/x/*` endpoints with web API auth stack (service tokens + RBAC).
- Document approval workflow for any future posting agents (Phase 21f+).

---

_Once stakeholders sign off on this spec, proceed with building `social/x_bot_interface.py`, classification agents, backend endpoints, and regression tests per Phase 21d._
