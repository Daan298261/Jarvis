from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import HTTPException

from .registry import analyze_artifact_public
from .store import MediaUpload, blob_path, register_analyze_artifact, update_upload_record


def _ocr_available() -> tuple[bool, str]:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        if not shutil.which("tesseract"):
            return False, "OCR engine not installed (install Tesseract or pip install pytesseract Pillow)."
        return True, "tesseract-cli"
    return True, "pytesseract"


def _run_ocr(image_path: Path) -> tuple[str | None, str | None]:
    available, backend = _ocr_available()
    if not available:
        return None, backend
    try:
        if backend == "pytesseract":
            from PIL import Image
            import pytesseract

            text = pytesseract.image_to_string(Image.open(image_path))
        else:
            proc = subprocess.run(
                ["tesseract", str(image_path), "stdout"],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if proc.returncode != 0:
                return None, (proc.stderr or proc.stdout or "tesseract failed").strip()[:500]
            text = proc.stdout
        cleaned = (text or "").strip()
        if not cleaned:
            return "", None
        return cleaned, None
    except Exception as exc:
        return None, f"OCR failed: {exc}"[:500]


def _extract_file_text(path: Path, content_type: str, name: str) -> tuple[str | None, str | None]:
    lower = name.lower()
    if lower.endswith(".txt") or content_type.startswith("text/"):
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip(), None
        except OSError as exc:
            return None, str(exc)
    if lower.endswith(".pdf") or content_type == "application/pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return None, "PDF text extraction requires pypdf (pip install pypdf)."
        try:
            reader = PdfReader(str(path))
            parts = []
            for page in reader.pages[:50]:
                parts.append(page.extract_text() or "")
            return "\n".join(parts).strip(), None
        except Exception as exc:
            return None, f"PDF extract failed: {exc}"[:500]
    return None, "No text extractor for this file type."


async def _transcribe_media(path: Path, name: str) -> tuple[str | None, str | None]:
    from ..workers.voice import VoiceSTTError, transcribe_audio

    try:
        text = await transcribe_audio(path.read_bytes(), name)
        return (text or "").strip(), None
    except (VoiceSTTError, RuntimeError, HTTPException) as exc:
        return None, str(exc)[:500]


async def _describe_image(path: Path) -> tuple[str | None, str | None]:
    try:
        from ..inference.manager import MANAGER
        from ..config import load_settings

        settings = load_settings()
        if not MANAGER.state.loaded:
            return None, "Vision describe requires the chat model to be loaded."
        await MANAGER.ensure_vision(settings)
        # Best-effort caption via chat completion with image — optional assist only.
        return None, "Vision describe is optional; OCR covers text-in-image."
    except Exception as exc:
        return None, str(exc)[:500]


async def analyze_upload(upload: MediaUpload, actions: list[str] | None = None) -> dict:
    path = blob_path(upload.id)
    if not path.is_file():
        raise HTTPException(404, "Upload bytes missing")
    requested = [item.strip().lower() for item in (actions or []) if item.strip()]
    if not requested:
        if upload.kind == "image":
            requested = ["ocr", "describe"]
        elif upload.kind in {"audio", "video"}:
            requested = ["transcribe"]
        else:
            requested = ["extract"]

    results: dict[str, dict] = {}
    extracted_text: str | None = None

    if "ocr" in requested and upload.kind == "image":
        text, err = _run_ocr(path)
        entry = {"status": "ok" if text is not None else "unavailable", "text": text or ""}
        if err:
            entry["limitation"] = err
        results["ocr"] = entry
        if text:
            extracted_text = text

    if "describe" in requested and upload.kind == "image":
        text, err = await _describe_image(path)
        entry = {"status": "ok" if text else "skipped", "text": text or ""}
        if err:
            entry["limitation"] = err
        results["describe"] = entry

    if "extract" in requested and upload.kind == "file":
        text, err = _extract_file_text(path, upload.content_type, upload.name)
        entry = {"status": "ok" if text is not None else "unavailable", "text": text or ""}
        if err:
            entry["limitation"] = err
        results["extract"] = entry
        if text:
            extracted_text = text

    if "transcribe" in requested and upload.kind in {"audio", "video"}:
        media_path = path
        cleanup: Path | None = None
        if upload.kind == "video":
            if not shutil.which("ffmpeg"):
                results["transcribe"] = {
                    "status": "unavailable",
                    "text": "",
                    "limitation": "Video transcription requires ffmpeg on PATH.",
                }
            else:
                cleanup = Path(tempfile.mkstemp(suffix=".wav")[1])
                proc = subprocess.run(
                    ["ffmpeg", "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", str(cleanup)],
                    capture_output=True,
                    text=True,
                    timeout=300,
                    check=False,
                )
                if proc.returncode != 0:
                    results["transcribe"] = {
                        "status": "unavailable",
                        "text": "",
                        "limitation": "ffmpeg could not extract audio from video.",
                    }
                else:
                    media_path = cleanup
        if "transcribe" not in results:
            text, err = await _transcribe_media(media_path, upload.name)
            entry = {"status": "ok" if text is not None else "unavailable", "text": text or ""}
            if err:
                entry["limitation"] = err
            results["transcribe"] = entry
            if text:
                extracted_text = text
        if cleanup and cleanup.exists():
            cleanup.unlink(missing_ok=True)

    summary = {
        "upload_id": upload.id,
        "kind": upload.kind,
        "actions": results,
        "extracted_text": extracted_text or "",
    }
    artifact_id = register_analyze_artifact(
        upload.id,
        {
            "type": "media_analyze",
            "upload_id": upload.id,
            "kind": upload.kind,
            "results": results,
            "extracted_text": extracted_text or "",
        },
    )
    summary["artifact_id"] = artifact_id
    update_upload_record(upload.id, analyze=summary)
    summary["artifact"] = analyze_artifact_public(artifact_id)
    return summary
