# MERID Socket.io Auth Debugging Guide

## 🔍 Debug Server-Side Handshake

### Enable Debug Logging
```javascript
// Add to your Socket.io setup
io.use((socket, next) => {
  console.log("=== Socket Handshake Debug ===");
  console.log("handshake auth:", socket.handshake.auth);
  console.log("handshake headers:", socket.handshake.headers);
  console.log("socket id:", socket.id);
  console.log("client IP:", socket.handshake.address);
  
  const token = socket.handshake.auth?.token;
  if (!token) {
    console.log("❌ No token in handshake");
    return next(new Error("no_token"));
  }

  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET_KEY);
    socket.user = payload;
    console.log("✅ JWT verified for user:", payload.sub);
    console.log("Token expires at:", new Date(payload.exp * 1000));
    return next();
  } catch (err) {
    console.log("❌ JWT verification failed:", err.message);
    console.log("Error type:", err.name);
    
    if (err.name === "TokenExpiredError") {
      console.log("Token expired at:", new Date(err.expiredAt * 1000));
      return next(new Error("jwt_expired"));
    }
    return next(new Error("unauthorized"));
  }
});
```

### FastAPI Python Version
```python
import jwt
import os
from datetime import datetime

@sio.event
async def connect(sid, environ, auth):
    print("=== Socket Handshake Debug ===")
    print(f"sid: {sid}")
    print(f"auth: {auth}")
    print(f"headers: {dict(environ)}")
    
    token = auth.get('token') if auth else None
    if not token:
        print("❌ No token in handshake")
        raise ConnectionRefusedError("no_token")
    
    try:
        payload = jwt.decode(token, os.getenv("JWT_SECRET_KEY"), algorithms=["HS256"])
        print(f"✅ JWT verified for user: {payload.get('sub')}")
        print(f"Token expires at: {datetime.fromtimestamp(payload.get('exp'))}")
        return True
    except jwt.ExpiredSignatureError as e:
        print(f"❌ Token expired: {e}")
        raise ConnectionRefusedError("jwt_expired")
    except jwt.InvalidTokenError as e:
        print(f"❌ Invalid token: {e}")
        raise ConnectionRefusedError("unauthorized")
```

---

## 🔍 Debug Client-Side Connection

### Enhanced Error Logging
```typescript
import { createDebugSocket } from './hooks/useSocketClient';

// Use debug socket for troubleshooting
const socket = createDebugSocket();

// Additional debugging
socket.io.on("reconnect_attempt", (attemptNumber) => {
  console.log("Reconnection attempt:", attemptNumber);
});

socket.io.on("reconnect", (attemptNumber) => {
  console.log("Reconnected after", attemptNumber, "attempts");
});

socket.io.on("reconnect_error", (error) => {
  console.log("Reconnection error:", error);
});
```

### Verify Token Before Connection
```typescript
function debugSocketConnection() {
  const token = localStorage.getItem("access_token");
  
  console.log("=== Socket Connection Debug ===");
  console.log("WebSocket URL:", import.meta.env.VITE_WS_URL);
  console.log("Token exists:", !!token);
  console.log("Token length:", token?.length || 0);
  console.log("Token prefix:", token?.substring(0, 20) + "...");
  
  if (!token) {
    console.error("❌ No token available - redirect to login");
    window.location.href = "/login";
    return null;
  }
  
  // Decode token to check expiry
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    const expiresAt = new Date(payload.exp * 1000);
    const isExpired = expiresAt < new Date();
    
    console.log("Token payload:", payload);
    console.log("Token expires at:", expiresAt);
    console.log("Token is expired:", isExpired);
    
    if (isExpired) {
      console.error("❌ Token expired before connection");
      return null;
    }
  } catch (decodeError) {
    console.error("❌ Cannot decode token:", decodeError);
    return null;
  }
  
  return createDebugSocket();
}
```

---

## 🚨 Common Issues & Solutions

### Issue 1: "no_token" Error
**Symptoms:** Server logs "No token in handshake"

**Causes:**
- Client not sending token in `auth.token`
- Token not found in localStorage
- Wrong token key in auth object

**Solutions:**
```typescript
// ✅ Correct auth format
const socket = io(WS_URL, {
  auth: { token: localStorage.getItem("access_token") },
});

// ❌ Wrong auth format
const socket = io(WS_URL, {
  auth: { accessToken: localStorage.getItem("access_token") }, // Wrong key
});
```

### Issue 2: "jwt_expired" Error
**Symptoms:** Server logs "Token expired"

**Causes:**
- Token actually expired
- Clock sync issues
- Token refresh not working

**Solutions:**
```typescript
// Check token expiry before connection
function isTokenExpired(token: string): boolean {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    return Date.now() >= payload.exp * 1000;
  } catch {
    return true; // Invalid token
  }
}

// Auto-refresh if expired
if (isTokenExpired(token)) {
  await refreshToken();
  token = localStorage.getItem("access_token");
}
```

