"""
Tests for web/api/quadratic_funding.py — Quadratic Funding API.

Covers all 10 endpoints:
- POST /proposals              (register)
- GET  /proposals              (list)
- GET  /proposals/{id}         (detail)
- GET  /proposals/{id}/support (support stats)
- POST /rounds                 (start)
- GET  /rounds                 (list)
- GET  /rounds/summary         (summaries)
- GET  /rounds/{id}            (detail)
- GET  /rounds/{id}/summary    (single summary)
- POST /contributions          (record)
- POST /rounds/finalize        (finalize)
- POST /rounds/note            (governance note)
"""

import unittest
import sys
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _build_client() -> TestClient:
    """Build a TestClient with the quadratic funding router."""
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

    from web.api.quadratic_funding import router
    import web.api.quadratic_funding as qf_module
    from governance.quadratic_funding import QuadraticFundingProgram

    app = FastAPI()
    app.include_router(router)

    # Reset program singleton to a fresh instance per test class
    qf_module._program = QuadraticFundingProgram()

    return TestClient(app)


# ── Helpers ──────────────────────────────────────────────────────

def _create_proposal(client: TestClient, **overrides) -> dict:
    defaults = {
        "title": "Test Proposal",
        "description": "A test proposal for unit testing",
        "requested_budget_usd": 1000.0,
        "target_swarm": "dev-swarm",
        "tags": ["test"],
        "owner": "test-owner",
    }
    defaults.update(overrides)
    return client.post("/api/v1/quadratic-funding/proposals", json=defaults).json()


def _create_round(client: TestClient, pool: float = 10000.0, proposal_ids=None) -> dict:
    payload = {"matching_pool_usd": pool}
    if proposal_ids is not None:
        payload["proposal_ids"] = proposal_ids
    return client.post("/api/v1/quadratic-funding/rounds", json=payload).json()


# ── Test Classes ─────────────────────────────────────────────────



















if __name__ == "__main__":
    unittest.main()
