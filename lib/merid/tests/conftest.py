import sys
import os

# Ensure the repository-local package root (this lib/merid folder) is first in sys.path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
