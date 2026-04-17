# docs/KALSHI_VPS_SETUP.md
# Chicago VPS Setup for Low-Latency Kalshi Trading

## Overview
This guide documents setting up a Chicago-based VPS for sub-1–2 ms latency to Kalshi API endpoints.

## Provider Selection

### Recommended Providers (Chicago Data Centers)
- **DigitalOcean**: ord1 (Chicago) - Good balance of cost/performance
- **Vultr**: ord1 (Chicago) - Excellent network performance
- **Linode**: ord1 (Chicago) - Reliable with good support
- **Hetzner**: No Chicago location (not recommended)

### Recommended Instance Specs
- **CPU**: 2+ vCPU (Intel Xeon preferred)
- **RAM**: 4GB minimum, 8GB recommended
- **Storage**: 80GB SSD (system + logs + data)
- **Network**: 1Gbps+ with low jitter

## Initial Server Setup

### 1. Server Provisioning
```bash
# Example: DigitalOcean ord1 (Chicago)
# Choose Ubuntu 22.04 LTS
# Enable IPv6 (optional but recommended)
# Enable monitoring (optional)
# Enable backups (recommended)
```

### 2. Initial System Configuration
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Set timezone to Chicago
sudo timedatectl set-timezone America/Chicago

# Install essential packages
sudo apt install -y htop iotop ntp chrony ufw git curl wget vim

# Create merid user
sudo adduser merid
sudo usermod -aG sudo merid
```

### 3. Network Optimization
```bash
# Edit /etc/sysctl.conf
sudo vim /etc/sysctl.conf

# Add these lines for low latency:
net.core.rmem_max = 134217728
net.core.wmem_max = 134217728
net.ipv4.tcp_rmem = 4096 65536 134217728
net.ipv4.tcp_wmem = 4096 65536 134217728
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_congestion_control = bbr

# Apply changes
sudo sysctl -p
```

## Time Synchronization Setup

### 1. Install and Configure chrony
```bash
# Install chrony (better than ntpd for low latency)
sudo apt install -y chrony

# Configure chrony
sudo vim /etc/chrony/chrony.conf
```

### 2. chrony.conf Configuration
```conf
# Use Chicago NTP servers for lowest latency
pool 0.chicago.pool.ntp.org iburst
pool 1.chicago.pool.ntp.org iburst
pool 2.chicago.pool.ntp.org iburst
pool 3.chicago.pool.ntp.org iburst

# Allow local clock to be used if servers fail
allow 127.0.0.1
allow ::1

# Enable hardware timestamping if available
hwtimestamp *

# Minimum samples for synchronization
minsamples 4

# Maximum delay before panic
maxdelay 0.1

# Enable burst mode for faster sync
burst
```

### 3. Start and Enable chrony
```bash
sudo systemctl restart chrony
sudo systemctl enable chrony

# Check synchronization
chronyc tracking
chronyc sources -v
```

## Firewall Configuration

### 1. Configure UFW
```bash
# Reset UFW to default
sudo ufw --force reset

# Default policies
sudo ufw default deny incoming
sudo ufw default allow outgoing

# Allow SSH (from your IP only)
sudo ufw allow from YOUR_IP to any port 22

# Allow required ports for MERID
sudo ufw allow 8000/tcp  # FastAPI
sudo ufw allow 8080/tcp  # Alternative port
sudo ufw allow 3000/tcp  # React dev server (if needed)

# Allow Kalshi endpoints
sudo ufw allow out to api.elections.kalshi.com port 443
sudo ufw allow out to api.elections.kalshi.com port 80
sudo ufw allow out to fix.elections.kalshi.com port 8228
sudo ufw allow out to fix.elections.kalshi.com port 98228

# Enable firewall
sudo ufw enable
```

## MERID Deployment

### 1. Install Python Environment
```bash
# Install Python 3.11+
sudo apt install -y python3.11 python3.11-venv python3-pip

# Create virtual environment
cd /opt
sudo mkdir merid
sudo chown merid:merid merid
cd merid
sudo -u merid python3.11 -m venv venv
sudo -u merid venv/bin/pip install --upgrade pip
```

### 2. Deploy MERID Code
```bash
# Clone repository (or use your preferred method)
sudo -u merid git clone https://github.com/your-org/merid.git .

# Install dependencies
sudo -u merid venv/bin/pip install -r requirements.txt
sudo -u merid venv/bin/pip install -e .
```

### 3. Environment Configuration
```bash
# Create environment file
sudo -u merid vim /opt/merid/.env
```

### 4. .env Configuration
```bash
# MERID Configuration
MERID_ENV=production
MERID_PROFILE=kalshi-only
MERID_TRADING_MODE=paper  # Start with paper, change to live later

# Kalshi Configuration
KALSHI_USE_DEMO=false  # Set to false for production
KALSHI_API_KEY_ID=your_api_key_id
KALSHI_PRIVATE_KEY_PATH=/opt/merid/secrets/kalshi_private_key.pem
KALSHI_EMAIL=your_email@example.com
KALSHI_PASSWORD=your_password

# Logging
MERID_LOG_LEVEL=INFO

# Performance
WEB_CONCURRENCY=4
```

### 5. Secrets Management
```bash
# Create secrets directory
sudo mkdir /opt/merid/secrets
sudo chown merid:merid /opt/merid/secrets
sudo chmod 700 /opt/merid/secrets

# Copy Kalshi private key
sudo cp kalshi_private_key.pem /opt/merid/secrets/
sudo chown merid:merid /opt/merid/secrets/kalshi_private_key.pem
sudo chmod 600 /opt/merid/secrets/kalshi_private_key.pem
```

## Systemd Service Setup

### 1. Create systemd service
```bash
sudo vim /etc/systemd/system/merid.service
```

### 2. merid.service Configuration
```ini
[Unit]
Description=MERID Kalshi Trading System
After=network.target chrony.service
Wants=chrony.service

