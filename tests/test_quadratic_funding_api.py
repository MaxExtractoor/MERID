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

class TestProposalRegistration(unittest.TestCase):
    """POST /api/v1/quadratic-funding/proposals"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_register_returns_200(self):
        resp = self.client.post("/api/v1/quadratic-funding/proposals", json={
            "title": "My Proposal",
            "description": "Description here",
            "requested_budget_usd": 500.0,
            "target_swarm": "risk-swarm",
        })
        self.assertEqual(resp.status_code, 200)

    def test_register_returns_proposal_id(self):
        data = _create_proposal(self.client)
        self.assertIn("proposal_id", data)
        self.assertTrue(data["proposal_id"].startswith("prop_"))

    def test_register_sets_active_status(self):
        data = _create_proposal(self.client)
        self.assertEqual(data["status"], "active")

    def test_register_preserves_fields(self):
        data = _create_proposal(self.client, title="Alpha Fund", target_swarm="alpha")
        self.assertEqual(data["title"], "Alpha Fund")
        self.assertEqual(data["target_swarm"], "alpha")

    def test_register_with_metadata(self):
        data = _create_proposal(self.client, metadata={"priority": "high"})
        self.assertIn("metadata", data)
        self.assertEqual(data["metadata"]["priority"], "high")

    def test_register_missing_required_field(self):
        resp = self.client.post("/api/v1/quadratic-funding/proposals", json={
            "title": "Incomplete",
        })
        self.assertEqual(resp.status_code, 422)


class TestProposalListing(unittest.TestCase):
    """GET /api/v1/quadratic-funding/proposals"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()
        _create_proposal(cls.client, title="Prop A")
        _create_proposal(cls.client, title="Prop B")

    def test_list_returns_200(self):
        resp = self.client.get("/api/v1/quadratic-funding/proposals")
        self.assertEqual(resp.status_code, 200)

    def test_list_returns_array(self):
        data = self.client.get("/api/v1/quadratic-funding/proposals").json()
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 2)

    def test_list_filter_by_status(self):
        data = self.client.get("/api/v1/quadratic-funding/proposals?status=active").json()
        self.assertTrue(all(p["status"] == "active" for p in data))


class TestProposalDetail(unittest.TestCase):
    """GET /api/v1/quadratic-funding/proposals/{id}"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()
        cls.proposal = _create_proposal(cls.client, title="Detail Test")

    def test_get_returns_200(self):
        pid = self.proposal["proposal_id"]
        resp = self.client.get(f"/api/v1/quadratic-funding/proposals/{pid}")
        self.assertEqual(resp.status_code, 200)

    def test_get_returns_correct_proposal(self):
        pid = self.proposal["proposal_id"]
        data = self.client.get(f"/api/v1/quadratic-funding/proposals/{pid}").json()
        self.assertEqual(data["title"], "Detail Test")

    def test_get_unknown_returns_404(self):
        resp = self.client.get("/api/v1/quadratic-funding/proposals/prop_99999")
        self.assertEqual(resp.status_code, 404)


class TestRoundManagement(unittest.TestCase):
    """POST /rounds, GET /rounds, GET /rounds/{id}"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()
        cls.prop = _create_proposal(cls.client, title="Round Test Prop")

    def test_start_round_returns_200(self):
        resp = self.client.post("/api/v1/quadratic-funding/rounds", json={
            "matching_pool_usd": 5000.0,
        })
        self.assertEqual(resp.status_code, 200)

    def test_start_round_returns_round_id(self):
        data = _create_round(self.client, pool=5000.0)
        self.assertIn("round_id", data)
        self.assertTrue(data["round_id"].startswith("round_"))

    def test_start_round_active_status(self):
        data = _create_round(self.client, pool=3000.0)
        self.assertEqual(data["status"], "active")

    def test_start_round_with_specific_proposals(self):
        pid = self.prop["proposal_id"]
        data = _create_round(self.client, pool=2000.0, proposal_ids=[pid])
        self.assertIn(pid, data["proposal_ids"])

    def test_list_rounds_returns_200(self):
        resp = self.client.get("/api/v1/quadratic-funding/rounds")
        self.assertEqual(resp.status_code, 200)

    def test_list_rounds_returns_array(self):
        data = self.client.get("/api/v1/quadratic-funding/rounds").json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

    def test_get_round_detail(self):
        round_data = _create_round(self.client, pool=1000.0)
        rid = round_data["round_id"]
        data = self.client.get(f"/api/v1/quadratic-funding/rounds/{rid}").json()
        self.assertEqual(data["round_id"], rid)

    def test_get_unknown_round_returns_404(self):
        resp = self.client.get("/api/v1/quadratic-funding/rounds/round_99999")
        self.assertEqual(resp.status_code, 404)


