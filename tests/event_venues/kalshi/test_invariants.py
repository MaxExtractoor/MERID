"""Tests for merid.event_venues.kalshi.invariants.

Validates:
- accept_valid: live (api.elections.kalshi.com) and demo REST/WS URLs pass validation
- reject_unknown: URLs that are not recognised Kalshi endpoints are rejected
- error_messages: rejection messages are actionable and name the correct live host
- env_match: KALSHI_ENV=live rejects demo URLs, and vice versa
- validate_config_or_raise: end-to-end startup gate

Note on host name: ``api.elections.kalshi.com`` is Kalshi's **production** trade
API for ALL markets (crypto, FX, elections, etc.).  The "elections" in the hostname
is a historical artefact.  It is NOT elections-only.
"""

from __future__ import annotations

import os
import unittest
from dataclasses import dataclass
from typing import Optional

import pytest

from merid.event_venues.kalshi.invariants import (
    DEMO_REST_BASE,
    DEMO_WS_BASE,
    LIVE_REST_BASE,
    LIVE_WS_BASE,
    VALID_KALSHI_API_PATTERNS,
    VALID_KALSHI_WS_PATTERNS,
    assert_valid_rest_url,
    assert_valid_ws_url,
    validate_config_env_match,
    validate_config_or_raise,
)


# ── Minimal config stub ────────────────────────────────────────────────────


@dataclass
class _StubConfig:
    """Minimal KalshiConfig-compatible stub for testing."""

    rest_api_url: str = LIVE_REST_BASE
    ws_api_url: str = LIVE_WS_BASE
    demo_rest_api_url: str = DEMO_REST_BASE
    demo_ws_api_url: str = DEMO_WS_BASE
    use_demo: bool = False
    api_key: Optional[str] = None
    private_key_path: Optional[str] = None
    private_key_pem: Optional[str] = None

    @property
    def base_url(self) -> str:
        return self.demo_rest_api_url if self.use_demo else self.rest_api_url

    @property
    def ws_url(self) -> str:
        return self.demo_ws_api_url if self.use_demo else self.ws_api_url


# ── Pattern constants ──────────────────────────────────────────────────────


class TestPatternConstants(unittest.TestCase):
    """Verify the canonical endpoint constants are correct."""

    def test_live_rest_base_uses_elections_host(self):
        """api.elections.kalshi.com is Kalshi's production trade API."""
        self.assertIn("api.elections.kalshi.com", LIVE_REST_BASE)

    def test_live_ws_base_uses_elections_host(self):
        self.assertIn("api.elections.kalshi.com", LIVE_WS_BASE)

    def test_live_rest_base_is_https(self):
        self.assertTrue(LIVE_REST_BASE.startswith("https://"))

    def test_live_ws_base_is_wss(self):
        self.assertTrue(LIVE_WS_BASE.startswith("wss://"))

    def test_demo_rest_base_uses_demo_host(self):
        self.assertIn("demo", DEMO_REST_BASE)

    def test_demo_ws_base_uses_demo_host(self):
        self.assertIn("demo", DEMO_WS_BASE)

    def test_valid_api_patterns_include_elections(self):
        """VALID_KALSHI_API_PATTERNS must include the production elections host."""
        elections_included = any("api.elections.kalshi.com" in p for p in VALID_KALSHI_API_PATTERNS)
        self.assertTrue(
            elections_included,
            f"api.elections.kalshi.com must be in VALID_KALSHI_API_PATTERNS, got: {VALID_KALSHI_API_PATTERNS}",
        )

    def test_valid_ws_patterns_include_elections(self):
        """VALID_KALSHI_WS_PATTERNS must include the production elections WS host."""
        elections_included = any("api.elections.kalshi.com" in p for p in VALID_KALSHI_WS_PATTERNS)
        self.assertTrue(
            elections_included,
            f"api.elections.kalshi.com must be in VALID_KALSHI_WS_PATTERNS, got: {VALID_KALSHI_WS_PATTERNS}",
        )


# ── assert_valid_rest_url ──────────────────────────────────────────────────


