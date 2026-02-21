# Contributing to MERID

Guidelines for contributing to the MERID Kalshi swarm intelligence platform.

---

## Setup

```bash
git clone <repository-url>
cd MERID
python -m venv venv
venv\Scripts\activate           # Windows
pip install -r requirements.txt
```

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

The UI is frozen at **17 views** grouped into 5 sidebar sections. See [docs/ui/kalshi_workflow.md](docs/ui/kalshi_workflow.md) for the canonical layout.

- Do not add new views without updating the frozen view list
- Do not reintroduce legacy views or components from `_legacy/` directories
- All new Kalshi features must wire through existing views
- Shared components live in `web/react/src/components/`

---

## Code Style

**Python:**

- PEP 8, type hints, docstrings for public functions
- Lines under 100 characters
- Use `utils.logger.get_logger()` for logging (f-string format)
- No `# type: ignore` without a justifying comment
- No bare `except: pass` — log with `logger.debug`

**TypeScript/React:**

- Follow existing patterns in `web/react/src/`
- Use TailwindCSS for styling
- Hooks go in `hooks/`, shared UI in `components/`
- API constants in `config/constants.ts`

---

## Testing

```bash
make golden-path              # full test suite
make preflight                # tests + readiness + drift audit + risk context
make risk-context             # print live risk state
```

---

## Pre-Merge Checklist

- [ ] `make preflight` passes
- [ ] No broken imports (`python -m py_compile <file>`)
- [ ] No new views outside the frozen 17-view layout
- [ ] Documentation updated if behavior changed
- [ ] No `_legacy/` code reintroduced

---

## Conflict Resolution

1. Resolve one file at a time
2. Validate: `python -m py_compile path/to/file.py`
3. Stage: `git add path/to/file.py`
4. Verify: `make golden-path`
5. Commit the merge

---

## Resources

- [README.md](README.md) — Project overview
- [docs/ui/kalshi_workflow.md](docs/ui/kalshi_workflow.md) — Operator workflow and UI map
- [ENV_SETUP.md](ENV_SETUP.md) — Environment variables
- [BUILD.md](BUILD.md) — Build and dev setup
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
