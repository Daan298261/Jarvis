import json, time, urllib.request, sqlite3
B="http://127.0.0.1:4780"
ids=["0a3441b0-456d-4dc6-8a0c-b320fa6aeaf8","5cadf86f-a8b6-4ddf-b173-ee883188cb7b"]
out=r"C:\Users\daanv\Documents\Projects\Jarvis\Jarvis\Desktop\harm-veto-poll.txt"
open(out,"w",encoding="utf-8").write("poll start\n")
deadline=time.time()+480
done=set()
while time.time()<deadline and len(done)<2:
  for tid in ids:
    if tid in done: continue
    try:
      with urllib.request.urlopen(B+f"/api/tasks/{tid}", timeout=90) as r:
        row=json.loads(r.read().decode())
      open(out,"a",encoding="utf-8").write(f"{tid[:8]} {row.get('status')} {row.get('stage')} {(row.get('current_action') or '')[:60]}\n")
      if row.get("status") in {"completed","failed","cancelled"}:
        done.add(tid)
        open(out,"a",encoding="utf-8").write("RESULT "+(row.get("result") or "")[:500]+"\n")
    except Exception as e:
      open(out,"a",encoding="utf-8").write(f"{tid[:8]} err {type(e).__name__}\n")
  time.sleep(10)
c=sqlite3.connect(r"C:\Users\daanv\Documents\Projects\Jarvis\Jarvis\data\jarvis.db", timeout=10)
c.row_factory=sqlite3.Row
open(out,"a",encoding="utf-8").write("final db\n")
for tid in ids:
  t=c.execute("select status,stage,substr(result,1,300) r from tasks where id=?",(tid,)).fetchone()
  open(out,"a",encoding="utf-8").write(str(dict(t))+"\n")
try:
  with urllib.request.urlopen(B+"/api/decision/reflex/metrics", timeout=60) as r:
    m=json.loads(r.read().decode())
  hv=[c for c in (m.get("decision_classes") or []) if c.get("decision_class")=="harm_veto"]
  open(out,"a",encoding="utf-8").write("harm_veto "+json.dumps(hv)[:900]+"\n")
except Exception as e:
  open(out,"a",encoding="utf-8").write(f"metrics {e}\n")
