# Vercel Environment Variables Setup for MERID

## 🔒 JWT Secrets - Server Side Only

### Backend Project (FastAPI/MERID Core)
In Vercel → Project → Settings → Environment Variables:

```
JWT_SECRET_KEY=your_super_secret_jwt_key_here_32_chars_min
REFRESH_TOKEN_SECRET=your_refresh_token_secret_here
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_API_SECRET=your_alpaca_api_secret
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
DATABASE_URL=your_database_connection_string
REDIS_URL=your_redis_connection_string
```

**Important:**
- ✅ Mark these as **"Sensitive"** variables
- ❌ **DO NOT** prefix with `VITE_` or `NEXT_PUBLIC_`
- ✅ Only accessible in server-side code

### Usage in FastAPI
```python
import os

JWT_SECRET = os.getenv("JWT_SECRET_KEY")
REFRESH_SECRET = os.getenv("REFRESH_TOKEN_SECRET")
ALPACA_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET = os.getenv("ALPACA_API_SECRET")

# Use in JWT signing
jwt.encode(payload, JWT_SECRET, algorithm="HS256")

# Use in API calls
alpaca = Alpaca(key_id=ALPACA_KEY, secret_key=ALPACA_SECRET)
```

---

## 🌐 Frontend Variables - Client Side

### Frontend Project (React Dashboard)
In Vercel → Project → Settings → Environment Variables:

```
VITE_API_BASE=https://api.merid.com
VITE_WS_URL=wss://api.merid.com
VITE_ENV_LABEL=PROD
VITE_SENTRY_DSN=your_sentry_dsn_for_error_tracking
```

**Important:**
- ✅ **MUST** prefix with `VITE_` for Vite
- ✅ Safe to expose (non-sensitive config only)
- ❌ Never put API keys or secrets here

### Usage in React
```typescript
const API_BASE = import.meta.env.VITE_API_BASE;
const WS_URL = import.meta.env.VITE_WS_URL;
const ENV_LABEL = import.meta.env.VITE_ENV_LABEL;

// API calls
fetch(`${API_BASE}/api/v1/portfolio/summary`);

// WebSocket connections
const socket = io(WS_URL, {
  auth: { token: localStorage.getItem("access_token") }
});
```

---

## 🔧 Environment-Specific Setup

### Development Environment
Create `.env.local` (never commit):
```bash
# .env.local
VITE_API_BASE=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_ENV_LABEL=DEV
```

### Production Environment
Set in Vercel dashboard:
```
VITE_API_BASE=https://api.merid.com
VITE_WS_URL=wss://api.merid.com
VITE_ENV_LABEL=PROD
```

### Staging Environment
Set in Vercel dashboard:
```
VITE_API_BASE=https://staging-api.merid.com
VITE_WS_URL=wss://staging-api.merid.com
VITE_ENV_LABEL=STAGING
```

---

## 🚀 Deployment Workflow

### 1. Backend Deployment
```bash
# Deploy FastAPI backend
vercel --prod

# Verify environment variables
vercel env ls
```

### 2. Frontend Deployment
```bash
# Deploy React frontend
vercel --prod

# Verify frontend can reach backend
curl https://your-frontend.vercel.app/api/v1/health
```

### 3. Cross-Origin Setup
Backend CORS configuration:
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://merid.vercel.app",
        "https://staging-merid.vercel.app",
        "http://localhost:3000"  # Development
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

---

## 🔍 Verification Checklist

### Backend Verification
```bash
# Test JWT signing
curl -X POST https://api.merid.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password"}'

# Should return JWT token
# Verify token is signed with correct secret
```

### Frontend Verification
```bash
# Check environment variables in browser console
console.log(import.meta.env.VITE_API_BASE);
console.log(import.meta.env.VITE_WS_URL);

# Should show production URLs
```

### Security Verification
```bash
# Check no secrets in frontend bundle
grep -r "sk_" dist/
grep -r "secret" dist/
grep -r "JWT_SECRET" dist/

# Should return nothing
```

---

## 🚨 Common Mistakes

### ❌ Don't Do This
```bash
# WRONG: Exposing secrets to frontend
VITE_ALPACA_API_KEY=sk_...  # BAD!
VITE_JWT_SECRET=secret123   # BAD!

# WRONG: Using wrong prefix
API_BASE=https://api.merid.com  # Won't work in Vite
NEXT_PUBLIC_API_BASE=https://...  # Wrong for Vite
```

### ✅ Do This Instead
```bash
# CORRECT: Frontend config only
VITE_API_BASE=https://api.merid.com

# CORRECT: Backend secrets (no VITE_ prefix)
ALPACA_API_KEY=sk_...  # Server-side only
JWT_SECRET=super_secret  # Server-side only
```

---

## 🔄 Environment Variable Access Patterns

### Frontend (React)
```typescript
// ✅ Safe - exposed to browser
const API_BASE = import.meta.env.VITE_API_BASE;

// ❌ Undefined - not accessible
const SECRET = import.meta.env.JWT_SECRET;  // undefined
```

### Backend (FastAPI)
```python
# ✅ Safe - server-side only
JWT_SECRET = os.getenv("JWT_SECRET")

# ❌ Not needed - frontend variables
API_BASE = os.getenv("VITE_API_BASE")  # Don't use in backend
```

---

## 📋 Quick Setup Commands

### Backend Setup
```bash
# Set JWT secret
vercel env add JWT_SECRET_KEY

# Set API keys
vercel env add ALPACA_API_KEY
vercel env add ALPACA_API_SECRET

# Verify
vercel env ls
```

### Frontend Setup
```bash
# Set API base URL
vercel env add VITE_API_BASE

# Set WebSocket URL
vercel env add VITE_WS_URL

# Verify
vercel env ls
```

### Deploy Both
```bash
# Deploy backend
cd backend && vercel --prod

# Deploy frontend
cd frontend && vercel --prod

# Test integration
curl https://frontend.vercel.app/api/v1/health
```

---

## 🔐 Security Best Practices

### ✅ Do
- Mark sensitive variables as "Sensitive" in Vercel
- Use different keys per environment
- Rotate secrets regularly
- Use HTTPS/WSS URLs in production
- Implement proper CORS

### ❌ Don't
- Commit `.env` files to git
- Use `VITE_` prefix for secrets
- Share keys across environments
- Use HTTP in production
- Skip CORS configuration

---

This setup ensures MERID maintains proper security separation between frontend and backend while providing all necessary configuration for production deployment.
