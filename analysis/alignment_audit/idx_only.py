import sqlite3
c = sqlite3.connect("file:data/decision_audit.db?mode=ro", uri=True)
for r in c.execute(
    "SELECT name, tbl_name FROM sqlite_master WHERE type='index' ORDER BY tbl_name"):
    print(r)
c.close()
print("DONE")
