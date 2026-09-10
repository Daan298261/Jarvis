# Companion PC endpoint (dev / cloud)

**Related RFCs:** RFC-0065 (bring-up), RFC-0059 (companion), RFC-0064 (realtime voice)

The Android companion does **not** embed the owner master key. Phones talk to:

| Surface | Default | Role |
| --- | --- | --- |
| PC Leader HTTP API | `http://127.0.0.1:4780` | Full Jarvis backend + companion routes |
| Mobile TLS gateway | `https://<lan-ip>:4781` | Allowlisted `/api/companion/*` only |

## Bring-up (cloud / no GPU)

```bash
# 1) Backend (skip llama.cpp auto-load)
JARVIS_SKIP_MODEL=1 PYTHONPATH=backend python3 -m uvicorn app.main:app \
  --host 127.0.0.1 --port 4780 --app-dir backend

# 2) Optional portal SPA on the same port
npm --prefix frontend ci
npm --prefix frontend run build

# 3) Optional mobile TLS ingress (needs LAN host SAN)
PYTHONPATH=backend python3 -m app.mobile.gateway --host 127.0.0.1 --port 4781
```

## Health probe

```bash
curl -sS http://127.0.0.1:4780/api/system | head
```

Expect HTTP 200 JSON with `hardware` / `model` fields. Model may report unloaded when `JARVIS_SKIP_MODEL=1`.

## Common failures

- **Connection refused** — uvicorn not running; start with the command above.
- **Model load errors in logs** — expected on cloud without GGUF; keep `JARVIS_SKIP_MODEL=1`.
- **Companion 401** — device session missing; pair + confirm fingerprint on desktop first.
- **Gateway 404 on non-companion paths** — intentional; owner APIs stay off the mobile ingress.
