# Process Manager Wiring Guide

## Overview
This document explains how to wire `.env.unified_edge` into your process manager (systemd, supervisor, k8s, etc.) so environment variables are correctly passed in live runs.

## Prerequisites

- `.env.unified_edge` file created
- Process manager installed (systemd, supervisor, or k8s)
- MERID system installed

## systemd

### Step 1: Create Environment File
```bash
# Copy .env.unified_edge to /etc/merid/.env
sudo cp .env.unified_edge /etc/merid/.env

# Set correct permissions
sudo chmod 600 /etc/merid/.env
sudo chown merid:merid /etc/merid/.env
```

### Step 2: Create systemd Service File
Create `/etc/systemd/system/merid.service`:

```ini
[Unit]
Description=MERID Trading System
After=network.target

[Service]
Type=simple
User=merid
Group=merid
WorkingDirectory=/opt/merid
EnvironmentFile=/etc/merid/.env
ExecStart=/usr/bin/python3 /opt/merid/web/main.py
Restart=always
RestartSec=10

# Logging
StandardOutput=journal
StandardError=journal
SyslogIdentifier=merid

# Security
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/log/merid /var/lib/merid

[Install]
WantedBy=multi-user.target
```

### Step 3: Enable and Start Service
```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable merid

# Start service
sudo systemctl start merid

# Check status
sudo systemctl status merid

# View logs
sudo journalctl -u merid -f
```

### Step 4: Verify Environment Variables
```bash
# Check if service can read environment file
sudo systemctl show merid --property=Environment

# Check specific environment variable
sudo systemctl show merid --property=Environment | grep MERID_DEPLOYMENT_REGIME
```

## Supervisor

### Step 1: Create Environment File
```bash
# Copy .env.unified_edge to /etc/merid/.env
sudo cp .env.unified_edge /etc/merid/.env

# Set correct permissions
sudo chmod 600 /etc/merid/.env
sudo chown merid:merid /etc/merid/.env
```

### Step 2: Create Supervisor Config
Create `/etc/supervisor/conf.d/merid.conf`:

```ini
[program:merid]
command=/usr/bin/python3 /opt/merid/web/main.py
directory=/opt/merid
user=merid
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/merid/supervisor.log
environment=MERID_DEPLOYMENT_REGIME="%(env_MERID_DEPLOYMENT_REGIME)s",\
    MERID_UNIFIED_EDGE_ENABLED="%(env_MERID_UNIFIED_EDGE_ENABLED)s",\
    MERID_CALIBRATION_VERSION="%(env_MERID_CALIBRATION_VERSION)s",\
    MERID_LIVE_SESSION_MAX_RISK_USD="%(env_MERID_LIVE_SESSION_MAX_RISK_USD)s",\
    MERID_RISK_BUDGET_MULTIPLIER="%(env_MERID_RISK_BUDGET_MULTIPLIER)s",\
    MERID_PROFILE="%(env_MERID_PROFILE)s",\
    MERID_PM_PROFILE="%(env_MERID_PM_PROFILE)s",\
    CME_CF_API_KEY="%(env_CME_CF_API_KEY)s",\
    CFB_ALLOW_COMPOSITE_FALLBACK="%(env_CFB_ALLOW_COMPOSITE_FALLBACK)s",\
    CFB_MAX_STALENESS_SECONDS="%(env_CFB_MAX_STALENESS_SECONDS)s",\
    CALIBRATION_DATA_LOGGING_ENABLED="%(env_CALIBRATION_DATA_LOGGING_ENABLED)s",\
    CALIBRATION_DATA_LOG_DIR="%(env_CALIBRATION_DATA_LOG_DIR)s",\
    CALIBRATION_DATA_RETENTION_DAYS="%(env_CALIBRATION_DATA_RETENTION_DAYS)s"
```

### Step 3: Reload and Start
```bash
# Reload supervisor
sudo supervisorctl reread
sudo supervisorctl update

# Start service
sudo supervisorctl start merid

# Check status
sudo supervisorctl status merid

# View logs
sudo tail -f /var/log/merid/supervisor.log
```

### Alternative: Use environment file with supervisor
If your supervisor version supports it:

```ini
[program:merid]
command=/usr/bin/python3 /opt/merid/web/main.py
directory=/opt/merid
user=merid
autostart=true
autorestart=true
redirect_stderr=true
stdout_logfile=/var/log/merid/supervisor.log
environment_file=/etc/merid/.env
```

## Kubernetes (k8s)