[Service]
Type=simple
User=merid
Group=merid
WorkingDirectory=/opt/merid
Environment=PATH=/opt/merid/venv/bin
EnvironmentFile=/opt/merid/.env
ExecStart=/opt/merid/venv/bin/python -m merid.loop --mode shadow --agents btc_15m_regime,eth_15m_regime,sol_15m_regime,xrp_15m_regime
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 3. Enable and Start Service
```bash
sudo systemctl daemon-reload
sudo systemctl enable merid
sudo systemctl start merid

# Check status
sudo systemctl status merid
sudo journalctl -u merid -f
```

## Performance Tuning

### 1. CPU Governor
```bash
# Set performance governor
sudo apt install -y cpufrequtils
sudo cpufreq-set -g performance
```

### 2. Disable Swapping
```bash
# Check swap usage
free -h

# Temporarily disable swap
sudo swapoff -a

# Permanently disable swap (comment out swap line in /etc/fstab)
sudo vim /etc/fstab
```

### 3. File System Optimization
```bash
# Use tmpfs for /tmp (faster I/O)
sudo mount -t tmpfs -o size=2G tmpfs /tmp

# Add to /etc/fstab for persistence
echo "tmpfs /tmp tmpfs size=2G 0 0" | sudo tee -a /etc/fstab
```

## Network Latency Testing

### 1. Test Latency to Kalshi
```bash
# Test API latency
ping -c 10 api.elections.kalshi.com

# Test WebSocket latency
curl -w "@curl-format.txt" -o /dev/null -s "https://api.elections.kalshi.com/trade-api/v2/health"
```

### 2. curl-format.txt
```bash
     time_namelookup:  %{time_namelookup}\n
        time_connect:  %{time_connect}\n
     time_appconnect:  %{time_appconnect}\n
    time_pretransfer:  %{time_pretransfer}\n
       time_redirect:  %{time_redirect}\n
  time_starttransfer:  %{time_starttransfer}\n
                     ----------\n
          time_total:  %{time_total}\n
```

### 3. Expected Latency Targets
- **API Latency**: < 10ms (Chicago to Chicago)
- **WebSocket**: < 5ms (Chicago to Chicago)
- **DNS Resolution**: < 2ms

## Monitoring and Alerting

### 1. Basic Monitoring
```bash
# Install monitoring tools
sudo apt install -y nethogs iftop

# Monitor network usage
sudo iftop -i eth0

# Monitor process usage
sudo nethogs
```

### 2. Log Management
```bash
# Configure log rotation
sudo vim /etc/logrotate.d/merid
```

### 3. merid logrotate config
```
/opt/merid/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    create 644 merid merid
    postrotate
        systemctl reload merid
    endscript
}
```

## Security Hardening

### 1. SSH Security
```bash
# Edit SSH config
sudo vim /etc/ssh/sshd_config

# Recommended settings:
Port 22  # Or change to non-standard port
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
ClientAliveInterval 300
ClientAliveCountMax 2

# Restart SSH
sudo systemctl restart ssh
```

### 2. Fail2Ban Setup
```bash
# Install fail2ban
sudo apt install -y fail2ban

# Configure fail2ban
sudo cp /etc/fail2ban/jail.conf /etc/fail2ban/jail.local
sudo vim /etc/fail2ban/jail.local

# Enable SSH protection
[sshd]
enabled = true
port = 22
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 3600

sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

## Backup and Recovery

### 1. Backup Script
```bash
# Create backup script
sudo vim /opt/merid/scripts/backup.sh
```

### 2. backup.sh
```bash
#!/bin/bash
BACKUP_DIR="/opt/backups/merid"
DATE=$(date +%Y%m%d_%H%M%S)

# Create backup directory
mkdir -p $BACKUP_DIR

# Backup configuration and data
tar -czf $BACKUP_DIR/merid_$DATE.tar.gz \
    /opt/merid/.env \
    /opt/merid/secrets/ \
    /opt/merid/data/ \
    /opt/merid/logs/

# Keep only last 7 days
find $BACKUP_DIR -name "merid_*.tar.gz" -mtime +7 -delete
```

### 3. Cron Job for Backups
```bash
# Add to crontab (merid user)
sudo -u merid crontab -e

# Add daily backup at 2 AM
0 2 * * * /opt/merid/scripts/backup.sh
```

## Troubleshooting

### Common Issues
1. **High Latency**: Check network configuration, firewall rules
2. **Time Sync Issues**: Verify chrony status and NTP servers
3. **Service Failures**: Check systemd logs and environment variables
4. **Memory Issues**: Monitor with `free -h` and `htop`

### Debug Commands
```bash
# Check system resources
htop
free -h
df -h

# Check network
ping -c 5 api.elections.kalshi.com
netstat -tuln

# Check service status
sudo systemctl status merid
sudo journalctl -u merid -n 100

# Check time sync
chronyc tracking
chronyc sources -v
```

## Validation Checklist

- [ ] Server provisioned in Chicago data center
- [ ] System optimized for low latency
- [ ] Time synchronization configured (chrony)
- [ ] Firewall configured with proper rules
- [ ] MERID deployed and configured
- [ ] Systemd service created and running
- [ ] Latency to Kalshi < 10ms
- [ ] Monitoring and logging configured
- [ ] Security hardening completed
- [ ] Backup procedures implemented
- [ ] Documentation completed

---

**Expected Results**: Sub-1–2 ms latency to Kalshi endpoints with 99.9% uptime for crypto trading operations.
