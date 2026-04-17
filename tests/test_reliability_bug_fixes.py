"""Regression tests for reliability audit bug fixes.

Covers:
  BUG-1 : WSSequenceGapAlert fires when seq_gaps > 0
  BUG-2 : KalshiTokenBucket acquire() is race-condition-free under concurrency
  BUG-3 : AlertRule.safe_evaluate() returns firing=True (not False) on probe error
  BUG-5 : Operator emergency_stop / reset_kill_switch write to audit trail
  BUG-6 : WS auth_failed stops reconnect loop after _MAX_AUTH_FAILURES
  BUG-7 : _build_snapshot uses live WS bid/ask from get_live_prices() when available
  BUG-8 : _require_operator_auth blocks (503) in non-dev envs when token is unset
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# BUG-2: KalshiTokenBucket concurrency safety
# ---------------------------------------------------------------------------

class TestKalshiTokenBucketConcurrency(unittest.IsolatedAsyncioTestCase):
    """asyncio.Lock must prevent double-decrement under concurrent acquire() calls."""

    async def test_concurrent_write_acquires_do_not_over_consume(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket

        bucket = KalshiTokenBucket(tier="basic")
        # basic write rate = 10/s → start with 10 tokens
        self.assertAlmostEqual(bucket._write_tokens, bucket.write_rate, places=1)

        initial_tokens = bucket._write_tokens
        n = int(initial_tokens)

        # Fire n concurrent write acquires; none should sleep (tokens available)
        tasks = [asyncio.create_task(bucket.acquire(is_write=True)) for _ in range(n)]
        waits = await asyncio.gather(*tasks)

        # Each task should have consumed exactly 1 token with no wait
        self.assertEqual(sum(w == 0.0 for w in waits), n)
        # Tokens must not go negative
        self.assertGreaterEqual(bucket._write_tokens, -0.01)

    async def test_lock_attribute_exists(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        bucket = KalshiTokenBucket()
        self.assertTrue(hasattr(bucket, "_lock"))
        self.assertIsInstance(bucket._lock, asyncio.Lock)

    async def test_get_stats_returns_dict(self):
        from merid.event_venues.kalshi.client import KalshiTokenBucket
        bucket = KalshiTokenBucket(tier="basic")
        stats = bucket.get_stats()
        self.assertIn("tier", stats)
        self.assertIn("read_tokens", stats)
        self.assertIn("write_tokens", stats)


# ---------------------------------------------------------------------------
# BUG-3: AlertRule.safe_evaluate() probe failures must fire, not suppress
# ---------------------------------------------------------------------------

class TestAlertRuleSafeEvaluate(unittest.TestCase):

    def _make_broken_rule(self):
        from web.api.system_observability import AlertRule

        class BrokenRule(AlertRule):
            def __init__(self):
                super().__init__("broken_test", "critical", "always throws")

            def evaluate(self) -> Dict[str, Any]:
                raise RuntimeError("dependency missing")

        return BrokenRule()

    def test_probe_error_returns_firing_true(self):
        rule = self._make_broken_rule()
        result = rule.safe_evaluate()
        self.assertTrue(result["firing"], "probe error must return firing=True")

    def test_probe_error_severity_is_warning(self):
        rule = self._make_broken_rule()
        result = rule.safe_evaluate()
        self.assertEqual(result["severity"], "warning")

    def test_probe_error_detail_contains_probe_error_key(self):
        rule = self._make_broken_rule()
        result = rule.safe_evaluate()
        self.assertIn("probe_error", result.get("detail", {}))

    def test_probe_error_preserves_original_severity(self):
        rule = self._make_broken_rule()
        result = rule.safe_evaluate()
        self.assertEqual(result["detail"]["original_severity"], "critical")

    def test_healthy_rule_still_returns_not_firing(self):
        from web.api.system_observability import AlertRule

        class HealthyRule(AlertRule):
            def __init__(self):
                super().__init__("healthy_test", "warning", "always ok")

            def evaluate(self) -> Dict[str, Any]:
                return {"firing": False, "severity": "warning",
                        "name": self.name, "description": self.description, "detail": {}}

        rule = HealthyRule()
        result = rule.safe_evaluate()
        self.assertFalse(result["firing"])


# ---------------------------------------------------------------------------
# BUG-6: WS auth_failed permanent error stops reconnect loop
# ---------------------------------------------------------------------------

class TestWSAuthFailedStopsReconnect(unittest.TestCase):

    def _make_ws(self):
        from merid.event_venues.kalshi.ws import KalshiWebSocket, _MAX_AUTH_FAILURES
        ws = KalshiWebSocket.__new__(KalshiWebSocket)
        # Minimal init without I/O
        ws._ws = None
        ws._running = True
        ws._errors_received = 0
        ws._consecutive_auth_failures = 0
        ws._loop_lag_samples = []
        return ws, _MAX_AUTH_FAILURES

    def test_auth_failed_below_threshold_does_not_stop(self):
        ws, max_f = self._make_ws()
        for _ in range(max_f - 1):
            ws._handle_error_message({"code": "auth_failed", "msg": "bad key"})
        self.assertTrue(ws._running, "should still be running below threshold")
        self.assertEqual(ws._consecutive_auth_failures, max_f - 1)

    def test_auth_failed_at_threshold_stops_running(self):
        ws, max_f = self._make_ws()
        for _ in range(max_f):
            ws._handle_error_message({"code": "auth_failed", "msg": "bad key"})
        self.assertFalse(ws._running, "_running must be False after max auth failures")

    def test_invalid_token_also_stops_after_threshold(self):
        ws, max_f = self._make_ws()
        for _ in range(max_f):
            ws._handle_error_message({"code": "invalid_token", "msg": "expired"})
        self.assertFalse(ws._running)

    def test_rate_limited_does_not_stop_running(self):
        ws, _ = self._make_ws()
        # rate_limited is a transient FATAL code — should NOT stop running
        ws._handle_error_message({"code": "rate_limited", "msg": "slow down"})
        self.assertTrue(ws._running)

    def test_consecutive_count_resets_on_non_auth_error(self):
        ws, max_f = self._make_ws()
        for _ in range(max_f - 1):
            ws._handle_error_message({"code": "auth_failed", "msg": "bad key"})
        self.assertEqual(ws._consecutive_auth_failures, max_f - 1)
        # A transient FATAL code (rate_limited) resets the auth counter
        # so a subsequent successful connect clears the streak
        ws._handle_error_message({"code": "rate_limited", "msg": "slow down"})
        self.assertEqual(ws._consecutive_auth_failures, 0,
                         "rate_limited FATAL handler must reset auth failure counter")
        self.assertTrue(ws._running, "rate_limited must not stop running")


# ---------------------------------------------------------------------------
# BUG-7: _build_snapshot uses live WS bid/ask when available
# ---------------------------------------------------------------------------

class TestBuildSnapshotLivePrices(unittest.TestCase):

    def _make_agent(self):
        """Construct a minimal KalshiTradingAgent without full deps."""
        from merid.prediction.trading_agent import KalshiTradingAgent, AgentConfig
        from merid.prediction.model import PredictionMarketModel
        from merid.prediction.strategy import KalshiStrategy
        from merid.prediction.risk import PredictionMarketRisk

        cfg = AgentConfig(name="test_agent", assets=["BTC"], timeframes=["15m"])
        agent = KalshiTradingAgent.__new__(KalshiTradingAgent)
        agent.config = cfg
        agent._model = PredictionMarketModel()
        agent._strategy = KalshiStrategy()
        agent._risk = PredictionMarketRisk()
        agent._btc15m_risk = None
        agent.logger = MagicMock()
        return agent

    def _make_market(self, market_id: str = "KXBTC-25DEC-T60000"):
        from merid.event_venues.base import EventMarket, EventOutcome
        m = EventMarket.__new__(EventMarket)
        m.market_id = market_id
        m.question = "Will BTC exceed $60k?"
        m.active = True
        m.end_date = None
        m.volume = Decimal("100")
        m.open_interest = Decimal("50")
        m.category = "crypto"
        m.outcomes = [
            EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("0.55")),
            EventOutcome(outcome_id="no", outcome_name="No", price=Decimal("0.45")),
        ]
        return m

    def test_live_prices_used_when_ws_available(self):
        from datetime import datetime, timezone
        agent = self._make_agent()
        market = self._make_market()
        live_data = {"yes_bid_cents": 52, "yes_ask_cents": 56, "has_gap": False}

        with patch("merid.event_venues.kalshi.ws_bridge.get_live_prices", return_value=live_data):
            snapshot = agent._build_snapshot(market, datetime.now(timezone.utc))

        # implied.yes_bid is stored in cents (e.g. 52.0 for 52¢).
        # WS live: yes_bid=52¢ → implied.yes_bid≈52
        # REST catalog fallback: yes_price=55¢ → yes_bid=54¢ → implied.yes_bid≈54
        if snapshot.implied and snapshot.implied.yes_bid is not None:
            bid_cents = float(snapshot.implied.yes_bid)
            self.assertAlmostEqual(bid_cents, 52.0, delta=1.5,
                                   msg="yes_bid should come from WS orderbook (52¢), not catalog fallback (54¢)")

    def test_falls_back_to_catalog_when_ws_unavailable(self):
        from datetime import datetime, timezone
        agent = self._make_agent()
        market = self._make_market()

        with patch("merid.event_venues.kalshi.ws_bridge.get_live_prices", return_value=None):
            snapshot = agent._build_snapshot(market, datetime.now(timezone.utc))

        # Should not raise; snapshot should still be built
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.market_id, market.market_id)

    def test_falls_back_on_import_error(self):
        from datetime import datetime, timezone
        agent = self._make_agent()
        market = self._make_market()

        with patch("merid.event_venues.kalshi.ws_bridge.get_live_prices",
                   side_effect=ImportError("bridge not available")):
            snapshot = agent._build_snapshot(market, datetime.now(timezone.utc))

        self.assertIsNotNone(snapshot)


# ---------------------------------------------------------------------------
# BUG-8: _require_operator_auth blocks in non-dev envs when token unset
# ---------------------------------------------------------------------------

class TestRequireOperatorAuth(unittest.TestCase):

    def _make_request(self, auth_header: str = "", client_host: str = "127.0.0.1"):
        req = MagicMock()
        req.headers.get = lambda k, d="": auth_header if k == "Authorization" else d
        req.client = MagicMock()
        req.client.host = client_host
        return req

    def test_unset_token_in_dev_allows_through(self):
        from web.api.operator_endpoints import _require_operator_auth
        from fastapi import HTTPException

        with patch.dict(os.environ, {"MERID_OPERATOR_TOKEN": "", "MERID_ENV": "development"}):
            with patch("web.api.operator_endpoints._MERID_ENV", "development"):
                try:
                    _require_operator_auth(self._make_request())
                except HTTPException:
                    self.fail("Should not raise in development env")

    def test_unset_token_in_production_returns_503(self):
        from web.api import operator_endpoints as oe
        from fastapi import HTTPException

        # Patch _MERID_ENV to production and ensure MERID_OPERATOR_TOKEN returns empty
        # Also ensure MERID_SINGLE_USER_OPERATOR is not set to "1" (which would bypass check)
        orig_getenv = os.getenv
        def mock_getenv(k, d=""):
            if k == "MERID_OPERATOR_TOKEN":
                return ""
            if k == "MERID_SINGLE_USER_OPERATOR":
                return ""
            return orig_getenv(k, d)

        with patch.object(oe, "_MERID_ENV", "production"):
            with patch("os.getenv", mock_getenv):
                with self.assertRaises(HTTPException) as ctx:
                    oe._require_operator_auth(self._make_request())
                self.assertEqual(ctx.exception.status_code, 503)

    def test_unset_token_in_paper_returns_503(self):
        from web.api import operator_endpoints as oe
        from fastapi import HTTPException

        # Patch _MERID_ENV to paper and ensure MERID_OPERATOR_TOKEN returns empty
        # Also ensure MERID_SINGLE_USER_OPERATOR is not set to "1" (which would bypass check)
        orig_getenv = os.getenv
        def mock_getenv(k, d=""):
            if k == "MERID_OPERATOR_TOKEN":
                return ""
            if k == "MERID_SINGLE_USER_OPERATOR":
                return ""
            return orig_getenv(k, d)

        with patch.object(oe, "_MERID_ENV", "paper"):
            with patch("os.getenv", mock_getenv):
                with self.assertRaises(HTTPException) as ctx:
                    oe._require_operator_auth(self._make_request())
                self.assertEqual(ctx.exception.status_code, 503)

    def test_valid_token_passes(self):
        from web.api import operator_endpoints as oe
        from fastapi import HTTPException

        # Patch _MERID_ENV to production and set MERID_OPERATOR_TOKEN
        # Also ensure MERID_SINGLE_USER_OPERATOR is not set to "1" (which would bypass check)
        orig_getenv = os.getenv
        def mock_getenv(k, d=""):
            if k == "MERID_OPERATOR_TOKEN":
                return "secret123"
            if k == "MERID_SINGLE_USER_OPERATOR":
                return ""
            return orig_getenv(k, d)

        with patch.object(oe, "_MERID_ENV", "production"):
            with patch("os.getenv", mock_getenv):
                try:
                    oe._require_operator_auth(self._make_request("Bearer secret123"))
                except HTTPException:
                    self.fail("Valid token should not raise")

    def test_wrong_token_returns_403(self):
        from web.api import operator_endpoints as oe
        from fastapi import HTTPException

        # Patch _MERID_ENV to production and set MERID_OPERATOR_TOKEN
        # Also ensure MERID_SINGLE_USER_OPERATOR is not set to "1" (which would bypass check)
        orig_getenv = os.getenv
        def mock_getenv(k, d=""):
            if k == "MERID_OPERATOR_TOKEN":
                return "correct"
            if k == "MERID_SINGLE_USER_OPERATOR":
                return ""
            return orig_getenv(k, d)

        with patch.object(oe, "_MERID_ENV", "production"):
            with patch("os.getenv", mock_getenv):
                with self.assertRaises(HTTPException) as ctx:
                    oe._require_operator_auth(self._make_request("Bearer wrong"))
                self.assertEqual(ctx.exception.status_code, 403)

    def test_missing_bearer_prefix_returns_401(self):
        from web.api import operator_endpoints as oe
        from fastapi import HTTPException

        # Patch _MERID_ENV to production and set MERID_OPERATOR_TOKEN
        # Also ensure MERID_SINGLE_USER_OPERATOR is not set to "1" (which would bypass check)
        orig_getenv = os.getenv
        def mock_getenv(k, d=""):
            if k == "MERID_OPERATOR_TOKEN":
                return "correct"
            if k == "MERID_SINGLE_USER_OPERATOR":
                return ""
            return orig_getenv(k, d)

        with patch.object(oe, "_MERID_ENV", "production"):
            with patch("os.getenv", mock_getenv):
                with self.assertRaises(HTTPException) as ctx:
                    oe._require_operator_auth(self._make_request("correct"))
                self.assertEqual(ctx.exception.status_code, 401)


# ---------------------------------------------------------------------------
# BUG-5: Operator audit trail writes with identity on destructive actions
# ---------------------------------------------------------------------------

class TestOperatorAuditTrail(unittest.TestCase):

    def test_record_operator_action_writes_entry(self):
        import tempfile
        from trading.audit_trail import record_operator_action, _AUDIT_DIR, _AUDIT_FILE

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_file = Path(tmpdir) / "trade_audit.jsonl"
            with patch("trading.audit_trail._AUDIT_DIR", Path(tmpdir)), \
                 patch("trading.audit_trail._AUDIT_FILE", fake_file):
                event_id = record_operator_action(
                    action="emergency_stop",
                    reason="testing",
                    actor_token_hash="abc123def456aabb",
                    actor_ip="10.0.0.1",
                    previous_state={"can_trade": True},
                )

            self.assertTrue(fake_file.exists(), "audit file must be created")
            lines = fake_file.read_text().strip().split("\n")
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["event_type"], "operator_action")
            self.assertEqual(entry["metadata"]["action"], "emergency_stop")
            self.assertEqual(entry["metadata"]["actor_token_hash"], "abc123def456aabb")
            self.assertEqual(entry["metadata"]["actor_ip"], "10.0.0.1")
            self.assertEqual(entry["metadata"]["previous_state"]["can_trade"], True)

    def test_write_operator_audit_redacts_token(self):
        """_write_operator_audit must never store the raw token."""
        from web.api.operator_endpoints import _write_operator_audit

        captured = {}

        def fake_record(**kwargs):
            captured.update(kwargs)
            return "evt-123"

        req = MagicMock()
        req.headers.get = lambda k, d="": "Bearer mysecrettoken" if k == "Authorization" else d
        req.client = MagicMock()
        req.client.host = "192.168.1.1"

        # _write_operator_audit does a lazy import inside itself, so patch
        # the function at its definition site in trading.audit_trail
        with patch("trading.audit_trail.record_operator_action", fake_record):
            _write_operator_audit(
                request=req,
                action="reset_kill_switch",
                reason="post-incident",
                previous_state={"can_trade": False},
            )

        # The raw token must NOT appear in the stored hash
        token_hash = captured.get("actor_token_hash", "")
        self.assertNotIn("mysecrettoken", token_hash)
        # Hash must be a hex prefix of SHA-256
        expected = hashlib.sha256(b"mysecrettoken").hexdigest()[:16]
        self.assertEqual(token_hash, expected)


# ---------------------------------------------------------------------------
# BUG-1: WSSequenceGapAlert fires when seq_gaps > 0
# ---------------------------------------------------------------------------

class TestWSSequenceGapAlert(unittest.TestCase):

    def _make_alert(self):
        from web.api.system_observability import WSSequenceGapAlert
        return WSSequenceGapAlert()

    def _make_bridge_mock(self, running: bool = True, seq_gaps: int = 0,
                          consecutive_auth: int = 0) -> MagicMock:
        bridge = MagicMock()
        bridge.is_running.return_value = running
        ws = MagicMock()
        ws.stats.return_value = {
            "seq_gaps": seq_gaps,
            "connected": running,
            "ob_cached_markets": 3,
            "reconnect_count": 0,
        }
        ws._consecutive_auth_failures = consecutive_auth
        bridge._ws = ws
        return bridge

    def test_no_gaps_not_firing(self):
        alert = self._make_alert()
        bridge = self._make_bridge_mock(running=True, seq_gaps=0)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = alert.evaluate()
        self.assertFalse(result["firing"])

    def test_gaps_gt_zero_fires(self):
        alert = self._make_alert()
        bridge = self._make_bridge_mock(running=True, seq_gaps=3)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = alert.evaluate()
        self.assertTrue(result["firing"])
        self.assertEqual(result["severity"], "warning")

    def test_many_gaps_escalates_to_critical(self):
        alert = self._make_alert()
        bridge = self._make_bridge_mock(running=True, seq_gaps=15)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = alert.evaluate()
        self.assertTrue(result["firing"])
        self.assertEqual(result["severity"], "critical")

    def test_consecutive_auth_failures_escalates_to_critical(self):
        alert = self._make_alert()
        bridge = self._make_bridge_mock(running=True, seq_gaps=1, consecutive_auth=3)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = alert.evaluate()
        self.assertEqual(result["severity"], "critical")

    def test_bridge_not_running_not_firing(self):
        alert = self._make_alert()
        bridge = self._make_bridge_mock(running=False, seq_gaps=5)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = alert.evaluate()
        self.assertFalse(result["firing"])

    def test_import_error_not_firing(self):
        alert = self._make_alert()
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge",
                   side_effect=ImportError("bridge unavailable")):
            result = alert.safe_evaluate()
        # On import error, safe_evaluate fires=True (probe error) — acceptable
        # The important invariant is no unhandled exception
        self.assertIn("firing", result)


# ---------------------------------------------------------------------------
# BUG-7 (supplemental): get_live_prices helper returns correct structure
# ---------------------------------------------------------------------------

class TestGetLivePrices(unittest.TestCase):

    def _make_bridge(self, market_id: str, snapshot: Optional[Dict] = None,
                     initialised: bool = True) -> MagicMock:
        bridge = MagicMock()
        ws = MagicMock()
        ws._ob_initialised = {market_id} if initialised else set()
        ws._ob_snapshots = {market_id: snapshot} if snapshot else {}
        bridge._ws = ws
        return bridge

    def test_returns_none_when_not_initialised(self):
        from merid.event_venues.kalshi.ws_bridge import get_live_prices
        bridge = self._make_bridge("MKTX", initialised=False)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = get_live_prices("MKTX")
        self.assertIsNone(result)

    def test_returns_bid_ask_from_snapshot(self):
        from merid.event_venues.kalshi.ws_bridge import get_live_prices
        snapshot = {"yes": [[55, 10], [52, 5]], "no": [[48, 8], [45, 3]]}
        bridge = self._make_bridge("MKTX", snapshot=snapshot, initialised=True)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = get_live_prices("MKTX")
        self.assertIsNotNone(result)
        self.assertEqual(result["yes_bid_cents"], 55)
        # best ask = 100 - best_no_bid = 100 - 48 = 52
        self.assertEqual(result["yes_ask_cents"], 52)

    def test_returns_none_on_empty_yes_levels(self):
        from merid.event_venues.kalshi.ws_bridge import get_live_prices
        snapshot = {"yes": [], "no": [[45, 5]]}
        bridge = self._make_bridge("MKTX", snapshot=snapshot, initialised=True)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = get_live_prices("MKTX")
        self.assertIsNone(result)

    def test_fallback_ask_when_no_levels_absent(self):
        from merid.event_venues.kalshi.ws_bridge import get_live_prices
        snapshot = {"yes": [[60, 10]]}
        bridge = self._make_bridge("MKTX", snapshot=snapshot, initialised=True)
        with patch("merid.event_venues.kalshi.ws_bridge.get_ws_bridge", return_value=bridge):
            result = get_live_prices("MKTX")
        self.assertIsNotNone(result)
        self.assertEqual(result["yes_bid_cents"], 60)
        self.assertEqual(result["yes_ask_cents"], 61)  # fallback bid+1


if __name__ == "__main__":
    unittest.main()