### Issue 3: CORS/Credentials Issues
**Symptoms:** Connection fails, no handshake logs

**Causes:**
- CORS not configured for WebSocket
- Credentials not allowed
- Wrong protocol (HTTP vs HTTPS)

**Solutions:**
```javascript
// FastAPI CORS setup
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend.vercel.app"],
    allow_credentials=True,  # Critical for cookies/auth
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

// Client must use correct protocol
const WS_URL = import.meta.env.VITE_WS_URL; // wss:// for prod, ws:// for dev
```

### Issue 4: Environment Variable Issues
**Symptoms:** JWT verification fails with "invalid signature"

**Causes:**
- Wrong JWT secret in environment
- Secret not loaded correctly
- Multiple secrets with different values

**Solutions:**
```bash
# Debug environment variables
vercel env ls JWT_SECRET_KEY

# Verify secret is loaded
console.log("JWT_SECRET_KEY exists:", !!process.env.JWT_SECRET_KEY);
console.log("JWT_SECRET_KEY length:", process.env.JWT_SECRET_KEY?.length);
```

---

## 🔧 Minimal Working Example

### Server (Node.js)
```javascript
import { createServer } from "http";
import { Server } from "socket.io";
import jwt from "jsonwebtoken";

const httpServer = createServer();
const io = new Server(httpServer, {
  path: "/ws/socket.io",
  cors: {
    origin: "http://localhost:3000",
    credentials: true,
  },
});

io.use((socket, next) => {
  const token = socket.handshake.auth?.token;
  if (!token) return next(new Error("no_token"));
  
  try {
    const payload = jwt.verify(token, process.env.JWT_SECRET_KEY);
    socket.user = payload;
    next();
  } catch (err) {
    if (err.name === "TokenExpiredError") {
      return next(new Error("jwt_expired"));
    }
    return next(new Error("unauthorized"));
  }
});

io.on("connection", (socket) => {
  console.log(`User ${socket.user.sub} connected`);
  socket.emit("welcome", { user: socket.user });
});

httpServer.listen(8000);
```

### Client (React)
```typescript
import { io } from "socket.io-client";

const socket = io("http://localhost:8000", {
  path: "/ws/socket.io",
  auth: { token: localStorage.getItem("access_token") },
  withCredentials: true,
});

socket.on("connect_error", async (err) => {
  console.error("Connection error:", err.message);
  
  if (err.message === "jwt_expired") {
    const res = await fetch("/auth/refresh", {
      method: "POST",
      credentials: "include",
    });
    
    if (res.ok) {
      const data = await res.json();
      localStorage.setItem("access_token", data.access);
      socket.auth = { token: data.access };
      socket.connect();
    }
  }
});

socket.on("welcome", (data) => {
  console.log("Welcome message:", data);
});
```

---

## 📋 Debugging Checklist

### Server-Side
- [ ] JWT_SECRET_KEY environment variable set
- [ ] CORS configured with credentials: true
- [ ] WebSocket path matches client (`/ws/socket.io`)
- [ ] Token verification logic working
- [ ] Debug logging enabled

### Client-Side
- [ ] Token exists in localStorage
- [ ] Token not expired
- [ ] Correct WebSocket URL (ws:// vs wss://)
- [ ] Auth format correct (`{ token }`)
- [ ] Error handlers attached

### Network
- [ ] Firewall allows WebSocket connections
- [ ] DNS resolves correctly
- [ ] SSL certificates valid (for WSS)
- [ ] Load balancer supports WebSocket

### Environment
- [ ] Development vs production URLs
- [ ] Environment variables loaded correctly
- [ ] Same origin policy satisfied
- [ ] Credentials included in requests

---

## 🚀 Quick Debug Commands

### Test Token Generation
```bash
# Generate test token
node -e "
const jwt = require('jsonwebtoken');
const token = jwt.sign(
  {sub: 'test-user', exp: Math.floor(Date.now()/1000) + 3600}, 
  process.env.JWT_SECRET_KEY
);
console.log('Test token:', token);
"
```

### Test WebSocket Connection
```bash
# Using wscat
npm install -g wscat
wscat -c "ws://localhost:8000/ws/socket.io?token=YOUR_TOKEN"

# Using curl (HTTP upgrade)
curl -i -N \
  -H "Connection: Upgrade" \
  -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Key: test" \
  -H "Sec-WebSocket-Version: 13" \
  http://localhost:8000/ws/socket.io
```

### Verify Environment
```bash
# Check Vercel env vars
vercel env ls

# Check local env
echo $JWT_SECRET_KEY
```

This guide should help you quickly identify and resolve any Socket.io authentication issues in the MERID platform.
