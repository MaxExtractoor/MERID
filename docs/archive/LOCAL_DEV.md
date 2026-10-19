# MERID — Local Development Guide

## Quick Start

```bash
# Backend
pip install -r requirements.txt
make serve                          # http://127.0.0.1:8000

# Frontend (separate terminal)
cd web/react
npm install
npm run dev                         # http://localhost:5173
```

No Docker, Redis, Neo4j, or external services required. MERID uses SQLite for storage and runs entirely locally.

---

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| MERID API | [http://localhost:8000](http://localhost:8000) | FastAPI backend |
| React Dashboard | [http://localhost:5173](http://localhost:5173) | Operator UI (Vite dev server) |
| Swagger Docs | [http://localhost:8000/docs](http://localhost:8000/docs) | Interactive API explorer |

---

## Environment

Create `.env` (optional — paper mode works without any credentials):

```bash
KALSHI_API_KEY_ID=your_key_id
KALSHI_PRIVATE_KEY_PATH=path/to/private_key.pem
KALSHI_USE_DEMO=true
MERID_PM_TRADING_MODE=paper
```

See [ENV_SETUP.md](../ENV_SETUP.md) for the full variable reference.

---

## Running Tests

```bash
make golden-path                    # full test suite
make preflight                      # tests + readiness + drift audit + risk context
pytest tests/ -v --tb=short         # unit tests directly
```

---

## MeridLoop

```bash
make loop-start                     # observe mode (no execution)
make loop-start-execute             # paper execution enabled
```

---

## Frontend Development

The React dashboard lives in `web/react/` and uses:

- **React 18** + TypeScript
- **TailwindCSS** for styling
- **Vite** for dev server and builds
- **Lucide** for icons

```bash
cd web/react
npm run dev                         # dev server with HMR
npm run build                       # production build → dist/
npm run lint                        # ESLint check
```

### UI Architecture

- **14 frozen views** in `src/views/`
- **46 shared components** in `src/components/`
- **12 hooks** in `src/hooks/`
- **API constants** in `src/config/constants.ts`
- **View type union** in `src/types/views.ts` (single source of truth)

See [docs/ui/kalshi_workflow.md](ui/kalshi_workflow.md) for the canonical view list.

---

## Data Reset

To reset all paper trading state:

```bash
MERID_FRESH_START=1 make serve
```

This clears paper positions, signals, consensus, and drift state. Kill switch state is preserved. Only works in paper mode.

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Port 8000 in use | Kill existing process or set `--port 8001` |
| Port 5173 in use | Vite will auto-increment to 5174 |
| `ModuleNotFoundError` | Activate venv and `pip install -r requirements.txt` |
| React build fails | `npm install` in `web/react/` |
| Stale data | Use `MERID_FRESH_START=1` to reset |
