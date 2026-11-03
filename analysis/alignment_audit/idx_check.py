import sqlite3
c = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
for r in c.execute("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'"):
    print(r)
for t in ("strategy_decisions", "strategy_decision_events",
          "strategy_decision_side_ev"):
    try:
        print(t, c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    except Exception as e:
        print(t, "ERR", e)
c.close()
