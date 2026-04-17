"""Find and fix .tsx/.ts files that use React.memo/forwardRef/lazy but don't import React."""
import os, re

src = r"c:\Dev\MERID\web\react\src"
react_use = re.compile(r"\bReact\.(memo|forwardRef|createRef|lazy|createElement)\b")
react_import = re.compile(r"import\s+React\b")
fixed = []

for root, dirs, files in os.walk(src):
    dirs[:] = [d for d in dirs if d != "node_modules"]
    for f in files:
        if not f.endswith((".tsx", ".ts")):
            continue
        fp = os.path.join(root, f)
        content = open(fp, "r", encoding="utf-8", errors="ignore").read()
        if react_use.search(content) and not react_import.search(content):
            # Add React import at line 1
            content = 'import React from "react";\n' + content
            open(fp, "w", encoding="utf-8").write(content)
            fixed.append(os.path.relpath(fp, src))

print(f"Fixed {len(fixed)} files:")
for f in sorted(fixed):
    print(f"  {f}")