### Step 1: Create ConfigMap
Create `merid-configmap.yaml`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: merid-config
data:
  MERID_DEPLOYMENT_REGIME: "SIM"
  MERID_UNIFIED_EDGE_ENABLED: "false"
  MERID_CALIBRATION_VERSION: "placeholder"
  MERID_LIVE_SESSION_MAX_RISK_USD: "300"
  MERID_RISK_BUDGET_MULTIPLIER: "0.0"
  MERID_PROFILE: "kalshi_crypto_15m_v2"
  MERID_PM_PROFILE: "baseline"
  CFB_ALLOW_COMPOSITE_FALLBACK: "true"
  CFB_MAX_STALENESS_SECONDS: "60"
  CALIBRATION_DATA_LOGGING_ENABLED: "true"
  CALIBRATION_DATA_LOG_DIR: "/var/log/merid/calibration"
  CALIBRATION_DATA_RETENTION_DAYS: "90"
```

### Step 2: Create Secret for API Keys
Create `merid-secret.yaml`:

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: merid-secret
type: Opaque
stringData:
  CME_CF_API_KEY: "your-api-key-here"
```

### Step 3: Create Deployment
Create `merid-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: merid
spec:
  replicas: 1
  selector:
    matchLabels:
      app: merid
  template:
    metadata:
      labels:
        app: merid
    spec:
      containers:
      - name: merid
        image: merid:latest
        envFrom:
        - configMapRef:
            name: merid-config
        - secretRef:
            name: merid-secret
        volumeMounts:
        - name: logs
          mountPath: /var/log/merid
        - name: calibration
          mountPath: /var/log/merid/calibration
      volumes:
      - name: logs
        emptyDir: {}
      - name: calibration
        emptyDir: {}
```

### Step 4: Apply Configuration
```bash
# Apply configmap
kubectl apply -f merid-configmap.yaml

# Apply secret
kubectl apply -f merid-secret.yaml

# Apply deployment
kubectl apply -f merid-deployment.yaml

# Check status
kubectl get pods -l app=merid

# View logs
kubectl logs -f deployment/merid
```

## Docker Compose

### Step 1: Create docker-compose.yml
```yaml
version: '3.8'

services:
  merid:
    image: merid:latest
    container_name: merid
    restart: always
    env_file:
      - .env.unified_edge
    volumes:
      - ./logs:/var/log/merid
      - ./calibration:/var/log/merid/calibration
    ports:
      - "8000:8000"
```

### Step 2: Start Service
```bash
# Start service
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f merid
```

## Verification

### Check Environment Variables are Loaded
```bash
# For systemd
sudo systemctl show merid --property=Environment

# For supervisor
sudo supervisorctl status merid

# For k8s
kubectl exec -it <pod-name> -- env | grep MERID

# For docker-compose
docker-compose exec merid env | grep MERID
```

### Check Logs for Deployment Regime
```bash
# Look for deployment regime log
grep "DEPLOYMENT-REGIME" /var/log/merid/merid.log

# Should see:
# [DEPLOYMENT-REGIME] Initialized with regime: SIM
```

### Check Logs for Spot Proxy Validation
```bash
# Look for spot proxy validation log
grep "SPOT-PROXY-VALIDATION" /var/log/merid/merid.log

# Should see:
# [SPOT-PROXY-VALIDATION] Checking spot proxy availability...
# [SPOT-PROXY-VALIDATION] Spot proxy validation passed
```

### Check Logs for Unified Edge Validation
```bash
# Look for unified edge validation log
grep "UNIFIED-EDGE-VALIDATION" /var/log/merid/merid.log

# Should see:
# [UNIFIED-EDGE-VALIDATION] Checking unified edge configuration...
# [UNIFIED-EDGE-VALIDATION] Configuration validated successfully
```

## Troubleshooting

### Environment Variables Not Loading
**Problem:** Environment variables not being read by process.

**Solution:**
- Check file permissions (should be 600)
- Check file ownership (should be correct user)
- Check file path (should be absolute)
- Check process manager configuration

### Service Fails to Start
**Problem:** Service fails to start after configuration change.

**Solution:**
- Check service logs: `journalctl -u merid -n 50`
- Check environment variables: `systemctl show merid --property=Environment`
- Check file syntax: `cat /etc/merid/.env`
- Check for syntax errors in service file

### Wrong Regime
**Problem:** System starts in wrong regime.

**Solution:**
- Check `MERID_DEPLOYMENT_REGIME` in `.env`
- Check if environment variable is loaded
- Restart service after changing `.env`
- Verify regime in logs

## Security Considerations

### File Permissions
- `.env` file should be `600` (read/write by owner only)
- `.env` file should be owned by service user
- API keys should be in secrets (k8s) or separate file

### Secrets Management
- API keys should not be in version control
- Use k8s secrets for production
- Use separate secret file for local development
- Rotate API keys regularly

### Audit Logging
- Log all configuration changes
- Log regime transitions
- Log calibration version changes
- Log risk budget changes

## Next Steps

After wiring process manager:
1. Verify environment variables are loaded
2. Verify service starts successfully
3. Verify logs show correct regime
4. Verify spot proxy validation passes
5. Verify unified edge validation passes
6. Proceed to T-2h pre-flight checks

## Contact

For issues with process manager wiring:
- Check process manager documentation
- Check service logs
- Check environment variables
- Rollback to previous configuration
