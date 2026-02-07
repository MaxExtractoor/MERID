# MERID Startup Guide

## Quick Start (Recommended)

### Windows
```powershell
.\start.ps1
```

This unified script starts both:
- **Backend API** (FastAPI) on port 8000
- **React Frontend** (Vite) on port 5173

Press `Ctrl+C` to stop all services.

---

## Port Configuration

All ports are now centralized in `.env`:

```env
MERID_BACKEND_PORT=8000      # Main FastAPI API
MERID_FRONTEND_PORT=5173     # React dashboard
MERID_USER_UI_PORT=3000      # Legacy User UI (start_merid.py)
MERID_AGENT_MESH_PORT=8080   # Agent communication
MERID_OPS_PORT=9090          # Ops/Admin interface
MERID_TELEMETRY_PORT=9091    # Metrics export
```

**Ports are now locked** - services will fail if port is occupied instead of incrementing.

---

## Manual Startup

### Backend Only
```powershell
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend Only
```powershell
cd web/react
npm run dev
```

### Legacy Multi-Service (4 services)
```powershell
python start_merid.py
```
Starts: User UI (3000), Agent Mesh (8080), Ops (9090), Telemetry (9091)

---

## Access Points

| Service | URL | Description |
|---------|-----|-------------|
| **React Dashboard** | http://localhost:5173 | Main UI (Trading, Agents, Risk, etc.) |
| **Backend API** | http://localhost:8000 | FastAPI REST API |
| **API Docs** | http://localhost:8000/docs | Interactive API documentation |
| **User UI** | http://localhost:3000/dashboard | Legacy dashboard |
| **Agent Mesh** | http://localhost:8080/health | Internal agent communication |
| **Ops/Admin** | http://localhost:9090/health | System controls |
| **Telemetry** | http://localhost:9091/metrics | Prometheus metrics |

---

## Troubleshooting

### Port Already in Use
If you see "Address already in use" errors:

1. **Find the process using the port:**
   ```powershell
   netstat -ano | findstr :8000
   ```

2. **Kill the process:**
   ```powershell
   taskkill /PID <process_id> /F
   ```

3. **Or change the port in `.env`:**
   ```env
   MERID_BACKEND_PORT=8001
   ```

### React Port Increments
If React starts on 5174 instead of 5173:
- Port 5173 is occupied
- Use `strictPort: true` in `vite.config.ts` to fail instead of incrementing
- Kill the process on 5173 or change `MERID_FRONTEND_PORT`

### Services Won't Start
1. Check `.env` file exists
2. Verify Python dependencies: `pip install -r requirements.txt`
3. Verify Node dependencies: `cd web/react && npm install`
4. Check logs for specific errors

---

## Development Workflow

### Full Stack Development
```powershell
# Terminal 1: Backend with hot reload
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend with hot reload
cd web/react
npm run dev
```

### Testing
```powershell
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/trading/test_paper_trading.py
```

### Code Quality
```powershell
# Linting
ruff check .

# Type checking
mypy .

# Format code
ruff format .
```

---

## Environment Setup

### First Time Setup
1. **Clone repository**
2. **Install Python dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```
3. **Install Node dependencies:**
   ```powershell
   cd web/react
   npm install
   ```
4. **Copy `.env.example` to `.env`** and configure API keys
5. **Run startup script:**
   ```powershell
   .\start.ps1
   ```

### API Keys Required
See `.env` for full list. Minimum required:
- `ALPACA_API_KEY` / `ALPACA_API_SECRET` (paper trading)
- `OPENAI_API_KEY` (AI features)
- `MONGODB_URI` (persistence)
- `REDIS_URL` (caching)

---

## Architecture

### Service Separation
- **Backend (8000)**: Main FastAPI app with all API endpoints
- **Frontend (5173)**: React SPA with Vite dev server
- **User UI (3000)**: Legacy Jinja2 templates (being phased out)
- **Agent Mesh (8080)**: Internal agent communication (localhost only)
- **Ops/Admin (9090)**: System controls (localhost only)
- **Telemetry (9091)**: Metrics export (localhost only)

### Data Flow
```
React (5173) → Backend API (8000) → Trading Adapters → Exchanges
                    ↓
              Agent Mesh (8080) → Agents → Strategies
                    ↓
              MongoDB/Redis → Persistence
```

---

## Production Deployment

### Build Frontend
```powershell
cd web/react
npm run build
```
Outputs to `web/react/dist/`

### Run Backend (Production)
```powershell
python -m uvicorn web.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Serve Frontend (Production)
Configure nginx or serve `web/react/dist/` with any static file server.

---

## Additional Resources

- **System Audit**: See `SYSTEM_AUDIT_2026-02-04.md` for comprehensive system overview
- **Coverage Report**: See `tests/MERID_COVERAGE_BACKLOG.md` for test coverage details
- **UI Build Plan**: See `web/UNIMPLEMENTED_TASKS_LIST.md` for UI development status
- **API Documentation**: http://localhost:8000/docs (when backend is running)

---

**Last Updated:** 2026-02-04  
**Maintainer:** MERID Development Team
