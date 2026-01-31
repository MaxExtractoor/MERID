# MERID Environment Configuration Strategy
# 
# SINGLE SOURCE OF TRUTH: .env
# All other .env* files are for reference/backups only

## Files to Keep:
- ✅ .env - ACTIVE local development configuration
- ✅ .env.example - Template for new developers (read-only)

## Files to Archive/Remove:
- ❌ .env.backup - Backup file (archive to .env.backup.old)
- ❌ .env.backup2 - Another backup (archive to .env.backup2.old)  
- ❌ .env.fixed - Fixed version (merge into .env if needed)
- ❌ .env.template - Template (replace with .env.example)

## Loading Strategy:
1. VS Code: Set python.envFile to ".env" in workspace settings
2. Uvicorn: Use --env-file .env explicitly
3. Code: Single load_dotenv(".env") call in web.main.py
4. Environment: MERID_ENV_FILE should point to .env

## Validation:
- python -c "import os; print('MERID_ENV_FILE:', os.getenv('MERID_ENV_FILE'))"
- python -c "import os; print('MERID_DEV_ALLOW_WS:', os.getenv('MERID_DEV_ALLOW_WS'))"
