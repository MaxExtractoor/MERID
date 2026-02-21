# MERID Socket.io Security Patterns

## JWT Expiry Handling

### Client Pattern
```typescript
import { initSocketWithRefresh } from './hooks/useSocketWithRefresh';

// Initialize socket with automatic refresh
const socket = initSocketWithRefresh();

// Handle logout
import { disconnectSocket } from './hooks/useSocketWithRefresh';
disconnectSocket();
```

### Server Pattern (Node.js - adapt to FastAPI)
```javascript
// JWT middleware for Socket.io
io.use((socket, next) => {
  const token = socket.handshake.auth.token;
  try {
    socket.user = jwt.verify(token, process.env.JWT_SECRET_KEY);
    next();
  } catch (e) {
    if (e.name === "TokenExpiredError") {
      return next(new Error("jwt expired"));
    }
    return next(new Error("unauthorized"));
  }
});
```

---

## Namespace-Based Security

### 1. Separate Namespaces by Trust Level
```javascript
const tradingNs = io.of("/trading");    // High security
const monitorNs = io.of("/monitor");     // Read-only
const publicNs = io.of("/public");       // No auth required
```

### 2. JWT Auth per Namespace
```javascript
function jwtAuth(socket, next) {
  const token = socket.handshake.auth.token;
  if (!token) return next(new Error("no token"));
  
  try {
    socket.user = jwt.verify(token, process.env.JWT_SECRET_KEY);
    next();
  } catch {
    next(new Error("unauthorized"));
  }
}

// Apply to sensitive namespaces
tradingNs.use(jwtAuth);
monitorNs.use(jwtAuth);
// publicNs - no auth required
```

### 3. Role-Based Event Authorization
```javascript
tradingNs.on("connection", socket => {
  const { role, permissions } = socket.user;

  socket.on("place_order", payload => {
    if (role !== "trader" && !permissions.includes("place_orders")) {
      socket.emit("error", { message: "Insufficient permissions" });
      return;
    }
    // Handle order placement
  });

  socket.on("cancel_order", payload => {
    if (role !== "trader" && !permissions.includes("cancel_orders")) {
      socket.emit("error", { message: "Insufficient permissions" });
      return;
    }
    // Handle order cancellation
  });

  socket.on("subscribe_prices", payload => {
    // Read-only - allow most roles
    if (!permissions.includes("view_prices")) {
      socket.emit("error", { message: "Cannot access price data" });
      return;
    }
    // Handle price subscription
  });
});
```

### 4. Disable Default Namespace
```javascript
// Don't expose unauthenticated default namespace
// Only use specific namespaces like /trading, /monitor
```

---

## Rate Limiting & Validation

### Connection Rate Limiting
```javascript
const rateLimit = new Map(); // socket.id -> { count, resetTime }

function checkRateLimit(socket, next) {
  const clientId = socket.handshake.address;
  const now = Date.now();
  const window = 60000; // 1 minute
  const maxConnections = 10;

  if (!rateLimit.has(clientId)) {
    rateLimit.set(clientId, { count: 1, resetTime: now + window });
    return next();
  }

  const client = rateLimit.get(clientId);
  if (now > client.resetTime) {
    rateLimit.set(clientId, { count: 1, resetTime: now + window });
    return next();
  }

  if (client.count >= maxConnections) {
    return next(new Error("rate_limited"));
  }

  client.count++;
  next();
}

io.use(checkRateLimit);
```

### Event Rate Limiting
```javascript
const eventRateLimit = new Map(); // socket.id -> { event: { count, resetTime } }

function checkEventRate(socket, event) {
  const socketId = socket.id;
  const now = Date.now();
  const window = 60000; // 1 minute
  
  if (!eventRateLimit.has(socketId)) {
    eventRateLimit.set(socketId, {});
  }

  const socketLimits = eventRateLimit.get(socketId);
  if (!socketLimits[event]) {
    socketLimits[event] = { count: 1, resetTime: now + window };
    return true;
  }

  const limit = socketLimits[event];
  if (now > limit.resetTime) {
    socketLimits[event] = { count: 1, resetTime: now + window };
    return true;
  }

  const maxEvents = event === "place_order" ? 10 : 100; // Stricter for trading
  if (limit.count >= maxEvents) {
    socket.emit("error", { message: "Rate limit exceeded" });
    return false;
  }

  limit.count++;
  return true;
}
```

