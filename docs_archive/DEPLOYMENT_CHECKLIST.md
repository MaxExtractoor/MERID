## MERID Stage 14 — Deployment Readiness Checklist

This checklist captures the mandatory steps before shipping MERID beyond Stage 13.

### 1. Validate Live Health
1. Open the MERID Reality Console and confirm the following panels show fresh data:
   - **Backtest Metrics** (no red/empty sections)
   - **Hardening & Chaos** (notes limited to informational items)
   - **Deployment Readiness** (automation failure rate below 10%, pending validations ≤ 2)
2. Hit `/api/readiness` and verify the returned `notes` array contains “Chaos sweep clean” or informational entries only.

### 2. Export Compliance Logs
1. Click **Export Audit Trail** in the Deployment Readiness card, or call `/api/audit-trail`.
2. Store the downloaded JSON in the release artifacts folder.
3. Confirm the archive includes `validations`, `automation`, and `audits` sections with recent timestamps.

### 3. Deterministic Replay Spot Check
1. Choose a recent `energy_id` from `/api/validations`.
2. POST to `/api/replay/{energy_id}`.
3. Ensure the response has `matches: true`. If not, investigate before deployment.

### 4. Automation Watchdog Verification
1. Confirm `/api/automation` shows no “failed” entries in the last 10 events.
2. If failures exist, trigger a manual retry via the watchdog (see `hardening/watchdog.py`) and recheck the feed.

### 5. Final Documentation & Approval
1. Attach the following to the release ticket:
   - Readiness report (`/api/readiness` payload)
   - Audit export JSON
   - Replay confirmation result
2. Obtain approval from operations before proceeding to deployment.

Once all items pass, MERID Stage 14 is complete and the release can be promoted.***
