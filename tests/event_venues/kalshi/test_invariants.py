"""Tests for merid.event_venues.kalshi.invariants.

Validates:
- accept_valid: live and demo REST/WS URLs pass validation
- reject_elections: the elections-only host is rejected for both REST and WS
- error_messages: rejection messages are actionable and name the correct live host
- env_match: KALSHI_ENV=live rejects demo URLs, and vice versa
- validate_config_or_raise: end-to-end startup gate
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

    def test_live_rest_base_uses_api_kalshi_com(self):
        self.assertIn("api.kalshi.com", LIVE_REST_BASE)
        self.assertNotIn("elections", LIVE_REST_BASE)

    def test_live_ws_base_uses_api_kalshi_com(self):
        self.assertIn("api.kalshi.com", LIVE_WS_BASE)
        self.assertNotIn("elections", LIVE_WS_BASE)

    def test_demo_rest_base_uses_demo_host(self):
        self.assertIn("demo", DEMO_REST_BASE)

    def test_demo_ws_base_uses_demo_host(self):
        self.assertIn("demo", DEMO_WS_BASE)

    def test_valid_api_patterns_exclude_elections(self):
        for pat in VALID_KALSHI_API_PATTERNS:
            self.assertNotIn("elections", pat, f"Pattern {pat!r} should not include elections host")

    def test_valid_ws_patterns_exclude_elections(self):
        for pat in VALID_KALSHI_WS_PATTERNS:
            self.assertNotIn("elections", pat, f"WS pattern {pat!r} should not include elections host")


# ── assert_valid_rest_url ──────────────────────────────────────────────────


class TestAssertValidRestUrl(unittest.TestCase):
    """Tests for assert_valid_rest_url."""

    # ── Accept valid URLs ────────────────────────────────────────────────

    def test_accepts_live_rest_base(self):
        """Live production URL should pass without exception."""
        assert_valid_rest_url(LIVE_REST_BASE)  # must not raise

    def test_accepts_demo_rest_base(self):
        """Demo sandbox URL should pass without exception."""
        assert_valid_rest_url(DEMO_REST_BASE)  # must not raise

    def test_accepts_live_rest_with_trailing_slash(self):
        assert_valid_rest_url(LIVE_REST_BASE + "/")

    # ── Reject elections host ────────────────────────────────────────────

    def test_rejects_elections_host(self):
        bad = "https://api.elections.kalshi.com/trade-api/v2"
        with self.assertRaises(ValueError) as ctx:
            assert_valid_rest_url(bad)
        err = str(ctx.exception)
        self.assertIn("elections", err.lower())
        self.assertIn(LIVE_REST_BASE, err)

    def test_rejects_elections_host_error_message_is_actionable(self):
        bad = "https://api.elections.kalshi.com/trade-api/v2"
        with self.assertRaises(ValueError) as ctx:
            assert_valid_rest_url(bad)
        err = str(ctx.exception)
        # Must recommend the correct live host explicitly
        self.assertIn("api.kalshi.com", err, "Error message must name the correct live host")
        self.assertIn(LIVE_REST_BASE, err, "Error message must include the canonical live URL")

    def test_rejects_unknown_host(self):
        with self.assertRaises(ValueError):
            assert_valid_rest_url("https://api.polymarket.com/v1")

    def test_rejects_empty_url(self):
        with self.assertRaises(ValueError):
            assert_valid_rest_url("")

    def test_rejects_none_like_empty_string(self):
        with self.assertRaises(ValueError):
            assert_valid_rest_url("")


# ── assert_valid_ws_url ───────────────────────────────────────────────────


class TestAssertValidWsUrl(unittest.TestCase):
    """Tests for assert_valid_ws_url."""

    # ── Accept valid URLs ────────────────────────────────────────────────

    def test_accepts_live_ws_base(self):
        assert_valid_ws_url(LIVE_WS_BASE)  # must not raise

    def test_accepts_demo_ws_base(self):
        assert_valid_ws_url(DEMO_WS_BASE)  # must not raise

    # ── Reject elections host ────────────────────────────────────────────

    def test_rejects_elections_ws_host(self):
        bad = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        with self.assertRaises(ValueError) as ctx:
            assert_valid_ws_url(bad)
        err = str(ctx.exception)
        self.assertIn("elections", err.lower())
        self.assertIn(LIVE_WS_BASE, err)

    def test_rejects_elections_ws_error_message_is_actionable(self):
        bad = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        with self.assertRaises(ValueError) as ctx:
            assert_valid_ws_url(bad)
        err = str(ctx.exception)
        self.assertIn("api.kalshi.com", err, "Error message must name the correct live WS host")
        self.assertIn(LIVE_WS_BASE, err, "Error message must include the canonical live WS URL")

    def test_rejects_unknown_ws_host(self):
        with self.assertRaises(ValueError):
            assert_valid_ws_url("wss://stream.binance.com/ws")

    def test_rejects_empty_ws_url(self):
        with self.assertRaises(ValueError):
            assert_valid_ws_url("")


# ── validate_config_env_match ─────────────────────────────────────────────


class TestValidateConfigEnvMatch(unittest.TestCase):
    """Tests for validate_config_env_match."""

    def test_live_env_with_live_config_is_clean(self):
        cfg = _StubConfig()  # defaults = live URLs, use_demo=False
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

    def test_live_env_with_elections_rest_url_raises_issue(self):
        cfg = _StubConfig(
            rest_api_url="https://api.elections.kalshi.com/trade-api/v2",
            use_demo=False,
        )
        issues = validate_config_env_match(cfg, "live")
        self.assertTrue(
            any("elections" in i.lower() for i in issues),
            f"Expected elections host warning, got: {issues}",
        )

    def test_live_env_with_elections_ws_url_raises_issue(self):
        cfg = _StubConfig(
            ws_api_url="wss://api.elections.kalshi.com/trade-api/ws/v2",
            use_demo=False,
        )
        issues = validate_config_env_match(cfg, "live")
        self.assertTrue(
            any("elections" in i.lower() for i in issues),
            f"Expected elections WS warning, got: {issues}",
        )

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

    def test_elections_rest_url_raises_value_error(self):
        cfg = _StubConfig(rest_api_url="https://api.elections.kalshi.com/trade-api/v2")
        with self.assertRaises(ValueError) as ctx:
            validate_config_or_raise(cfg, "live")
        self.assertIn("elections", str(ctx.exception).lower())
        self.assertIn("api.kalshi.com", str(ctx.exception))

    def test_elections_ws_url_raises_value_error(self):
        cfg = _StubConfig(ws_api_url="wss://api.elections.kalshi.com/trade-api/ws/v2")
        with self.assertRaises(ValueError) as ctx:
            validate_config_or_raise(cfg, "live")
        self.assertIn("elections", str(ctx.exception).lower())
        self.assertIn("api.kalshi.com", str(ctx.exception))

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
        """KalshiConfig() default REST URL must not be the elections host."""
        from merid.event_venues.kalshi.models import KalshiConfig

        cfg = KalshiConfig.__new__(KalshiConfig)
        # Access the default field value without __post_init__ side effects
        import dataclasses
        defaults = {f.name: f.default for f in dataclasses.fields(KalshiConfig) if f.default is not dataclasses.MISSING}
        rest_default = defaults.get("rest_api_url", "")
        assert_valid_rest_url(rest_default)  # must not raise

    def test_default_ws_url_is_valid(self):
        """KalshiConfig() default WS URL must not be the elections host."""
        from merid.event_venues.kalshi.models import KalshiConfig

        import dataclasses
        defaults = {f.name: f.default for f in dataclasses.fields(KalshiConfig) if f.default is not dataclasses.MISSING}
        ws_default = defaults.get("ws_api_url", "")
        assert_valid_ws_url(ws_default)  # must not raise

    def test_default_rest_url_uses_api_kalshi_com(self):
        """Live default must point to api.kalshi.com, not elections or demo host."""
        from merid.event_venues.kalshi.models import KalshiConfig

        import dataclasses
        defaults = {f.name: f.default for f in dataclasses.fields(KalshiConfig) if f.default is not dataclasses.MISSING}
        rest_default = defaults.get("rest_api_url", "")
        self.assertIn("api.kalshi.com", rest_default)
        self.assertNotIn("elections", rest_default)
        self.assertNotIn("demo", rest_default)


if __name__ == "__main__":
    unittest.main()