### Payload Validation
```javascript
const Joi = require("joi");

const orderSchema = Joi.object({
  symbol: Joi.string().required(),
  side: Joi.string().valid("buy", "sell").required(),
  quantity: Joi.number().positive().required(),
  type: Joi.string().valid("market", "limit").required(),
  price: Joi.when("type", {
    is: "limit",
    then: Joi.number().positive().required(),
    otherwise: Joi.optional()
  })
});

tradingNs.on("place_order", async (payload) => {
  // Validate payload
  const { error, value } = orderSchema.validate(payload);
  if (error) {
    socket.emit("error", { 
      message: "Invalid order format", 
      details: error.details[0].message 
    });
    return;
  }

  // Check rate limit
  if (!checkEventRate(socket, "place_order")) {
    return;
  }

  // Process order
  try {
    const result = await placeOrder(value, socket.user);
    socket.emit("order_placed", result);
  } catch (err) {
    socket.emit("error", { message: "Order failed", details: err.message });
  }
});
```

---

## Client-Side Security

### Secure Socket Initialization
```typescript
import { initSocketWithRefresh } from './hooks/useSocketWithRefresh';

// Only initialize after authentication
function initializeAuthenticatedSocket() {
  const token = localStorage.getItem("access_token");
  if (!token) {
    console.error("No token available");
    return null;
  }

  return initSocketWithRefresh();
}

// Use in components
const socket = initializeAuthenticatedSocket();

if (socket) {
  socket.on("connect_error", (err) => {
    if (err.message === "unauthorized") {
      // Redirect to login
      window.location.href = "/login";
    }
  });
}
```

### Namespace Connection
```typescript
// Connect to specific namespace
import { io } from "socket.io-client";

const tradingSocket = io("/trading", {
  auth: { token: localStorage.getItem("access_token") },
  transports: ["websocket"]
});

const monitorSocket = io("/monitor", {
  auth: { token: localStorage.getItem("access_token") },
  transports: ["websocket"]
});
```

---

## Environment Security

### Vercel Environment Variables
```
# Backend project only (server-side)
JWT_SECRET_KEY=your_jwt_secret_here
REFRESH_TOKEN_SECRET=your_refresh_secret_here
SOCKET_SECRET_KEY=your_socket_secret_here

# Frontend project only (client-side)
VITE_WS_URL=wss://api.merid.com
VITE_API_BASE=https://api.merid.com
```

### FastAPI Implementation
```python
import os
from fastapi import WebSocket, WebSocketDisconnect
import jwt

JWT_SECRET = os.getenv("JWT_SECRET_KEY")

async def verify_websocket_token(websocket: WebSocket):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="No token provided")
        return None
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        await websocket.close(code=4001, reason="Token expired")
        return None
    except jwt.InvalidTokenError:
        await websocket.close(code=4001, reason="Invalid token")
        return None
```

---

## Security Checklist

### ✅ Implementation Checklist
- [ ] JWT middleware on all sensitive namespaces
- [ ] Role-based event authorization
- [ ] Connection rate limiting
- [ ] Event rate limiting
- [ ] Payload validation with schemas
- [ ] Automatic token refresh on expiry
- [ ] Secure token storage (HTTP-only cookies preferred)
- [ ] HTTPS/WSS in production
- [ ] Proper error messages (don't leak internals)

### ✅ Deployment Checklist
- [ ] JWT secrets in server environment only
- [ ] No VITE_/NEXT_PUBLIC_ prefixes on secrets
- [ ] Separate frontend/backend projects on Vercel
- [ ] CORS properly configured
- [ ] Rate limits appropriate for production load
- [ ] Monitoring for connection abuse

### 🚨 Security Red Flags
- [ ] Default namespace exposed without auth
- [ ] JWT secrets in frontend bundle
- [ ] No rate limiting on trading events
- [ ] Missing payload validation
- [ ] HTTP connections in production
- [ ] Verbose error messages to clients

This provides enterprise-grade Socket.io security for MERID's real-time trading features.
