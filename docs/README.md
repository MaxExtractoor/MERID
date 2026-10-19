# MERID Documentation Index

MERID's canonical runtime is the Kalshi 15-minute crypto trading stack
(`web.main_15m_lean:app` on port 8011, launched by `start_15m.ps1`, profile
`kalshi_crypto_15m_v2`). Start here:

- **[GETTING_STARTED.md](GETTING_STARTED.md)** — setup, safe observation
  modes, and live-launch prerequisites.
- **[API_REFERENCE.md](API_REFERENCE.md)** — REST endpoint reference.
- **[pm-spot-operator.md](pm-spot-operator.md)** — PM/spot operator guide.
- **[trader_tracker_exposure_layers.md](trader_tracker_exposure_layers.md)** —
  exposure accounting layers.
- **[UI/](UI/)** — operator dashboard views and the Kalshi workflow.
- **[runbooks/](runbooks/)** — operational playbooks (circuit breaker,
  emergency lockdown, rollback, credential rotation, …).
- **[decisions/](decisions/)** — architecture decision records.
- **[incidents/](incidents/)** — post-incident reports.
- **[archive/](archive/)** — historical audits, research notes, and retired
  design documents. Kept for provenance; not part of the current operating
  manual.

Root-level operational docs: `README.md`, `QUICKSTART.md`, `RUNBOOK.md`,
`ENV_SETUP.md`, `LIVE_TRADING_STATUS.md`, `AGENTS.md` (the durable
live-execution contract), `CONTRIBUTING.md`.
