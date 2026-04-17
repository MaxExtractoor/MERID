# Portfolio Risk Audit Checklist — Contractor Brief

## 1. Bankroll-Driven Startup Self-Check

Required behavior on service startup, given env:

```bash
export KALSHI_PORTFOLIO_BANKROLL_CENTS=1000000   # $10,000
export KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT=0.50    # 50%
export KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT=0.10  # 10%
export KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT=0.16   # 16%
```

### Expected logs

Contractor must ensure logs include raw env, derived cents, and human-readable dollars/percentages:

```text
============================================================
PORTFOLIO RISK AGENT STARTUP - CONFIG SELF-CHECK
  Raw env: KALSHI_PORTFOLIO_BANKROLL_CENTS=1000000 ($10000.00)
  Raw env: KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT=0.5 (50%)
  Raw env: KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT=0.1 (10%)
  Raw env: KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT=0.16 (16%)
  Derived: max_notional_cents=500000 (bankroll × 50%)
  Derived: max_daily_loss_cents=100000 (bankroll × 10%)
  Derived: max_per_asset_cents=160000 (bankroll × 16%)
  Actual config: max_notional=$5000.00 ✓
  Actual config: max_daily_loss=$1000.00 ✓
  Actual config: max_per_asset=$1600.00 ✓
  Check interval: 30s
============================================================
```

### Verification checklist

Contractor must confirm:

- [ ] `max_notional_cents == bankroll_cents * KALSHI_PORTFOLIO_MAX_NOTIONAL_PCT` 
- [ ] `max_daily_loss_cents == bankroll_cents * KALSHI_PORTFOLIO_MAX_DAILY_LOSS_PCT` 
- [ ] `max_per_asset_cents == bankroll_cents * KALSHI_PORTFOLIO_MAX_PER_ASSET_PCT` 
- [ ] `PortfolioRiskManager.max_absolute_risk == 2 * max_notional` (no separate env or magic constant)

