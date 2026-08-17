"""Upload validation, storage, text extraction, and session-scoped serving."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import UploadFile

ROOT = Path(__file__).resolve().parent
UPLOADS_DIR = ROOT / "uploads"

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
MAX_FILES_PER_MESSAGE = int(os.getenv("MAX_FILES_PER_MESSAGE", 5))
MAX_EXTRACTED_CHARS = int(os.getenv("MAX_EXTRACTED_CHARS", 80000))

ALLOWED_MIMES: dict[str, tuple[str, set[str]]] = {
    "image/png": ("image", {".png"}),
    "image/jpeg": ("image", {".jpg", ".jpeg"}),
    "image/webp": ("image", {".webp"}),
    "image/gif": ("image", {".gif"}),
    "text/plain": ("document", {".txt"}),
    "application/pdf": ("document", {".pdf"}),
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
        "document",
        {".docx"},
    ),
}

_EXT_TO_MIME = {ext: mime for mime, (_, exts) in ALLOWED_MIMES.items() for ext in exts}


class UploadError(ValueError):
    """Raised when an upload fails validation."""


_lock = Lock()
_registry: dict[str, dict] = {}


def _safe_filename(name: str) -> str:
    base = Path(name).name
    base = re.sub(r"[^\w.\- ]", "_", base).strip()
    if not base or base in (".", ".."):
        base = "file"
    return base[:200]


def _sniff_mime(data: bytes, filename: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"%PDF":
        return "application/pdf"
    if data[:2] == b"PK" and ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".txt":
        return "text/plain"
    return None


def _detect_mime(data: bytes, filename: str, declared: str | None) -> str:
    sniffed = _sniff_mime(data, filename)
    if sniffed:
        return sniffed
    if declared and declared in ALLOWED_MIMES:
        ext = Path(filename).suffix.lower()
        allowed_exts = ALLOWED_MIMES[declared][1]
        if ext in allowed_exts:
            return declared
    ext = Path(filename).suffix.lower()
    if ext in _EXT_TO_MIME:
        return _EXT_TO_MIME[ext]
    raise UploadError(f"Unsupported file type: {filename}")


def _extract_text(mime: str, path: Path) -> str:
    if mime == "text/plain":
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    elif mime == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        parts = [page.extract_text() or "" for page in reader.pages]
        text = "\n".join(parts)
    elif (
        mime
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        from docx import Document

        doc = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
    else:
        return ""

    text = text.strip()
    if len(text) > MAX_EXTRACTED_CHARS:
        text = text[:MAX_EXTRACTED_CHARS] + "\n… [truncated]"
    return text


def _register_entry(
    attachment_id: str,
    session_id: str,
    path: Path,
    mime: str,
    name: str,
    kind: str,
) -> None:
    with _lock:
        _registry[attachment_id] = {
            "session_id": session_id,
            "path": path,
            "mime": mime,
            "name": name,
            "kind": kind,
        }


def _entry_from_disk(session_id: str, attachment_id: str) -> dict | None:
    dest_dir = UPLOADS_DIR / session_id / attachment_id
    if not dest_dir.is_dir():
        return None
    candidates = [
        path
        for path in dest_dir.iterdir()
        if path.is_file() and path.name != "extracted.txt"
    ]
    if not candidates:
        return None
    path = candidates[0]
    mime = _sniff_mime(path.read_bytes()[:8192], path.name)
    if mime is None:
        ext = path.suffix.lower()
        mime = _EXT_TO_MIME.get(ext)
    if mime is None or mime not in ALLOWED_MIMES:
        return None
    kind, _ = ALLOWED_MIMES[mime]
    entry = {
        "session_id": session_id,
        "path": path,
        "mime": mime,
        "name": path.name,
        "kind": kind,
    }
    _register_entry(attachment_id, session_id, path, mime, path.name, kind)
    return entry


async def save_uploads(session_id: str, uploads: list[UploadFile]) -> list[dict]:
    if len(uploads) > MAX_FILES_PER_MESSAGE:
        raise UploadError(f"Maximum {MAX_FILES_PER_MESSAGE} files per message.")

    UPLOADS_DIR.mkdir(exist_ok=True)
    attachments: list[dict] = []

    for upload in uploads:
        if not upload.filename:
            raise UploadError("File has no name.")

        data = await upload.read()
        if not data:
            raise UploadError(f"{upload.filename} is empty.")
        if len(data) > MAX_UPLOAD_BYTES:
            limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
            raise UploadError(f"{upload.filename} exceeds the {limit_mb} MB limit.")

        mime = _detect_mime(data, upload.filename, upload.content_type)
        kind, _ = ALLOWED_MIMES[mime]

        attachment_id = uuid4().hex
        safe_name = _safe_filename(upload.filename)
        dest_dir = UPLOADS_DIR / session_id / attachment_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / safe_name
        dest_path.write_bytes(data)

        if kind == "document":
            extracted = _extract_text(mime, dest_path)
            (dest_dir / "extracted.txt").write_text(extracted, encoding="utf-8")

        _register_entry(attachment_id, session_id, dest_path, mime, safe_name, kind)
        attachments.append(
            {"id": attachment_id, "name": safe_name, "mime": mime, "kind": kind}
        )

    return attachments


def resolve_attachment(session_id: str, attachment_id: str) -> dict | None:
    with _lock:
        entry = _registry.get(attachment_id)
    if entry is not None:
        if entry["session_id"] != session_id:
            return None
        return entry
    return _entry_from_disk(session_id, attachment_id)


def get_extracted_text(session_id: str, attachment_id: str) -> str:
    extracted_path = UPLOADS_DIR / session_id / attachment_id / "extracted.txt"
    if extracted_path.is_file():
        return extracted_path.read_text(encoding="utf-8")
    return ""


def read_image_data_url(session_id: str, attachment_id: str) -> str | None:
    entry = resolve_attachment(session_id, attachment_id)
    if entry is None or entry["kind"] != "image":
        return None
    data = entry["path"].read_bytes()
    encoded = base64.standard_b64encode(data).decode("ascii")
    return f"data:{entry['mime']};base64,{encoded}"