class TestAssertValidRestUrl(unittest.TestCase):
    """Tests for assert_valid_rest_url."""

    # ── Accept valid URLs ────────────────────────────────────────────────

    def test_accepts_live_rest_base(self):
        """Live production URL (api.elections.kalshi.com) must pass without exception."""
        assert_valid_rest_url(LIVE_REST_BASE)  # must not raise

    def test_accepts_demo_rest_base(self):
        """Demo sandbox URL must pass without exception."""
        assert_valid_rest_url(DEMO_REST_BASE)  # must not raise

    def test_accepts_live_elections_host_directly(self):
        """Explicitly verify the elections hostname is accepted."""
        assert_valid_rest_url("https://api.elections.kalshi.com/trade-api/v2")

    def test_accepts_live_rest_with_trailing_slash(self):
        assert_valid_rest_url(LIVE_REST_BASE + "/")

    # ── Reject unknown hosts ─────────────────────────────────────────────

    def test_rejects_unknown_host(self):
        with self.assertRaises(ValueError):
            assert_valid_rest_url("https://api.polymarket.com/v1")

    def test_rejects_empty_url(self):
        with self.assertRaises(ValueError):
            assert_valid_rest_url("")

    def test_rejects_bare_kalshi_com(self):
        """api.kalshi.com (without 'elections') is not a documented Kalshi endpoint."""
        with self.assertRaises(ValueError):
            assert_valid_rest_url("https://api.kalshi.com/trade-api/v2")

    def test_rejection_error_message_names_correct_live_host(self):
        """Error message must point operators to the correct live host."""
        with self.assertRaises(ValueError) as ctx:
            assert_valid_rest_url("https://api.kalshi.com/trade-api/v2")
        err = str(ctx.exception)
        self.assertIn("api.elections.kalshi.com", err, "Error must name the correct live host")
        self.assertIn(LIVE_REST_BASE, err, "Error must include the canonical live URL")


# ── assert_valid_ws_url ───────────────────────────────────────────────────


class TestAssertValidWsUrl(unittest.TestCase):
    """Tests for assert_valid_ws_url."""

    # ── Accept valid URLs ────────────────────────────────────────────────

    def test_accepts_live_ws_base(self):
        assert_valid_ws_url(LIVE_WS_BASE)  # must not raise

    def test_accepts_demo_ws_base(self):
        assert_valid_ws_url(DEMO_WS_BASE)  # must not raise

    def test_accepts_live_elections_ws_host_directly(self):
        """Explicitly verify the elections WS hostname is accepted."""
        assert_valid_ws_url("wss://api.elections.kalshi.com/trade-api/ws/v2")

    # ── Reject unknown hosts ─────────────────────────────────────────────

    def test_rejects_unknown_ws_host(self):
        with self.assertRaises(ValueError):
            assert_valid_ws_url("wss://stream.binance.com/ws")

    def test_rejects_empty_ws_url(self):
        with self.assertRaises(ValueError):
            assert_valid_ws_url("")

    def test_rejects_bare_kalshi_com_ws(self):
        """wss://api.kalshi.com is not a documented Kalshi WS endpoint."""
        with self.assertRaises(ValueError):
            assert_valid_ws_url("wss://api.kalshi.com/trade-api/ws/v2")

    def test_rejection_error_message_names_correct_live_ws_host(self):
        with self.assertRaises(ValueError) as ctx:
            assert_valid_ws_url("wss://api.kalshi.com/trade-api/ws/v2")
        err = str(ctx.exception)
        self.assertIn("api.elections.kalshi.com", err, "Error must name the correct live WS host")
        self.assertIn(LIVE_WS_BASE, err, "Error must include the canonical live WS URL")


# ── validate_config_env_match ─────────────────────────────────────────────


class TestValidateConfigEnvMatch(unittest.TestCase):
    """Tests for validate_config_env_match."""

    def test_live_env_with_live_config_is_clean(self):
        cfg = _StubConfig()  # defaults = live elections URLs, use_demo=False
        issues = validate_config_env_match(cfg, "live")
        self.assertEqual(issues, [], f"Expected no issues, got: {issues}")

    def test_demo_env_with_demo_config_is_clean(self):
        cfg = _StubConfig(use_demo=True)
        issues = validate_config_env_match(cfg, "demo")
        self.assertEqual(issues, [], f"Expected no issues, got: {issues}")

    def test_live_env_with_demo_use_demo_flag_raises_issue(self):
        cfg = _StubConfig(use_demo=True)
        issues = validate_config_env_match(cfg, "live")
        self.assertTrue(
            any("use_demo" in i.lower() for i in issues),
            f"Expected use_demo warning, got: {issues}",
        )

    def test_live_env_with_demo_rest_url_raises_issue(self):
        cfg = _StubConfig(rest_api_url=DEMO_REST_BASE, use_demo=False)
        issues = validate_config_env_match(cfg, "live")
        self.assertTrue(
            any("demo" in i.lower() for i in issues),
            f"Expected demo URL warning, got: {issues}",
        )

    def test_live_env_with_elections_host_is_clean(self):
        """api.elections.kalshi.com is the correct live host — no warning expected."""
        cfg = _StubConfig(
            rest_api_url="https://api.elections.kalshi.com/trade-api/v2",
            ws_api_url="wss://api.elections.kalshi.com/trade-api/ws/v2",
            use_demo=False,
        )
        issues = validate_config_env_match(cfg, "live")
        self.assertEqual(issues, [], f"Elections host should be fine for live, got: {issues}")

    def test_empty_env_returns_no_issues(self):
        """Unknown/empty KALSHI_ENV should not raise issues."""
        cfg = _StubConfig()
        issues = validate_config_env_match(cfg, "")
        self.assertEqual(issues, [])

    def test_reads_env_var_when_not_passed(self):
        """Should read KALSHI_ENV from environment when kalshi_env arg is None."""
        cfg = _StubConfig(use_demo=True)
        orig = os.environ.get("KALSHI_ENV")
        try:
            os.environ["KALSHI_ENV"] = "live"
            issues = validate_config_env_match(cfg, None)
            self.assertTrue(
                any("use_demo" in i.lower() for i in issues),
                f"Expected use_demo issue when KALSHI_ENV=live, got: {issues}",
            )
        finally:
            if orig is None:
                os.environ.pop("KALSHI_ENV", None)
            else:
                os.environ["KALSHI_ENV"] = orig


