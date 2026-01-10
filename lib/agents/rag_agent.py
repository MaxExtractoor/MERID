import json
import sys
from pathlib import Path

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)

# Read input
input_data = sys.stdin.read().strip()

if not input_data:
    print('{"error": "No input received"}')
    sys.exit(0)

try:
    params = json.loads(input_data)
except:
    print('{"error": "Invalid JSON input"}')
    sys.exit(0)

query = params.get("query", "")
directory = params.get("directory", "C:\\Dev\\MERID\\knowledge")

dir_path = Path(directory)

result = {
    "query": query,
    "directory": str(dir_path),
    "files_found": [],
    "content": "",
    "status": "processing"
}

if not dir_path.exists():
    result["status"] = "error"
    result["message"] = "Knowledge directory not found"
else:
    txt_files = list(dir_path.glob("*.txt"))
    result["files_found"] = [f.name for f in txt_files]
    
    if not txt_files:
        result["status"] = "empty"
        result["message"] = "No .txt files found"
    else:
        content_parts = []
        for file_path in txt_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                content_parts.append(f"=== {file_path.name} ===\n{content.strip()}")
            except Exception as e:
                content_parts.append(f"ERROR reading {file_path.name}: {str(e)}")
        
        result["content"] = "\n\n".join(content_parts)
        result["status"] = "success"
        result["message"] = f"Loaded {len(txt_files)} file(s)"

# FINAL OUTPUT — UNBUFFERED
print(json.dumps(result))
sys.stdout.flush()
sys.exit(0)
