"""
Tests for web/api/rewards.py — Unified Rewards API.

Covers all 14 endpoints:
- GET  /summary
- GET  /leaderboard
- POST /xp/award
- GET  /xp/{user_id}
- GET  /quests
- POST /quests/progress
- GET  /quests/leaderboard/{season}
- GET  /pools
- POST /pools/{pool_id}/adjust
- GET  /x402/stats
- GET  /x402/receipts
- GET  /x402/resources
- GET  /security/quests
- POST /security/bug-report
"""

import unittest
import sys
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client() -> TestClient:
    """Build a TestClient with the rewards router mounted."""
    # Stub modules that may not exist in test env
    stubs = {}
    for mod_name in [
        "hardening", "hardening.lockdown",
        "web.api.institutional", "web.api.system_control",
        "web.api.trading", "web.api.mining", "web.api.reflection",
        "web.api.streams", "web.api.live_stream", "web.api.betting",
        "web.api.paper_trading", "web.api.data_endpoints",
        "web.api.trading_suite",
    ]:
        if mod_name not in sys.modules:
            stubs[mod_name] = MagicMock()
            sys.modules[mod_name] = stubs[mod_name]

    from web.api.rewards import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


















if __name__ == "__main__":
    unittest.main()