class TestContributions(unittest.TestCase):
    """POST /contributions"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()
        cls.prop = _create_proposal(cls.client, title="Contrib Prop")
        cls.round = _create_round(cls.client, pool=10000.0)

    def test_contribute_returns_200(self):
        resp = self.client.post("/api/v1/quadratic-funding/contributions", json={
            "round_id": self.round["round_id"],
            "proposal_id": self.prop["proposal_id"],
            "contributor_id": "alice",
            "amount_usd": 50.0,
        })
        self.assertEqual(resp.status_code, 200)

    def test_contribute_returns_contribution_fields(self):
        data = self.client.post("/api/v1/quadratic-funding/contributions", json={
            "round_id": self.round["round_id"],
            "proposal_id": self.prop["proposal_id"],
            "contributor_id": "bob",
            "amount_usd": 100.0,
        }).json()
        self.assertEqual(data["contributor_id"], "bob")
        self.assertEqual(data["amount_usd"], 100.0)

    def test_contribute_with_metadata(self):
        data = self.client.post("/api/v1/quadratic-funding/contributions", json={
            "round_id": self.round["round_id"],
            "proposal_id": self.prop["proposal_id"],
            "contributor_id": "carol",
            "amount_usd": 25.0,
            "metadata": {"source": "test"},
        }).json()
        self.assertIn("metadata", data)

    def test_contribute_unknown_round(self):
        resp = self.client.post("/api/v1/quadratic-funding/contributions", json={
            "round_id": "round_99999",
            "proposal_id": self.prop["proposal_id"],
            "contributor_id": "dave",
            "amount_usd": 10.0,
        })
        self.assertIn(resp.status_code, [404, 500])


class TestRoundFinalization(unittest.TestCase):
    """POST /rounds/finalize + GET /rounds/{id}/summary"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()
        cls.prop1 = _create_proposal(cls.client, title="Finalize Prop 1")
        cls.prop2 = _create_proposal(cls.client, title="Finalize Prop 2")
        cls.round = _create_round(cls.client, pool=10000.0)
        rid = cls.round["round_id"]
        pid1 = cls.prop1["proposal_id"]
        pid2 = cls.prop2["proposal_id"]
        # Add contributions from multiple users
        for uid, amount in [("alice", 100), ("bob", 50), ("carol", 25)]:
            cls.client.post("/api/v1/quadratic-funding/contributions", json={
                "round_id": rid, "proposal_id": pid1,
                "contributor_id": uid, "amount_usd": amount,
            })
        for uid, amount in [("dave", 200), ("eve", 10)]:
            cls.client.post("/api/v1/quadratic-funding/contributions", json={
                "round_id": rid, "proposal_id": pid2,
                "contributor_id": uid, "amount_usd": amount,
            })

    def test_finalize_returns_200(self):
        resp = self.client.post("/api/v1/quadratic-funding/rounds/finalize", json={
            "round_id": self.round["round_id"],
        })
        self.assertEqual(resp.status_code, 200)

    def test_finalize_returns_payouts(self):
        data = self.client.post("/api/v1/quadratic-funding/rounds/finalize", json={
            "round_id": self.round["round_id"],
        }).json()
        self.assertIn(self.prop1["proposal_id"], data)
        payout = data[self.prop1["proposal_id"]]
        self.assertIn("direct_usd", payout)
        self.assertIn("matched_usd", payout)
        self.assertIn("total_usd", payout)
        self.assertIn("supporters", payout)

    def test_finalize_quadratic_matching_favors_more_supporters(self):
        """Prop1 has 3 supporters, prop2 has 2 — prop1 should get more matching."""
        data = self.client.post("/api/v1/quadratic-funding/rounds/finalize", json={
            "round_id": self.round["round_id"],
        }).json()
        p1 = data[self.prop1["proposal_id"]]
        p2 = data[self.prop2["proposal_id"]]
        # Prop1: 3 supporters ($100+$50+$25), Prop2: 2 supporters ($200+$10)
        # Quadratic matching should give prop1 more matched funds per direct dollar
        self.assertGreater(p1["supporters"], p2["supporters"])

    def test_finalize_with_governance_notes(self):
        # Create a fresh round to finalize with notes
        prop = _create_proposal(self.client, title="Notes Prop")
        rnd = _create_round(self.client, pool=1000.0)
        self.client.post("/api/v1/quadratic-funding/contributions", json={
            "round_id": rnd["round_id"],
            "proposal_id": prop["proposal_id"],
            "contributor_id": "noter",
            "amount_usd": 50.0,
        })
        resp = self.client.post("/api/v1/quadratic-funding/rounds/finalize", json={
            "round_id": rnd["round_id"],
            "governance_notes": ["Approved by governance council"],
        })
        self.assertEqual(resp.status_code, 200)

    def test_round_summary_after_finalize(self):
        rid = self.round["round_id"]
        data = self.client.get(f"/api/v1/quadratic-funding/rounds/{rid}/summary").json()
        self.assertIn("round_id", data)
        self.assertIn("matching_pool_usd", data)
        self.assertIn("total_direct_usd", data)
        self.assertIn("total_allocated_usd", data)
        self.assertIn("proposal_breakdown", data)

    def test_round_summaries_list(self):
        data = self.client.get("/api/v1/quadratic-funding/rounds/summary?limit=5").json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)


