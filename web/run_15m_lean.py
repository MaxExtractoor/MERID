from __future__ import annotations

print("=== [RUN-15M-LEAN] FILE EXECUTING - TOP OF run_15m_lean.py ===", flush=True)

"""
DEPRECATED: This script is no longer used for production startup.
Use start_15m.ps1 instead, which calls uvicorn directly without event loop policy overrides.
The WindowsSelectorEventLoopPolicy override was preventing FastAPI lifespan from being called.
"""

import sys
from pathlib import Path

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

print("=== [RUN-15M-LEAN] DEPRECATED - Use start_15m.ps1 instead ===", flush=True)
print("=== [RUN-15M-LEAN] This script overrides event loop policy and breaks FastAPI lifespan ===", flush=True)
sys.exit(1)
