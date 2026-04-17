import re
import json

def clean_json_response(raw_text):
    # If the agent already returned a dict, just return it
    if isinstance(raw_text, dict):
        return raw_text
        
    try:
        if not isinstance(raw_text, str):
            raw_text = str(raw_text)
            
        # Use a non-greedy search to find the FIRST occurrence of { and LAST of }
        # This handles cases where the LLM adds extra text before or after the JSON.
        json_match = re.search(r'(\{.*\}|\[.*\])', raw_text, re.DOTALL)
        if json_match:
            clean_text = json_match.group(1)
        else:
            clean_text = raw_text
            
        return json.loads(clean_text)
    except Exception as e:
        print(f"Parsing error: {e}")
        return None