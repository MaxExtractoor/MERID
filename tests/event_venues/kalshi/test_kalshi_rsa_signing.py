"""Unit tests for Kalshi RSA signing correctness.

Covers:
  - Signature message format: timestamp + METHOD + path only (no body)
  - Timestamp is milliseconds
  - Required headers present
  - Each call produces a fresh signature
  - 401 response surfaces as OperationResult.fail with status_code=401
  - Cache isolation between different key paths
"""

from __future__ import annotations

import base64
import time
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

import pytest


def _make_rsa_client():
    """Create a KalshiVenueClient with an in-memory RSA key (no disk I/O)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.backends import default_backend
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.models import KalshiConfig

    private_key = rsa.generate_private_key(
        public_exponent=65537, key_size=2048, backend=default_backend()
    )

    # Bypass __post_init__ env lookups by using object.__new__ + direct assignment
    config = KalshiConfig.__new__(KalshiConfig)
    config.api_key = "test-key-id-abcdef"
    config.private_key_path = "/tmp/test_key.pem"
    config.private_key_pem = None
    config.use_demo = True
    config.email = None
    config.password = None
    config.timeout = 30.0
    config.ws_timeout = 60.0
    config.rest_api_url = "https://api.elections.kalshi.com/trade-api/v2"
    config.demo_rest_api_url = "https://demo-api.kalshi.co/trade-api/v2"
    config.demo_ws_api_url = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    config.ws_api_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"

    client = KalshiVenueClient(config)
    client._private_key = private_key
    client._cached_key_source = config.private_key_path
    client._auth_mode = "rsa"
    return client, private_key


class TestKalshiRSASigning(unittest.TestCase):
    """Test that _sign_headers produces correctly formatted auth headers."""

    def setUp(self):
        self.client, self.private_key = _make_rsa_client()

    def test_sign_headers_returns_required_keys(self):
        hdrs = self.client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
        self.assertIn("KALSHI-ACCESS-KEY", hdrs)
        self.assertIn("KALSHI-ACCESS-TIMESTAMP", hdrs)
        self.assertIn("KALSHI-ACCESS-SIGNATURE", hdrs)
        self.assertIn("Content-Type", hdrs)

    def test_sign_headers_key_id_matches_config(self):
        hdrs = self.client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
        self.assertEqual(hdrs["KALSHI-ACCESS-KEY"], "test-key-id-abcdef")

    def test_sign_headers_timestamp_is_milliseconds(self):
        """Timestamp must be current time in milliseconds (13 digits)."""
        now_ms = int(time.time() * 1000)
        hdrs = self.client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
        ts = int(hdrs["KALSHI-ACCESS-TIMESTAMP"])
        # Within 5 seconds of now
        self.assertLessEqual(abs(ts - now_ms), 5000)
        # Must be ~13 digits (ms), not ~10 digits (seconds)
        self.assertGreater(ts, 1_000_000_000_000)

    def test_sign_headers_signature_is_base64(self):
        hdrs = self.client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
        sig_b64 = hdrs["KALSHI-ACCESS-SIGNATURE"]
        # Must be valid base64
        decoded = base64.b64decode(sig_b64)
        self.assertGreater(len(decoded), 0)

    def test_sign_headers_no_body_in_signed_message(self):
        """Critical: signature must cover timestamp+METHOD+path ONLY — no body.

        We verify by recovering the signed message from the signature and checking
        that it equals ts+METHOD+path without any body content appended.
        """
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        path = "/trade-api/v2/portfolio/orders"
        hdrs = self.client._sign_headers("POST", path)
        sig = base64.b64decode(hdrs["KALSHI-ACCESS-SIGNATURE"])
        ts = hdrs["KALSHI-ACCESS-TIMESTAMP"]

        # Correct message: no body
        msg_correct = (ts + "POST" + path).encode()

        pub = self.private_key.public_key()
        # verify() raises InvalidSignature if msg doesn't match — should NOT raise
        pub.verify(
            sig,
            msg_correct,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

    def test_sign_headers_body_would_break_verification(self):
        """If body were included, the 'no body' verify would fail (regression guard)."""
        from cryptography.hazmat.primitives.asymmetric import padding, utils
        from cryptography.hazmat.primitives import hashes
        from cryptography.exceptions import InvalidSignature

        path = "/trade-api/v2/portfolio/orders"
        hdrs = self.client._sign_headers("POST", path)
        sig = base64.b64decode(hdrs["KALSHI-ACCESS-SIGNATURE"])
        ts = hdrs["KALSHI-ACCESS-TIMESTAMP"]

        body = '{"ticker":"TEST","count":1}'
        msg_with_body = (ts + "POST" + path + body).encode()

        pub = self.private_key.public_key()
        with self.assertRaises(Exception):  # InvalidSignature
            pub.verify(
                sig,
                msg_with_body,
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.DIGEST_LENGTH,
                ),
                hashes.SHA256(),
            )

    def test_sign_headers_different_on_each_call(self):
        """PSS randomized padding → each signature is unique even for same inputs."""
        h1 = self.client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
        h2 = self.client._sign_headers("GET", "/trade-api/v2/portfolio/balance")
        # PSS always produces different signatures
        self.assertNotEqual(
            h1["KALSHI-ACCESS-SIGNATURE"],
            h2["KALSHI-ACCESS-SIGNATURE"],
        )

    def test_sign_headers_method_uppercased(self):
        """Method must be uppercased in signed message."""
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes

        path = "/trade-api/v2/portfolio/balance"
        hdrs_lower = self.client._sign_headers("get", path)
        sig = base64.b64decode(hdrs_lower["KALSHI-ACCESS-SIGNATURE"])
        ts = hdrs_lower["KALSHI-ACCESS-TIMESTAMP"]

        # Must verify against uppercase GET
        msg_upper = (ts + "GET" + path).encode()
        pub = self.private_key.public_key()
        pub.verify(
            sig, msg_upper,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )

    def test_sign_headers_no_private_key_raises(self):
        """Must raise RuntimeError if private key not loaded."""
        self.client._private_key = None
        with self.assertRaises(RuntimeError, msg="RSA private key not loaded"):
            self.client._sign_headers("GET", "/trade-api/v2/portfolio/balance")


class TestKalshiRSACacheIsolation(unittest.TestCase):
    """RSA key cache is per client instance and keyed by path/pem source (BUG-3)."""

    def test_cache_invalidated_on_different_path(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend
        from merid.event_venues.kalshi.client import KalshiVenueClient
        from merid.event_venues.kalshi.models import KalshiConfig

        key1 = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        key2 = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())

        # Client points at live path but carries a stale key from another path (should reload)
        config = KalshiConfig.__new__(KalshiConfig)
        config.api_key = "live-key-id"
        config.private_key_path = "/path/to/live_key.pem"
        config.private_key_pem = None
        config.use_demo = False
        config.email = None
        config.password = None
        config.timeout = 30.0
        config.ws_timeout = 60.0
        config.rest_api_url = "https://api.elections.kalshi.com/trade-api/v2"
        config.demo_rest_api_url = "https://demo-api.kalshi.co/trade-api/v2"
        config.demo_ws_api_url = "wss://demo-api.kalshi.co/trade-api/ws/v2"
        config.ws_api_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"

        client = KalshiVenueClient(config)
        client._private_key = key1
        client._cached_key_source = "/path/to/demo_key.pem"

        import asyncio

        async def _run():
            # Patch open() to return key2's PEM bytes
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import padding
            pem = key2.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
            with patch("builtins.open", unittest.mock.mock_open(read_data=pem)):
                await client._authenticate_rsa()

        asyncio.run(_run())

        # Client must have key2 from disk, NOT the stale key1 / demo path cache
        self.assertIsNot(client._private_key, key1)
        self.assertEqual(client._cached_key_source, "/path/to/live_key.pem")


def _make_demo_client_fixed_url():
    """Create a password-auth demo client with a hardcoded demo URL, bypassing env."""
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.models import KalshiConfig

    config = KalshiConfig.__new__(KalshiConfig)
    config.api_key = None
    config.private_key_path = None
    config.private_key_pem = None
    config.use_demo = True
    config.email = "t@t.com"
    config.password = "pw"
    config.timeout = 30.0
    config.ws_timeout = 60.0
    # Fixed URLs — not loaded from env so respx can predict them
    config.demo_rest_api_url = "https://demo-api.kalshi.co/trade-api/v2"
    config.rest_api_url = "https://api.elections.kalshi.com/trade-api/v2"
    config.demo_ws_api_url = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    config.ws_api_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
    return KalshiVenueClient(config)


@pytest.mark.asyncio
class TestKalshi401Handling:
    """Test that 401/403 responses surface correctly as OperationResult.fail."""

    async def test_401_returns_operation_result_fail(self):
        """GET /portfolio/balance returning 401 must give OperationResult with success=False.

        status_code is stored in result.metadata['status_code'].
        """
        import respx
        from httpx import Response

        client = _make_demo_client_fixed_url()

        with respx.mock:
            respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
                return_value=Response(200, json={"token": "tok", "member_id": "m"})
            )
            respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/balance").mock(
                return_value=Response(401, json={"error": "unauthorized"})
            )
            await client.connect()
            result = await client._request_with_resilience("GET", "/portfolio/balance")

        assert not result.success
        assert result.metadata.get("status_code") == 401

    async def test_403_returns_operation_result_fail(self):
        """403 must also surface as OperationResult.fail."""
        import respx
        from httpx import Response

        client = _make_demo_client_fixed_url()

        with respx.mock:
            respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
                return_value=Response(200, json={"token": "tok", "member_id": "m"})
            )
            respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/balance").mock(
                return_value=Response(403, json={"error": "forbidden"})
            )
            await client.connect()
            result = await client._request_with_resilience("GET", "/portfolio/balance")

        assert not result.success
        assert result.metadata.get("status_code") == 403

    async def test_200_returns_operation_result_ok(self):
        """Sanity: 200 must give OperationResult with success=True."""
        import respx
        from httpx import Response

        client = _make_demo_client_fixed_url()

        with respx.mock:
            respx.post("https://demo-api.kalshi.co/trade-api/v2/login").mock(
                return_value=Response(200, json={"token": "tok", "member_id": "m"})
            )
            respx.get("https://demo-api.kalshi.co/trade-api/v2/portfolio/balance").mock(
                return_value=Response(200, json={"balance": {"available_balance": 10000}})
            )
            await client.connect()
            result = await client._request_with_resilience("GET", "/portfolio/balance")

        assert result.success
        assert result.data is not None


class TestKalshiConfigUrlConsistency(unittest.TestCase):
    """Test that base_url returns the correct bucket based on use_demo.

    Uses __new__ bypass to avoid .env leaking into config.
    """

    def _make_config(self, use_demo: bool, demo_url: str, live_url: str):
        from merid.event_venues.kalshi.models import KalshiConfig
        c = KalshiConfig.__new__(KalshiConfig)
        c.api_key = "test-id"
        c.private_key_path = None
        c.private_key_pem = None
        c.use_demo = use_demo
        c.email = None
        c.password = None
        c.timeout = 30.0
        c.ws_timeout = 60.0
        c.rest_api_url = live_url
        c.demo_rest_api_url = demo_url
        c.demo_ws_api_url = "wss://demo-api.kalshi.co/trade-api/ws/v2"
        c.ws_api_url = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        return c

    def test_base_url_uses_demo_url_when_use_demo_true(self):
        """base_url must return demo_rest_api_url when use_demo=True."""
        c = self._make_config(
            use_demo=True,
            demo_url="https://demo-api.kalshi.co/trade-api/v2",
            live_url="https://api.elections.kalshi.com/trade-api/v2",
        )
        self.assertEqual(c.base_url, "https://demo-api.kalshi.co/trade-api/v2")
        self.assertEqual(c.base_url, c.demo_rest_api_url)

    def test_base_url_uses_rest_url_when_use_demo_false(self):
        """base_url must return rest_api_url when use_demo=False."""
        c = self._make_config(
            use_demo=False,
            demo_url="https://demo-api.kalshi.co/trade-api/v2",
            live_url="https://api.elections.kalshi.com/trade-api/v2",
        )
        self.assertEqual(c.base_url, "https://api.elections.kalshi.com/trade-api/v2")
        self.assertEqual(c.base_url, c.rest_api_url)


if __name__ == "__main__":
    unittest.main()
