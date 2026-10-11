import json
import sqlite3

c = sqlite3.connect("data/mobile/companion.db")
row = c.execute(
    "select payload from records where kind='network' and id='config'"
).fetchone()
print(json.loads(row[0]) if row else None)
c.close()
