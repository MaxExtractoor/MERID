# MERID Operator Training Guide - Reality Enforcement System

## Introduction

This guide trains operators to work with MERID's Reality Enforcement System, which fundamentally changes how you interact with the platform.

**Core Principle:** MERID will not show you information it cannot prove.

---

## The Paradigm Shift

### Traditional Systems
- Show optimistic estimates
- Display "loading" states
- Aggregate uncertainty into confidence scores
- Hide gaps in knowledge

### MERID Reality Enforcement
- Shows nothing without valid assertions
- Displays "unavailable" states honestly
- Preserves multi-dimensional truth
- Exposes gaps in knowledge

**This feels uncomfortable. That's the point.**

---

## System Modes

### 🟢 OPERATIONAL Mode

**What it means:**
- Core domains have valid assertions
- Regime entropy < 0.5
- Conflicts < 30%
- Execution allowed

**What you see:**
- Reality Status Panel shows green badge
- All panels render normally
- Execution buttons enabled
- Full dashboard functionality

**What to do:**
- Operate normally
- Monitor Reality Status Panel
- Watch for degradation warnings

---

### 🟡 DEGRADED Mode

**What it means:**
- Some assertions expired or low confidence
- Regime entropy 0.5-0.7
- System still functional but limited

**What you see:**
- Reality Status Panel shows yellow badge
- Some panels show warnings
- Execution throttled
- Reduced functionality

**What to do:**
- Reduce position sizes
- Increase caution
- Monitor blind spots
- Wait for assertion refresh

**DO NOT:**
- Ignore warnings
- Increase risk
- Override safety limits

---

### 🔴 BLIND Mode

**What it means:**
- >40% assertions expired
- Core domain has zero valid assertions
- Regime entropy > 0.7
- System cannot make reliable decisions

**What you see:**
- Reality Status Panel shows red badge
- Dark red overlay covers screen
- Most panels disappear
- Only failure panels visible
- All execution buttons disabled

**What to do:**
- **STOP TRADING**
- Protect existing positions
- Review failure reason
- Wait for system recovery
- Do NOT force exit

**DO NOT:**
- Try to "fix" the system
- Override blindness mode
- Continue trading
- Panic close positions

---

## Training Drills

### Drill 1: Silent Failure

**Scenario:** UI removes 60% of panels without warning.

**Incorrect Response:**
- Try to refresh the page
- Check browser console
- Assume it's a bug
- Try to restore panels

**Correct Response:**
- Do nothing
- Check Reality Status Panel
- Read failure reason
- Wait for recovery
- Trust the system

**Why:** The system is protecting you from making decisions with insufficient information.

---

### Drill 2: Conflicting Truth

**Scenario:** Two different regime classifications shown simultaneously.

**Incorrect Response:**
- Pick the one you prefer
- Average them together
- Ignore the conflict
- Choose based on bias

**Correct Response:**
- Reduce exposure immediately
- Increase position monitoring
- Wait for conflict resolution
- Accept uncertainty

**Why:** Conflicts indicate genuine uncertainty. Pretending otherwise is dangerous.

---

### Drill 3: Blindness Trigger

**Scenario:** System enters Blindness Mode during active trading.

**Incorrect Response:**
- Force exit blindness mode
- Continue trading manually
- Override safety checks
- Panic close all positions

**Correct Response:**
- Stop new trades immediately
- Protect capital, not alpha
- Monitor existing positions
- Wait for system recovery
- Review what caused blindness

**Why:** Blindness Mode means MERID cannot make reliable decisions. Neither can you without the data.

---

## Understanding the Reality Status Panel

### Mode Badge

- **OPERATIONAL** (Green) - System fully functional
- **DEGRADED** (Yellow) - Reduced functionality
- **BLIND** (Red) - Cannot make decisions
- **CONFLICTED** (Orange) - Contradictory assertions
- **UNSTABLE** (Red) - System state uncertain

### Metrics

**Valid Assertions %**
- 100% - All assertions valid
- 70-99% - Some decay/expiration
- 50-69% - Significant degradation
- <50% - Critical state

**Regime Entropy**
- 0.0-0.3 - Low uncertainty (stable)
- 0.3-0.5 - Moderate uncertainty
- 0.5-0.7 - High uncertainty (caution)
- >0.7 - Extreme uncertainty (blindness)