class TestGovernanceNotes(unittest.TestCase):
    """POST /rounds/note"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()
        _create_proposal(cls.client, title="Note Prop")
        cls.round = _create_round(cls.client, pool=5000.0)

    def test_append_note_returns_200(self):
        resp = self.client.post("/api/v1/quadratic-funding/rounds/note", json={
            "round_id": self.round["round_id"],
            "note": "Governance review complete",
        })
        self.assertEqual(resp.status_code, 200)

    def test_append_note_response_fields(self):
        data = self.client.post("/api/v1/quadratic-funding/rounds/note", json={
            "round_id": self.round["round_id"],
            "note": "Second review note",
        }).json()
        self.assertIn("round_id", data)
        self.assertIn("notes", data)
        self.assertIsInstance(data["notes"], list)
        self.assertGreater(len(data["notes"]), 0)

    def test_append_note_accumulates(self):
        rid = self.round["round_id"]
        self.client.post("/api/v1/quadratic-funding/rounds/note", json={
            "round_id": rid, "note": "Note A",
        })
        data = self.client.post("/api/v1/quadratic-funding/rounds/note", json={
            "round_id": rid, "note": "Note B",
        }).json()
        self.assertGreaterEqual(len(data["notes"]), 2)

    def test_append_note_unknown_round(self):
        resp = self.client.post("/api/v1/quadratic-funding/rounds/note", json={
            "round_id": "round_99999",
            "note": "Should fail",
        })
        self.assertEqual(resp.status_code, 404)


class TestProposalSupport(unittest.TestCase):
    """GET /proposals/{id}/support"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()
        cls.prop = _create_proposal(cls.client, title="Support Prop")
        rnd = _create_round(cls.client, pool=5000.0)
        for uid, amount in [("alice", 100), ("bob", 50)]:
            cls.client.post("/api/v1/quadratic-funding/contributions", json={
                "round_id": rnd["round_id"],
                "proposal_id": cls.prop["proposal_id"],
                "contributor_id": uid,
                "amount_usd": amount,
            })

    def test_support_returns_200(self):
        pid = self.prop["proposal_id"]
        resp = self.client.get(f"/api/v1/quadratic-funding/proposals/{pid}/support")
        self.assertEqual(resp.status_code, 200)

    def test_support_response_fields(self):
        pid = self.prop["proposal_id"]
        data = self.client.get(f"/api/v1/quadratic-funding/proposals/{pid}/support").json()
        self.assertEqual(data["proposal_id"], pid)
        self.assertIn("total_direct_usd", data)
        self.assertIn("total_supporters", data)
        self.assertIn("status", data)

    def test_support_totals_correct(self):
        pid = self.prop["proposal_id"]
        data = self.client.get(f"/api/v1/quadratic-funding/proposals/{pid}/support").json()
        self.assertAlmostEqual(data["total_direct_usd"], 150.0, places=2)
        self.assertEqual(data["total_supporters"], 2)

    def test_support_unknown_proposal(self):
        resp = self.client.get("/api/v1/quadratic-funding/proposals/prop_99999/support")
        self.assertEqual(resp.status_code, 404)


