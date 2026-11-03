import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
con = sqlite3.connect(f"file:{(ROOT / 'data/calibration.db').as_posix()}?mode=ro", uri=True)
for t in ("forecasts", "brier_stats"):
    print(con.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0])
    print("---")
print("counts:", con.execute("SELECT COUNT(*) FROM forecasts").fetchone(),
      con.execute("SELECT COUNT(*) FROM brier_stats").fetchone())
print("--- forecast sample ---")
cols = [c[1] for c in con.execute("PRAGMA table_info(forecasts)")]
print(cols)
for r in con.execute("SELECT * FROM forecasts ORDER BY rowid DESC LIMIT 3"):
    print(r)
con.close()