**Active Conflicts**
- 0 - No conflicts
- 1-2 - Minor disagreements
- 3-5 - Significant conflicts
- >5 - Critical conflict state

**Blind Spots**
- Lists domains without valid assertions
- Core domains: Market, Execution, Treasury
- Non-core: Onchain, Governance, Simulation, Agent, System

---

## Self-Deception Metrics

The system monitors itself for lying. You should too.

### Confidence Inflation
**What it means:** System claiming higher confidence than historical accuracy supports.

**Warning threshold:** >0.3

**What to do:**
- Reduce trust in confidence scores
- Demand more evidence
- Review assertion sources

### Agreement Bias
**What it means:** Agents agreeing too easily (suspiciously low conflict rate).

**Warning threshold:** >0.2

**What to do:**
- Question consensus
- Look for dissenting views
- Increase skepticism

### Narrative Comfort
**What it means:** System avoiding uncertainty language (too comfortable).

**Warning threshold:** >0.8

**What to do:**
- Assume higher uncertainty
- Reduce position sizes
- Increase monitoring

---

## Operator Mindset

### Trust Empty Screens

**Old mindset:** "The UI is broken, I need to see something."

**New mindset:** "The UI is honest, absence of data is information."

Empty screens mean:
- System lacks valid assertions
- Data sources unavailable
- Truth insufficient for display

**This is success, not failure.**

### Respect Missing Data

**Old mindset:** "I'll estimate the missing values."

**New mindset:** "Missing data means I cannot make this decision."

Do NOT:
- Fill gaps with assumptions
- Use stale data
- Extrapolate from partial information
- Rely on intuition when data missing

### Pause When Panels Disappear

**Old mindset:** "Something's wrong, I need to act."

**New mindset:** "The system is protecting me, I should wait."

When panels disappear:
- System detected invalid assertions
- Data quality insufficient
- Truth requirements not met

**Wait for recovery, don't override.**

### Fear Confidence, Not Uncertainty

**Old mindset:** "High confidence = good, uncertainty = bad."

**New mindset:** "Overconfidence kills capital, uncertainty is honest."

High confidence can mean:
- Genuine strong signal (rare)
- Self-deception (common)
- Insufficient skepticism (dangerous)

Low confidence means:
- System is honest
- Uncertainty acknowledged
- Risk properly assessed

---

## Common Mistakes

### Mistake 1: Forcing Exit from Blindness Mode

**Why it's wrong:** Blindness Mode protects you from making decisions without valid data.

**Consequence:** Trading with no truth backing, high risk of losses.

**Correct action:** Wait for system recovery, review what caused blindness.

### Mistake 2: Ignoring Warnings

**Why it's wrong:** Warnings indicate degrading data quality or increasing uncertainty.

**Consequence:** Decisions based on unreliable information.

**Correct action:** Reduce risk, increase monitoring, wait for improvement.

### Mistake 3: Averaging Conflicting Signals

**Why it's wrong:** Conflicts indicate genuine disagreement, averaging hides this.

**Consequence:** False confidence in uncertain situations.

**Correct action:** Acknowledge conflict, reduce exposure, wait for resolution.

### Mistake 4: Trusting Stale Data

**Why it's wrong:** Assertions decay over time, old data is unreliable.

**Consequence:** Decisions based on outdated information.

**Correct action:** Check assertion timestamps, wait for fresh data.

### Mistake 5: Overriding Safety Checks

**Why it's wrong:** Safety checks enforce truth discipline.

**Consequence:** System cannot protect you from bad decisions.

**Correct action:** Respect safety checks, understand why they triggered.

---

## Emergency Procedures

### Procedure 1: System Enters Blindness During Trade

1. **STOP** - Do not place new trades
2. **ASSESS** - Check Reality Status Panel for reason
3. **PROTECT** - Monitor existing positions, set stops if needed
4. **WAIT** - Allow system to recover
5. **REVIEW** - Understand what caused blindness

**DO NOT:**
- Force exit blindness mode
- Continue trading manually
- Close all positions in panic

### Procedure 2: High Conflict Rate

