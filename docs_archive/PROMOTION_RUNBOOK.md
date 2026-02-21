# MERID Promotion Runbook

**Purpose:** Step-by-step procedure to bring a domain or agent class from paper to live execution.  
**Audience:** Operator (you or future you).  
**Rule:** Do not skip steps. Each step has a verifiable pass/fail condition.

---

## Prerequisites

- MERID repo checked out and dependencies installed.
- Python environment active (`python --version` >= 3.11).
- Web API running (for dashboard verification): `make run-api`.

---

## Part A: Promote a Domain to Live

### Step 1 — Blueprint Checks

Verify architecture and config sanity.

```bash
make blueprint-check
```

**Pass condition:** Exit code 0, all checks PASS.  
**If it fails:** Fix the reported config/manifest issue and re-run.

---

### Step 2 — Paper Trading Matrix

Run the full multi-asset SLO test suite.

```bash
make paper-matrix-test
```

**Pass condition:** All 50 tests pass, exit code 0.  
**If it fails:** Read the failing test name — it maps directly to the SLO that's broken (latency, throughput, coherence, reconciliation, risk limits, execution guard, or book quality).

---

### Step 3 — Agent Gauntlet

Run the per-agent quality gate across all 8 SLO dimensions.

```bash
make gauntlet
```

**Pass condition:** All registered agents show `[PASS]`, exit code 0.  
**If it fails:** The output shows which agent failed which SLO. Fix the agent, then re-run with `make gauntlet-fast` for a quick 5-cycle check.

---

### Step 4 — Generate Promotion Report

Aggregate all three rings into a single verdict.

```bash
make promotion-report
```

**Pass condition:** All three rings show `[PASS]`, the target domain shows `[ELIGIBLE]`, and the overall verdict is `ELIGIBLE FOR LIVE`.  
**If it fails:** The report tells you exactly which ring and which check is blocking. Fix upstream, then re-run.

For structured output:
```bash
make promotion-report-json
```

---

### Step 5 — Verify in Operator Dashboard

Open the Operator Dashboard → **System** tab → **Promotion Status** card.

**Check:**
- All three ring badges are green.
- Guard Enforcement shows **LIVE ALLOWED**.
- The target domain row shows **ELIGIBLE**.

If the card shows stale data, click the refresh button (or wait 60s for auto-poll).

---

### Step 6 — Sync Guard and Switch Mode

The ExecutionGuard must have the latest promotion state before you flip to live.

```bash
# Force-refresh the promotion report via API
curl -X POST http://localhost:8000/api/operator/promotion-report/refresh

# Verify guard has synced (check promotion_enforcement section)
curl http://localhost:8000/api/operator/summary | python -m json.tool
```

Then switch the domain to live mode through the Operator Control Plane UI, or:

```bash
curl -X POST http://localhost:8000/api/operator/mode -d '{"mode": "live"}'
```

**Pass condition:** The guard's `promotion_enforcement.eligible_domains` includes your target domain.

---

### Step 7 — Verify Live Execution is Accepted

Send a small test trade and confirm the guard allows it:

```bash
# Check the most recent verdicts
curl http://localhost:8000/api/operator/guard/verdicts | python -m json.tool
```

**Pass condition:** The verdict for your domain shows `allowed: true` and `promotion_eligibility` is in `checks_passed`.

---

## Part B: Promote a New Agent

### Step 1 — Register the Agent

Ensure the agent is registered in `CanonicalAgentRegistry` and has a valid `category`.

### Step 2 — Run Gauntlet for the Agent

```bash
python -m merid.agent_gauntlet --agent <agent_id> --cycles 10
```

**Pass condition:** All 8 SLOs pass: liveness, error_rate, latency_p95, confidence_avg, confidence_variance, fill_rejection_rate, max_drawdown, sharpe_ratio.

### Step 3 — Regenerate Promotion Report

```bash
make promotion-report
```

**Pass condition:** The agent appears in the `[PROMOTED]` list, not `[BLOCKED]`.

