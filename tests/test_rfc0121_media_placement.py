from __future__ import annotations

import json
import sqlite3
import uuid

import httpx
import pytest

from app.media.store import UPLOAD_RECORD_KIND, save_upload
from app.mobile import store
from app.projects.paths import (
    UNGROUPED_MEDIA_PROJECT_ID,
    media_relative_path,
    project_artifacts_dir,
    project_media_dir,
    resolve_media_project_id,
)
from app.swarm.nodes import load_or_create_local_node_id


@pytest.fixture
def media_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.media.store.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.swarm.nodes.data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def media_app(allow_loopback_api):
    from app.auth import require_owner_private_key
    from app.main import app

    app.dependency_overrides[require_owner_private_key] = lambda: None
    yield app
    app.dependency_overrides.pop(require_owner_private_key, None)


def _upload_payload_from_db(data_root, upload_id: str) -> dict:
    db_path = data_root / "mobile" / "companion.db"
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT payload FROM records WHERE kind=? AND id=?",
        (UPLOAD_RECORD_KIND, upload_id),
    ).fetchone()
    conn.close()
    assert row is not None
    return json.loads(row[0])


@pytest.mark.asyncio
async def test_new_upload_colocated_under_project_media(media_env, media_app):
    project_id = str(uuid.uuid4())
    payload = b"rfc-0121-bytes"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=media_app), base_url="http://test") as client:
        created = await client.post(
            "/api/media/uploads",
            content=payload,
            headers={
                "x-filename": "note.txt",
                "content-type": "text/plain",
                "x-jarvis-upload-kind": "file",
                "x-jarvis-project-id": project_id,
            },
        )
    assert created.status_code == 200
    body = created.json()
    upload_id = body["id"]
    assert body["project_id"] == project_id
    assert body["relative_path"] == media_relative_path(project_id, upload_id)
    assert body["node_id"] == load_or_create_local_node_id()

    on_disk = media_env / body["relative_path"]
    assert on_disk.is_file()
    assert on_disk.read_bytes() == payload
    assert not (media_env / "media" / "uploads" / upload_id).exists()

    record = _upload_payload_from_db(media_env, upload_id)
    assert "data" not in record
    assert "bytes" not in record
    assert record["sha256"]
    assert len(json.dumps(record)) < 4096


def test_save_upload_default_ungrouped_project(media_env):
    item = save_upload(
        b"ungrouped",
        kind="file",
        filename="x.txt",
        content_type="text/plain",
        owner="desktop",
    )
    assert item.project_id == UNGROUPED_MEDIA_PROJECT_ID
    assert resolve_media_project_id(None) == UNGROUPED_MEDIA_PROJECT_ID
    path = media_env / item.relative_path
    assert path.is_file()
    assert path.parent == project_media_dir(UNGROUPED_MEDIA_PROJECT_ID)


def test_project_artifacts_dir_helper(media_env):
    pid = str(uuid.uuid4())
    artifacts = project_artifacts_dir(pid)
    assert artifacts.is_dir()
    assert artifacts.name == "artifacts"


@pytest.mark.asyncio
async def test_companion_upload_uses_leader_project_layout(media_env):
    from app.api.companion import router
    from tests.test_rfc0109_media_upload import _device_headers

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)
    device, headers = _device_headers()
    project_id = str(uuid.uuid4())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/companion/attachments",
            content=b"from-phone",
            headers={
                **headers,
                "x-filename": "phone.txt",
                "x-jarvis-upload-kind": "file",
                "x-jarvis-project-id": project_id,
            },
        )
    assert created.status_code == 200
    body = created.json()
    assert body["project_id"] == project_id
    rel = body["relative_path"]
    assert rel.startswith(f"projects/{project_id}/media/")
    assert (media_env / rel).read_bytes() == b"from-phone"
