#!/usr/bin/env python
import sys
from pathlib import Path
from modulefinder import ModuleFinder

ROOT = Path(__file__).resolve().parents[0]
sys.path.insert(0, str(ROOT))

def main():
    finder = ModuleFinder()
    # Adjust this if your entrypoint differs
    finder.run_script("web/main_15m_lean.py")

    modules = sorted(m for m in finder.modules.keys() if not m.startswith("_"))
    out_path = ROOT / "output" / "kalshi_15m_imports.txt"
    out_path.parent.mkdir(exist_ok=True, parents=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for name in modules:
            mod = finder.modules[name]
            f.write(f"{name} -> {mod.__file__}\n")

    print(f"Wrote {len(modules)} modules to {out_path}")

if __name__ == "__main__":
    main()