External portfolio risk guides emphasize explicit risk limits at portfolio and position level; this design aligns with best practice by binding limits to total account capital rather than static amounts. [waterloocap](https://waterloocap.com/risk-management-for-portfolios/)

***

## 2. Toy Bankroll Flip Test

Env change:

```bash
export KALSHI_PORTFOLIO_BANKROLL_CENTS=500000   # $5,000
```

### Backend

- [ ] Restart portfolio risk service with only bankroll changed.
- [ ] Startup logs now show:
  - `bankroll_cents=500000 ($5000.00)` 
  - `max_notional=$2500.00` (50%)
  - `max_daily_loss=$500.00` (10%)
  - `max_per_asset=$800.00` (16%)
- [ ] `grep -r "25000\|2000" merid/prediction/*.py` returns no hits for those literals as defaults or magic values.

### UI

- [ ] ExecutionGateStrip exposure % uses the updated bankroll-driven `max_notional`.
- [ ] `/api/v1/kalshi/portfolio-risk/summary` includes:
  - `bankroll_cents` 
  - `max_notional_cents`, `max_daily_loss_cents`, `max_per_asset_cents` 
  - corresponding percentages that match env (50, 10, 16).
- [ ] Any UI risk widgets show these same percentages, not hardcoded numbers.

This mirrors industry guidance to express risk controls as percentages of capital and to monitor them continuously. [guardfolio](https://www.guardfolio.ai/blog/portfolio-risk-management-complete-guide)

***

## 3. Regression Test Contract

Contractor must run:

```bash
python -m pytest tests/test_portfolio_risk_hardened.py::TestPortfolioRiskConfigBankrollDriven -v
```

### Expected passing tests

- [ ] `test_config_derives_from_settings_bankroll` 
  - Settings properties compute bankroll-driven values from env.
- [ ] `test_portfolio_risk_config_post_init_derives_correctly` 
  - Zero defaults trigger derivation from settings in `__post_init__`.
- [ ] `test_explicit_yaml_values_override_settings` 
  - Explicit YAML values remain respected when provided.
- [ ] `test_no_hardcoded_25k_or_2k_defaults` 
  - No reintroduction of old hardcoded `$25k/$2k` defaults.
- [ ] `test_summary_includes_bankroll_and_percentages` 
  - API summary exposes bankroll and percentage limits for UI.

If any test is modified, contractor must add/adjust assertions to maintain the same invariants.

***

## 4. Breach Messaging Requirements

When limits are exceeded, logs must include both absolute and percentage-of-bankroll context, similar to:

```text
WARNING: Total notional $26000.00 (52.0% of bankroll) > limit $25000.00 (50% of bankroll)
```

Not acceptable:

```text
WARNING: Total notional $26000 > limit $25000
```

Because it hides how big the breach is relative to bankroll, it conflicts with standard practice of monitoring limits as percentages of capital and drawdown thresholds. [guardfolio](https://www.guardfolio.ai/blog/risk-management)

Contractor must ensure:

- [ ] All breach warnings include:
  - Dollar current value and limit.
  - Percent of bankroll for current and limit.
- [ ] Same pattern used for:
  - Total notional.
  - Daily loss.
  - Per-asset exposure.

***

## 5. Files and Allowed Changes

Contractor may only modify the following (or adjacent) files for this work and must keep the described behaviors:

| File | Required behavior |
|------|-------------------|
| `merid/settings.py` | Defines `KALSHI_PORTFOLIO_*` env vars; exposes computed bankroll-driven properties; zero/None handled cleanly. |
| `merid/prediction/agent_grid_config.py` | `PortfolioRiskConfig.__post_init__` derives from `settings` when values are `Decimal("0")` or missing; no static monetary defaults. |
| `merid/prediction/portfolio_risk_agent.py` | On startup, emits self-check block with raw env, derived cents, actual dollar values, and ✓ markers; schedules periodic checks using these limits. |
| `merid/prediction/portfolio_risk_manager.py` | Derives `max_absolute_risk` as `2 * max_notional`; uses bankroll-driven limits for all internal checks. |
| `tests/test_portfolio_risk_hardened.py` | Codifies all bankroll-driven invariants and anti-drift tests; must pass before sign-off. |

Any additional file changes must be explicitly called out in the PR description and justified as necessary for this risk behavior.

***

## 6. Anti-Drift Rules

**Never:**

- Hardcode `$25,000` or `$2,000` (or corresponding cents) as defaults in `agent_grid_config.py` or related config.
- Use `Decimal("25000")` or `Decimal("2000")` as default values in `PortfolioRiskConfig`.
- Remove or bypass `__post_init__` derivation logic that ties config back to `settings`.
- Comment out, silence, or significantly weaken the startup self-check logging.

**Always:**

- Use `Decimal("0")` (or equivalent) as defaults that indicate "derive from settings."
- Log both raw env and derived values on startup in a clearly delimited block.
- Include bankroll percentages in all breach messages.
- Run the hardened regression tests before merging or deploying any portfolio risk changes.

These rules align with standard portfolio risk frameworks that stress explicit limits, documented processes, and automated monitoring to prevent silent configuration drift. [waterloocap](https://waterloocap.com/risk-management-for-portfolios/)

***

## 7. Sign-Off Checklist (Contractor Must Confirm)

Before the contractor marks portfolio risk work complete and requests review:

- [ ] All 5 regression tests pass locally.
- [ ] Startup logs show the self-check block with the expected ✓ lines.
- [ ] Toy bankroll flip test shows all limits updating proportionally from env.
- [ ] UI risk views and API summary reflect consistent bankroll, percentages, and dollar limits.
- [ ] Breach messages tested (e.g., via unit test or forced condition) and include "% of bankroll" context.
- [ ] `grep -r "25000\|2000" merid/prediction/*.py` shows no remaining hardcoded `$25K/$2K` defaults.

You can optionally reference general portfolio risk literature in the PR rationale (e.g., "limits expressed as % of capital, monitored continuously, and backed by tests") to make the intent obvious to future readers. [guardfolio](https://www.guardfolio.ai/blog/portfolio-risk-management-complete-guide)
