#!/usr/bin/env python
"""
Wrapper script to run uvicorn with correct sys.path
CRITICAL FIX: Use web.main_15m_lean (production) not web.main (legacy)
"""
import sys
import os

# Add current directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import uvicorn and run
import uvicorn
from web.main_15m_lean import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8011, log_level="info", reload=False)
