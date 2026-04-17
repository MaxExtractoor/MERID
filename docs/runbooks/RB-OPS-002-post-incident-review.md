# RB-OPS-002: Post-Incident Review (PIR) Process

**Last updated:** 2026-02-07
**Owner:** Operations
**Trigger:** Any P1/P2 incident, any trading halt lasting > 5 minutes, any data loss event

---

## Timeline

| Step | When | Owner |
|------|------|-------|
| Incident resolved | T+0 | On-call operator |
| PIR document started | T+24h | Incident commander |
| PIR meeting scheduled | T+48h | Team lead |
| PIR finalized + action items filed | T+72h | Incident commander |
| Action items completed | T+2 weeks | Assigned owners |

---

## PIR Template

Copy this template to `docs/pirs/PIR-YYYY-MM-DD-<short-title>.md`:

```markdown
# PIR: <Short Title>

**Date of incident:** YYYY-MM-DD HH:MM UTC
**Duration:** X minutes
**Severity:** P1 / P2 / P3
**Incident commander:** <name>
**Author:** <name>

## Summary

One paragraph describing what happened, the impact, and the resolution.

## Impact

- **Trading halted:** Yes/No (duration)
- **Data loss:** Yes/No (details)
- **Financial impact:** $X (realized losses, missed opportunities)
- **Users affected:** N/A (internal system)

## Timeline

| Time (UTC) | Event |
|------------|-------|
| HH:MM | First alert / anomaly detected |
| HH:MM | Operator notified |
| HH:MM | Trading halted |
| HH:MM | Root cause identified |
| HH:MM | Fix deployed |
| HH:MM | Trading resumed |
| HH:MM | All-clear confirmed |

## Root Cause

Detailed technical explanation of what went wrong and why.

## Detection

- How was the incident detected? (alert, manual observation, user report)
- How long between incident start and detection?
- What could have detected it faster?

## Resolution

Step-by-step description of how the incident was resolved.

## What Went Well

- Item 1
- Item 2

## What Went Wrong

- Item 1
- Item 2

## Action Items

| ID | Action | Owner | Priority | Due Date | Status |
|----|--------|-------|----------|----------|--------|
| 1 | | | P1/P2/P3 | YYYY-MM-DD | Open |
| 2 | | | P1/P2/P3 | YYYY-MM-DD | Open |

## Lessons Learned

Key takeaways for the team.
```

---

## PIR Meeting Agenda (30 min)

1. **Timeline review** (5 min) — Walk through the incident chronologically
2. **Root cause** (10 min) — Technical deep-dive, blameless discussion
3. **Detection & response** (5 min) — What worked, what didn't
4. **Action items** (10 min) — Assign owners and due dates

## Rules

- **Blameless:** Focus on systems and processes, not individuals
- **Honest:** Capture what actually happened, not what should have happened
- **Actionable:** Every finding must have a concrete action item with an owner
- **Timely:** PIR must be completed within 72 hours of resolution

---

## Filing

- Store completed PIRs in `docs/pirs/`
- Link action items to GitHub issues
- Review open action items in weekly standup
