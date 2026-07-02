#!/usr/bin/env python3
"""Dry-run launcher for Kelly fraction experiment."""

import os
import sys
from pathlib import Path

# Set required environment variables
os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
os.environ["MERID_EXECUTION_MODE"] = "dry_run"

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Import and run the main module
import web.main_15m_lean