### Step 4 — Verify in Dashboard

Operator Dashboard → System → Promotion Status → expand → Agents section.  
The agent should show its category and 100% SLO pass rate.

---

## Part C: Emergency Rollback

If anything goes wrong after going live:

```bash
# Immediate: activate global kill switch
curl -X POST http://localhost:8000/api/operator/kill-switch -d '{"active": true}'

# Or domain-specific:
curl -X POST http://localhost:8000/api/operator/domain-kill -d '{"domain": "crypto", "active": true}'
```

The kill switch takes precedence over all other checks (including promotion).  
After stabilizing, deactivate the kill switch and investigate.

---

## Part D: Manual Override

When you need to manually promote or demote a domain/agent outside the automated pipeline:

### Promote a domain manually

```bash
curl -X POST http://localhost:8000/api/operator/promotion-override \
  -H "Content-Type: application/json" \
  -d '{"action":"promote","entity_type":"domain","entity_id":"crypto","reason":"passed manual review","operator":"your_name"}'
```

### Demote an agent manually

```bash
curl -X POST http://localhost:8000/api/operator/promotion-override \
  -H "Content-Type: application/json" \
  -d '{"action":"demote","entity_type":"agent","entity_id":"agent_alpha","reason":"SLO regression observed","operator":"your_name"}'
```

**Important:** Manual overrides are recorded in the change log with `source: operator` and are visible in the dashboard with a purple badge. They do NOT change the underlying promotion report — they record your intent for audit purposes.

### View the change log

```bash
# All recent events
curl http://localhost:8000/api/operator/promotion-log

# Only operator overrides
curl "http://localhost:8000/api/operator/promotion-log?source=operator"

# Only automated transitions
curl "http://localhost:8000/api/operator/promotion-log?source=automation"

# Filter to a specific domain
curl "http://localhost:8000/api/operator/promotion-log?entity_type=domain&entity_id=crypto"
```

---

## Part E: Governance Notifications

Promotion events are automatically dispatched to configured notification channels for out-of-band review.

### What triggers a notification

- **All operator overrides** (manual promote/demote via the override API).
- **Automated transitions** where a domain or agent changes from eligible→blocked or blocked→eligible (not initial baseline events).

### Configure channels via environment variables

```bash
# Webhook (Slack, Discord, Teams, or any custom endpoint)
export MERID_GOVERNANCE_WEBHOOK_URL="https://hooks.slack.com/services/T.../B.../..."

# Telegram Bot API
export MERID_GOVERNANCE_TELEGRAM_TOKEN="123456:ABC-DEF..."
export MERID_GOVERNANCE_TELEGRAM_CHAT_ID="-100123456789"
```

A structured log channel is always active by default (no configuration needed).

### Notification format

Each notification includes:
- Entity type and ID (domain/agent).
- Previous → new status.
- Source badge (🤖 AUTO, 👤 OPERATOR, ⚙️ SYSTEM).
- Reason and timestamp.

---

## Quick Reference

| Command | What it does |
|---------|-------------|
| `make blueprint-check` | Ring 1: config/manifest sanity |
| `make paper-matrix-test` | Ring 2: 50 SLO tests |
| `make gauntlet` | Ring 3: per-agent 8-SLO gate |
| `make promotion-report` | All 3 rings + domain/agent verdict |
| `make promotion-report-fast` | Same, 5-cycle gauntlet |
| `make promotion-report-json` | Structured JSON output |
| `make promotion-test` | 37 promotion report + checklist tests |
| `make guard-promotion-test` | 17 guard enforcement tests |
| `make promotion-log-test` | 52 change log tests |
| `make governance-test` | 34 governance notifier tests |

---

## Programmatic Checklist

The promotion checklist is also available as a live API endpoint:

```bash
curl http://localhost:8000/api/operator/promotion-checklist
```

Returns a JSON array of steps, each with `name`, `status` (pass/fail/unknown), `command`, and `detail`. This is what the dashboard card reads to show per-step status.
