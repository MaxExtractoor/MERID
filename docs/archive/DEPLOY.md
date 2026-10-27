# MERID Deployment Guide

## Quick Start (Production)

### 1. Environment Setup

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your production values
nano .env
```

### 2. Deploy to Railway (Recommended)

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login to Railway
railway login

# Link to your project
railway link

# Deploy
railway up
```

### 3. Deploy with Docker

```bash
# Build image
docker build -t merid:latest .

# Run container
docker run -d \
  --name merid \
  -p 8011:8011 \
  --env-file .env \
  merid:latest
```

### 4. Local Production Mode

```bash
# Using the startup script
./start.sh production

# Or manually
export MERID_ENV=production
export MERID_PROFILE=kalshi-only
python -m web.main
```

## Critical Production Settings

### Trading Mode (MUST SET CORRECTLY)

```env
# START WITH PAPER TRADING
MERID_TRADING_MODE=paper
MERID_PM_TRADING_MODE=paper
MERID_PM_LIVE_ENABLED=false
MERID_LIVE_TRADING_UNLOCKED=false
```

### Safety Limits

```env
# Set appropriate limits for your capital
MERID_MAX_ORDER_SIZE_USD=100
MERID_MAX_DAILY_LOSS_USD=500
MERID_MAX_POSITION_SIZE_USD=1000
MERID_PM_MAX_NOTIONAL_PER_MARKET=500
MERID_PM_MAX_DAILY_LOSS=250
MERID_PM_MAX_TOTAL_NOTIONAL=5000
```

### Kalshi Credentials

```env
# Required for live trading
KALSHI_API_KEY_ID=your_key_id
KALSHI_API_PRIVATE_KEY_PATH=/path/to/private_key.pem
```

## Health Checks

### Backend Health

```bash
# Check API health
curl http://localhost:8011/api/v1/health

# Expected response:
# {"status": "healthy", "timestamp": "2026-02-26T..."}
```

### Frontend Build

```bash
cd web/react
npm run build

# Check dist/ folder exists
ls -la dist/
```

## Monitoring

### Logs

```bash
# View Docker logs
docker logs -f merid

# View Railway logs
railway logs
```

### Key Metrics

- `/api/v1/health` - System health
- `/api/v1/operator/summary` - Trading status
- `/api/v1/kalshi/balance` - Kalshi balance
- `/api/v1/kalshi/positions` - Current positions

## Troubleshooting

### 401 Errors

The system has auth bypass for development. In production:
1. Set `MERID_DEV_AUTH_BYPASS=0`
2. Ensure users login via `/api/v1/auth/login/email`
3. Frontend sends token in `Authorization: Bearer <token>` header

### WebSocket Issues

```env
# Enable dev mode for testing
MERID_DEV_ALLOW_WS=true

# Disable in production
MERID_DEV_ALLOW_WS=false
```

### Database

SQLite is used by default (no external DB needed):
```env
DATABASE_URL=sqlite:///./data/merid.db
```

## Security Checklist

- [ ] Changed all default passwords
- [ ] Set strong MERID_DASHBOARD_API_KEY
- [ ] Disabled dev bypasses in production
- [ ] Enabled CAPTCHA for public deployments
- [ ] Set appropriate trading limits
- [ ] Configured CORS for your domain only
- [ ] Enabled HTTPS
- [ ] Set up monitoring/alerting

## Support

For issues:
1. Check logs: `docker logs merid` or `railway logs`
2. Verify .env configuration
3. Test health endpoints
4. Review 401_ERROR_AUDIT.md for auth issues
