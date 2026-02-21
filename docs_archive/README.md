# docs_archive/

**Archived documentation from prior MERID architecture phases.**

These files were moved here on 2026-02-21 during the UI/UX audit cleanup.
They reference the old multi-venue crypto exchange architecture, legacy views,
and pre-Kalshi workflows that no longer apply.

## What's here

- Root-level stale docs (35 files) — sprint summaries, integration reports, audit reports
- `docs/` overflow (154 files) — old architecture specs, swarm plans, deployment guides
- `web/` docs (6 files) — old CSS/theme/mobile guides
- `web/react/` docs (12 files) — old deployment, JWT, socket, Netlify guides
- `.windsurf/` phase summaries (13 files) — old phase completion summaries
- `legacy_test_docs/` (12 files) — stale UI layout, system architecture, coverage reports, doc index

## Canonical documentation

The active documentation lives in:

```text
README.md                          — Project overview
ENV_SETUP.md                       — Environment setup
QUICKSTART.md                      — Quick start guide
BUILD.md                           — Build instructions
CHANGELOG.md                       — Change log
CONTRIBUTING.md                    — Contribution guide
docs/ui/kalshi_workflow.md         — Canonical Kalshi swarm operator workflow (14 views, 8 steps)
docs/GETTING_STARTED.md            — Onboarding
docs/LOCAL_DEV.md                  — Local development
docs/TESTING_GUIDE.md              — Testing
docs/API_REFERENCE.md              — API reference
docs/ERROR_CODE_REFERENCE.md       — Error codes
docs/WEBSOCKET_MESSAGE_FORMATS.md  — WebSocket message formats
docs/KALSHI_UI_CHANGELOG.md        — Kalshi UI change log
```

## Do not re-import

These archived docs should NOT be moved back into the active tree.
If you need to reference old architecture decisions, read them here but
do not let them drift the current frozen 14-view Kalshi-only layout.
