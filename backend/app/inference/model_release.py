"""Release one selected local model through its runtime's native API."""
from __future__ import annotations

import asyncio

import httpx

from ..config import AppSettings
from .backends import inference_headers


def _loaded_instances(body: object) -> dict[str, list[str]]:
    if not isinstance(body, dict) or not isinstance(body.get("models"), list):
        raise RuntimeError("Runtime did not return a verifiable loaded-model inventory")
    result: dict[str, list[str]] = {}
    for row in body["models"]:
        if not isinstance(row, dict) or not row.get("type"):
            raise RuntimeError("Runtime returned an invalid model inventory")
        if row.get("type") != "llm":
            continue
        if not isinstance(row.get("loaded_instances"), list) or not row.get("key"):
            raise RuntimeError("Runtime does not expose model instances for verified unload")
        if any(not isinstance(instance, dict) or not instance.get("id") for instance in row["loaded_instances"]):
            raise RuntimeError("Runtime returned an invalid loaded model instance")
        result[str(row["key"])] = [str(instance["id"]) for instance in row["loaded_instances"]
                                  if isinstance(instance, dict) and instance.get("id")]
    return result


async def release_external_model(settings: AppSettings, backend: str, model: str) -> None:
    if settings.inference.host not in {"127.0.0.1", "localhost", "::1"}:
        raise RuntimeError("Unload is available for local model runtimes only")
    if backend not in {"lmstudio", "ollama"} or not model:
        raise RuntimeError("This runtime has no supported model unload operation")
    host = settings.inference.host
    base = f"http://{'[' + host + ']' if ':' in host else host}:{settings.inference.port}"
    async with httpx.AsyncClient(timeout=10, trust_env=False, headers=inference_headers(settings.inference.api_key)) as client:
        if backend == "lmstudio":
            async def inventory():
                response = await client.get(base + "/api/v1/models")
                response.raise_for_status()
                return _loaded_instances(response.json())

            before = await inventory()
            targets = set(before.get(model, []))
            targets.update(instance for instances in before.values() for instance in instances if instance == model)
            for instance in sorted(targets):
                response = await client.post(base + "/api/v1/models/unload", json={"instance_id": instance})
                response.raise_for_status()
            for attempt in range(8):
                after = await inventory()
                if not after.get(model) and not targets.intersection(instance for instances in after.values() for instance in instances):
                    return
                if attempt < 7:
                    await asyncio.sleep(0.25)
        else:
            async def ollama_names():
                response = await client.get(base + "/api/ps")
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict) or not isinstance(body.get("models"), list):
                    raise RuntimeError("Ollama did not return a verifiable loaded-model inventory")
                return [str(row.get("name") or row.get("model")) for row in body["models"] if isinstance(row, dict)]

            target = next((name for name in await ollama_names() if name.removesuffix(":latest") == model.removesuffix(":latest")), None)
            if not target:
                return
            response = await client.post(base + "/api/generate", json={"model": target, "keep_alive": 0, "stream": False})
            response.raise_for_status()
            for attempt in range(8):
                if target not in await ollama_names():
                    return
                if attempt < 7:
                    await asyncio.sleep(0.25)
    raise RuntimeError("The selected model is still loaded; unload was not confirmed")
