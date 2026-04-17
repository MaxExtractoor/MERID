# MERID Memory Log

## 2026-03-07 — Loop + Web Health Hardening
- Restored the timeout-isolated `_run_step` implementation (deduped duplicate definition) and kept SLO metrics wired.
- Unified the MeridLoop singleton so `get_merid_loop()` always returns the running loop if it exists; background code still falls back to `LoopConfig.from_paper_config()` when the loop has never been started.
- Cleaned `web/main.py` imports (dropped unused `TrustedHostMiddleware`) and fixed health routing: `global_health_router` vs `health_api_router` no longer collide.
- `/health` now only reports "running" when the loop’s `_running` flag is true and surfaces `last_tick_at` / `last_error` metadata for operator visibility.
- Removed the unreachable Kalshi enhanced views (`KalshiDashboardViewEnhanced` + test, `KalshiAgentPerformanceViewWithDebates`) and documented that their functionality lives inside the canonical dashboard/performance views.