1. **REDUCE** - Cut position sizes by 50%
2. **MONITOR** - Watch for conflict resolution
3. **DIVERSIFY** - Spread risk across uncorrelated assets
4. **WAIT** - Let system resolve conflicts
5. **REVIEW** - Understand source of conflicts

**DO NOT:**
- Pick one side and ignore the other
- Average conflicting signals
- Increase risk

### Procedure 3: Rapid Degradation

1. **ALERT** - System moving from OPERATIONAL to DEGRADED quickly
2. **PAUSE** - Stop new trades immediately
3. **REVIEW** - Check which assertions are expiring
4. **PROTECT** - Tighten stops on existing positions
5. **WAIT** - Allow assertion refresh

**DO NOT:**
- Ignore the degradation
- Continue normal operations
- Assume it will recover quickly

---

## Success Metrics

You are operating correctly when:

- ✅ You trust empty screens
- ✅ You wait for system recovery
- ✅ You reduce risk during degradation
- ✅ You stop trading in blindness mode
- ✅ You respect conflicts
- ✅ You monitor self-deception metrics
- ✅ You fear overconfidence
- ✅ You accept uncertainty

You are operating incorrectly when:

- ❌ You try to "fix" the UI
- ❌ You force exit blindness mode
- ❌ You ignore warnings
- ❌ You average conflicting signals
- ❌ You trust stale data
- ❌ You override safety checks
- ❌ You panic during failures
- ❌ You seek false confidence

---

## Advanced Topics

### Understanding Assertion Decay

Assertions lose validity over time through exponential decay:

```
effective_confidence = raw × provenance × e^(-λt) × (1 - entropy)
```

**What this means:**
- Even valid assertions become unreliable
- Decay rate varies by data type
- Price data decays quickly (λ=0.1)
- Regime data decays slowly (λ=0.05)

**Operator impact:**
- Fresh data is always better
- Old assertions trigger warnings
- System automatically invalidates expired assertions

### Provenance Scores

Not all data sources are equal:

- **0.95** - Highly reliable (Kraken exchange)
- **0.90** - Reliable (Binance exchange)
- **0.80** - Moderate (Social sentiment)
- **0.70** - Low (Unverified sources)

**Operator impact:**
- High provenance = more trust
- Low provenance = more skepticism
- System weights by provenance automatically

### Regime Compatibility

How well assertions fit current market state:

- **1.0** - Perfect fit
- **0.8** - Good fit
- **0.6** - Moderate fit
- **<0.5** - Poor fit

**Operator impact:**
- Low compatibility triggers warnings
- System adjusts confidence automatically
- Mismatched regimes reduce reliability

---

## Certification

To be certified as a MERID operator, you must:

1. ✅ Complete all training drills correctly
2. ✅ Demonstrate trust in empty screens
3. ✅ Show proper response to blindness mode
4. ✅ Understand self-deception metrics
5. ✅ Respect conflict preservation
6. ✅ Accept uncertainty as information

**Certification Question:**

*"The system enters Blindness Mode during an active trade with 50% profit. What do you do?"*

**Correct Answer:**
- Stop new trades
- Monitor existing position
- Set protective stop if needed
- Wait for system recovery
- Do NOT force exit blindness mode
- Do NOT close position in panic

**Incorrect Answer:**
- Force exit blindness mode to continue trading
- Close position immediately
- Try to "fix" the system
- Ignore the blindness warning

---

## Final Truth

> **A system that feels confident while uncertain is dangerous.**
>
> **A system that feels uncomfortable while honest is alive.**

MERID's Reality Enforcement System will:
- Make you uncomfortable
- Show you less information
- Block actions you want to take
- Force you to wait
- Expose uncertainty

**This is not a bug. This is the design.**

Your job as an operator is to:
- Trust the system's restraint
- Respect its limitations
- Accept its honesty
- Work within its boundaries

**If MERID appears quiet, slow, or restrictive — it is working correctly.**

---

## Support

If you have questions:
1. Review this training guide
2. Check Reality Status Panel
3. Read failure messages carefully
4. Wait for system recovery
5. Contact support only if system behavior is unexpected

**Remember:** Most "problems" are actually the system protecting you.

---

🔒 **END OF OPERATOR TRAINING GUIDE** 🔒
