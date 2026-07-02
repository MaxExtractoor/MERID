import sqlite3
import json

conn = sqlite3.connect(r'c:\Dev\MERID\data\kalshi_fills.db')
cursor = conn.cursor()

# Get table names
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("Tables:", tables)

# If fills table exists, query recent DOGE/XRP trades
if tables:
    for table in tables:
        table_name = table[0]
        try:
            cursor.execute(f"SELECT * FROM {table_name} LIMIT 5")
            columns = [desc[0] for desc in cursor.description]
            print(f"\n{table_name} columns: {columns}")
            rows = cursor.fetchall()
            for row in rows:
                print(row)
        except Exception as e:
            print(f"Error querying {table_name}: {e}")

conn.close()
