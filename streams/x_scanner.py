from core.env import capabilities
from twitter_api import TwitterAPI  # Assume pip install twitter-api-v2
from core.energy import create_energy
from core.orchestrator import get_core
from queue import PriorityQueue
import asyncio, time

api = TwitterAPI(consumer_key=capabilities.x_api_key, consumer_secret=capabilities.x_api_secret, access_token=capabilities.x_access_token, access_secret=capabilities.x_access_token_secret)

post_queue = PriorityQueue()  # (priority, content) — higher consensus = higher priority
last_post = 0.0

async def scan_x():
    while True:
        # Scan X for keywords (e.g., BTC)
        posts = api.search_tweets("BTC lang:en -is:retweet", count=50, tweet_mode="extended")
        for post in posts:
            payload = post.full_text
            energy = create_energy("x", payload)
            result = await get_core().run_cycle(energy)
            
            if result["approved"]:
                post_content = f"MERID Consensus: {result['consensus']:.1%} on '{payload[:100]}...' #Crypto @grok"
                priority = result["consensus"]  # Higher % = higher priority
                post_queue.put((priority, post_content))
        
        # Post from queue if time since last post > 3600s (1/hour max)
        if not post_queue.empty() and time.time() - last_post > 3600:
            priority, content = post_queue.get()
            api.update_status(content)
            last_post = time.time()
            print(f"Posted to X: {content}")

        await asyncio.sleep(300)  # Scan every 5 min

asyncio.run(scan_x())
