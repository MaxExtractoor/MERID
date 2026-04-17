"""Capture profiling data during a paper gate run.

Polls /health/event_loop/profiles/summary periodically and saves results.
"""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime
from pathlib import Path

async def capture_profiles(output_dir: str = "./validation_results", duration: int = 300):
    """Poll profiling endpoints during gate run."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    results = {
        "captures": [],
        "start_time": datetime.now().isoformat(),
    }
    
    print(f"Capturing profiles for {duration}s...")
    
    async with aiohttp.ClientSession() as session:
        for i in range(0, duration, 30):  # Poll every 30s
            try:
                # Fetch summary
                async with session.get(
                    "http://127.0.0.1:8011/health/event_loop/profiles/summary",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        summary = await resp.json()
                        capture = {
                            "timestamp": datetime.now().isoformat(),
                            "elapsed": i,
                            "summary": summary,
                        }
                        results["captures"].append(capture)
                        
                        # Print top offenders
                        if summary.get("top_coroutines"):
                            print(f"\n[{i}s] Top offenders:")
                            for c in summary["top_coroutines"][:5]:
                                print(f"  - {c['coroutine']}: {c['count']}x")
                
                # Also fetch full profiles periodically
                if i % 60 == 0:  # Every minute
                    async with session.get(
                        "http://127.0.0.1:8011/health/event_loop/profiles",
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        if resp.status == 200:
                            profiles = await resp.json()
                            # Save to separate file
                            profile_file = output_path / f"profiles_capture_{i}s.json"
                            with open(profile_file, 'w') as f:
                                json.dump(profiles, f, indent=2)
                            print(f"  Saved {profiles.get('count', 0)} profiles to {profile_file}")
                            
            except Exception as e:
                print(f"[{i}s] Error: {e}")
            
            await asyncio.sleep(30)
    
    # Save summary
    results["end_time"] = datetime.now().isoformat()
    output_file = output_path / "profiles_capture_summary.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nProfile capture complete. Summary saved to {output_file}")
    return results

if __name__ == "__main__":
    duration = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    asyncio.run(capture_profiles(duration=duration))
