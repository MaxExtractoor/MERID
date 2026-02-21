# Tailwind JIT Netlify Deployment Fix

## 🎯 The Problem
Tailwind styles disappear on Netlify due to incorrect JIT (Just-In-Time) purge configuration.

---

## ✅ Quick Fix Checklist

### 1. Correct Tailwind Config
Create/update `tailwind.config.cjs`:
```javascript
module.exports = {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
```

### 2. Remove Old Purge Config
❌ **Delete these from your config:**
```javascript
// OLD - Remove these
purge: ["./src/**/*.{js,jsx,ts,tsx}"],
purge: {
  content: ["./src/**/*.{js,jsx,ts,tsx}"],
},
```

✅ **Use this instead:**
```javascript
// NEW - Tailwind v3+ syntax
content: [
  "./index.html",
  "./src/**/*.{js,jsx,ts,tsx}",
],
```

### 3. Netlify Build Settings
Update `netlify.toml`:
```toml
[build]
  command = "npm run build"
  publish = "dist"

# For Create React App
# [build]
#   command = "CI=false npm run build"
#   publish = "build"
```

### 4. PostCSS Config
Create `postcss.config.cjs`:
```javascript
module.exports = {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
```

---

## 🔧 Step-by-Step Fix

### Step 1: Backup Current Config
```bash
cp tailwind.config.js tailwind.config.backup  # if exists
```

### Step 2: Create Correct Config
```bash
cat > tailwind.config.cjs << 'EOF'
module.exports = {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
EOF
```

### Step 3: Update Package.json
```json
{
  "scripts": {
    "build": "vite build",
    "dev": "vite"
  },
  "devDependencies": {
    "autoprefixer": "^10.4.14",
    "postcss": "^8.4.24",
    "tailwindcss": "^3.3.0"
  }
}
```

### Step 4: Test Local Build
```bash
# Clean build
rm -rf dist node_modules
npm install
npm run build

# Verify CSS contains Tailwind classes
grep "bg-slate-900" dist/assets/*.css
grep "dark:" dist/assets/*.css
```

### Step 5: Deploy to Netlify
```bash
# Clear Netlify cache
# Via UI: Site settings → Build & deploy → Build cache → Clear cache

# Or trigger new build
git commit --allow-empty -m "trigger netlify rebuild"
git push
```

---

## 🚨 Common Mistakes to Avoid

### ❌ Wrong File Extension
```bash
# Wrong
tailwind.config.js    # May not be picked up by Netlify
tailwind.config.json  # Wrong format

# Correct
tailwind.config.cjs   # CommonJS for Node.js build
```

### ❌ Missing Content Paths
```javascript
// Wrong - missing HTML file
content: ["./src/**/*.{js,jsx,ts,tsx}"]

// Wrong - wrong extensions
content: ["./src/**/*.html"]

// Correct
content: [
  "./index.html",
  "./src/**/*.{js,jsx,ts,tsx}",
]
```

### ❌ Old Purge Syntax
```javascript
// Wrong - Tailwind v2 syntax
purge: ["./src/**/*.{js,jsx,ts,tsx}"]

// Correct - Tailwind v3 syntax
content: ["./src/**/*.{js,jsx,ts,tsx}"]
```

### ❌ Wrong Build Directory
```toml
# Wrong for Vite
[build]
  publish = "build"  # Vite uses 'dist'

# Correct for Vite
[build]
  publish = "dist"
```

---

## 🔍 Troubleshooting

### Check Build Output
```bash
# After local build
ls -la dist/assets/
# Should see CSS files with Tailwind classes

# Check specific classes
grep -o "bg-slate-[0-9]\+" dist/assets/*.css
grep -o "dark:bg-" dist/assets/*.css
```

### Verify Tailwind Processing
```bash
# Build with verbose output
npm run build -- --mode production

# Look for these logs:
# "Rebuilding..."
# "Tailwind CSS processing..."
```

### Debug Netlify Build
```bash
# Check Netlify build logs
# In Netlify UI: Deploys → Select build → View build log

# Look for:
# "PostCSS found tailwindcss"
# "Tailwind CSS compilation successful"
```

---

## 🚀 Automated Fix Script

### Quick Fix Script
```bash
#!/bin/bash
# fix-tailwind-netlify.sh

echo "🔧 Fixing Tailwind for Netlify..."

# Create correct tailwind config
cat > tailwind.config.cjs << 'EOF'
module.exports = {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
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

# Update netlify.toml
cat > netlify.toml << 'EOF'
[build]
  command = "npm run build"
  publish = "dist"

[build.environment]
  VITE_API_BASE = "https://api.merid.com"
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

# Verify
if grep -q "bg-slate-900" dist/assets/*.css; then
  echo "✅ Tailwind fix successful!"
  echo "🚀 Ready to deploy to Netlify"
else
  echo "❌ Tailwind classes not found in build"
  echo "🔍 Check the build output above"
fi
```

### Usage
```bash
chmod +x fix-tailwind-netlify.sh
./fix-tailwind-netlify.sh
```

---

## 📋 Final Verification Checklist

### Before Deploy
- [ ] `tailwind.config.cjs` exists with correct `content` paths
- [ ] `postcss.config.cjs` exists
- [ ] No old `purge` keys in config
- [ ] CSS file imports `@tailwind` directives
- [ ] Local `npm run build` works
- [ ] `dist/assets/` contains CSS with Tailwind classes

### After Deploy
- [ ] Site loads without unstyled flash
- [ ] Dark mode toggle works
- [ ] Responsive classes work
- [ ] Custom utilities work
- [ ] No "CSS not found" errors in console

### If Still Broken
1. Clear Netlify build cache
2. Check Netlify build logs for Tailwind processing
3. Verify base directory setting (if repo is nested)
4. Ensure `src/` directory structure is correct
5. Check for CSS import errors in main entry point

---

## 🎯 One-Command Solution

If you want the fastest fix:

```bash
# Replace your config with this working version
cat > tailwind.config.cjs << 'EOF'
module.exports = {
  darkMode: "class",
  content: [
    "./index.html",
    "./src/**/*.{js,jsx,ts,tsx}",
  ],
  theme: { extend: {} },
  plugins: [],
};
EOF

# Rebuild and deploy
npm run build
git add .
git commit -m "fix tailwind config for netlify"
git push
```

This should resolve 99% of Tailwind deployment issues on Netlify.
