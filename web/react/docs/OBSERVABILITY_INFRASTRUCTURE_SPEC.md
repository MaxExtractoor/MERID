# Observability Infrastructure Specification

## Overview
This document specifies the infrastructure required for Tier 1 observability dashboards (bundle size, network rate, view load times).

## Required Components

### 1. Bundle Size Monitoring
**Purpose:** Track JavaScript bundle sizes over time to detect regressions

**Implementation:**

#### Frontend Integration
```typescript
// src/utils/bundleSizeTracker.ts
export interface BundleMetrics {
  mainBundle: number;
  vendorChunk: number;
  total: number;
  timestamp: string;
}

export function reportBundleMetrics(metrics: BundleMetrics) {
  fetch(API_ENDPOINTS.OBSERVABILITY_BUNDLE_SIZE, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(metrics),
  });
}

// Call this in App.tsx after bundle loads
if (process.env.NODE_ENV === 'production') {
  const mainBundle = performance.getEntriesByType('resource')
    .filter(e => e.name.includes('main'))
    .reduce((sum, e) => sum + (e as PerformanceResourceTiming).transferSize, 0);
  
  reportBundleMetrics({
    mainBundle,
    vendorChunk: 0, // Calculate similarly
    total: mainBundle,
    timestamp: new Date().toISOString(),
  });
}
```

#### Backend API Endpoint
**Endpoint:** `POST /api/observability/bundle-size`

**Implementation:**
```python
# web/api/observability.py
from fastapi import APIRouter, HTTPException
from datetime import datetime
from typing import Optional

router = APIRouter(prefix="/api/observability", tags=["observability"])

@router.post("/bundle-size")
async def report_bundle_size(metrics: BundleSizeMetrics):
    """Store bundle size metrics for monitoring"""
    # Store in database or time-series database
    await db.bundle_metrics.insert_one({
        **metrics.dict(),
        "timestamp": datetime.utcnow()
    })
    return {"status": "recorded"}

@router.get("/bundle-size/history")
async def get_bundle_size_history(days: int = 30):
    """Retrieve bundle size history for dashboard"""
    # Query time-series database
    metrics = await db.bundle_metrics.find({
        "timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}
    }).to_list(None)
    return metrics
```

#### Dashboard Visualization
Use Grafana to visualize bundle size trends:
- Line chart showing main bundle size over time
- Alert when bundle size increases by > 10%
- Compare across deployments

---

### 2. Network Rate Monitoring
**Purpose:** Track API request rates, response times, and error rates

**Implementation:**

#### Frontend Integration
```typescript
// src/utils/networkTracker.ts
export interface NetworkMetrics {
  endpoint: string;
  method: string;
  duration: number;
  status: number;
  timestamp: string;
}

export function trackNetworkRequest(
  endpoint: string,
  method: string,
  duration: number,
  status: number
) {
  if (process.env.NODE_ENV === 'production') {
    fetch(API_ENDPOINTS.OBSERVABILITY_NETWORK_RATE, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint,
        method,
        duration,
        status,
        timestamp: new Date().toISOString(),
      }),
    });
  }
}

// Integrate with useApiData hook
const response = await fetch(url, options);
const duration = performance.now() - startTime;
trackNetworkRequest(url, method, duration, response.status);
```

#### Backend API Endpoint
**Endpoint:** `POST /api/observability/network-rate`

**Implementation:**
```python
@router.post("/network-rate")
async def report_network_metrics(metrics: NetworkMetrics):
    """Store network metrics for monitoring"""
    await db.network_metrics.insert_one({
        **metrics.dict(),
        "timestamp": datetime.utcnow()
    })
    return {"status": "recorded"}

@router.get("/network-rate/summary")
async def get_network_summary(hours: int = 24):
    """Retrieve network metrics summary"""
    # Calculate aggregates: avg duration, error rate, request count
    pipeline = [
        {"$match": {"timestamp": {"$gte": datetime.utcnow() - timedelta(hours=hours)}}},
        {"$group": {
            "_id": "$endpoint",
            "avg_duration": {"$avg": "$duration"},
            "error_rate": {
                "$avg": {"$cond": [{"$gte": ["$status", 400]}, 1, 0]}
            },
            "request_count": {"$sum": 1}
        }}
    ]
    return await db.network_metrics.aggregate(pipeline).to_list(None)
```

#### Dashboard Visualization
Use Grafana to visualize network metrics:
- Line chart showing request rate over time
- Line chart showing average response time
- Gauge showing current error rate
- Alert when error rate > 5% or response time > 2s

---

### 3. View Load Time Monitoring
**Purpose:** Track how long each view takes to load

**Implementation:**

#### Frontend Integration
```typescript
// src/utils/viewLoadTracker.ts
export interface ViewLoadMetrics {
  view: string;
  loadTime: number;
  firstContentfulPaint: number;
  largestContentfulPaint: number;
  timestamp: string;
}

export function trackViewLoad(view: string) {
  if (process.env.NODE_ENV === 'production' && 'performance' in window) {
    const timing = performance.timing;
    const navigationStart = timing.navigationStart;
    const loadTime = timing.loadEventEnd - navigationStart;
    
    // Use PerformanceObserver for FCP and LCP
    const observer = new PerformanceObserver((list) => {
      const entries = list.getEntries();
      const fcp = entries.find(e => e.name === 'first-contentful-paint')?.startTime || 0;
      const lcp = entries.find(e => e.entryType === 'largest-contentful-paint')?.startTime || 0;
      
      fetch(API_ENDPOINTS.OBSERVABILITY_VIEW_LOAD, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          view,
          loadTime,
          firstContentfulPaint: fcp,
          largestContentfulPaint: lcp,
          timestamp: new Date().toISOString(),
        }),
      });
    });
    
    observer.observe({ entryTypes: ['paint', 'largest-contentful-paint'] });
  }
}

// Call this in each view's useEffect
useEffect(() => {
  trackViewLoad('kalshi-vol-dashboard');
}, []);
```

