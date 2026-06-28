---
description: Run a laddered paper trading session with pre-flight checks and bracket tracking
---

# Ladder Paper Trading Session

## Pre-Flight (before starting MERID)

1. **Run the pre-flight validation script**
// turbo
```
py scripts/preflight_check.py
```
All 7 checks must pass. Fix any failures before proceeding.

2. **Verify environment flags**
```
# These should be set in your .env or shell:
MERID_ALLOW_LIVE_TRADES=false    # MUST be false for paper sessions
```

3. **Clear stale session data (optional, for a clean run)**
```
# Only if you want a completely fresh session log:
del data\session_log.jsonl
```

## Starting the Session

4. **Start MERID**
```
py main.py
```

5. **Open these dashboards side-by-side:**
   - **Trading tab** → SymbolStatusMatrix (feed/venue/tradeable per symbol)
   - **Risk tab** → ModeSafetyPanel (gate state, PnL delta, kill switch)
   - **Overview tab** → SessionLogPanel (event timeline with bracket labels)

6. **Seed the ladder portfolios**
```
# Via API or UI PaperLadderCard "Seed All Agents" button:
curl -X POST http://localhost:8000/api/v1/paper-ladder/seed-all
```

## During the Session

7. **Monitor these signals continuously:**
   - **Gate state**: should stay CLEAR. If LIMITED, check PnL consistency widget.
   - **SymbolStatusMatrix**: watch for symbols going stale or venues degrading.
   - **SessionLogPanel**: bracket transitions appear as "Bracket: Sandbox ($1,000)" events.
   - **PnL consistency delta**: should stay < $5. Amber = investigate.

8. **If gate goes BLOCKED:**
   - Read the remediation hint in the GateChangeToast.
   - Check SessionLogPanel for the triggering event.
   - Do NOT restart — let the safety system do its job.
   - Fix the root cause (e.g., reset kill switch, wait for recon).

9. **Bracket transitions happen automatically:**
   - Promotion: profit target + min trades + win rate → next tier, re-seeded.
   - Demotion: drawdown breach → previous tier, re-seeded.
   - Each transition is logged to the session timeline with bracket metadata.

## Post-Session Analysis

10. **Export the session log for analysis:**
```
# The JSONL file contains all events with session_id and bracket metadata:
type data\session_log.jsonl
```

11. **Per-bracket analysis checklist:**
    - [ ] Realized PnL per bracket
    - [ ] Max drawdown per bracket
    - [ ] Hit rate (win/loss) per bracket
    - [ ] Gate LIMITED/BLOCKED frequency per bracket
    - [ ] Feed staleness incidents per bracket
    - [ ] Reconciliation warnings per bracket
    - [ ] PnL consistency delta trend across brackets

12. **Key questions to answer:**
    - Did larger brackets trigger more safety incidents?
    - Was there a bracket where PnL looked great but safety signals were complaining?
    - Did the gate correctly block during genuine risk events?
    - Were any gate blocks false positives (too conservative)?

## Ladder Tiers Reference

| Tier | Name | Seed | Profit Target | Max DD | Min Trades | Min Win Rate |
|------|------|------|---------------|--------|------------|--------------|
| 0 | Sandbox | $1,000 | 10% | 20% | 10 | 0% |
| 1 | Rookie | $5,000 | 8% | 10% | 50 | 45% |
| 2 | Contender | $15,000 | 6% | 8% | 100 | 48% |
| 3 | Pro | $50,000 | 5% | 5% | 200 | 50% |
| 4 | Live-Ready | $100,000 | — | 3% | — | 50% |
