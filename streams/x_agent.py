import asyncio
import tweepy
import time
from queue import PriorityQueue
from core.env import capabilities
from core.energy import create_energy
from core.orchestrator import MeridCore

# Tweepy v1.1 API for posting (uses your keys)
auth = tweepy.OAuth1UserHandler(
    capabilities.x_api_key,
    capabilities.x_api_secret,
    capabilities.x_access_token,
    capabilities.x_access_token_secret
)
api = tweepy.API(auth)

# Priority queue for posts (higher consensus = higher priority)
post_queue = PriorityQueue()
last_post_time = 0

merid = MeridCore()

async def scan_and_post():
    global last_post_time
    print("[X Agent] Started — scanning X and posting approved consensus")
    while True:
        try:
            # Scan X for crypto keywords
            tweets = api.search_tweets(q="BTC OR ETH OR crypto lang:en -is:retweet", count=50, tweet_mode="extended")
            for tweet in tweets:
                payload = tweet.full_text
                energy = create_energy("x", payload)
                result = await merid.run_cycle(energy)
                
                if result["approved"] and result["consensus"] >= 0.75:
                    content = f"MERID Reality: {result['consensus']:.1%} consensus on crypto signal. @grok"
                    priority = -result["consensus"]  # Negative for max-heap (higher first)
                    post_queue.put((priority, content))
            
            # Post if queue has items and cooldown passed (max 1 post/hour)
            if not post_queue.empty() and time.time() - last_post_time > 3600:
                priority, content = post_queue.get()
                api.update_status(content)
                last_post_time = time.time()
                print(f"[X Agent] Posted: {content}")
                
        except Exception as e:
            print(f"[X Agent] Error: {e}")
        
        await asyncio.sleep(300)  # Scan every 5 min

if __name__ == "__main__":
    asyncio.run(scan_and_post())
