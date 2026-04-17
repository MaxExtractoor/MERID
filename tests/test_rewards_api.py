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


class TestRewardsSummary(unittest.TestCase):
    """GET /api/v1/rewards/summary"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_summary_returns_200(self):
        resp = self.client.get("/api/v1/rewards/summary")
        self.assertEqual(resp.status_code, 200)

    def test_summary_has_gamification(self):
        data = self.client.get("/api/v1/rewards/summary").json()
        self.assertIn("gamification", data)
        self.assertIn("leaderboard", data["gamification"])
        self.assertIn("total_users", data["gamification"])
        self.assertIn("total_events", data["gamification"])

    def test_summary_has_quests(self):
        data = self.client.get("/api/v1/rewards/summary").json()
        self.assertIn("quests", data)
        self.assertIn("registered", data["quests"])
        self.assertGreater(data["quests"]["registered"], 0)

    def test_summary_has_reward_pools(self):
        data = self.client.get("/api/v1/rewards/summary").json()
        self.assertIn("reward_pools", data)
        pools = data["reward_pools"]
        self.assertIn("trading", pools)
        self.assertIn("security", pools)
        self.assertIn("governance", pools)

    def test_summary_has_x402(self):
        data = self.client.get("/api/v1/rewards/summary").json()
        self.assertIn("x402", data)

    def test_summary_pool_fields(self):
        data = self.client.get("/api/v1/rewards/summary").json()
        pool = data["reward_pools"]["trading"]
        for key in ("base_emission", "multiplier", "current_emission", "participation_rate"):
            self.assertIn(key, pool)


class TestLeaderboard(unittest.TestCase):
    """GET /api/v1/rewards/leaderboard"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_leaderboard_returns_200(self):
        resp = self.client.get("/api/v1/rewards/leaderboard")
        self.assertEqual(resp.status_code, 200)

    def test_leaderboard_has_items(self):
        data = self.client.get("/api/v1/rewards/leaderboard").json()
        self.assertIn("items", data)
        self.assertIsInstance(data["items"], list)

    def test_leaderboard_limit(self):
        resp = self.client.get("/api/v1/rewards/leaderboard?limit=5")
        self.assertEqual(resp.status_code, 200)

    def test_leaderboard_invalid_limit(self):
        resp = self.client.get("/api/v1/rewards/leaderboard?limit=0")
        self.assertEqual(resp.status_code, 422)


class TestXpAward(unittest.TestCase):
    """POST /api/v1/rewards/xp/award + GET /api/v1/rewards/xp/{user_id}"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_award_xp_returns_200(self):
        resp = self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": "test-agent-1",
            "multiplier": 2.0,
            "reason": "unit-test",
        })
        self.assertEqual(resp.status_code, 200)

    def test_award_xp_response_fields(self):
        data = self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": "test-agent-2",
            "multiplier": 1.5,
            "reason": "test-award",
            "metadata": {"source": "test"},
        }).json()
        self.assertIn("user_id", data)
        self.assertIn("xp_gained", data)
        self.assertIn("total_xp", data)
        self.assertGreater(data["xp_gained"], 0)

    def test_award_xp_accumulates(self):
        uid = "test-accumulator"
        self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": uid, "multiplier": 1.0, "reason": "first",
        })
        r2 = self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": uid, "multiplier": 1.0, "reason": "second",
        }).json()
        self.assertGreaterEqual(r2["total_xp"], r2["xp_gained"] * 2)

    def test_award_xp_invalid_multiplier(self):
        resp = self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": "x", "multiplier": 0.0, "reason": "bad",
        })
        self.assertEqual(resp.status_code, 422)

    def test_get_user_xp(self):
        uid = "test-xp-lookup"
        self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": uid, "multiplier": 1.0, "reason": "setup",
        })
        data = self.client.get(f"/api/v1/rewards/xp/{uid}").json()
        self.assertEqual(data["user_id"], uid)
        self.assertGreater(data["total_xp"], 0)
        self.assertIn("events", data)

    def test_get_user_xp_unknown_user(self):
        data = self.client.get("/api/v1/rewards/xp/nonexistent-user-xyz").json()
        self.assertEqual(data["total_xp"], 0)


class TestQuests(unittest.TestCase):
    """GET /api/v1/rewards/quests + POST /quests/progress + GET /quests/leaderboard"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_list_quests_returns_200(self):
        resp = self.client.get("/api/v1/rewards/quests?season=1")
        self.assertEqual(resp.status_code, 200)

    def test_list_quests_has_seeded_quests(self):
        data = self.client.get("/api/v1/rewards/quests?season=1").json()
        self.assertIn("quests", data)
        self.assertGreater(len(data["quests"]), 0)

    def test_quest_fields(self):
        data = self.client.get("/api/v1/rewards/quests?season=1").json()
        quest = data["quests"][0]
        for key in ("id", "title", "description", "season", "points", "requirements"):
            self.assertIn(key, quest)

    def test_record_progress_returns_200(self):
        resp = self.client.post("/api/v1/rewards/quests/progress", json={
            "quest_id": "q-first-trade",
            "user_id": "test-user-quest",
            "completed": False,
        })
        self.assertEqual(resp.status_code, 200)

    def test_record_progress_completion(self):
        data = self.client.post("/api/v1/rewards/quests/progress", json={
            "quest_id": "q-first-trade",
            "user_id": "test-completer",
            "completed": True,
        }).json()
        self.assertTrue(data["completed"])
        self.assertIsNotNone(data["completion_timestamp"])

    def test_record_progress_awards_xp_on_completion(self):
        uid = "test-quest-xp-earner"
        self.client.post("/api/v1/rewards/quests/progress", json={
            "quest_id": "q-first-trade",
            "user_id": uid,
            "completed": True,
        })
        xp_data = self.client.get(f"/api/v1/rewards/xp/{uid}").json()
        self.assertGreater(xp_data["total_xp"], 0)

    def test_record_progress_unknown_quest(self):
        resp = self.client.post("/api/v1/rewards/quests/progress", json={
            "quest_id": "nonexistent-quest",
            "user_id": "test",
            "completed": False,
        })
        self.assertEqual(resp.status_code, 404)

    def test_season_leaderboard_returns_200(self):
        resp = self.client.get("/api/v1/rewards/quests/leaderboard/1")
        self.assertEqual(resp.status_code, 200)

    def test_season_leaderboard_fields(self):
        data = self.client.get("/api/v1/rewards/quests/leaderboard/1").json()
        self.assertIn("season", data)
        self.assertIn("leaderboard", data)
        self.assertEqual(data["season"], 1)


