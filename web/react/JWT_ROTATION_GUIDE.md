# JWT Secret Rotation Guide for MERID

## 🔒 Vercel Environment Variables Setup

### Backend Project (Server-Side Only)
In Vercel → Project → Settings → Environment Variables:

```
JWT_SECRET_KEY=your_current_jwt_secret_here
REFRESH_TOKEN_SECRET=your_current_refresh_secret_here
MERID_DASHBOARD_API_KEY=your_dashboard_api_key_here
```

**Critical Rules:**
- ✅ Mark as **"Sensitive"** variables
- ❌ **NEVER** prefix with `NEXT_PUBLIC_` or `VITE_`
- ✅ Only accessible in server-side code

---

## 🔄 Secret Rotation Workflow

### Step 1: Generate New Secret
```bash
# Generate new JWT secret (32+ characters recommended)
openssl rand -base64 32
# Output: abc123def456ghi789jkl012mno345pq

# Or use Node.js
node -e "console.log(require('crypto').randomBytes(32).toString('base64'))"
```

### Step 2: Add New Secret to Vercel
In Vercel → Project → Settings → Environment Variables:
```
JWT_SECRET_KEY_NEXT=abc123def456ghi789jkl012mno345pq
```

### Step 3: Grace Period Implementation (Optional)

#### Backend Code - Accept Both Keys
```javascript
import jwt from "jsonwebtoken";

const JWT_SECRETS = [
  process.env.JWT_SECRET_KEY,           // Current
  process.env.JWT_SECRET_KEY_NEXT,       // New
].filter(Boolean); // Remove undefined

export function signToken(payload) {
  // Sign with new key
  return jwt.sign(payload, process.env.JWT_SECRET_KEY_NEXT || process.env.JWT_SECRET_KEY);
}

export function verifyToken(token) {
  // Try each secret
  for (const secret of JWT_SECRETS) {
    try {
      return jwt.verify(token, secret);
    } catch (err) {
      if (err.name !== "JsonWebTokenError") throw err;
      continue; // Try next secret
    }
  }
  throw new Error("Invalid token");
}
```

#### FastAPI Version
```python
import jwt
import os

JWT_SECRETS = [
    os.getenv("JWT_SECRET_KEY"),
    os.getenv("JWT_SECRET_KEY_NEXT"),
]
JWT_SECRETS = [s for s in JWT_SECRETS if s]  # Remove None

def sign_token(payload: dict) -> str:
    # Sign with new key if available, else current
    secret = os.getenv("JWT_SECRET_KEY_NEXT") or os.getenv("JWT_SECRET_KEY")
    return jwt.encode(payload, secret, algorithm="HS256")

def verify_token(token: str) -> dict:
    for secret in JWT_SECRETS:
        try:
            return jwt.decode(token, secret, algorithms=["HS256"])
        except jwt.InvalidTokenError:
            continue
    raise jwt.InvalidTokenError("Invalid token")
```

### Step 4: Deploy and Monitor
```bash
# Deploy backend with grace period code
vercel --prod

# Monitor for errors
vercel logs

# Wait for old tokens to expire (typically 24-48 hours)
```

### Step 5: Complete Rotation
1. Move `JWT_SECRET_KEY_NEXT` → `JWT_SECRET_KEY`
2. Delete old `JWT_SECRET_KEY` value
3. Remove grace period code (optional)

---

## 🚀 Automated Rotation (Advanced)

### Vercel Marketplace Integration API
```javascript
// Example: Programmatically rotate secrets
const VERCEL_TOKEN = process.env.VERCEL_TOKEN;
const PROJECT_ID = "prj_xxx";

async function rotateSecret(projectId, secretName, newValue) {
  const response = await fetch(
    `https://api.vercel.com/v1/projects/${projectId}/env`,
    {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${VERCEL_TOKEN}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        key: secretName,
        value: newValue,
        type: 'secret',
        target: ['production'],
      }),
    }
  );
  
  return response.json();
}

