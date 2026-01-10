from dotenv import load_dotenv
import os
from agents.registry import load_agents

load_dotenv()
print(os.getenv("SUPABASE_URL"))
print(os.getenv("NEO4J_URI"))

agents = load_agents()
print([a.agent_id for a in agents])
