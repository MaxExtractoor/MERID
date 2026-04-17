from pathlib import Path

path = Path(r"C:\Users\Chris\.windsurf\worktrees\MERID\MERID-6f096c3e\web\api\dashboard_data.py")
lines = path.read_text().splitlines()
while lines and not lines[-1].strip():
    lines.pop()
if len(lines) >= 2 and lines[-2].strip() == '@router.get("/assets/universe")' and lines[-1].strip() == 'async def get_asset_universe_snapshot():':
    lines = lines[:-2]
    path.write_text("\n".join(lines) + "\n")
else:
    raise SystemExit('Trailing duplicate definition not found; no changes made')