// Usage
const newSecret = generateSecret();
await rotateSecret(PROJECT_ID, 'JWT_SECRET_KEY_NEXT', newSecret);
```

### GitHub Actions Rotation
```yaml
# .github/workflows/rotate-secrets.yml
name: Rotate JWT Secrets

on:
  schedule:
    - cron: '0 2 * * 0'  # Weekly on Sunday 2 AM

jobs:
  rotate:
    runs-on: ubuntu-latest
    steps:
      - name: Generate new secret
        id: secret
        run: |
          NEW_SECRET=$(openssl rand -base64 32)
          echo "::add-mask::$NEW_SECRET"
          echo "secret=$NEW_SECRET" >> $GITHUB_OUTPUT
      
      - name: Update Vercel env
        run: |
          curl -X POST "https://api.vercel.com/v1/projects/${{ secrets.PROJECT_ID }}/env" \
            -H "Authorization: Bearer ${{ secrets.VERCEL_TOKEN }}" \
            -H "Content-Type: application/json" \
            -d '{
              "key": "JWT_SECRET_KEY_NEXT",
              "value": "${{ steps.secret.outputs.secret }}",
              "type": "secret",
              "target": ["production"]
            }'
```

---

## 🔍 Verification Checklist

### Before Rotation
- [ ] Current JWT secret working
- [ ] Token refresh endpoint functional
- [ ] Monitoring/logging in place
- [ ] Backup of current secrets

### During Rotation
- [ ] New secret added as `_NEXT` variant
- [ ] Grace period code deployed
- [ ] New tokens being signed with new secret
- [ ] Old tokens still accepted

### After Rotation
- [ ] Old tokens expired (24-48 hours)
- [ ] `JWT_SECRET_KEY_NEXT` moved to `JWT_SECRET_KEY`
- [ ] Old secret removed
- [ ] Grace period code cleaned up
- [ ] All functionality verified

---

## 🚨 Troubleshooting

### Common Issues

#### Tokens Invalid After Rotation
```bash
# Check if new secret is set
vercel env ls JWT_SECRET_KEY

# Verify token signing
node -e "
const jwt = require('jsonwebtoken');
const token = jwt.sign({test: true}, process.env.JWT_SECRET_KEY);
console.log('Token:', token);
console.log('Verify:', jwt.verify(token, process.env.JWT_SECRET_KEY));
"
```

#### Frontend Can't Connect
```bash
# Check environment variables
vercel env ls VITE_API_BASE

# Verify backend is using correct secret
curl -X POST https://api.merid.com/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test","password":"test"}'
```

#### Grace Period Issues
```javascript
// Debug multiple secrets
console.log('Available secrets:', JWT_SECRETS.length);
console.log('Current secret:', !!process.env.JWT_SECRET_KEY);
console.log('Next secret:', !!process.env.JWT_SECRET_KEY_NEXT);
```

---

## 📋 Quick Commands

### Manual Rotation
```bash
# 1. Generate new secret
NEW_SECRET=$(openssl rand -base64 32)

# 2. Add to Vercel
vercel env add JWT_SECRET_KEY_NEXT

# 3. Deploy
vercel --prod

# 4. Wait (monitor logs)
vercel logs

# 5. Complete rotation
vercel env rm JWT_SECRET_KEY
vercel env add JWT_SECRET_KEY  # with new value
vercel env rm JWT_SECRET_KEY_NEXT
```

### Verify Rotation
```bash
# Test token with old secret
OLD_TOKEN=$(curl -s -X POST https://api.merid.com/auth/login -d '{"email":"test","password":"test"}' | jq -r .access_token)

# Test token with new secret (after grace period)
NEW_TOKEN=$(curl -s -X POST https://api.merid.com/auth/login -d '{"email":"test","password":"test"}' | jq -r .access_token)

# Verify both work during grace period
curl -H "Authorization: Bearer $OLD_TOKEN" https://api.merid.com/api/v1/portfolio/summary
curl -H "Authorization: Bearer $NEW_TOKEN" https://api.merid.com/api/v1/portfolio/summary
```

---

This rotation process ensures zero-downtime JWT secret updates while maintaining security for the MERID platform.
