import sys
import os
from openai import OpenAI
from twitter_agent import MERIDTwitterAgent
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# Setup Clients
local_client = OpenAI(base_url='http://localhost:11434/v1/', api_key='ollama')
cloud_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
twitter = MERIDTwitterAgent()
supabase = create_client(os.getenv('SUPABASE_URL'), os.getenv('SUPABASE_KEY'))

def save_report(query, summary, tweets):
    try:
        data = {
            "query": query,
            "sentiment_summary": summary,
            "raw_tweets": tweets if isinstance(tweets, list) else [tweets]
        }
        supabase.table("sentiment_reports").insert(data).execute()
        print("--- [Supabase] Report Logged Successfully ---")
    except Exception as e:
        print(f"--- [Supabase] Error: {e} ---")

def run_relay(user_query):
    print(f'--- [MERID] Analyzing Query Locally ---')
    try:
        analysis = local_client.chat.completions.create(
            model='merid-strategist',
            messages=[{'role': 'system', 'content': 'Reply ONLY with RELAY if live data is needed.'}, 
                      {'role': 'user', 'content': user_query}]
        )
        decision = analysis.choices[0].message.content.strip()
        
        if 'RELAY' in decision.upper():
            tweets = twitter.get_market_sentiment(user_query)
            context = "\n".join(tweets) if isinstance(tweets, list) else tweets
            
            cloud_res = cloud_client.chat.completions.create(
                model='gpt-4o',
                messages=[{'role': 'system', 'content': f'Context: {context}'}, {'role': 'user', 'content': user_query}]
            )
            summary = cloud_res.choices[0].message.content
            
            # Persist to Supabase
            save_report(user_query, summary, tweets)
            
            return f"\n[MERID-X-RELAY]: {summary}"
        
        return f"\n[MERID-LOCAL]: {decision}"
    except Exception as e:
        return f'Error: {e}'

if __name__ == '__main__':
    query = ' '.join(sys.argv[1:]) if len(sys.argv) > 1 else 'Bitcoin vibe'
    print(run_relay(query))
