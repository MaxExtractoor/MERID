# Momentum Scalping + Hedging State Machine
## System States and Transitions

```
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                              MARKET REGIME GATE                                         │
│  ┌─────────────────────────────────────────────────────────────────────────────────┐  │
│  │  Evaluates: Return%, ATR%, Vol Ratio, ADX across BTC, ETH, SOL, XRP, DOGE     │  │
│  │  Output: ALLOW → Normal operation                                               │  │
│  │          REDUCE → Size reduced 50%                                              │  │
│  │          BLOCK  → No new entries (all states)                                   │  │
│  └─────────────────────────────────────────────────────────────────────────────────┘  │
│                                          │                                              │
│                                          ▼                                              │
│                               ┌─────────────────┐                                       │
│                               │   REGIME = BLOCK│                                       │
│                               │   (Flat/Chop)   │                                       │
│                               └────────┬────────┘                                       │
│                                        │                                                │
│                                        │ Stay in current state,                        │
│                                        │ no new entries allowed                        │
│                                        ▼                                                │
└─────────────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          │ REGIME = ALLOW
                                          ▼
┌─────────────────────────────────────────────────────────────────────────────────────────┐
│                                     STATE MACHINE                                       │
│                                                                                         │
│  ┌─────────────┐                                                                         │
│  │   STATE D   │                                                                        │
│  │    FLAT     │◀─────────────────────────────────────────────────────────────────┐    │
│  │  No Positions│                                                                    │    │
│  │             │                                                                     │    │
│  │  Net β: 0.0 │                                                                     │    │
│  │  Entries: ✗ │                                                                     │    │
│  │  Hedges: ✗ │                                                                     │    │
│  └──────┬──────┘                                                                     │    │
│         │                                                                            │    │
│         │ Re-entry: Trend established + Low vol + 15m hysteresis                   │    │
│         │ (from State C: DD < 2% + Stabilization)                                   │    │
│         ▼                                                                            │    │
│  ┌─────────────┐     Drawdown ≥ 5%      ┌─────────────┐     Drawdown ≥ 10%           │    │
│  │   STATE A   │────────────────────────▶│   STATE B   │────────────────────────┐   │    │
│  │  SCALP-ONLY │◀────────────────────────│ SCALP+HEDGE │                        │   │    │
│  │             │   Recovery: DD < 3%    │  (Protected)  │◀───────────────────────┼───┘    │
│  │  Normal     │   + Vol normalized     │               │   Recovery: DD < 5%   │        │
│  │  Operation  │   + 15m hysteresis    │               │   + Stabilization     │        │
│  │             │                        │               │                        │        │
│  │  Net β: 0.8-1.2 per asset            │  Net β: 0.3-0.6 per asset              │        │
│  │  Entries: ✓ Full size                │  Entries: ✓ Reduced size (60%)        │        │
│  │  Hedges: None                        │  Hedges: Active 50% of exposure        │        │
│  │             │                        │               │                        │        │
│  │ Triggers to B:                       │ Triggers to A:│                        │        │
│  │ • DD ≥ 5%                            │ • DD < 3%     │                        │        │
│  │ • Cycle RESTRICTED                   │ • Vol norm    │                        │        │
│  │ • Vol spike > 2σ                     │ • 15m in B    │                        │        │
│  │ • Correlation break                  │               │                        │        │
│  │ • Manual hedge signal                │ Triggers to C:│                        │        │
│  │                                      │ • DD ≥ 10%    │                        │        │
│  │                                      │ • 3+ losses   │                        │        │
│  │                                      │ • Liquidity ↓ │                        │        │
│  │                                      │ • Manual halt │                        │        │
│  └─────────────┘                        └───────┬───────┘                        │        │
│                                                 │                                │        │
│                                                 │ Drawdown ≥ 10%                 │        │
│                                                 ▼                                │        │
│                                        ┌─────────────────┐                       │        │
│                                        │    STATE C      │                       │        │
│                                        │   HEDGE-ONLY    │───────────────────────┘        │
│                                        │                 │  Recovery: DD < 5% + 30min   │
│                                        │  Risk-Off Mode  │──────────────────────────────▶│
│                                        │                 │  Or: All flat → State D      │
│                                        │  Net β: 0.0-0.2 │                               │
│                                        │  Entries: ✗     │                               │
│                                        │  Hedges: 100%   │                               │
│                                        │                 │                               │
│                                        │  • Maintain hedges                               │
│                                        │  • Reduce exposure                               │
│                                        │  • Preserve capital                              │
│                                        └─────────────────┘                               │
│                                                                                         │
└─────────────────────────────────────────────────────────────────────────────────────────┘

Hysteresis & Cooldown Rules:
─────────────────────────────────────────────────────────────────────────────────────────
• Minimum 15 minutes in any state before transition to less restrictive state
• State transitions logged with reason code for audit trail
• Manual override can force any state (admin only, logged)
• Emergency kill switch bypasses state machine → immediate State D (FLAT)

State Transition Matrix:
─────────────────────────────────────────────────────────────────────────────────────────
From \ To │   A (SCALP)   │  B (HEDGE)   │  C (RISK-OFF) │   D (FLAT)
──────────┼───────────────┼──────────────┼───────────────┼────────────
A         │      —        │   DD ≥ 5%    │   DD ≥ 10%    │ Manual kill
B         │  DD < 3%+time │      —       │   DD ≥ 10%    │ Manual kill
C         │      ✗        │ DD < 5%+time │       —       │ All closed
D         │ Trend+vol+time│      ✗       │      ✗        │     —

Legend:
───────
DD      = Drawdown from daily/session peak
Vol     = Realized volatility (BTC 15m annualized)
Time    = Minimum hysteresis time (15 minutes)
β       = Net beta (directional exposure to underlying)
Entries = New scalping entries allowed
Hedges  = Active hedging orders
