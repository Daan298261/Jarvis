"""RFC-0229 S1 (UX re-review): the Manager's ES-module scripts are served as JavaScript.

On Windows Python's ``mimetypes`` reads the registry, where ``.js`` is often mapped
to ``text/plain``; WebView2 and browsers refuse a module script with that type and
the whole Manager UI (live Start/Restart/Stop included) would be lost. ``main.py``
pins ``.js`` to ``text/javascript`` before the ``/assets`` mount.
"""
import os
import subprocess
import sys
import textwrap
from pathlib import Path

from fastapi.testclient import TestClient

from app.manager import main

BACKEND = Path(__file__).resolve().parents[1] / "backend"

_PROBE = textwrap.dedent(
    """
    import mimetypes
    mimetypes.add_type("text/plain", ".js")  # what an affected Windows registry does
    assert mimetypes.guess_type("x.js")[0] == "text/plain", mimetypes.guess_type("x.js")
    print("PRESET", mimetypes.guess_type("x.js")[0])

    from fastapi.testclient import TestClient
    from app.manager import main

    client = TestClient(main.app)
    for name in ("app.js", "controls.js"):
        response = client.get(f"/assets/{name}")
        print("ASSET", name, response.status_code, response.headers.get("content-type"))
        assert response.status_code == 200, (name, response.status_code)
        assert response.headers["content-type"].startswith("text/javascript"), (name, response.headers["content-type"])
    print("OK")
    """
)


def test_manager_js_served_as_javascript_when_registry_says_text_plain(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(BACKEND), "JARVIS_ROOT": str(tmp_path)}
    env.pop("JARVIS_MANAGER_WATCHDOG", None)
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], env=env, cwd=tmp_path, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PRESET text/plain" in result.stdout
    assert "ASSET app.js 200 text/javascript" in result.stdout
    assert "ASSET controls.js 200 text/javascript" in result.stdout
    assert result.stdout.strip().endswith("OK")


def test_admin_page_is_html_and_loads_app_js_as_module():
    response = TestClient(main.app).get("/admin")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<script type="module" src="/assets/app.js">' in response.text
    assert '<script src="/assets/app.js">' not in response.text
