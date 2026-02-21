#!/usr/bin/env python3
"""Quick Ollama connectivity test."""

import requests
import time

def test_ollama():
    """Test Ollama /api/generate endpoint."""
    
    print("Testing Ollama connectivity...")
    
    # 1. Test /api/tags
    print("\n1. Testing /api/tags...")
    try:
        resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=5)
        print(f"   Status: {resp.status_code}")
        models = resp.json().get("models", [])
        print(f"   Models: {len(models)} found")
        for m in models:
            print(f"     - {m['name']} ({m['size'] / 1e9:.2f} GB)")
    except Exception as e:
        print(f"   ERROR: {e}")
        return
    
    # 2. Test /api/generate with simple prompt
    print("\n2. Testing /api/generate (this may take 30-60s on first load)...")
    payload = {
        "model": "gemma3:1b",
        "prompt": "What is 2+2? Answer in one word only.",
        "stream": False,
        "options": {
            "num_predict": 10,
            "temperature": 0.0
        }
    }
    
    start = time.time()
    try:
        print("   Sending request...")
        resp = requests.post(
            "http://127.0.0.1:11434/api/generate",
            json=payload,
            timeout=120  # 2 minute timeout for first model load
        )
        elapsed = time.time() - start
        
        print(f"   Status: {resp.status_code}")
        print(f"   Time: {elapsed:.1f}s")
        
        if resp.status_code == 200:
            data = resp.json()
            response_text = data.get("response", "")
            print(f"   Response: {response_text[:200]}")
            print(f"   Done: {data.get('done', False)}")
            
            if data.get("done"):
                print("\n✓ Ollama is working correctly!")
                print(f"  Model loaded in {elapsed:.1f}s")
                return True
        else:
            print(f"   ERROR: {resp.text}")
            
    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        print(f"   TIMEOUT after {elapsed:.1f}s")
        print("   Model may be too large or Ollama is stuck")
    except Exception as e:
        print(f"   ERROR: {e}")
    
    return False

if __name__ == "__main__":
    success = test_ollama()
    if not success:
        print("\n⚠ Ollama has issues - MERID agents will use stub responses")
        print("\nTroubleshooting:")
        print("  1. Check if model is too large: ollama list")
        print("  2. Try smaller model: ollama pull gemma2:2b")
        print("  3. Check Ollama logs for errors")
        print("  4. Restart Ollama: taskkill /F /IM ollama.exe && ollama serve")
