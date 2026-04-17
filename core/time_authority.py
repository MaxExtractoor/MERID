from datetime import datetime, timezone
import time

def current_time():
    now = datetime.now(timezone.utc)
    return {
        "utc_iso": now.isoformat(),
        "unix": int(time.time())
    }
