# Kalshi API Audit - Pass 3.1: WS Handshake and Auth

**Objective:** Compare WS connection code to Kalshi docs for URL, headers, and signature requirements.

**Kalshi Reference:** 
- [docs.kalshi.com/quick_start_websockets](https://docs.kalshi.com/getting_started/quick_start_websockets)
- [quantvps.com/kalshi-order-book-api-endpoints](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained)

---

## Current State Analysis

### 1. WebSocket URL

#### Kalshi Documented URLs

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Live:** `wss://api.elections.kalshi.com/trade-api/ws/v2`
- **Demo:** `wss://demo-api.kalshi.co/trade-api/ws/v2`

---

#### Current Implementation: `ws.py` - Connection

```python
# Config
self.config.ws_url  # Set from environment or config

# Connection
self._ws = await websockets.connect(
    self.config.ws_url,
    extra_headers=headers,
    ping_interval=20,
    ping_timeout=60,
    close_timeout=5,
)
```

**URL Source:** Configured via `KALSHI_WS_URL` or derived from `KALSHI_API_BASE_URL`

**Status:** ✅ Supports both live and demo URLs via configuration

**Issues:**
- ⚠️ **No validation:** Doesn't validate URL format or protocol
- ⚠️ **No default:** Requires explicit configuration

---

### 2. Authentication Headers

#### Kalshi Documented Headers

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- `KALSHI-ACCESS-KEY` - API key ID
- `KALSHI-ACCESS-SIGNATURE` - RSA-PSS SHA256 signature
- `KALSHI-ACCESS-TIMESTAMP` - Timestamp in milliseconds

---

#### Current Implementation: `ws.py` - Auth Headers

```python
# Create signature
timestamp = str(int(time.time() * 1000) + 5000)
method = "GET"
path = "/trade-api/ws/v2"
msg_string = timestamp + method + path

signature = private_key.sign(
    msg_string.encode("utf-8"),
    padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.DIGEST_LENGTH
    ),
    hashes.SHA256()
)

# Create headers
headers = {
    "Content-Type": "application/json",
    "KALSHI-ACCESS-KEY": self.config.api_key,
    "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
    "KALSHI-ACCESS-TIMESTAMP": timestamp
}
```

**Headers Used:**
- ✅ `KALSHI-ACCESS-KEY` - Correct
- ✅ `KALSHI-ACCESS-SIGNATURE` - Correct
- ✅ `KALSHI-ACCESS-TIMESTAMP` - Correct
- ⚠️ `Content-Type` - Extra header (not documented for WS)

**Status:** ✅ Matches documented headers (plus extra Content-Type)

**Issues:**
- ⚠️ **Extra header:** `Content-Type` not documented for WS (may be harmless)
- ⚠️ **Timestamp buffer:** Adds 5000ms buffer (not documented, may cause issues)

---

### 3. Signature Algorithm

#### Kalshi Documented Signature

From [quantvps.com](https://www.quantvps.com/blog/kalshi-order-book-api-endpoints-explained):
- **Algorithm:** RSA-PSS with SHA256
- **Message format:** `timestamp + GET + path`
- **Timestamp:** Current time in milliseconds

---

#### Current Implementation: `ws.py` - Signature

```python
# Signature algorithm
signature = private_key.sign(
    msg_string.encode("utf-8"),
    padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.DIGEST_LENGTH
    ),
    hashes.SHA256()
)
```

**Algorithm:**
- ✅ RSA-PSS - Correct
- ✅ SHA256 hash - Correct
- ✅ MGF1 with SHA256 - Correct
- ✅ DIGEST_LENGTH salt - Correct

**Message Format:**
```python
timestamp = str(int(time.time() * 1000) + 5000)  # +5000ms buffer
method = "GET"
path = "/trade-api/ws/v2"
msg_string = timestamp + method + path
```

**Status:** ✅ Algorithm matches documented requirements

**Issues:**
- ⚠️ **Timestamp buffer:** Adds 5000ms buffer to prevent "header timestamp expired" errors
- ⚠️ **Not documented:** Buffer is a workaround, not documented by Kalshi

**Root Cause:** Clock skew or network latency causing timestamp validation failures

**Required Fix:**
1. Verify if buffer is actually needed (test without it)
2. If needed, document as Kalshi implementation quirk
3. If not needed, remove buffer

---

### 4. REST API Signature (for comparison)

#### Current Implementation: `client.py` - `_sign_headers()`

```python
def _sign_headers(self, method: str, path: str) -> Dict[str, str]:
    """Generate RSA authentication headers for Kalshi API v2."""
    # Timestamp in milliseconds
    ts_ms = str(int(time.time() * 1000) + 5000)
    message = ts_ms + method.upper() + path
    signature = self._private_key.sign(
        message.encode(),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "KALSHI-ACCESS-KEY": self.config.api_key,
        "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
        "Content-Type": "application/json",
    }
```

**Comparison with WS:**
- ✅ Same algorithm (RSA-PSS SHA256)
- ✅ Same message format (timestamp + method + path)
- ✅ Same timestamp buffer (+5000ms)
- ✅ Same headers

**Status:** ✅ Consistent between WS and REST

---

### 5. Connection Parameters

#### Current Implementation: `ws.py` - Connection

```python
self._ws = await websockets.connect(
    self.config.ws_url,
    extra_headers=headers,
    ping_interval=20,
    ping_timeout=60,
    close_timeout=5,
)
```

**Parameters:**
- `ping_interval=20` - Send ping every 20 seconds
- `ping_timeout=60` - Wait 60 seconds for pong response
- `close_timeout=5` - Wait 5 seconds for close handshake

**Status:** ⚠️ Not documented by Kalshi

**Issues:**
- ⚠️ **No documentation:** Kalshi doesn't specify ping/pong requirements
- ⚠️ **Custom values:** May not match Kalshi's expectations

**Risk:** If Kalshi has different ping/pong expectations, connection may be dropped

---

### 6. Error Handling

#### Current Implementation: `ws.py` - Connection

```python
try:
    self._ws = await websockets.connect(...)
    self._running = True
    logger.info("Connected to Kalshi WebSocket with authentication headers")
except websockets.exceptions.InvalidStatusCode as e:
    logger.error(f"Kalshi WebSocket auth failed: HTTP {e.status_code}")
except Exception as e:
    logger.error(f"Kalshi WebSocket connection failed: {e}")
```

**Status:** ✅ Basic error handling

**Issues:**
- ⚠️ **Limited error info:** Doesn't log full error details
- ⚠️ **No retry logic:** Immediate failure on auth error
- ⚠️ **No specific handling:** Doesn't differentiate between auth errors and network errors

---

## Required Fixes

### Fix 1: Remove Timestamp Buffer (Test First)

**File:** `ws.py` and `client.py`

**Current:**
```python
timestamp = str(int(time.time() * 1000) + 5000)
```

**Proposed:**
```python
timestamp = str(int(time.time() * 1000))
```

**Implementation:**
1. Test connection without buffer in dev environment
2. If connection succeeds, remove buffer
3. If connection fails, document as required workaround
4. Add configuration option to enable/disable buffer

---

### Fix 2: Remove Extra Content-Type Header

**File:** `ws.py`

**Current:**
```python
headers = {
    "Content-Type": "application/json",
    "KALSHI-ACCESS-KEY": self.config.api_key,
    ...
}
```

**Proposed:**
```python
headers = {
    "KALSHI-ACCESS-KEY": self.config.api_key,
    "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
    "KALSHI-ACCESS-TIMESTAMP": timestamp
}
```

**Implementation:**
1. Remove Content-Type header from WS connection
2. Test connection without it
3. Keep in REST API (where it's needed)

---

### Fix 3: Add URL Validation

**File:** `ws.py` - `connect()`

**Add validation:**
```python
def _validate_ws_url(self, url: str) -> None:
    """Validate WebSocket URL format."""
    if not url.startswith("wss://"):
        raise ValueError(f"WebSocket URL must use wss:// protocol, got: {url}")
    
    if "trade-api/ws/v2" not in url:
        logger.warning(
            f"WebSocket URL may be incorrect: {url}. "
            "Expected path: /trade-api/ws/v2"
        )
```

**Implementation:**
1. Add validation method
2. Call before connection
3. Fail fast on invalid URL

---

### Fix 4: Improve Error Handling

**File:** `ws.py` - `connect()`

**Add specific handling:**
```python
try:
    self._ws = await websockets.connect(...)
    self._running = True
    logger.info("Connected to Kalshi WebSocket with authentication headers")
except websockets.exceptions.InvalidStatusCode as e:
    if e.status_code == 401:
        logger.error(
            "[WS-AUTH-FAILED] Authentication failed. Check API key and private key. "
            f"Status: {e.status_code}"
        )
    elif e.status_code == 403:
        logger.error(
            "[WS-AUTH-FORBIDDEN] Access forbidden. Check API permissions. "
            f"Status: {e.status_code}"
        )
    else:
        logger.error(f"[WS-CONNECTION-FAILED] HTTP {e.status_code}: {e}")
    raise
except ConnectionError as e:
    logger.error(f"[WS-NETWORK-ERROR] Network connection failed: {e}")
    raise
except Exception as e:
    logger.error(f"[WS-UNKNOWN-ERROR] Unexpected error: {e}", exc_info=True)
    raise
```

**Implementation:**
1. Add specific error handling for auth failures
2. Add network error handling
3. Log full error details
4. Preserve original exception

---

### Fix 5: Document Ping/Pong Parameters

**File:** `ws.py` - `connect()`

**Add documentation:**
```python
# Ping/pong parameters (not documented by Kalshi, empirically determined)
# ping_interval=20: Send ping every 20 seconds to keep connection alive
# ping_timeout=60: Wait 60 seconds for pong response before closing
# close_timeout=5: Wait 5 seconds for close handshake
# These values may need adjustment based on Kalshi's actual requirements
```

**Implementation:**
1. Add inline documentation
2. Document how values were determined
3. Note that these are not documented by Kalshi

---

## Audit Checklist

- [ ] Document WS URL requirements (✅ documented)
- [ ] Document auth headers (✅ documented)
- [ ] Document signature algorithm (✅ documented)
- [ ] Identify timestamp buffer issue (⚠️ +5000ms buffer)
- [ ] Identify extra header issue (⚠️ Content-Type)
- [ ] Identify missing URL validation (⚠️ no validation)
- [ ] Identify limited error handling (⚠️ basic only)
- [ ] Identify undocumented ping/pong (⚠️ custom values)
- [ ] Plan migration path (5 fixes)
- [ ] Test timestamp buffer removal
- [ ] Remove extra Content-Type header
- [ ] Add URL validation
- [ ] Improve error handling
- [ ] Document ping/pong parameters

---

## Next Steps

1. **Immediate:** Test connection without timestamp buffer in dev
2. **Immediate:** Test connection without Content-Type header
3. **Short-term:** Add URL validation
4. **Short-term:** Improve error handling
5. **Medium-term:** Document ping/pong parameters
6. **Medium-term:** Add configuration for buffer toggle
7. **Long-term:** Verify all parameters with Kalshi support

**Priority:** MEDIUM - Auth is working but has undocumented workarounds

**Risk:** Timestamp buffer may cause issues if Kalshi tightens validation. Extra header is likely harmless but should be removed for cleanliness.

**Note:** Signature algorithm matches documented requirements exactly. The main issues are workarounds (timestamp buffer) and missing validation.
