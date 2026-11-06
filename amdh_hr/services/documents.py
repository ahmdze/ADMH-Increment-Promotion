"""مخزن الوثائق: بصمة SHA-256، منع التكرار، وربط متعدد للكيانات."""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import uuid
from pathlib import Path

from ..errors import not_found, validation
from ..util import now_iso
from . import audit

MAX_SIZE = 20 * 1024 * 1024
ALLOWED = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
MIME_OVERRIDES = {".pdf": "application/pdf", ".tif": "image/tiff", ".tiff": "image/tiff"}


def _extension(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise validation("نوع الملف غير مدعوم (PDF أو JPG/PNG/TIFF).")
    return suffix


def save(db, paths, user: dict, filename: str, content: bytes, entity_type: str,
         entity_id: str, purpose: str = "", ip: str = "") -> dict:
    if not content:
        raise validation("الملف فارغ.")
    if len(content) > MAX_SIZE:
        raise validation("حجم الملف يتجاوز 20 ميغابايت.")
    suffix = _extension(filename)
    digest = hashlib.sha256(content).hexdigest()
    paths.attachments_dir.mkdir(parents=True, exist_ok=True)
    stored_name = digest + suffix
    target = Path(paths.attachments_dir) / stored_name
    document = db.one("SELECT * FROM documents WHERE sha256=?", (digest,))
    if document is None:
        if not target.exists():
            target.write_bytes(content)
        document = {
            "document_id": uuid.uuid4().hex, "sha256": digest,
            "filename": str(filename or stored_name), "stored_name": stored_name,
            "mime": MIME_OVERRIDES.get(suffix) or mimetypes.guess_type(filename)[0] or "",
            "size": len(content),
        }
        with db.write() as conn:
            conn.execute(
                "INSERT INTO documents(document_id, sha256, filename, stored_name, mime, size, "
                "uploaded_by, uploaded_at) VALUES (?,?,?,?,?,?,?,?)",
                (document["document_id"], digest, document["filename"], stored_name,
                 document["mime"], len(content), user.get("username", ""), now_iso()))
    link = db.one("SELECT link_id FROM document_links WHERE document_id=? AND entity_type=? "
                  "AND entity_id=? AND purpose=?", (document["document_id"], entity_type,
                                                    entity_id, purpose))
    if link is None:
        with db.write() as conn:
            conn.execute("INSERT INTO document_links(link_id, document_id, entity_type, entity_id, "
                         "purpose, created_at) VALUES (?,?,?,?,?,?)",
                         (uuid.uuid4().hex, document["document_id"], entity_type, entity_id,
                          purpose, now_iso()))
            audit.log(db, user, "إرفاق وثيقة", entity_type, entity_id,
                      f"{document['filename']} ({len(content)} بايت)", ip=ip, conn=conn)
    return _public(document)


def _public(document: dict) -> dict:
    keys = ("document_id", "filename", "mime", "size", "sha256", "uploaded_by", "uploaded_at")
    return {key: document.get(key) for key in keys}


def list_for(db, entity_type: str, entity_id: str) -> list[dict]:
    rows = db.query(
        "SELECT d.*, l.link_id, l.purpose FROM document_links l "
        "JOIN documents d ON d.document_id=l.document_id "
        "WHERE l.entity_type=? AND l.entity_id=? ORDER BY d.uploaded_at DESC",
        (entity_type, entity_id))
    return [dict(row) for row in rows]


def fetch(db, paths, document_id: str) -> dict:
    document = db.one("SELECT * FROM documents WHERE document_id=?", (document_id,))
    if not document:
        raise not_found("الوثيقة غير موجودة.")
    path = Path(paths.attachments_dir) / document["stored_name"]
    if not path.exists():
        raise not_found("ملف الوثيقة غير موجود في المخزن.")
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != document["sha256"]:
        raise validation("بصمة الملف لا تطابق السجل — الملف تالف.")
    return {**_public(document), "content_b64": base64.b64encode(content).decode("ascii")}


def unlink(db, user: dict, link_id: str, ip: str = "") -> dict:
    row = db.one("SELECT * FROM document_links WHERE link_id=?", (link_id,))
    if not row:
        raise not_found("الرابط غير موجود.")
    with db.write() as conn:
        conn.execute("DELETE FROM document_links WHERE link_id=?", (link_id,))
        audit.log(db, user, "إزالة رابط وثيقة", row["entity_type"], row["entity_id"],
                  row["document_id"], ip=ip, conn=conn)
    return {"unlinked": link_id}