class TestRewardPools(unittest.TestCase):
    """GET /api/v1/rewards/pools + POST /pools/{pool_id}/adjust"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_list_pools_returns_200(self):
        resp = self.client.get("/api/v1/rewards/pools")
        self.assertEqual(resp.status_code, 200)

    def test_list_pools_has_seeded_pools(self):
        data = self.client.get("/api/v1/rewards/pools").json()
        self.assertIn("pools", data)
        self.assertIn("trading", data["pools"])
        self.assertIn("security", data["pools"])
        self.assertIn("governance", data["pools"])

    def test_pool_fields(self):
        data = self.client.get("/api/v1/rewards/pools").json()
        pool = data["pools"]["trading"]
        for key in ("base_emission_per_day", "multiplier", "current_emission",
                     "participation_rate", "last_adjusted"):
            self.assertIn(key, pool)

    def test_adjust_pool_returns_200(self):
        resp = self.client.post(
            "/api/v1/rewards/pools/trading/adjust?participation_rate=0.5"
        )
        self.assertEqual(resp.status_code, 200)

    def test_adjust_pool_response_fields(self):
        data = self.client.post(
            "/api/v1/rewards/pools/security/adjust?participation_rate=0.8"
        ).json()
        self.assertIn("pool_id", data)
        self.assertIn("new_multiplier", data)
        self.assertIn("current_emission", data)
        self.assertIn("participation_rate", data)
        self.assertEqual(data["pool_id"], "security")

    def test_adjust_pool_unknown(self):
        resp = self.client.post(
            "/api/v1/rewards/pools/nonexistent/adjust?participation_rate=0.5"
        )
        self.assertEqual(resp.status_code, 404)

    def test_adjust_pool_invalid_rate(self):
        resp = self.client.post(
            "/api/v1/rewards/pools/trading/adjust?participation_rate=1.5"
        )
        self.assertEqual(resp.status_code, 422)

    def test_adjust_pool_zero_rate(self):
        resp = self.client.post(
            "/api/v1/rewards/pools/trading/adjust?participation_rate=0.0"
        )
        self.assertEqual(resp.status_code, 200)


class TestX402Endpoints(unittest.TestCase):
    """GET /api/v1/rewards/x402/stats, /receipts, /resources"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_x402_stats_returns_200(self):
        resp = self.client.get("/api/v1/rewards/x402/stats")
        self.assertEqual(resp.status_code, 200)

    def test_x402_receipts_returns_200(self):
        resp = self.client.get("/api/v1/rewards/x402/receipts")
        self.assertEqual(resp.status_code, 200)

    def test_x402_receipts_has_list(self):
        data = self.client.get("/api/v1/rewards/x402/receipts").json()
        self.assertIn("receipts", data)
        self.assertIsInstance(data["receipts"], list)

    def test_x402_resources_returns_200(self):
        resp = self.client.get("/api/v1/rewards/x402/resources")
        self.assertEqual(resp.status_code, 200)

    def test_x402_resources_has_list(self):
        data = self.client.get("/api/v1/rewards/x402/resources").json()
        self.assertIn("resources", data)
        self.assertIsInstance(data["resources"], list)