#### Backend API Endpoint
**Endpoint:** `POST /api/observability/view-load`

**Implementation:**
```python
@router.post("/view-load")
async def report_view_load(metrics: ViewLoadMetrics):
    """Store view load metrics for monitoring"""
    await db.view_metrics.insert_one({
        **metrics.dict(),
        "timestamp": datetime.utcnow()
    })
    return {"status": "recorded"}

@router.get("/view-load/summary")
async def get_view_load_summary(days: int = 7):
    """Retrieve view load metrics summary"""
    pipeline = [
        {"$match": {"timestamp": {"$gte": datetime.utcnow() - timedelta(days=days)}}},
        {"$group": {
            "_id": "$view",
            "avg_load_time": {"$avg": "$loadTime"},
            "avg_fcp": {"$avg": "$firstContentfulPaint"},
            "avg_lcp": {"$avg": "$largestContentfulPaint"},
            "sample_count": {"$sum": 1}
        }}
    ]
    return await db.view_metrics.aggregate(pipeline).to_list(None)
```

#### Dashboard Visualization
Use Grafana to visualize view load metrics:
- Bar chart comparing average load time across views
- Line chart showing load time trends per view
- Heatmap showing FCP/LCP by view
- Alert when any view load time > 3s

---

## Infrastructure Requirements

### Time-Series Database
**Recommended:** InfluxDB or Prometheus + Grafana

**Setup:**
```yaml
# docker-compose.yml
version: '3.8'
services:
  influxdb:
    image: influxdb:2.7
    ports:
      - "8086:8086"
    environment:
      - INFLUXDB_DB=merid_observability
      - INFLUXDB_ADMIN_USER=admin
      - INFLUXDB_ADMIN_PASSWORD=password
    volumes:
      - influxdb_data:/var/lib/influxdb2

  grafana:
    image: grafana/grafana:10.0
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/dashboards:/etc/grafana/provisioning/dashboards
      - ./grafana/datasources:/etc/grafana/provisioning/datasources

volumes:
  influxdb_data:
  grafana_data:
```

### API Endpoints to Add
Add to `src/config/constants.ts`:

```typescript
export const API_ENDPOINTS = {
  // ... existing endpoints
  
  // Observability
  OBSERVABILITY_BUNDLE_SIZE: '/api/observability/bundle-size',
  OBSERVABILITY_BUNDLE_HISTORY: '/api/observability/bundle-size/history',
  OBSERVABILITY_NETWORK_RATE: '/api/observability/network-rate',
  OBSERVABILITY_NETWORK_SUMMARY: '/api/observability/network-rate/summary',
  OBSERVABILITY_VIEW_LOAD: '/api/observability/view-load',
  OBSERVABILITY_VIEW_SUMMARY: '/api/observability/view-load/summary',
} as const;
```

## Grafana Dashboards

### Dashboard 1: Bundle Size Trends
- Panel 1: Main bundle size over time (line chart)
- Panel 2: Vendor chunk size over time (line chart)
- Panel 3: Total bundle size over time (line chart)
- Panel 4: Bundle size by deployment (bar chart)
- Alert: Bundle size increase > 10%

### Dashboard 2: Network Performance
- Panel 1: Request rate over time (line chart)
- Panel 2: Average response time over time (line chart)
- Panel 3: Error rate over time (line chart)
- Panel 4: Request count by endpoint (bar chart)
- Alert: Error rate > 5% or response time > 2s

### Dashboard 3: View Load Times
- Panel 1: Average load time by view (bar chart)
- Panel 2: FCP by view (bar chart)
- Panel 3: LCP by view (bar chart)
- Panel 4: Load time trends per view (line chart)
- Alert: Any view load time > 3s

## Backend Implementation Checklist

### API Endpoints
- [ ] Create observability router
- [ ] Implement `POST /api/observability/bundle-size`
- [ ] Implement `GET /api/observability/bundle-size/history`
- [ ] Implement `POST /api/observability/network-rate`
- [ ] Implement `GET /api/observability/network-rate/summary`
- [ ] Implement `POST /api/observability/view-load`
- [ ] Implement `GET /api/observability/view-load/summary`

### Database
- [ ] Set up time-series database (InfluxDB or Prometheus)
- [ ] Create collections for bundle metrics
- [ ] Create collections for network metrics
- [ ] Create collections for view metrics
- [ ] Add indexes for efficient querying

### Infrastructure
- [ ] Deploy InfluxDB container
- [ ] Deploy Grafana container
- [ ] Configure Grafana data sources
- [ ] Import Grafana dashboards
- [ ] Set up alerting rules

### Frontend Integration
- [ ] Create bundle size tracker utility
- [ ] Create network tracker utility
- [ ] Create view load tracker utility
- [ ] Integrate with useApiData hook
- [ ] Add tracking to App.tsx
- [ ] Add tracking to each view

### Testing
- [ ] Test metric collection
- [ ] Test dashboard visualization
- [ ] Test alerting
- [ ] Load test metric ingestion

## Priority

1. **High Priority:** Network rate monitoring - Critical for performance
2. **High Priority:** View load time monitoring - Critical for UX
3. **Medium Priority:** Bundle size monitoring - Important for optimization

## Estimated Effort

- Backend API implementation: 2-3 days
- Infrastructure setup: 1-2 days
- Frontend integration: 1 day
- Dashboard configuration: 1 day
- Testing: 1 day

**Total:** 6-8 days
