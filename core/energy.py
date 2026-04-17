import uuid
from core.time_authority import current_time

def create_energy(source, payload):
    return {
        "energy_id": str(uuid.uuid4()),
        "timestamp": current_time(),
        "source": source,
        "payload": payload,
        "entropy": None,
        "novelty": None,
        "status": "unprocessed"
    }

