@echo off
set MERID_PROFILE=kalshi_crypto_15m_v2
set MERID_EXECUTION_MODE=normal
.venv\Scripts\uvicorn.exe web.main_15m_lean:app --host 0.0.0.0 --port 8011
