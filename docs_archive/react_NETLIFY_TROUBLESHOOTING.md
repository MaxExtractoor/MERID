# Netlify Tailwind Troubleshooting Guide

## Common Issue: Tailwind Styles Disappear

### Root Cause
Incorrect `content`/`purge` configuration causing Tailwind to remove all classes during build.

---

## ✅ Fix: Correct Tailwind Config

### Create/Update `tailwind.config.cjs`
```javascript
module.exports = {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
```

### Key Points
- ✅ Use `content` (not `purge`) for Tailwind v3+
- ✅ Include `./index.html` for Vite projects
- ✅ Include all React file extensions: `{js,ts,jsx,tsx}`
- ✅ Remove any old `purge` keys

---

## ✅ Fix: Netlify Build Configuration

### Update `netlify.toml`
```toml
[build]
  command = "npm run build"
  publish = "dist"

[build.environment]
  VITE_API_BASE = "https://api.merid.com"
  VITE_WS_URL = "wss://api.merid.com"
```

### For Create React App
```toml
[build]
  command = "CI=false npm run build"
  publish = "build"
```

---

## ✅ Fix: PostCSS Configuration

### Create `postcss.config.cjs`
```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

---

## ✅ Fix: CSS Import

### Ensure Tailwind CSS is imported
```css
/* src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;
```

### Import in main entry point
```typescript
// src/main.tsx or src/index.tsx
import './index.css';
import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

---

## ✅ Fix: Package.json Scripts

### Ensure build script includes PostCSS
```json
{
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0"
  },
  "devDependencies": {
    "@types/react": "^18.2.0",
    "@types/react-dom": "^18.2.0",
    "@vitejs/plugin-react": "^4.0.0",
    "autoprefixer": "^10.4.14",
    "postcss": "^8.4.24",
    "tailwindcss": "^3.3.0",
    "typescript": "^5.0.2",
    "vite": "^4.3.9"
  }
}
```

---

## ✅ Fix: Vite Configuration

### Update `vite.config.ts`
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  css: {
    postcss: './postcss.config.cjs',
  },
})
```

---

## 🔧 Troubleshooting Steps

### 1. Verify Local Build
```bash
# Clean build
rm -rf dist node_modules
npm install
npm run build

# Check dist folder contains CSS
ls -la dist/assets/
# Should see .css files with Tailwind classes
```

### 2. Check Tailwind Compilation
```bash
# Build with verbose output
npm run build -- --mode production

# Look for Tailwind processing in output
# Should see "Rebuilding..." messages
```

### 3. Test CSS Output
```bash
# Check if Tailwind classes are in final CSS
grep "bg-slate-900" dist/assets/*.css
grep "dark:" dist/assets/*.css
```

### 4. Clear Netlify Cache
```bash
# Via Netlify UI
# Site Settings → Build & Deploy → Build cache → Clear cache

# Or trigger new build
git commit --allow-empty -m "trigger rebuild"
git push
```

---

## 🚨 Common Mistakes to Avoid

### ❌ Wrong Config File Name
```bash
# Wrong
tailwind.config.js    # May not be picked up
tailwind.json         # Wrong format

# Correct
tailwind.config.cjs   # CommonJS for Node.js
tailwind.config.js    # ES Module (if package.json type: module)
```

### ❌ Missing Content Paths
```javascript
// Wrong - missing React files
content: ["./index.html"]

// Wrong - wrong extensions
content: ["./src/**/*.html"]

// Correct
content: [
  "./index.html",
  "./src/**/*.{js,ts,jsx,tsx}",
]
```

### ❌ Old Purge Syntax
```javascript
// Wrong - Tailwind v2 syntax
purge: ["./src/**/*.{js,jsx,ts,tsx}"]

// Correct - Tailwind v3 syntax
content: ["./src/**/*.{js,jsx,ts,tsx}"]
```

### ❌ Missing CSS Import
```typescript
// Wrong - CSS not imported
import React from 'react';
import App from './App';

// Correct - CSS imported first
import './index.css';
import React from 'react';
import App from './App';
```

---

## ✅ Verification Checklist

### Before Deployment
- [ ] `tailwind.config.cjs` exists with correct `content` paths
- [ ] `postcss.config.cjs` exists
- [ ] CSS file imports `@tailwind` directives
- [ ] Main entry point imports CSS
- [ ] Local `npm run build` works
- [ ] `dist/assets/` contains CSS files
- [ ] CSS files contain Tailwind classes

### After Deployment
- [ ] Site loads without unstyled content
- [ ] Dark mode toggle works
- [ ] Responsive classes work
- [ ] Custom Tailwind utilities work
- [ ] No "CSS not found" errors in console

---

## 🚀 Quick Fix Script

### Automated Fix
```bash
#!/bin/bash
# fix-tailwind.sh

echo "🔧 Fixing Tailwind configuration..."

# Create correct tailwind config
cat > tailwind.config.cjs << 'EOF'
module.exports = {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
EOF

# Create postcss config
cat > postcss.config.cjs << 'EOF'
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
EOF

# Ensure CSS import
if ! grep -q "@tailwind" src/index.css; then
  echo '@tailwind base;
@tailwind components;
@tailwind utilities;' > src/index.css
fi

# Rebuild
npm install
npm run build

echo "✅ Tailwind configuration fixed!"
echo "🚀 Deploy to Netlify"
```

Run with: `chmod +x fix-tailwind.sh && ./fix-tailwind.sh`

---

This guide should resolve 99% of Tailwind deployment issues on Netlify.
