# MERID End-to-End Implementation Guide

## 🚀 Complete Socket.io JWT Refresh Implementation

### Server Setup (Node.js/Socket.io)
```javascript
// socketServer.js
import { Server } from "socket.io";
import jwt from "jsonwebtoken";

const io = new Server(httpServer, {
  path: "/ws/socket.io",
  transports: ["websocket"],
  cors: {
    origin: ["http://localhost:5173", "https://merid-ui.vercel.app"],
    credentials: true,
  },
});

function verifyAccess(token) {
  return jwt.verify(token, process.env.JWT_SECRET_KEY);
}

io.use((socket, next) => {
  const token = socket.handshake.auth?.token;
  if (!token) return next(new Error("no_token"));

  try {
    const payload = verifyAccess(token);
    socket.user = { id: payload.sub, role: payload.role };
    return next();
  } catch (err) {
    if (err.name === "TokenExpiredError") {
      return next(new Error("jwt_expired"));
    }
    return next(new Error("unauthorized"));
  }
});

io.on("connection", (socket) => {
  console.log("MERID socket connected:", socket.user);

  socket.on("subscribe_prices", (symbols) => {
    // Attach to MERID price stream
    console.log("Subscribing to prices:", symbols);
  });

  socket.on("disconnect", (reason) => {
    console.log("socket disconnect:", reason);
  });
});

export default io;
```

### Client Implementation
```typescript
// Already created: src/hooks/useMeridSocketComplete.ts
import { useMeridSocket } from './hooks/useMeridSocketComplete';

// Usage in component
const { socket, connected } = useMeridSocket();

useEffect(() => {
  if (!socket) return;
  socket.emit("subscribe_prices", ["BTC-USD", "ETH-USD"]);
}, [socket]);
```

---

## 🎨 Chart.js Dark-Mode Plugin

### Plugin Implementation
```typescript
// Already created: src/chartDarkModePlugin.ts
import { registerMeridDarkModePlugin } from './chartDarkModePlugin';

// Register once in app startup
registerMeridDarkModePlugin();

// Charts will automatically adapt to theme changes
```

### Usage Example
```typescript
import { Chart } from "chart.js";
import { registerMeridDarkModePlugin } from './chartDarkModePlugin';

// Register plugin
registerMeridDarkModePlugin();

// Create chart - colors will auto-adjust
const chart = new Chart(ctx, {
  type: "line",
  data: chartData,
  options: {
    // Standard options - plugin handles dark mode
  },
});

// When theme changes, just call update()
chart.update();
```

---

## 🔐 Vercel JWT Secret Rotation

### Automated Rotation Script
```bash
# Already created: rotate-jwt-secret.sh
chmod +x rotate-jwt-secret.sh
./rotate-jwt-secret.sh
```

### Backend Implementation (Python)
```python
# Already created: src/utils/jwtRotation.py
from jwtRotation import sign_access, verify_access, is_rotation_active

# Use in FastAPI endpoints
@app.post("/auth/login")
async def login(credentials: AuthCredentials):
    payload = {"sub": credentials.email, "exp": datetime.utcnow() + timedelta(minutes=15)}
    access_token = sign_access(payload)
    return {"access": access_token, "refresh": create_refresh_token(payload)}
```

### Manual Rotation Steps
1. **Generate new secret**: `openssl rand -base64 48`
2. **Add as JWT_SECRET_KEY_NEXT** in Vercel dashboard
3. **Deploy rotation-aware code** that accepts both keys
4. **Wait for old tokens to expire** (24-48 hours)
5. **Move JWT_SECRET_KEY_NEXT → JWT_SECRET_KEY**
6. **Remove old secret and grace period code**

---

## 🚀 Netlify Deployment Configuration

### Complete netlify.toml
```toml
# Already updated: netlify.toml
[build]
  command = "npm run build"
  publish = "dist"

[build.environment]
  NODE_ENV = "production"
  VITE_API_BASE = "https://api.merid.yourdomain"
  VITE_WS_URL = "wss://api.merid.yourdomain"
```

### Tailwind Configuration
```javascript
// Already created: tailwind.config.cjs
module.exports = {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
```

### Deployment Commands
```bash
# Build and deploy
npm run build
netlify deploy --prod

# Clear cache if needed
# Via Netlify UI: Site settings → Build & deploy → Build cache → Clear cache
```

---

## 🧪 Socket.io Reconnection Testing

### Test Component
```typescript
// Already created: src/components/SocketTest.tsx
import SocketTest from './components/SocketTest';

// Add to your app for testing
<SocketTest />
```

### Test Plan
1. **Short-lived token**: Set access token expiry to 60 seconds in dev
2. **Login normally**: Confirm `connected === true`
3. **Wait for expiry**: Should see `connect_error` with `jwt_expired`
4. **Auto-refresh**: Should see `/auth/refresh` call
5. **Reconnect**: Should automatically reconnect and resume
6. **Price ticks**: Should continue receiving updates

### Expected Console Output
```
MERID socket connected
Subscribed to price updates
MERID socket connect_error: jwt_expired
Attempting JWT refresh...
JWT refresh successful, reconnecting...
MERID socket connected
Price tick received: {symbol: "BTC-USD", price: 42000}
```

---

## 📋 Complete Implementation Checklist

### ✅ Socket.io Implementation
- [ ] Server middleware with JWT verification
- [ ] Client hook with automatic refresh
- [ ] Error handling for expired tokens
- [ ] Reconnection logic with backoff
- [ ] Test component for debugging

### ✅ Chart.js Dark Mode
- [ ] Dark mode plugin registered
- [ ] Charts adapt to theme changes
- [ ] Tailwind color consistency
- [ ] Automatic updates on theme toggle

### ✅ JWT Secret Rotation
- [ ] Rotation script created
- [ ] Backend supports dual keys
- [ ] Vercel environment setup
- [ ] Grace period implementation

### ✅ Netlify Deployment
- [ ] Correct Tailwind configuration
- [ ] Environment variables set
- [ ] Build commands configured
- [ ] Cache clearing procedures

---

## 🚀 Quick Start Commands

### Setup Socket.io
```typescript
// In your main app component
import { useMeridSocket } from './hooks/useMeridSocketComplete';

function App() {
  const { socket, connected } = useMeridSocket();
  
  return (
    <div>
      <div>WebSocket: {connected ? "✅" : "❌"}</div>
      {/* Your app content */}
    </div>
  );
}
```

### Setup Charts
```typescript
// In chart component
import { registerMeridDarkModePlugin } from './chartDarkModePlugin';

registerMeridDarkModePlugin();

// Charts will now auto-adapt to dark mode
```

### Deploy to Netlify
```bash
# Build and deploy
npm run build
netlify deploy --prod

# Test the deployment
curl https://your-app.netlify.app
```

### Rotate JWT Secret
```bash
# Run rotation script
./rotate-jwt-secret.sh

# Deploy rotation-aware code
git add .
git commit -m "add jwt rotation support"
git push
vercel deploy --prod
```

---

## 🔍 Troubleshooting

### Socket.io Issues
- Check token in localStorage: `localStorage.getItem("merid-access")`
- Verify server logs for handshake details
- Confirm WebSocket URL matches environment

### Chart Issues
- Ensure plugin is registered before chart creation
- Check Tailwind theme class on `<html>` element
- Call `chart.update()` after theme changes

### Deployment Issues
- Clear Netlify build cache
- Verify Tailwind `content` paths
- Check environment variables in Netlify UI

This complete end-to-end implementation provides production-ready Socket.io JWT refresh, dark-mode charts, secret rotation, and deployment configuration for the MERID platform.
