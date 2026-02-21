"""
Kalshi REST API Client
Handles authentication and HTTP requests to Kalshi REST API
"""

import time
import base64
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from cryptography.hazmat.primitives import serialization, hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = logging.getLogger(__name__)


class KalshiRestClient:
    """
    Kalshi REST API Client
    
    Handles authentication using RSA-PSS signatures and provides methods
    for common operations (balance, positions, orders)
    
    Usage:
        client = KalshiRestClient(
            key_id="your_key_id",
            private_key_path="path/to/key.pem",
            env="demo"
        )
        
        # Get balance
        balance = await client.get_balance()
        
        # Create order
        order = await client.create_order(
            ticker="KXHARRIS24-LSV",
            side="buy",
            action="yes",
            quantity=1,
            price=50,
            client_order_id="unique-id"
        )
    """
    
    def __init__(
        self,
        key_id: str,
        private_key_path: str,
        env: str = "demo"
    ):
        if not REQUESTS_AVAILABLE:
            raise ImportError("requests not installed: pip install requests")
        if not CRYPTO_AVAILABLE:
            raise ImportError("cryptography not installed: pip install cryptography")
        
        self.key_id = key_id
        self.private_key_path = Path(private_key_path)
        self.env = env
        
        # API base URLs (host only, no path - path is added per-request)
        if env == "demo":
            self.base_url = "https://demo-api.kalshi.co"
        elif env == "prod":
            self.base_url = "https://api.kalshi.com"
        else:
            raise ValueError(f"Invalid env: {env}. Must be 'demo' or 'prod'")
        
        self.api_prefix = "/trade-api/v2"
        
        self.private_key: Optional[rsa.RSAPrivateKey] = None
        self.session = requests.Session()
        
        # Load private key
        self._load_private_key()
        
    def _load_private_key(self) -> None:
        """Load RSA private key from PEM file"""
        if not self.private_key_path.exists():
            raise FileNotFoundError(f"Private key not found: {self.private_key_path}")
        
        with open(self.private_key_path, "rb") as f:
            self.private_key = serialization.load_pem_private_key(
                f.read(),
                password=None
            )
        
        logger.info(f"Loaded private key from {self.private_key_path}")
    
    def _sign_pss(self, text: str) -> str:
        """
        Sign text using RSA-PSS with SHA-256
        
        Args:
            text: Text to sign (timestamp + method + path)
        
        Returns:
            Base64-encoded signature
        """
        if self.private_key is None:
            raise RuntimeError("Private key not loaded")
        
        message = text.encode("utf-8")
        
        signature = self.private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH
            ),
            hashes.SHA256()
        )
        
        return base64.b64encode(signature).decode("utf-8")
    
    def _create_auth_headers(self, method: str, full_path: str) -> Dict[str, str]:
        """
        Create authentication headers for Kalshi REST request
        
        Args:
            method: HTTP method (GET, POST, etc.)
            full_path: Full request path including /trade-api/v2 prefix
        
        Returns:
            Headers dict with KALSHI-ACCESS-* fields
        """
        # Timestamp in milliseconds
        timestamp = str(int(time.time() * 1000))
        
        # Strip query string from path for signing
        path_for_signing = full_path.split("?")[0]
        
        # Pre-hash string: timestamp + method + full_path
        # Kalshi requires the FULL path including /trade-api/v2
        msg_string = timestamp + method + path_for_signing
        
        # Sign with RSA-PSS
        signature = self._sign_pss(msg_string)
        
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": signature,
            "KALSHI-ACCESS-TIMESTAMP": timestamp
        }
    
    # Retry configuration
    MAX_RETRIES = 3
    RETRY_BASE_DELAY = 1.0   # seconds
    RETRY_MAX_DELAY = 30.0   # cap backoff
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def _request(
        self,
        method: str,
        path: str,
        json_data: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Make authenticated request to Kalshi API with retry/backoff.
        
        Retries on 429 (rate limit) and transient 5xx errors with
        exponential backoff + jitter. Respects Retry-After header.
        
        Args:
            method: HTTP method
            path: API path (e.g., "/portfolio/balance")
            json_data: Request body (for POST/PUT)
            params: Query parameters
        
        Returns:
            Response JSON
        """
        import random

        full_path = f"{self.api_prefix}{path}"
        url = f"{self.base_url}{full_path}"
        last_exc: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES + 1):
            # Re-sign on every attempt (timestamp changes)
            headers = self._create_auth_headers(method, full_path)

            try:
                response = self.session.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params,
                    timeout=10
                )

                if response.status_code not in self.RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                    return response.json()

                # Retryable error — compute delay
                if attempt >= self.MAX_RETRIES:
                    response.raise_for_status()  # final attempt, raise

                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                else:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)

                delay = min(delay, self.RETRY_MAX_DELAY)
                jitter = random.uniform(0, delay * 0.25)
                wait = delay + jitter

                logger.warning(
                    f"Kalshi API {response.status_code} on {method} {path} "
                    f"(attempt {attempt + 1}/{self.MAX_RETRIES + 1}), "
                    f"retrying in {wait:.1f}s"
                )
                time.sleep(wait)

            except requests.exceptions.HTTPError as e:
                last_exc = e
                if e.response is not None and e.response.status_code in self.RETRYABLE_STATUS_CODES and attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    jitter = random.uniform(0, delay * 0.25)
                    wait = min(delay + jitter, self.RETRY_MAX_DELAY)
                    logger.warning(
                        f"Kalshi API HTTP error {e.response.status_code} on {method} {path} "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES + 1}), "
                        f"retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"HTTP error: {e}")
                if e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                raise
            except requests.exceptions.RequestException as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    jitter = random.uniform(0, delay * 0.25)
                    wait = min(delay + jitter, self.RETRY_MAX_DELAY)
                    logger.warning(
                        f"Kalshi API request error on {method} {path} "
                        f"(attempt {attempt + 1}/{self.MAX_RETRIES + 1}): {e}, "
                        f"retrying in {wait:.1f}s"
                    )
                    time.sleep(wait)
                    continue
                logger.error(f"Request error: {e}")
                raise

        # Should not reach here, but safety net
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Unexpected retry exhaustion on {method} {path}")
    
    def get_balance(self) -> Dict[str, Any]:
        """
        Get portfolio balance
        
        Returns:
            Balance info dict
        """
        return self._request("GET", "/portfolio/balance")
    
    def get_positions(self) -> List[Dict[str, Any]]:
        """
        Get current positions
        
        Returns:
            List of position dicts
        """
        result = self._request("GET", "/portfolio/positions")
        return result.get("positions", [])
    
    def get_orders(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get orders
        
        Args:
            ticker: Filter by market ticker
            status: Filter by status (e.g., "resting", "filled")
        
        Returns:
            List of order dicts
        """
        params = {}
        if ticker:
            params["ticker"] = ticker
        if status:
            params["status"] = status
        
        result = self._request("GET", "/portfolio/orders", params=params)
        return result.get("orders", [])
    
    def create_order(
        self,
        ticker: str,
        side: str,           # "yes" or "no" (contract side)
        action: str,         # "buy" or "sell" (trade action)
        quantity: int,
        price: int,          # Price in cents (1-99)
        client_order_id: str,
        order_type: str = "limit",
        time_in_force: str = "gtc"
    ) -> Dict[str, Any]:
        """
        Create order per Kalshi API spec
        
        Args:
            ticker: Market ticker (e.g., "KXHARRIS24-LSV")
            side: "yes" or "no" (which contract side)
            action: "buy" or "sell" (trade direction)
            quantity: Number of contracts
            price: Price in cents (1-99)
            client_order_id: Unique idempotency key
            order_type: "limit" or "market"
            time_in_force: "gtc", "ioc", "fok"
        
        Returns:
            Order response dict
        """
        order_data: Dict[str, Any] = {
            "ticker": ticker,
            "client_order_id": client_order_id,
            "action": action,
            "side": side,
            "count": quantity,
            "type": order_type,
        }
        
        # Pass time-in-force (gtc, ioc, fok)
        if time_in_force and time_in_force != "gtc":
            order_data["time_in_force"] = time_in_force
        
        # Add price for limit orders (only the relevant side)
        if order_type == "limit":
            if side == "yes":
                order_data["yes_price"] = price
            else:
                order_data["no_price"] = price
        
        logger.info(
            f"Creating order: {action} {quantity}x {ticker} {side} @ {price}¢ "
            f"(tif={time_in_force}, client_order_id={client_order_id})"
        )
        
        result = self._request("POST", "/portfolio/orders", json_data=order_data)
        
        logger.info(f"Order created: {result.get('order', {}).get('order_id')}")
        
        return result
    
    def amend_order(
        self,
        order_id: str,
        price: Optional[int] = None,
        quantity: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Amend a resting order (cancel-replace).
        
        Kalshi supports PATCH on /portfolio/orders/{order_id} to update
        the price and/or quantity of an existing resting order without
        losing queue priority when only qty decreases.
        
        Args:
            order_id: Kalshi order ID to amend
            price: New price in cents (1-99), or None to keep current
            quantity: New contract count, or None to keep current
        
        Returns:
            Amended order response
        """
        patch_data: Dict[str, Any] = {}
        if price is not None:
            patch_data["price"] = price
        if quantity is not None:
            patch_data["count"] = quantity
        
        if not patch_data:
            raise ValueError("amend_order requires at least price or quantity")
        
        logger.info(
            f"Amending order {order_id}: {patch_data}"
        )
        
        return self._request("PATCH", f"/portfolio/orders/{order_id}", json_data=patch_data)
    
    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """
        Cancel order
        
        Args:
            order_id: Kalshi order ID
        
        Returns:
            Cancellation response
        """
        return self._request("DELETE", f"/portfolio/orders/{order_id}")
    
    def batch_cancel_orders(
        self,
        ticker: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cancel multiple orders at once.
        
        If ticker is provided, cancels all resting orders for that market.
        If ticker is None, cancels ALL resting orders across all markets.
        
        Args:
            ticker: Optional market ticker to scope cancellation
        
        Returns:
            Batch cancel response with count of cancelled orders
        """
        params: Dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        
        logger.warning(
            f"Batch cancel orders: ticker={ticker or 'ALL'}"
        )
        
        return self._request("DELETE", "/portfolio/orders", params=params)
    
    def get_market(self, ticker: str) -> Dict[str, Any]:
        """
        Get market info
        
        Args:
            ticker: Market ticker
        
        Returns:
            Market info dict
        """
        return self._request("GET", f"/markets/{ticker}")
    
    def get_orderbook(self, ticker: str, depth: int = 5) -> Dict[str, Any]:
        """
        Get orderbook snapshot (REST, not WS)
        
        Args:
            ticker: Market ticker
            depth: Number of levels per side
        
        Returns:
            Orderbook dict
        """
        params = {"depth": depth}
        return self._request("GET", f"/markets/{ticker}/orderbook", params=params)


# Singleton instance
_rest_client: Optional[KalshiRestClient] = None


def get_rest_client(
    key_id: str,
    private_key_path: str,
    env: str = "demo"
) -> KalshiRestClient:
    """Get singleton REST client instance, recreating if credentials or env changed."""
    global _rest_client

    if (
        _rest_client is None
        or _rest_client.key_id != key_id
        or str(_rest_client.private_key_path) != str(private_key_path)
        or _rest_client.env != env
    ):
        _rest_client = KalshiRestClient(
            key_id=key_id,
            private_key_path=private_key_path,
            env=env,
        )

    return _rest_client
