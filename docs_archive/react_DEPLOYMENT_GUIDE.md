# MERID React Deployment Guide

## Vercel Deployment (Step-by-Step)

### 1. Local Build Test
```bash
npm run build
```

### 2. Push to GitHub
- Only source code + config files
- No `dist/` folder

### 3. Vercel Setup
- "Add New Project" → Import GitHub repo
- Framework preset: **Vite** or **Create React App**
- Build command: `npm run build`
- Output directory:
  - Vite: `dist`
  - CRA: `build`

### 4. Environment Variables
In Vercel → Project → Settings → Environment Variables:
```
VITE_API_BASE=https://api.merid.yourdomain
VITE_WS_URL=wss://api.merid.yourdomain
VITE_ENV_LABEL=PROD
```

### 5. Usage in Code
```ts
const API_BASE = import.meta.env.VITE_API_BASE;
fetch(`${API_BASE}/api/v1/portfolio/summary`);
```

### 6. Troubleshooting
- If only raw HTML shows: Tailwind/PostCSS not running
- Check `postcss.config.cjs` and `tailwind.config.cjs` paths
- Verify `content` includes `./src/**/*.{js,jsx,ts,tsx}`

---

## Netlify Deployment

### Vite Configuration
```toml
# netlify.toml
[build]
  command = "npm run build"
  publish = "dist"

[build.environment]
  VITE_API_BASE = "https://api.merid.yourdomain"
  VITE_WS_URL = "wss://api.merid.yourdomain"
```

### Create React App Configuration
```toml
# netlify.toml
[build]
  command = "CI=false npm run build"
  publish = "build"

[build.environment]
  VITE_API_BASE = "https://api.merid.yourdomain"
  VITE_WS_URL = "wss://api.merid.yourdomain"
```

### Requirements
- `tailwind.config.*` at repo root
- `postcss.config.*` at repo root
- `content` in Tailwind config: `./src/**/*.{js,jsx,ts,tsx}`

---

## Secure API Keys Management

### ✅ Frontend (Vercel/Netlify)
Only non-sensitive config:
```
VITE_API_BASE=https://api.merid.yourdomain
VITE_ENV_LABEL=PROD
VITE_WS_URL=wss://api.merid.yourdomain
```

### ✅ Backend (FastAPI)
Add sensitive keys as **protected environment variables**:
```
ALPACA_API_KEY=your_key_here
BINANCE_API_SECRET=your_secret_here
IBKR_USERNAME=your_username
```

### 🚫 NEVER Expose
- Trading API keys in frontend build
- Broker credentials in browser
- Secret tokens in `VITE_` variables

### ✅ Correct Pattern
```ts
// Frontend talks to backend only
await fetch(`${API_BASE}/api/v1/orders/open`, {
  credentials: "include", // cookie-based auth
});

// Backend uses env keys to call brokers
const alpaca = new Alpaca({
  keyId: process.env.ALPACA_API_KEY,
  secretKey: process.env.ALPACA_API_SECRET,
});
```

---

## Environment Variable Reference

### Frontend Variables
| Variable | Purpose | Example |
|----------|---------|---------|
| `VITE_API_BASE` | Backend API URL | `https://api.merid.com` |
| `VITE_WS_URL` | WebSocket URL | `wss://api.merid.com` |
| `VITE_ENV_LABEL` | Environment label | `PROD` |

### Backend Variables (Sensitive)
| Variable | Purpose | Platform |
|----------|---------|----------|
| `ALPACA_API_KEY` | Alpaca trading | Vercel/Netlify |
| `BINANCE_API_SECRET` | Binance trading | Vercel/Netlify |
| `JWT_SECRET` | JWT signing | Vercel/Netlify |

---

## Troubleshooting Checklist

### Build Issues
- [ ] `npm run build` works locally
- [ ] Tailwind config at repo root
- [ ] PostCSS config present
- [ ] Content glob includes all source files

### Runtime Issues
- [ ] Environment variables set correctly
- [ ] API endpoints accessible
- [ ] WebSocket connections work
- [ ] Authentication flows work

### Security Issues
- [ ] No API keys in frontend bundle
- [ ] Only backend has sensitive env vars
- [ ] HTTPS/WSS URLs in production
- [ ] CORS configured correctly

---

## Quick Copy-Paste Commands

### Vercel CLI
```bash
# Install Vercel CLI
npm i -g vercel

# Deploy
vercel --prod

# Set env vars
vercel env add VITE_API_BASE
vercel env add VITE_WS_URL
```

### Netlify CLI
```bash
# Install Netlify CLI
npm i -g netlify-cli

# Deploy
netlify deploy --prod --dir=dist

# Set env vars
netlify env:set VITE_API_BASE https://api.merid.com
netlify env:set VITE_WS_URL wss://api.merid.com
```
