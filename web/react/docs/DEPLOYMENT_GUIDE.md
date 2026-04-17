# MERID React Dashboard Deployment Guide

## Overview

This guide covers deploying the MERID React dashboard to various environments, including development, staging, and production setups.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Environment Setup](#environment-setup)
- [Build Process](#build-process)
- [Deployment Options](#deployment-options)
- [Configuration](#configuration)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements

- **Node.js**: 18.x or higher
- **npm**: 9.x or higher
- **Git**: For version control
- **Docker**: (optional) For containerized deployment

### Required Dependencies

```bash
# Core dependencies
npm install react react-dom react-router-dom

# UI libraries
npm install lucide-react recharts axios

# WebSocket support
npm install socket.io-client

# Development dependencies
npm install -D @types/react @types/react-dom @types/socket.io-client
npm install -D @testing-library/react @testing-library/jest-dom
npm install -D jest @types/jest ts-jest
npm install -D vite @vitejs/plugin-react typescript
```

---

## Environment Setup

### Development Environment

1. **Clone the repository**:
```bash
git clone <repository-url>
cd merid/web/react
```

2. **Install dependencies**:
```bash
npm install
```

3. **Environment variables**:
Create `.env.development`:
```env
VITE_API_BASE=http://localhost:8000
VITE_WS_URL=ws://localhost:3000
VITE_NODE_ENV=development
```

4. **Start development server**:
```bash
npm run dev
```

### Production Environment

1. **Environment variables**:
Create `.env.production`:
```env
VITE_API_BASE=https://api.merid.com
VITE_WS_URL=wss://ws.merid.com
VITE_NODE_ENV=production
```

2. **Build the application**:
```bash
npm run build
```

3. **Preview the build**:
```bash
npm run preview
```

---

## Build Process

### Vite Configuration

The project uses Vite for fast development and optimized builds. Key configuration in `vite.config.ts`:

```typescript
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve } from 'path';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['react', 'react-dom'],
          ui: ['lucide-react', 'recharts'],
          utils: ['axios', 'socket.io-client'],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
```

### Build Optimization

The build process includes:

1. **Code splitting**: Automatic vendor chunk splitting
2. **Tree shaking**: Removal of unused code
3. **Minification**: JavaScript and CSS minification
4. **Source maps**: For debugging in production
5. **Asset optimization**: Image and font optimization

### Custom Build Scripts

```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview",
    "build:analyze": "vite build --mode analyze",
    "build:staging": "vite build --mode staging",
    "test": "jest",
    "test:watch": "jest --watch",
    "test:coverage": "jest --coverage",
    "lint": "eslint src --ext ts,tsx --report-unused-disable-directives --max-warnings 0",
    "lint:fix": "eslint src --ext ts,tsx --fix",
    "type-check": "tsc --noEmit"
  }
}
```

---

## Deployment Options

### Static Site Deployment

#### Netlify

1. **Create `netlify.toml`**:
```toml
[build]
  command = "npm run build"
  publish = "dist"

[build.environment]
  NODE_ENV = "production"
  VITE_API_BASE = "https://api.merid.com"
  VITE_WS_URL = "wss://ws.merid.com"

[[redirects]]
  from = "/*"
  to = "/index.html"
  status = 200
```

2. **Deploy**:
```bash
npm install -g netlify-cli
netlify deploy --prod --dir=dist
```

#### Vercel

1. **Create `vercel.json`**:
```json
{
  "buildCommand": "npm run build",
  "outputDirectory": "dist",
  "installCommand": "npm install",
  "framework": "vite",
  "env": {
    "VITE_API_BASE": "https://api.merid.com",
    "VITE_WS_URL": "wss://ws.merid.com"
  },
  "rewrites": [
    { "source": "/(.*)", "destination": "/index.html" }
  ]
}
```

2. **Deploy**:
```bash
npm install -g vercel
vercel --prod
```

#### GitHub Pages

1. **Configure base URL** in `vite.config.ts`:
```typescript
export default defineConfig({
  base: '/merid-dashboard/',
  // ... other config
});
```

2. **Create GitHub Actions workflow** in `.github/workflows/deploy.yml`:
```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [ main ]

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Setup Node.js
      uses: actions/setup-node@v3
      with:
        node-version: '18'
        cache: 'npm'
    
    - name: Install dependencies
      run: npm ci
    
    - name: Build
      run: npm run build
    
    - name: Deploy to GitHub Pages
      uses: peaceiris/actions-gh-pages@v3
      with:
        github_token: ${{ secrets.GITHUB_TOKEN }}
        publish_dir: ./dist
```

### Container Deployment

#### Docker

1. **Create `Dockerfile`**:
```dockerfile
# Build stage
FROM node:18-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

2. **Create `nginx.conf`**:
```nginx
server {
    listen 80;
    server_name localhost;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml application/xml+rss text/javascript;
}
```

3. **Build and run**:
```bash
docker build -t merid-dashboard .
docker run -p 80:80 merid-dashboard
```

#### Kubernetes

1. **Create deployment.yaml**:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: merid-dashboard
spec:
  replicas: 3
  selector:
    matchLabels:
      app: merid-dashboard
  template:
    metadata:
      labels:
        app: merid-dashboard
    spec:
      containers:
      - name: merid-dashboard
        image: merid-dashboard:latest
        ports:
        - containerPort: 80
        env:
        - name: VITE_API_BASE
          value: "https://api.merid.com"
        - name: VITE_WS_URL
          value: "wss://ws.merid.com"
---
apiVersion: v1
kind: Service
metadata:
  name: merid-dashboard-service
spec:
  selector:
    app: merid-dashboard
  ports:
  - port: 80
    targetPort: 80
  type: LoadBalancer
```

### Cloud Platform Deployment

#### AWS S3 + CloudFront

1. **Build and upload to S3**:
```bash
npm run build
aws s3 sync dist/ s3://your-bucket --delete
```

2. **Configure CloudFront**:
- Origin: S3 bucket
- Default root object: index.html
- Custom error pages: 403 -> index.html

#### Azure Blob Storage

1. **Upload to Azure Blob**:
```bash
npm run build
az storage blob upload-batch --source dist --destination '$web'
```

#### Google Cloud Storage

1. **Upload to GCS**:
```bash
npm run build
gsutil -m rsync -r dist/ gs://your-bucket/
```

---

## Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `VITE_API_BASE` | API base URL | `http://localhost:8000` | Yes |
| `VITE_WS_URL` | WebSocket URL | `ws://localhost:3000` | Yes |
| `VITE_NODE_ENV` | Environment | `development` | No |
| `VITE_SENTRY_DSN` | Sentry DSN | - | No |
| `VITE_GOOGLE_ANALYTICS` | GA Tracking ID | - | No |

### Runtime Configuration

The application reads configuration at runtime:

```typescript
// src/config/environment.ts
export const config = {
  apiBase: import.meta.env.VITE_API_BASE,
  wsUrl: import.meta.env.VITE_WS_URL,
  isDevelopment: import.meta.env.DEV,
  isProduction: import.meta.env.PROD,
  sentryDsn: import.meta.env.VITE_SENTRY_DSN,
  googleAnalytics: import.meta.env.VITE_GOOGLE_ANALYTICS,
};
```

### Feature Flags

Implement feature flags for gradual rollouts:

```typescript
// src/config/features.ts
export const features = {
  enableNewTradingUI: import.meta.env.VITE_ENABLE_NEW_TRADING_UI === 'true',
  enableAdvancedCharts: import.meta.env.VITE_ENABLE_ADVANCED_CHARTS === 'true',
  enableBetaFeatures: import.meta.env.VITE_ENABLE_BETA === 'true',
};
```

---

## Monitoring

### Application Monitoring

#### Sentry Integration

1. **Install Sentry**:
```bash
npm install @sentry/react @sentry/tracing
```

2. **Configure Sentry** in `src/sentry.ts`:
```typescript
import * as Sentry from '@sentry/react';
import { BrowserTracing } from '@sentry/tracing';

if (import.meta.env.PROD) {
  Sentry.init({
    dsn: import.meta.env.VITE_SENTRY_DSN,
    integrations: [new BrowserTracing()],
    tracesSampleRate: 0.1,
    environment: import.meta.env.MODE,
  });
}
```

#### Performance Monitoring

```typescript
// src/utils/performance.ts
export const performance = {
  mark: (name: string) => {
    if (import.meta.env.DEV) {
      performance.mark(name);
    }
  },
  
  measure: (name: string, startMark: string, endMark: string) => {
    if (import.meta.env.DEV) {
      performance.measure(name, startMark, endMark);
    }
  },
};
```

### Error Tracking

```typescript
// src/utils/errorReporting.ts
export const reportError = (error: Error, context?: Record<string, any>) => {
  console.error('Application error:', error, context);
  
  if (import.meta.env.PROD && window.Sentry) {
    window.Sentry.captureException(error, {
      tags: context,
    });
  }
};
```

### Analytics

#### Google Analytics

```typescript
// src/utils/analytics.ts
export const analytics = {
  track: (event: string, properties?: Record<string, any>) => {
    if (import.meta.env.PROD && window.gtag) {
      window.gtag('event', event, properties);
    }
  },
  
  pageview: (path: string) => {
    if (import.meta.env.PROD && window.gtag) {
      window.gtag('config', import.meta.env.VITE_GOOGLE_ANALYTICS, {
        page_path: path,
      });
    }
  },
};
```

---

## Troubleshooting

### Common Build Issues

#### Module Resolution Errors

**Problem**: `Cannot resolve module 'react'`

**Solution**:
```bash
npm install
npm run type-check
```

#### TypeScript Errors

**Problem**: TypeScript compilation errors

**Solution**:
```bash
npm run type-check
# Fix specific errors in tsconfig.json
```

#### Build Memory Issues

**Problem**: Out of memory during build

**Solution**:
```bash
# Increase Node.js memory limit
export NODE_OPTIONS="--max-old-space-size=8192"
npm run build
```

### Runtime Issues

#### WebSocket Connection Failures

**Problem**: WebSocket cannot connect

**Solution**:
1. Check `VITE_WS_URL` environment variable
2. Verify WebSocket server is running
3. Check network connectivity and firewall settings

#### API Request Failures

**Problem**: API requests failing

**Solution**:
1. Check `VITE_API_BASE` environment variable
2. Verify API server is accessible
3. Check CORS configuration
4. Verify authentication tokens

#### Performance Issues

**Problem**: Slow loading or poor performance

**Solution**:
1. Check bundle size with `npm run build:analyze`
2. Implement code splitting
3. Use React.memo for expensive components
4. Optimize API calls with caching

### Deployment Issues

#### 404 Errors on SPA Routes

**Problem**: Direct navigation to routes returns 404

**Solution**:
Configure server to redirect all routes to `index.html`:

**Nginx**:
```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

**Apache**:
```apache
<IfModule mod_rewrite.c>
  RewriteEngine On
  RewriteCond %{REQUEST_FILENAME} !-f
  RewriteCond %{REQUEST_FILENAME} !-d
  RewriteRule . /index.html [L]
</IfModule>
```

#### Environment Variables Not Loading

**Problem**: Environment variables undefined in production

**Solution**:
1. Ensure variables are prefixed with `VITE_`
2. Check `.env.production` file exists
3. Verify deployment platform environment settings

#### Asset Loading Issues

**Problem**: CSS, images, or fonts not loading

**Solution**:
1. Check asset paths in build output
2. Verify base URL configuration
3. Check CDN configuration if applicable

### Debugging Tools

#### Browser DevTools

1. **Console**: Check for JavaScript errors
2. **Network**: Verify API requests and WebSocket connections
3. **Performance**: Analyze loading times and bottlenecks
4. **Elements**: Inspect DOM and CSS

#### React Developer Tools

```bash
npm install -D react-devtools
```

#### Source Maps

Ensure source maps are enabled in production builds for debugging:

```typescript
// vite.config.ts
export default defineConfig({
  build: {
    sourcemap: true, // Enable source maps
  },
});
```

---

## Security Considerations

### Environment Variables

- Never commit sensitive data to version control
- Use platform-specific environment variable management
- Rotate secrets regularly

### Content Security Policy

Implement CSP headers for security:

```html
<meta http-equiv="Content-Security-Policy" 
      content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';">
```

### HTTPS Enforcement

Force HTTPS in production:

```typescript
// src/utils/security.ts
if (import.meta.env.PROD && window.location.protocol !== 'https:') {
  window.location.replace(`https:${window.location.href.substring(window.location.protocol.length)}`);
}
```

---

## Maintenance

### Regular Updates

1. **Update dependencies**:
```bash
npm outdated
npm update
```

2. **Security audits**:
```bash
npm audit
npm audit fix
```

3. **Performance monitoring**:
- Monitor bundle size
- Track Core Web Vitals
- Analyze user experience metrics

### Backup and Recovery

1. **Backup build artifacts**
2. **Document deployment process**
3. **Maintain rollback procedures**
4. **Monitor deployment health**

---

## Support

For deployment issues:

1. Check this documentation first
2. Review error logs and console output
3. Test in development environment
4. Contact the development team with detailed error information

### Additional Resources

- [Vite Documentation](https://vitejs.dev/)
- [React Documentation](https://react.dev/)
- [Deployment Platform Guides](https://docs.github.com/en/pages/getting-started-with-github-pages)
- [Web Performance Best Practices](https://web.dev/performance/)
