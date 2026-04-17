import os

KEYWORDS = ["swarm", "agent", "promotion", "domain"]
MAX_HITS = 200
BASE_DIRS = ["merid", "web"]
TARGET_EXTENSIONS = (".py", ".tsx")
OUTPUT_FILE = "swarm_agent_hits.txt"

hits = 0
with open(OUTPUT_FILE, "w", encoding="utf-8") as out:
    for base in BASE_DIRS:
        for root, _, files in os.walk(base):
            if hits >= MAX_HITS:
                break
            for fname in files:
                if hits >= MAX_HITS:
                    break
                if not fname.lower().endswith(TARGET_EXTENSIONS):
                    continue
                path = os.path.join(root, fname)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        for lineno, line in enumerate(fh, 1):
                            if hits >= MAX_HITS:
                                break
                            stripped = line.strip()
                            if not stripped.startswith("#"):
                                continue
                            lower = stripped.lower()
                            if any(keyword in lower for keyword in KEYWORDS):
                                snippet = stripped
                                if len(snippet) > 200:
                                    snippet = snippet[:200] + "..."
                                out.write(f"{path}:{lineno}:{snippet}\n")
                                hits += 1
                                if hits >= MAX_HITS:
                                    break
                except Exception:
                    continue
            if hits >= MAX_HITS:
                break
        if hits >= MAX_HITS:
            break
print(f"Saved {hits} hits to {OUTPUT_FILE}")
