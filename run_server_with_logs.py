import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

# Get the actual username
username = os.environ.get('USERNAME', 'user')
python_path = f'C:\\Users\\{username}\\AppData\\Local\\Programs\\Python\\Python311\\python.exe'

# Use timestamped log file in logs directory to avoid stale data
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
logs_dir = Path(r'c:\Dev\MERID\logs')
logs_dir.mkdir(parents=True, exist_ok=True)
log_filename = logs_dir / f'server_debug_{timestamp}.log'

# Run the server and capture output
with open(log_filename, 'w') as log_file:
    process = subprocess.Popen(
        [python_path, 'web/main_15m_lean.py'],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,  # Line buffered
        cwd=r'c:\Dev\MERID'
    )
    process.wait()
