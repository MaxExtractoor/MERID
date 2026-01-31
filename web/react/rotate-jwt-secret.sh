#!/usr/bin/env bash
set -euo pipefail

PROJECT="merid-backend"
SCOPE="your-team-or-user"

NEW_SECRET=$(openssl rand -base64 48)

echo "🔄 Creating new JWT secret..."
vercel env add JWT_SECRET_KEY_NEXT production <<< "$NEW_SECRET" --project $PROJECT --scope $SCOPE

echo "🚀 Deploy backend that reads both JWT_SECRET_KEY and JWT_SECRET_KEY_NEXT for verification and signs with NEXT..."
echo "   (you push code and run 'vercel deploy --prod' here)"

echo "⏳ Once traffic is on new version and old tokens mostly expired:"
echo "   - Move JWT_SECRET_KEY_NEXT value into JWT_SECRET_KEY in Vercel dashboard"
echo "   - Remove JWT_SECRET_KEY_NEXT"

echo "✅ JWT secret rotation initiated!"
echo "📋 Next steps:"
echo "   1. Deploy code that supports both secrets"
echo "   2. Wait for old tokens to expire (24-48 hours)"
echo "   3. Complete rotation in Vercel dashboard"
echo "   4. Remove grace period code"
