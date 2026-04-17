# MERID Security Checklist

## ✅ Secure API Key Management

### Frontend (React) - SAFE
```typescript
// ✅ Safe: Only non-sensitive config
const API_BASE = import.meta.env.VITE_API_BASE; // https://api.merid.com
const WS_URL = import.meta.env.VITE_WS_URL;     // wss://api.merid.com
const ENV_LABEL = import.meta.env.VITE_ENV_LABEL; // PROD

// ✅ Safe: Talk to backend only
fetch(`${API_BASE}/api/v1/portfolio/summary`, {
  credentials: "include", // HTTP-only cookies
});
```

### Backend (FastAPI) - SAFE
```python
# ✅ Safe: Sensitive keys in server environment
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
BINANCE_API_SECRET = os.getenv("BINANCE_API_SECRET")
JWT_SECRET = os.getenv("JWT_SECRET")

# ✅ Safe: Backend calls brokers
alpaca = Alpaca(key_id=ALPACA_API_KEY, secret_key=ALPACA_API_SECRET)
```

### 🚫 NEVER DO THIS
```typescript
// 🚫 DANGEROUS: Never expose trading keys to frontend
const ALPACA_KEY = import.meta.env.VITE_ALPACA_API_KEY; // BAD!

// 🚫 DANGEROUS: Never call brokers from browser
fetch('https://api.alpaca.markets/v2/positions', {
  headers: { 'APCA-API-KEY-ID': ALPACA_KEY } // BAD!
});
```

---

## ✅ Deployment Security

### Vercel Environment Variables
```
# Frontend Project (Safe)
VITE_API_BASE=https://api.merid.com
VITE_WS_URL=wss://api.merid.com
VITE_ENV_LABEL=PROD

# Backend Project (Sensitive - Protected)
ALPACA_API_KEY=your_actual_key_here
BINANCE_API_SECRET=your_actual_secret_here
JWT_SECRET=your_jwt_secret_here
```

### Netlify Environment Variables
```toml
# netlify.toml
[build.environment]
  VITE_API_BASE = "https://api.merid.com"
  VITE_WS_URL = "wss://api.merid.com"
```

---

## ✅ Authentication Patterns

### HTTP-Only Cookies (Recommended)
```typescript
// Frontend
fetch('/api/v1/portfolio/summary', {
  credentials: "include", // Sends HTTP-only cookies
});

// Backend
@app.post("/auth/login")
def login():
    response.set_cookie(
        "merid_token", 
        token, 
        httponly=True, 
        secure=True, 
        samesite="strict"
    )
```

### JWT in localStorage (Alternative)
```typescript
// Frontend
const token = localStorage.getItem("merid-token");
fetch('/api/v1/portfolio/summary', {
  headers: { 'Authorization': `Bearer ${token}` }
});

// Socket.io
const socket = io(WS_URL, {
  auth: { token } // Sent in handshake
});
```

---

## ✅ WebSocket Security

### HTTP-Only Cookie Auth
```typescript
// ✅ Safe: Cookies sent automatically
const socket = io(WS_URL, {
  withCredentials: true, // Sends HTTP-only cookies
  transports: ["websocket"]
});
```

### JWT Token Auth
```typescript
// ✅ Safe: Token sent in auth
const token = localStorage.getItem("merid-token");
const socket = io(WS_URL, {
  auth: { token },
  transports: ["websocket"]
});
```

### Server Validation
```python
# ✅ Validate on every connection
@sio.event
async def connect(sid, environ, auth):
    # From cookies
    cookies = environ.get("HTTP_COOKIE", "")
    token = parse_jwt_from_cookies(cookies)
    
    # Or from auth
    token = auth.get("token") if auth else None
    
    user = verify_jwt(token)
    if not user:
        raise ConnectionRefusedError("unauthorized")
```

---

## ✅ CORS Security

### FastAPI CORS Config
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://merid.com", "https://app.merid.com"],
    allow_credentials=True,  # For cookies
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

---

## ✅ Environment Security

### Production Checklist
- [ ] All API keys in backend environment variables
- [ ] No trading keys in frontend bundle
- [ ] HTTPS/WSS URLs in production
- [ ] HTTP-only cookies for auth
- [ ] Secure cookie flags set
- [ ] CORS properly configured
- [ ] Environment variables marked as "Sensitive" on Vercel
- [ ] No `.env` files committed to git

### Development Checklist
- [ ] Use `.env.example` for template
- [ ] `.env` in `.gitignore`
- [ ] Different keys for dev/prod
- [ ] Local testing with production-like security

---

## 🚨 Red Flags to Watch For

### In Frontend Code
```typescript
// 🚨 RED FLAG: API keys in frontend
const API_KEY = process.env.ALPACA_API_KEY;

// 🚨 RED FLAG: Direct broker calls
fetch('https://api.alpaca.markets/...');

// 🚨 RED FLAG: Secrets in build
console.log('API Key:', import.meta.env.SECRET_KEY);
```

### In Environment
```bash
# 🚨 RED FLAG: Trading keys with VITE_ prefix
VITE_ALPACA_API_KEY=sk_...  # BAD!

# 🚨 RED FLAG: Secrets in public repos
.env files committed to git
```

### In Bundle
```javascript
// 🚨 RED FLAG: Check built bundle for secrets
grep -r "sk_" dist/
grep -r "secret" dist/
```

---

## ✅ Best Practices Summary

### Do ✅
- Keep all trading keys on backend
- Use HTTP-only cookies for auth
- Mark sensitive env vars as "Protected"
- Use HTTPS/WSS in production
- Validate tokens on every request
- Implement proper CORS
- Use different keys per environment

### Don't 🚫
- Expose API keys to frontend
- Store secrets in localStorage
- Commit `.env` files
- Use HTTP in production
- Skip token validation
- Allow wildcard CORS
- Share keys across environments

---

## 🔒 Quick Security Test

### Test Frontend Bundle
```bash
# Check for exposed secrets
npm run build
grep -i "sk_\|secret\|key\|token" dist/
```

### Test Environment
```bash
# Verify no sensitive env vars in frontend
curl https://your-app.vercel.app | grep -i "sk_\|secret"
```

### Test WebSocket
```bash
# Test connection without auth
wscat -c wss://your-api.com/ws/socket.io
# Should fail without proper auth
```

---

This checklist ensures MERID maintains enterprise-grade security across all deployments.
