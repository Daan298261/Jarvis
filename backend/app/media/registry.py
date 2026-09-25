from __future__ import annotations

from ..mobile.store import database, get

from .store import ANALYZE_ARTIFACT_KIND


def analyze_artifact_public(artifact_id: str) -> dict | None:
    with database() as db:
        record = get(db, ANALYZE_ARTIFACT_KIND, artifact_id)
    if not record:
        return None
    return {
        "id": record["id"],
        "type": record.get("type") or "media_analyze",
        "upload_id": record.get("upload_id"),
        "kind": record.get("kind"),
        "extracted_text": record.get("extracted_text") or "",
        "results": record.get("results") or {},
        "created_at": record.get("created_at"),
    }


def list_analyze_artifacts_for_upload(upload_id: str) -> list[dict]:
    with database() as db:
        rows = db.execute(
            "SELECT payload FROM records WHERE kind=? AND json_extract(payload, '$.upload_id')=?",
            (ANALYZE_ARTIFACT_KIND, upload_id),
        ).fetchall()
    items = []
    for row in rows:
        import json

        record = json.loads(row[0])
        public = analyze_artifact_public(record["id"])
        if public:
            items.append(public)
    return items
