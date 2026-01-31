# MERID Logging - One Pager
**Date:** 2026-01-26  
**Version:** 1.0.0  

---

## 🎯 Overview

MERID uses a **queue-based logging backend** that provides production-ready multiprocessing logging with zero disruption to existing code.

---

## 🏗️ Architecture

### **Queue Backend**
- **QueueListener** - Thread-based listener owns all file handlers
- **QueueHandler** - Workers send LogRecords through multiprocessing.Queue
- **dictConfig Integration** - Seamless integration with existing logging configurations

### **Key Components**
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Worker Process │    │   Worker Process │    │   Worker Process │
│                 │    │                 │    │                 │
│ logging.getLogger │    │ logging.getLogger │    │ logging.getLogger │
│      .info()      │    │      .info()      │    │      .info()      │
└─────────┬───────┘    └─────────┬───────┘    └─────────┬───────┘
          │                      │                      │
          │                      │                      │
          ▼                      ▼                      ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                multiprocessing.Queue                     │
    │                     (shared across workers)              │
    └─────────────────────┬───────────────────────────────────┘
                          │
                          ▼
    ┌─────────────────────────────────────────────────────────────┐
    │                 QueueListener Thread                     │
    │                 (owns all file handlers)                │
    │                                                     │
    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
    │  │ TimedRotating│  │   Rotating  │  │   Console  │    │
    │  │ FileHandler │  │ FileHandler │  │   Handler  │    │
    │  └─────────────┘  └─────────────┘  └─────────────┘    │
    └─────────────────────────────────────────────────────────────┘
```

---

## 📁 Log File Locations

### **Production**
- **Default:** `/var/log/merid/merid.log`
- **Environment Variable:** `MERID_LOG_PATH`
- **Rotation:** TimedRotatingFileHandler (midnight, 7 backups)

### **Development**
- **Default:** `logs/merid.log`
- **Override:** `MERID_LOG_PATH=./logs/dev.log`

### **Container/CI**
```bash
# Docker
docker run -e MERID_LOG_PATH=/var/log/merid/app.log -v /var/log/merid:/var/log/merid merid-app

# Kubernetes
env:
  - name: MERID_LOG_PATH
    value: /var/log/merid/app.log
volumeMounts:
  - name: merid-logs
    mountPath: /var/log/merid
```

---

## 🔧 Configuration

### **Standard Usage**
```python
# In main/orchestrator
import merid_logging_config

merid_logging_config.start_merid_logging()

# Use existing loggers as-is
logger = logging.getLogger("merid.agent.trader")
logger.info("placing order")

# In each worker process
merid_logging_config.init_merid_worker_logging()
logger = logging.getLogger("merid.worker")
logger.info("worker started")

# At process exit
merid_logging_config.shutdown_merid_logging()
```

### **Environment Variables**
```bash
# Production
export MERID_LOG_PATH=/var/log/merid/production.log

# Development
export MERID_LOG_PATH=./logs/dev.log

# Service-specific
export MERID_LOG_PATH=/var/log/merid/trader-service.log
```

### **dictConfig Integration**
```python
# merid_logging_config.py handles dictConfig automatically
# Existing dictConfig patterns work unchanged

# Custom configuration (if needed)
cfg = merid_logging_config.base_dict_config("/custom/path.log")
logging.config.dictConfig(cfg)
```

---

## 🔄 Rotation Semantics

### **TimedRotatingFileHandler**
- **When:** Midnight (00:00 UTC)
- **Interval:** 1 day
- **Backups:** 7 files
- **Encoding:** UTF-8
- **Format:** `%(asctime)s [%(process)d] %(processName)s %(levelname)s %(name)s %(message)s`

### **Rotation Behavior**
- **Single Process:** Only QueueListener thread handles rotation
- **No Race Conditions:** Workers never touch files directly
- **Atomic Operations:** Safe file renaming and creation
- **Data Integrity:** No log records lost during rotation

---

## 📊 Log Format

### **Standard Format**
```
2026-01-27 01:30:15,123 [12345] MainProcess INFO merid.agent.trader placing order
```

### **Fields**
- **timestamp:** ISO 8601 format (UTC)
- **process:** Process ID
- **processName:** Process name (MainProcess, Process-1, etc.)
- **levelname:** Log level (INFO, WARNING, ERROR, etc.)
- **name:** Logger name (merid.agent.trader, merid.worker, etc.)
- **message:** Log message

---

## 🚀 Scraping & Monitoring

### **File Locations**
```bash
# Find current log file
find /var/log/merid -name "merid.log" -type f

# Find rotated logs
find /var/log/merid -name "merid.log.*" -type f

