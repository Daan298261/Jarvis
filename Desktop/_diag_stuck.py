import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
con = sqlite3.connect(ROOT / "data" / "jarvis.db")
for tid in (
    "ac1e0adf-7e3b-4726-85d3-a91c8dc5b4ec",
    "1573ac01-e061-4a31-ae12-3b8e7db52309",
):
    print(
        tid[:8],
        con.execute(
            "select status,stage,started_at,updated_at,substr(error,1,120) from tasks where id=?",
            (tid,),
        ).fetchone(),
    )
print(
    "running",
    con.execute(
        "select id,status,stage,substr(prompt,1,60) from tasks where status='running'"
    ).fetchall(),
)
print(
    "queued",
    con.execute(
        "select id,status,stage,substr(prompt,1,60) from tasks where status='queued'"
    ).fetchall(),
)
con.close()
