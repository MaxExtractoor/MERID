#!/usr/bin/env python3
"""
ANALYZE KALSHI CRYPTO DATA FROM API

We have 26 markets classified as "crypto" but they look like sports markets.
Let me analyze the actual data to find real crypto markets.
"""

import asyncio
import json
import os
import re
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

async def analyze_kalshi_markets():
    """Analyze the Kalshi markets to find real crypto markets."""
    print("🔍 ANALYZING KALSHI MARKETS FOR REAL CRYPTO")
    print("=" * 60)
    
    try:
        import httpx
        
        # Use the working API configuration
        api_key_id = os.getenv('KALSHI_API_KEY_ID')
        private_key_path = os.getenv('KALSHI_PRIVATE_KEY_PATH')
        base_url = "https://api.elections.kalshi.com"
        
        print(f"📡 Using API: {base_url}")
        print(f"🔑 API Key: {api_key_id[:8] if api_key_id else 'None'}...")
        
        # Get markets
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/trade-api/v2/markets",
                params={"limit": 1000},
                timeout=30.0
            )
            
            if response.status_code != 200:
                print(f"❌ API Error: {response.status_code}")
                return
            
            markets = response.json().get("markets", [])
            print(f"📊 Total markets retrieved: {len(markets)}")
        
        # Analyze market patterns
        ticker_patterns = {}
        crypto_candidates = []
        real_crypto_markets = []
        
        for market in markets:
            ticker = market.get("ticker", "")
            title = market.get("title", "").lower()
            subtitle = market.get("subtitle", "").lower()
            
            # Extract ticker prefix
            if '-' in ticker:
                prefix = ticker.split('-')[0]
                ticker_patterns[prefix] = ticker_patterns.get(prefix, 0) + 1
            
            # Look for actual crypto indicators
            crypto_keywords = ['bitcoin', 'btc', 'ethereum', 'eth', 'solana', 'sol', 'crypto']
            price_keywords = ['price', 'high', 'low', 'close', 'usd', '$']
            
            # Check for crypto + price indicators
            crypto_score = 0
            crypto_matches = []
            
            # Title analysis
            for keyword in crypto_keywords:
                if keyword in title:
                    crypto_score += 3
                    crypto_matches.append(f"title:{keyword}")
            
            # Price indicators
            for keyword in price_keywords:
                if keyword in title:
                    crypto_score += 1
                    crypto_matches.append(f"price:{keyword}")
            
            # Ticker analysis
            ticker_upper = ticker.upper()
            for keyword in ['BTC', 'ETH', 'SOL', 'CRYPTO']:
                if keyword in ticker_upper:
                    crypto_score += 2
                    crypto_matches.append(f"ticker:{keyword}")
            
            # Check for CF Benchmarks or indices
            if any(indicator in title for indicator in ['cfb', 'rti', 'cme', 'index']):
                crypto_score += 2
                crypto_matches.append("index")
            
            if crypto_score >= 3:  # Threshold for crypto market
                crypto_candidates.append({
                    'ticker': ticker,
                    'title': market.get("title", ""),
                    'subtitle': market.get("subtitle", ""),
                    'crypto_score': crypto_score,
                    'crypto_matches': crypto_matches,
                    'close_time': market.get("close_time"),
                    'status': market.get("status")
                })
            
            # Look for very specific crypto patterns
            if (any(keyword in title for keyword in ['bitcoin', 'btc']) and 
                any(keyword in title for keyword in ['price', 'high', 'low', 'close'])):
                real_crypto_markets.append({
                    'ticker': ticker,
                    'title': market.get("title", ""),
                    'subtitle': market.get("subtitle", ""),
                    'close_time': market.get("close_time"),
                    'status': market.get("status")
                })
        
        print(f"\n📊 TICKER PATTERNS:")
        for pattern, count in sorted(ticker_patterns.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  - {pattern}: {count} markets")
        
        print(f"\n💰 CRYPTO CANDIDATES (score >= 3): {len(crypto_candidates)}")
        
        if crypto_candidates:
            print(f"\n🔍 TOP CRYPTO CANDIDATES:")
            for market in crypto_candidates[:10]:
                print(f"  💰 Score {market['crypto_score']}: {market['ticker']}")
                print(f"     Title: {market['title'][:80]}...")
                print(f"     Matches: {', '.join(market['crypto_matches'])}")
                print(f"     Status: {market['status']}")
                print()
        
        print(f"\n🎯 REAL CRYPTO MARKETS (crypto + price): {len(real_crypto_markets)}")
        
        if real_crypto_markets:
            print(f"\n💎 REAL CRYPTO MARKETS:")
            for market in real_crypto_markets:
                print(f"  💎 {market['ticker']}")
                print(f"     Title: {market['title']}")
                print(f"     Status: {market['status']}")
                print(f"     Close: {market['close_time']}")
                print()
        else:
            print(f"❌ No real crypto markets found with current data")
        
        # Check what our current classification thinks is crypto
        currently_classified_crypto = []
        for market in markets:
            title = market.get("title", "").lower()
            
            # Our current (incorrect) classification logic
            if any(keyword in title for keyword in ['ada', 'crypto']):  # This was catching sports player names
                currently_classified_crypto.append({
                    'ticker': market.get("ticker", ""),
                    'title': market.get("title", ""),
                    'reason': 'contains ada/crypto keyword'
                })
        
        print(f"\n❌ CURRENTLY MISCLASSIFIED AS CRYPTO: {len(currently_classified_crypto)}")
        for market in currently_classified_crypto[:5]:
            print(f"  - {market['ticker']}: {market['title'][:60]}... ({market['reason']})")
        
        # Summary
        print(f"\n📊 ANALYSIS SUMMARY:")
        print(f"  Total markets: {len(markets)}")
        print(f"  Crypto candidates (score >= 3): {len(crypto_candidates)}")
        print(f"  Real crypto markets: {len(real_crypto_markets)}")
        print(f"  Misclassified markets: {len(currently_classified_crypto)}")
        
        if real_crypto_markets:
            print(f"\n🎉 SUCCESS! Found {len(real_crypto_markets)} real crypto markets")
        else:
            print(f"\n⚠️  No real crypto markets found")
            print(f"  Possible reasons:")
            print(f"    1. Account doesn't have crypto market access")
            print(f"    2. Crypto markets use different naming patterns")
            print(f"    3. Need different API endpoint for crypto markets")
        
        # Save analysis
        analysis = {
            "timestamp": datetime.now().isoformat(),
            "total_markets": len(markets),
            "ticker_patterns": dict(list(ticker_patterns.items())[:20]),
            "crypto_candidates": len(crypto_candidates),
            "real_crypto_markets": len(real_crypto_markets),
            "misclassified_crypto": len(currently_classified_crypto),
            "real_crypto_examples": real_crypto_markets[:5],
            "top_crypto_candidates": crypto_candidates[:10]
        }
        
        with open('kalshi_crypto_analysis.json', 'w') as f:
            json.dump(analysis, f, indent=2)
        
        print(f"\n📋 Analysis saved to: kalshi_crypto_analysis.json")
        
        return len(real_crypto_markets) > 0
        
    except Exception as e:
        print(f"❌ Analysis failed: {e}")
        return False

async def main():
    """Main function."""
    print("🚀 ANALYZE KALSHI CRYPTO DATA")
    print("=" * 50)
    
    success = await analyze_kalshi_markets()
    
    if success:
        print(f"\n🎉 REAL CRYPTO MARKETS FOUND!")
        print(f"  Next step: Update classification logic")
    else:
        print(f"\n⚠️  NO REAL CRYPTO MARKETS FOUND")
        print(f"  Need to investigate API access or endpoints")

if __name__ == "__main__":
    asyncio.run(main())