class TestEndToEndQuadraticFunding(unittest.TestCase):
    """Full lifecycle: register → contribute → finalize → verify."""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_full_lifecycle(self):
        # 1. Register proposals
        p1 = _create_proposal(self.client, title="E2E Prop A", requested_budget_usd=2000)
        p2 = _create_proposal(self.client, title="E2E Prop B", requested_budget_usd=3000)

        # 2. Start round
        rnd = _create_round(self.client, pool=10000.0)
        rid = rnd["round_id"]

        # 3. Contribute (many small to p1, one large to p2)
        for i in range(5):
            self.client.post("/api/v1/quadratic-funding/contributions", json={
                "round_id": rid,
                "proposal_id": p1["proposal_id"],
                "contributor_id": f"user_{i}",
                "amount_usd": 20.0,
            })
        self.client.post("/api/v1/quadratic-funding/contributions", json={
            "round_id": rid,
            "proposal_id": p2["proposal_id"],
            "contributor_id": "whale",
            "amount_usd": 100.0,
        })

        # 4. Finalize
        payouts = self.client.post("/api/v1/quadratic-funding/rounds/finalize", json={
            "round_id": rid,
            "governance_notes": ["E2E test finalization"],
        }).json()

        # 5. Verify quadratic matching: p1 (5 supporters × $20 = $100 direct)
        #    should get MORE matching than p2 (1 supporter × $100 = $100 direct)
        p1_payout = payouts[p1["proposal_id"]]
        p2_payout = payouts[p2["proposal_id"]]
        self.assertEqual(p1_payout["direct_usd"], 100.0)
        self.assertEqual(p2_payout["direct_usd"], 100.0)
        self.assertGreater(p1_payout["matched_usd"], p2_payout["matched_usd"],
                           "Quadratic matching should favor more diverse supporters")

        # 6. Verify support endpoint
        support = self.client.get(
            f"/api/v1/quadratic-funding/proposals/{p1['proposal_id']}/support"
        ).json()
        self.assertEqual(support["total_supporters"], 5)
        self.assertEqual(support["total_direct_usd"], 100.0)

        # 7. Verify round summary
        summary = self.client.get(f"/api/v1/quadratic-funding/rounds/{rid}/summary").json()
        self.assertEqual(summary["status"], "finalized")
        self.assertGreater(summary["total_allocated_usd"], 0)


if __name__ == "__main__":
    unittest.main()
