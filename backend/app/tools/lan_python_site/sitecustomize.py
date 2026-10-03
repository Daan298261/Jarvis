"""Loaded automatically when PYTHONPATH includes this directory.

Owner Python (the python tool, terminal ``python -c``, venv scripts Jarvis
starts) must source RFC1918 TCP and UDP from the home NIC. HTTP_PROXY covers
urllib; this covers raw ``connect`` / ``sendto`` and ``trust_env=False`` httpx.
"""
from __future__ import annotations

try:
    from app.tools.lan_socket_bind import install_lan_bind

    install_lan_bind()
except Exception:
    pass