# List all log files
ls -la /var/log/merid/
```

### **Monitoring Commands**
```bash
# Real-time monitoring
tail -f /var/log/merid/merid.log

# Search for specific patterns
grep "ERROR" /var/log/merid/merid.log
grep "merid.agent.trader" /var/log/merid/merid.log

# Count log entries by level
grep -c "INFO" /var/log/merid/merid.log
grep -c "ERROR" /var/log/merid/merid.log
```

### **Log Aggregation**
```bash
# ELK Stack
filebeat.inputs:
- type: log
  paths:
    - /var/log/merid/*.log
  fields:
    service: merid
    environment: production

# Fluentd
<source>
  @type tail
  path /var/log/merid
  pos_file /var/log/fluentd/merid.log.pos
  tag merid.*
</source>
```

---

## 🛡️ Security Considerations

### **File Permissions**
- **Default:** 644 (rw-r--r--)
- **Process:** Only QueueListener thread writes to files
- **Workers:** No direct file access

### **Log Content**
- **No Secrets:** Ensure no passwords, tokens, or sensitive data in logs
- **PII Compliance:** Follow data privacy regulations
- **Audit Trail:** All operations logged with process information

### **Access Control**
```bash
# Log directory permissions
chmod 755 /var/log/merid
chown merid:merid /var/log/merid

# Log file permissions
chmod 644 /var/log/merid/merid.log
```

---

## 🔍 Troubleshooting

### **Common Issues**

#### **Log File Not Created**
```bash
# Check directory permissions
ls -la /var/log/merid/

# Check environment variable
echo $MERID_LOG_PATH

# Test logging backend
python -c "import merid_logging_config; merid_logging_config.start_merid_logging()"
```

#### **No Log Messages**
```bash
# Check queue status
python -c "import merid_logging_config; print('Queue:', merid_logging_config.LOG_QUEUE)"

# Check listener status
python -c "import merid_logging_config; print('Listener:', merid_logging_config.LOG_LISTENER)"
```

#### **Permission Errors**
```bash
# Create log directory
mkdir -p /var/log/merid
chmod 755 /var/log/merid

# Check disk space
df -h /var/log/merid
```

### **Health Check**
```bash
# System health snapshot
python meridctl.py status --save

# Check specific components
python meridctl.py status --output /tmp/health.json
cat /tmp/health.json
```

---

## 📚 Integration Examples

### **FastAPI Integration**
```python
from fastapi import FastAPI
import merid_logging_config

app = FastAPI()

@app.on_event("startup")
async def startup_event():
    merid_logging_config.start_merid_logging()

@app.on_event("shutdown")
async def shutdown_event():
    merid_logging_config.shutdown_merid_logging()

@app.get("/")
async def root():
    logger = logging.getLogger("merid.api")
    logger.info("API request received")
    return {"status": "ok"}
```

### **Docker Integration**
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Set log path environment
ENV MERID_LOG_PATH=/var/log/merid/app.log

# Create log directory
RUN mkdir -p /var/log/merid

CMD ["python", "app.py"]
```

### **Systemd Service**
```ini
# /etc/systemd/system/merid.service
[Unit]
Description=MERID Service
After=network.target

[Service]
Type=simple
User=merid
Group=merid
WorkingDirectory=/opt/merid
Environment=MERID_LOG_PATH=/var/log/merid/merid.log
ExecStart=/opt/merid/venv/bin/python -m merid.main
ExecStop=/opt/merid/venv/bin/python -c "import merid_logging_config; merid_logging_config.shutdown_merid_logging()"
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 🎯 Best Practices

### **Do's**
- ✅ Use `start_merid_logging()` in main process
- ✅ Call `init_merid_worker_logging()` in workers
- ✅ Set `MERID_LOG_PATH` for production
- ✅ Monitor log file sizes and rotation
- ✅ Use structured logging for machine parsing
- ✅ Include process information in logs
- ✅ Test logging in development before production

### **Don'ts**
- ❌ Don't create file handlers in workers
- ❌ Don't bypass the queue for logging
- ❌ Don't log sensitive information
- ❌ Don't ignore Windows file handle cleanup
- ❌ Don't use hardcoded log paths in production
- ❌ Don't forget to call `shutdown_merid_logging()`

---

## 📞 Support

### **Documentation**
- **Full Documentation:** `/docs/MERID_LOGGING_RULES_OF_THE_ROAD.md`
- **API Reference:** `merid_logging_config.py`
- **Examples:** `/examples/logging/`

### **Troubleshooting**
- **Health Check:** `python meridctl.py status`
- **Logs:** `/var/log/merid/merid.log`
- **Issues:** Check system health snapshot first

---

**MERID Logging v1.0.0 - Production-Ready Multiprocessing Logging**