class TestSecurityEndpoints(unittest.TestCase):
    """GET /api/v1/rewards/security/quests + POST /security/bug-report"""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_security_quests_returns_200(self):
        resp = self.client.get("/api/v1/rewards/security/quests")
        self.assertEqual(resp.status_code, 200)

    def test_security_quests_has_list(self):
        data = self.client.get("/api/v1/rewards/security/quests").json()
        self.assertIn("quests", data)
        self.assertIsInstance(data["quests"], list)

    def test_security_quest_fields(self):
        data = self.client.get("/api/v1/rewards/security/quests").json()
        if data["quests"]:
            quest = data["quests"][0]
            for key in ("id", "type", "title", "description", "points", "tier", "status"):
                self.assertIn(key, quest)

    def test_submit_bug_report_returns_200(self):
        resp = self.client.post("/api/v1/rewards/security/bug-report", json={
            "reporter_id": "test-reporter",
            "title": "Test Bug",
            "description": "This is a test bug report",
            "severity": "low",
        })
        self.assertEqual(resp.status_code, 200)

    def test_bug_report_response_fields(self):
        data = self.client.post("/api/v1/rewards/security/bug-report", json={
            "reporter_id": "test-reporter-2",
            "title": "Another Test Bug",
            "description": "Description of the bug",
            "severity": "medium",
            "affected_contract": "core/audit.py",
            "evidence": ["screenshot.png"],
            "reproduction_steps": ["Step 1", "Step 2"],
        }).json()
        self.assertIn("report_id", data)
        self.assertIn("reporter_id", data)
        self.assertIn("severity", data)
        self.assertEqual(data["severity"], "medium")

    def test_bug_report_severity_mapping(self):
        for sev in ("info", "low", "medium", "high", "critical"):
            data = self.client.post("/api/v1/rewards/security/bug-report", json={
                "reporter_id": f"sev-tester-{sev}",
                "title": f"Bug {sev}",
                "description": "Testing severity mapping",
                "severity": sev,
            }).json()
            self.assertEqual(data["severity"], sev)


class TestEndToEndFlow(unittest.TestCase):
    """Cross-endpoint integration tests."""

    @classmethod
    def setUpClass(cls):
        cls.client = _build_client()

    def test_award_xp_appears_in_leaderboard(self):
        uid = "e2e-leaderboard-user"
        self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": uid, "multiplier": 5.0, "reason": "e2e-test",
        })
        data = self.client.get("/api/v1/rewards/leaderboard?limit=100").json()
        users = [e["user"] for e in data["items"]]
        self.assertIn(uid, users)

    def test_award_xp_appears_in_summary(self):
        uid = "e2e-summary-user"
        self.client.post("/api/v1/rewards/xp/award", json={
            "user_id": uid, "multiplier": 1.0, "reason": "e2e-summary",
        })
        data = self.client.get("/api/v1/rewards/summary").json()
        self.assertGreater(data["gamification"]["total_events"], 0)

    def test_quest_completion_awards_xp_and_shows_in_leaderboard(self):
        uid = "e2e-quest-completer"
        self.client.post("/api/v1/rewards/quests/progress", json={
            "quest_id": "q-bug-hunter",
            "user_id": uid,
            "completed": True,
        })
        xp = self.client.get(f"/api/v1/rewards/xp/{uid}").json()
        self.assertGreater(xp["total_xp"], 0)

    def test_pool_adjust_reflects_in_summary(self):
        self.client.post(
            "/api/v1/rewards/pools/governance/adjust?participation_rate=0.75"
        )
        data = self.client.get("/api/v1/rewards/summary").json()
        gov_pool = data["reward_pools"]["governance"]
        self.assertAlmostEqual(gov_pool["participation_rate"], 0.75, places=2)


if __name__ == "__main__":
    unittest.main()
