"""Evidence attachment storage — content-addressed, verified, append-only.

Design rules (GxP / ALCOA+):

1. **The checksum is the identity.** A file is stored under
   ``<root>/<yyyymm>/<sha256><ext>``, so the same bytes can never produce two
   different "originals" and a re-upload is detectable instead of silently
   overwriting something else.
2. **Verify after writing, not before.** The hash is computed while streaming,
   the stream is flushed to disk, then the stored file is read back and hashed
   again. A short write or a full disk must fail the request, not file a
   corrupt original.
3. **Nothing is overwritten in place.** Writes go to a temp file in the same
   directory and are published with ``os.replace`` (atomic on POSIX).
4. **Deletion is a business action, not a cleanup.** The caller may only remove
   a file it just wrote and failed to register; filed evidence is protected by
   the database trigger and never removed here.

The module is deliberately synchronous — it is called from async handlers via
``asyncio.to_thread`` so a 25 MB upload never blocks the event loop.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings

CHUNK = 1024 * 1024  # 1 MiB

# Filenames are stored for display only; the path never contains user input.
_UNSAFE = re.compile(r"[^A-Za-z0-9._\u0600-\u06FF-]+")

# Types the protocol actually produces: chromatograms, spectra, PDF reports,
# spreadsheets, images of the instrument display, and plain text exports.
ALLOWED_MIME: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/csv": ".csv",
    "text/plain": ".txt",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tif",
    "application/zip": ".zip",
    "application/octet-stream": ".bin",
}


class AttachmentError(Exception):
    """Raised for anything the caller must surface as a 4xx, never a 500."""

    def __init__(self, code: str, message_ar: str, message_en: str, field: str | None = None):
        super().__init__(message_en)
        self.code = code
        self.message_ar = message_ar
        self.message_en = message_en
        self.field = field


@dataclass(frozen=True)
class StoredFile:
    storage_path: str
    sha256: str
    size_bytes: int
    safe_name: str
    extension: str


def sanitise_filename(raw: str) -> str:
    """Keep a human-readable name without ever trusting it as a path."""
    name = os.path.basename((raw or "").replace("\\", "/")).strip()
    name = _UNSAFE.sub("_", name).lstrip(".")
    if not name:
        raise AttachmentError(
            "VALIDATION_ERROR", "اسم الملف غير صالح", "Invalid file name", field="file"
        )
    return name[:180]


def storage_root() -> Path:
    return Path(get_settings().storage_path).resolve()


def resolve_within_root(storage_path: str) -> Path:
    """Refuse any stored path that escapes the storage root (path-traversal guard)."""
    root = storage_root()
    candidate = (root / storage_path).resolve()
    if root != candidate and root not in candidate.parents:
        raise AttachmentError(
            "NOT_FOUND",
            "الملف غير موجود",
            "File not found",
        )
    return candidate


def max_upload_bytes() -> int:
    return int(get_settings().max_upload_mb) * 1024 * 1024


def store_stream(stream, *, file_name: str, mime_type: str, max_bytes: int | None = None) -> StoredFile:
    """Consume a binary stream, validate size/type, store it and verify the hash.

    ``stream`` is any object with ``.read(n)``; FastAPI's ``UploadFile.file``
    works directly.
    """
    limit = max_bytes if max_bytes is not None else max_upload_bytes()
    safe_name = sanitise_filename(file_name)
    extension = ALLOWED_MIME.get((mime_type or "").split(";")[0].strip().lower())
    if extension is None:
        raise AttachmentError(
            "VALIDATION_ERROR",
            "نوع الملف غير مسموح للمرفقات المخبرية",
            "This file type is not allowed as laboratory evidence",
            field="file",
        )
    if mime_type.split(";")[0].strip().lower() == "application/octet-stream":
        # fall back to the extension the operator chose, still sanitised
        extension = Path(safe_name).suffix.lower() or ".bin"

    root = storage_root()
    root.mkdir(parents=True, exist_ok=True)
    tmp_dir = root / ".incoming"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256()
    size = 0
    fd, tmp_name = tempfile.mkstemp(dir=tmp_dir, prefix="upload-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as handle:
            while True:
                chunk = stream.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise AttachmentError(
                        "VALIDATION_ERROR",
                        f"حجم الملف يتجاوز الحد المسموح ({limit // (1024 * 1024)} ميجابايت)",
                        f"File exceeds the {limit // (1024 * 1024)} MB limit",
                        field="file",
                    )
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())

        if size == 0:
            raise AttachmentError(
                "VALIDATION_ERROR", "الملف فارغ", "The file is empty", field="file"
            )

        sha = digest.hexdigest()
        relative_dir = Path(sha[:6])
        month = Path(_month_bucket())
        target_dir = root / month
        target_dir.mkdir(parents=True, exist_ok=True)
        final_rel = month / relative_dir / f"{sha}{extension}"
        final_path = root / final_rel
        final_path.parent.mkdir(parents=True, exist_ok=True)

        if not final_path.exists():
            os.replace(tmp_name, final_path)
            # publish only after the bytes are on disk
            with open(final_path, "rb") as verify:
                check = hashlib.sha256()
                for part in iter(lambda: verify.read(CHUNK), b""):
                    check.update(part)
            if check.hexdigest() != sha:
                final_path.unlink(missing_ok=True)
                raise AttachmentError(
                    "VALIDATION_ERROR",
                    "فشل التحقق من سلامة الملف بعد الكتابة",
                    "The stored file failed its post-write checksum verification",
                    field="file",
                )
        else:
            # identical content already filed: reuse the stored blob, keep one copy
            os.unlink(tmp_name)
        return StoredFile(
            storage_path=str(final_rel),
            sha256=sha,
            size_bytes=size,
            safe_name=safe_name,
            extension=extension,
        )
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def _month_bucket() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y%m")


def discard_unregistered(storage_path: str) -> None:
    """Remove a blob whose database row could not be written.

    Only used when registration failed; the file was never filed, so no signed
    record points at it. Never call this for an existing attachment.
    """
    try:
        resolve_within_root(storage_path).unlink(missing_ok=True)
    except OSError:
        pass


def read_for_verification(storage_path: str, expected_sha: str) -> tuple[bytes, bool]:
    """Read a stored attachment and re-hash it.

    Returns the bytes plus whether the content still matches the checksum that
    was recorded at filing time. The caller must audit a mismatch rather than
    silently serving changed evidence.
    """
    path = resolve_within_root(storage_path)
    if not path.is_file():
        raise AttachmentError("NOT_FOUND", "الملف غير موجود", "File not found")
    body = path.read_bytes()
    return body, hashlib.sha256(body).hexdigest() == expected_sha
