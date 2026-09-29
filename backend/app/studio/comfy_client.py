"""HTTP client for a local ComfyUI sidecar (BlackGrid Multimedia Studio)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx


class ComfyClient:
    def __init__(self, base_url: str, *, timeout: float = 120.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout

    async def healthy(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
                r = await client.get(f"{self.base_url}/system_stats")
                return r.status_code == 200
        except Exception:
            return False

    async def queue_prompt(self, prompt: dict[str, dict[str, Any]], *, client_id: str | None = None) -> dict[str, Any]:
        cid = client_id or str(uuid.uuid4())
        body = {"prompt": prompt, "client_id": cid}
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            r = await client.post(f"{self.base_url}/prompt", json=body)
            r.raise_for_status()
            data = r.json()
            data["client_id"] = cid
            return data

    async def history(self, prompt_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            r = await client.get(f"{self.base_url}/history/{prompt_id}")
            r.raise_for_status()
            return r.json()

    async def upload_image(self, path: Path, *, subfolder: str = "", overwrite: bool = True) -> dict[str, Any]:
        if not path.is_file():
            raise FileNotFoundError(path)
        data = {"subfolder": subfolder, "type": "input", "overwrite": str(overwrite).lower()}
        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            with path.open("rb") as handle:
                files = {"image": (path.name, handle, "application/octet-stream")}
                r = await client.post(f"{self.base_url}/upload/image", data=data, files=files)
            r.raise_for_status()
            return r.json()

    async def list_queue(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            r = await client.get(f"{self.base_url}/queue")
            r.raise_for_status()
            return r.json()
