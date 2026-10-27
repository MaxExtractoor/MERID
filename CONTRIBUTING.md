# Contributing to MERID

Guidelines for contributing to MERID, a production trading system for
**Kalshi 15-minute crypto markets** (BTC, ETH, SOL, XRP, DOGE).

---

## Setup

```powershell
git clone https://github.com/MaxExtractoor/MERID.git
cd MERID
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
```

See [QUICKSTART.md](QUICKSTART.md) for a safe first run and
[ENV_SETUP.md](ENV_SETUP.md) for environment configuration.

---

## Workflow

1. **Branch** — `git checkout -b feature/your-feature`
2. **Code** — Follow existing style, add tests
3. **Test** — `make preflight`
4. **Commit** — `git commit -m "feat: description"`
5. **Push** — `git push origin feature/your-feature`
6. **PR** — Describe changes, link issues

---

## Architecture Rules

The dashboard runs **8 routed views** plus 2 legacy deep-link views. The
canonical mapping is `VIEW_COMPONENTS` in `web/react/src/App.tsx`; the type
union lives in `web/react/src/types/views.ts`.

| Section | Views |
|---------|-------|
| Trading | dashboard, trade, grid |
| Analytics | risk, calibration |
| Operator | monitor |
| System | logs, settings |
| Legacy deep links | kalshi-dashboard, kalshi-portfolio |

- A new view requires updating **all four**: `types/views.ts` (union),
  `App.tsx` (`VIEW_COMPONENTS`), `Sidebar.tsx` (nav), `CommandPalette.tsx`
- Do not reintroduce legacy stub views — dead views belong in git history,
  not the filesystem
- Legacy view keys in `types/views.ts` exist only for deep-link backward
  compatibility; do not add entries to `LegacyView`
- Shared components live in `web/react/src/components/`; view-specific
  sub-components may live in `views/`
- The 15m stack (`web/main_15m_lean.py`, `merid/loop_15m.py`,
  `merid/event_venues/kalshi/`) is the only supported execution path.
  Legacy boundaries are defined in [ARCHITECTURE_15M.md](ARCHITECTURE_15M.md)
  and enforced by `tests/test_15m_architectural_separation.py`

---

## Code Style

**Python:**

- PEP 8, type hints, docstrings for public functions
- Lines under 100 characters
- Use `utils.logger.get_logger()` for logging (f-string format)
- No `# type: ignore` without a justifying comment
- No bare `except: pass` — log with `logger.debug`
- `Decimal` for all price/fee/PnL arithmetic; exact integer centi-contracts

**TypeScript/React:**

- Follow existing patterns in `web/react/src/`
- Use TailwindCSS for styling
- Hooks go in `hooks/`, shared UI in `components/`
- API constants in `config/constants.ts`
- No new `any` types or `@ts-ignore` without a justifying comment

---

## Testing

```powershell
make test                    # unit/regression suite
make golden-path             # full test suite
make preflight               # tests + readiness + drift audit + risk context
make risk-context            # print live risk state
python -m pytest tests/test_15m_architectural_separation.py -v  # boundary firewall
```

CI gates on `main` include `kalshi-15m-ci`, `merid-safety-ci`,
`kill-switch-ci`, `paper-gate`, `production-data-guards`,
`reconciliation-safety`, `red-team-invariants`, and `rti-settlement-safety`.

---

## Pre-Merge Checklist

- [ ] `make preflight` passes
- [ ] No broken imports (`python -m py_compile <file>`)
- [ ] No new views outside the routed set in `App.tsx`
- [ ] Documentation updated if behavior changed
- [ ] No `_legacy/` code reintroduced
- [ ] No changes to live-entry gates, reconciliation, or exit protections
      without explicit review (see `.github/CODEOWNERS` and
      [AGENTS.md](AGENTS.md))

---

## Conflict Resolution

1. Resolve one file at a time
2. Validate: `python -m py_compile path/to/file.py`
3. Stage: `git add path/to/file.py`
4. Verify: `make golden-path`
5. Commit the merge

---

## Resources

- [README.md](README.md) — project overview
- [QUICKSTART.md](QUICKSTART.md) — safe startup modes
- [AGENTS.md](AGENTS.md) — live-trading operational contract
- [docs/UI/kalshi_workflow.md](docs/UI/kalshi_workflow.md) — operator workflow and UI map
- [ENV_SETUP.md](ENV_SETUP.md) — environment variables
- [BUILD.md](BUILD.md) — build and dev setup
- API docs: [http://localhost:8011/docs](http://localhost:8011/docs)