# ── validate_config_or_raise ──────────────────────────────────────────────


class TestValidateConfigOrRaise(unittest.TestCase):
    """Tests for validate_config_or_raise — the startup gate."""

    def test_valid_live_config_does_not_raise(self):
        cfg = _StubConfig()
        validate_config_or_raise(cfg, "live")  # must not raise

    def test_valid_demo_config_does_not_raise(self):
        cfg = _StubConfig(use_demo=True)
        validate_config_or_raise(cfg, "demo")  # must not raise

    def test_elections_live_config_does_not_raise(self):
        """Explicitly confirm that api.elections.kalshi.com passes the startup gate."""
        cfg = _StubConfig(
            rest_api_url="https://api.elections.kalshi.com/trade-api/v2",
            ws_api_url="wss://api.elections.kalshi.com/trade-api/ws/v2",
        )
        validate_config_or_raise(cfg, "live")  # must not raise

    def test_unknown_rest_host_raises_value_error(self):
        cfg = _StubConfig(rest_api_url="https://api.kalshi.com/trade-api/v2")
        with self.assertRaises(ValueError) as ctx:
            validate_config_or_raise(cfg, "live")
        self.assertIn("api.elections.kalshi.com", str(ctx.exception))

    def test_unknown_ws_host_raises_value_error(self):
        cfg = _StubConfig(ws_api_url="wss://api.kalshi.com/trade-api/ws/v2")
        with self.assertRaises(ValueError) as ctx:
            validate_config_or_raise(cfg, "live")
        self.assertIn("api.elections.kalshi.com", str(ctx.exception))

    def test_empty_rest_url_raises_value_error(self):
        cfg = _StubConfig(rest_api_url="")
        with self.assertRaises(ValueError):
            validate_config_or_raise(cfg, "live")

    def test_empty_ws_url_raises_value_error(self):
        cfg = _StubConfig(ws_api_url="")
        with self.assertRaises(ValueError):
            validate_config_or_raise(cfg, "live")


# ── KalshiConfig integration ──────────────────────────────────────────────


class TestKalshiConfigDefaults(unittest.TestCase):
    """Verify that the real KalshiConfig defaults pass invariant checks."""

    def test_default_rest_url_is_valid(self):
        """KalshiConfig() default REST URL must be a recognised Kalshi endpoint."""
        from merid.event_venues.kalshi.models import KalshiConfig

        import dataclasses
        defaults = {f.name: f.default for f in dataclasses.fields(KalshiConfig) if f.default is not dataclasses.MISSING}
        rest_default = defaults.get("rest_api_url", "")
        assert_valid_rest_url(rest_default)  # must not raise

    def test_default_ws_url_is_valid(self):
        """KalshiConfig() default WS URL must be a recognised Kalshi endpoint."""
        from merid.event_venues.kalshi.models import KalshiConfig

        import dataclasses
        defaults = {f.name: f.default for f in dataclasses.fields(KalshiConfig) if f.default is not dataclasses.MISSING}
        ws_default = defaults.get("ws_api_url", "")
        assert_valid_ws_url(ws_default)  # must not raise

    def test_default_rest_url_uses_elections_host(self):
        """Live default must point to api.elections.kalshi.com (Kalshi's production API)."""
        from merid.event_venues.kalshi.models import KalshiConfig

        import dataclasses
        defaults = {f.name: f.default for f in dataclasses.fields(KalshiConfig) if f.default is not dataclasses.MISSING}
        rest_default = defaults.get("rest_api_url", "")
        self.assertIn("api.elections.kalshi.com", rest_default)
        self.assertNotIn("demo", rest_default)


if __name__ == "__main__":
    unittest.main()
