import os
import tweepy
from dotenv import load_dotenv

load_dotenv()

class MERIDTwitterAgent:
    def __init__(self):
        self.client = tweepy.Client(
            bearer_token=os.getenv('X_BEARER_TOKEN'),
            consumer_key=os.getenv('X_API_KEY'),
            consumer_secret=os.getenv('X_API_SECRET'),
            access_token=os.getenv('X_ACCESS_TOKEN'),
            access_token_secret=os.getenv('X_ACCESS_TOKEN_SECRET'),
            wait_on_rate_limit=True
        )

    def get_market_sentiment(self, query):
        try:
            search_query = f"{query} -is:retweet lang:en"
            response = self.client.search_recent_tweets(
                query=search_query, 
                max_results=10
            )
            if not response.data:
                return "No recent discussions found."
            return [t.text for t in response.data]
        except Exception as e:
            return f"X API Error: {e}"
