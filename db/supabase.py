from supabase import create_client
from core.env import capabilities

client = create_client(capabilities.supabase_url, capabilities.supabase_key)

# Table setups from history
# energy_events, agent_votes, consensus_results
# Use client.table('energy_events').insert({...})
