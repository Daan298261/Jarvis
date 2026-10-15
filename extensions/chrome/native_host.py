"""Chrome native messaging host. Stdlib only; stdout is exclusively framed JSON."""
import json
import os
from pathlib import Path
import re
import struct
import sys
import threading
import time
import uuid

ROOT = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "ANZU" / "chrome-connector"
MAX_MESSAGE = 512 * 1024


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise ValueError("Truncated native header")
    size = struct.unpack("<I", header)[0]
    if size > MAX_MESSAGE:
        raise ValueError("Native message too large")
    body = stream.read(size)
    if len(body) != size:
        raise ValueError("Truncated native body")
    value = json.loads(body)
    if not isinstance(value, dict):
        raise ValueError("Native message must be an object")
    return value


def write_message(stream, value):
    body = json.dumps(value).encode("utf-8")
    if len(body) > MAX_MESSAGE:
        raise ValueError("Native message too large")
    stream.write(struct.pack("<I", len(body)) + body)
    stream.flush()


def atomic_json(path, value):
    temporary = path.with_suffix(f".{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    temporary.replace(path)


def main():
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    ROOT.mkdir(parents=True, exist_ok=True)
    session = uuid.uuid4().hex
    stop = threading.Event()
    sent = {}
    shared = {}
    lock = threading.Lock()
    state = ROOT / "connection.json"
    atomic_json(state, {"session": session, "heartbeat": time.time()})

    def pump():
        try:
            while not stop.is_set():
                if json.loads(state.read_text()).get("session") != session:
                    return
                atomic_json(state, {"session": session, "heartbeat": time.time(), **shared})
                now = time.time()
                with lock:
                    for key, expiry in list(sent.items()):
                        if expiry <= now:
                            sent.pop(key, None)
                            (ROOT / f"{key}.response.json").unlink(missing_ok=True)
                    for path in ROOT.glob("*.request.json"):
                        value = json.loads(path.read_text(encoding="utf-8"))
                        key = value.get("id", "")
                        if not re.fullmatch(r"[0-9a-f]{32}", key) or path.name != f"{key}.request.json":
                            continue
                        if value.get("session") != session or value.get("expires", 0) <= now:
                            path.unlink(missing_ok=True)
                            continue
                        if key not in sent:
                            sent[key] = value["expires"]
                            write_message(sys.stdout.buffer, value)
                stop.wait(0.2)
        except (OSError, ValueError):
            stop.set()

    worker = threading.Thread(target=pump, daemon=True)
    worker.start()
    try:
        while not stop.is_set():
            value = read_message(sys.stdin.buffer)
            if value is None:
                break
            key = value.get("id", "")
            with lock:
                if value.get("type") == "shared":
                    shared["url"] = str(value.get("url") or "")[:8000]
                if key in sent and sent[key] > time.time():
                    atomic_json(ROOT / f"{key}.response.json", value)
    finally:
        stop.set()
        worker.join(timeout=2)
        try:
            if json.loads(state.read_text()).get("session") == session:
                state.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    main()
