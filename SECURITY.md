# Security Policy

MERID is a live-trading system that executes real-money orders on Kalshi.
Security issues — especially anything that could affect credential handling,
order integrity, reconciliation, or the live-entry authorization path — are
treated as top priority.

## Reporting a Vulnerability

**Do not open a public issue for security reports.**

Report vulnerabilities privately via GitHub's
[private vulnerability reporting](../../security/advisories/new) on this
repository, or contact the repository owner directly.

Please include:

- A description of the issue and its potential impact
- Affected component/path (e.g. `merid/event_venues/kalshi/`, `start_15m.ps1`)
- Steps to reproduce or a proof of concept, if available
- Whether the issue could affect live order submission, credential
  confidentiality, or reconciliation integrity

## Scope

Highest-severity areas:

- **Credential & secret handling** — Kalshi API keys, RSA private keys,
  `.env` handling, `core/secrets_guard.py`
- **Live-entry authorization** — `AGENTS.md` contract, `start_15m.ps1`
  latches, startup preflight, `MERID_OBSERVE_ONLY` handling
- **Order integrity** — `merid/event_venues/kalshi/` order router/gate,
  `client_order_id` idempotency, submission-unknown recovery
- **Reconciliation & fill trust** — fills ledger, trusted fill watermark,
  position reconciliation
- **Exit protections** — reduce-only exits, circuit breaker, kill switches
  (`merid/risk/`, `trading/guards/`)

## Operational rules

- Never commit secrets. `.env`, `*.pem`, and credential files are gitignored;
  verified templates (`.env.example`, `.env.*.example`) must contain
  placeholders only.
- If you believe a secret has been committed, report it immediately and
  rotate the affected credential — do not assume history is unobserved.
- Production deployments must keep the safety controls described in
  `AGENTS.md` enabled; disabling them is not a supported configuration.

## Supported Versions

Security fixes apply to the current `main` branch only. The
`archive/main-pre-15m` branch and legacy entrypoints are unmaintained.
