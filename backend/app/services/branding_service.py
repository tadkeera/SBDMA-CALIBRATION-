"""Report header branding: the official letterhead and its logo.

What this is for: every report the platform emits (certificate PDF, Excel export,
printed page) must carry the agency's official letterhead — four Arabic lines on the
right, four English lines on the left, and the logo centred between them, above a
rule. The wording and the logo therefore cannot live in code alone; a QA officer has
to be able to change them without a deployment.

Where it lives:
  * the text lines are one row in ``system_settings`` (key ``report.header``), so
    every change is dated and attributed;
  * the image is written under ``<STORAGE_PATH>/branding/logo.<ext>`` and described
    by the same row (sha256, size, content type) — the bytes stay out of the
    database, and the checksum is what the reports rely on.

Everything here is read on demand: a report generated a second after a logo change
carries the new logo, with no cache to invalidate.
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import blobstore
from app.core.config import get_settings
from app.core.exceptions import ValidationFailedError
from app.core.rbac import Principal
from app.models.audit import SystemSetting
from app.services.audit_service import AuditService

HEADER_KEY = "report.header"
CATEGORY = "reports"

#: The official letterhead, as the agency writes it. Four lines each, in order.
DEFAULT_HEADER_AR: tuple[str, ...] = (
    "الجمهورية اليمنية",
    "وزارة الصحة العامة والسكان",
    "الهيئة العليا للأدوية والمستلزمات الطبية",
    "المختبر الوطني للرقابة الدوائية - عدن",
)
DEFAULT_HEADER_EN: tuple[str, ...] = (
    "Republic of Yemen",
    "Ministry of Public Health and Population",
    "Supreme Board for Drugs & Medical Appliances",
    "National Quality Control Laboratory - ADEN",
)

HEADER_LINES = 4
MAX_LINE_LENGTH = 120

#: Accepted uploads. WEBP is accepted because it is what a modern design tool
#: exports, and it is converted to PNG on the way in: ReportLab cannot embed WEBP,
#: and a logo that renders on screen but not on the certificate is worse than a
#: rejected upload.
ALLOWED_IMAGE_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}
MAX_LOGO_BYTES = 2 * 1024 * 1024
LOGO_DIR = "branding"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


class BrandingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit = AuditService(session)

    # ----------------------------------------------------------------- reading
    async def _row(self) -> SystemSetting | None:
        return (
            await self.session.execute(select(SystemSetting).where(SystemSetting.key == HEADER_KEY))
        ).scalar_one_or_none()

    async def get(self) -> dict[str, Any]:
        """The effective letterhead: stored values, or the defaults."""
        row = await self._row()
        value = (row.value_jsonb if row else None) or {}
        return {
            "header_ar": list(value.get("header_ar") or DEFAULT_HEADER_AR),
            "header_en": list(value.get("header_en") or DEFAULT_HEADER_EN),
            "is_default": not row or not value.get("header_ar"),
            "logo": value.get("logo"),
            "updated_at": value.get("updated_at"),
            "updated_by": value.get("updated_by"),
        }

    async def load(self) -> dict[str, Any]:
        """Read the letterhead and resolve the logo bytes for a renderer.

        Returns the same shape as :meth:`get` plus ``logo_bytes``/``logo_sha256`` so
        a PDF or Excel writer never has to touch the filesystem itself.
        """
        branding = await self.get()
        logo = branding.get("logo")
        branding["logo_bytes"] = None
        if logo:
            # the logo is filed evidence of the letterhead: on a serverless platform the
            # file is in /tmp and gone after a cold start, so restore it from the
            # database before deciding the letterhead has no logo
            await blobstore.materialise(logo["storage_path"], expected_sha=logo.get("sha256"))
            path = Path(get_settings().storage_path) / logo["storage_path"]
            if path.is_file():
                body = path.read_bytes()
                integrity = hashlib.sha256(body).hexdigest() == logo.get("sha256")
                branding["logo_bytes"] = body
                branding["logo_integrity_ok"] = integrity
            else:
                # The row survived but the file did not: report it instead of
                # silently printing a letterhead that lost its logo.
                branding["logo_integrity_ok"] = False
        return branding

    # ----------------------------------------------------------------- writing
    async def update_header(
        self,
        principal: Principal,
        *,
        header_ar: list[str],
        header_en: list[str],
        ip: str | None = None,
    ) -> dict[str, Any]:
        arabic = self._clean_lines(header_ar, field="header_ar")
        english = self._clean_lines(header_en, field="header_en")

        row = await self._row()
        before = dict(row.value_jsonb or {}) if row else {}
        if row is None:
            row = SystemSetting(key=HEADER_KEY, category=CATEGORY)
            self.session.add(row)
            await self.session.flush()

        value = dict(before)
        value.update(
            {
                "header_ar": arabic,
                "header_en": english,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "updated_by": principal.username,
            }
        )
        row.value_jsonb = value
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = principal.user_id
        if not row.description_ar:
            row.description_ar = "ترويسة التقارير الرسمية والشعار"

        await self.audit.record(
            action="REPORT_HEADER_UPDATED",
            entity_type="system_setting",
            entity_id=None,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=principal.department_id,
            old_values={"header_ar": before.get("header_ar"), "header_en": before.get("header_en")},
            new_values={"header_ar": arabic, "header_en": english},
            reason="official report letterhead edited",
            ip_address=ip,
        )
        # the router layer does not commit: a service that mutates must publish its
        # own work, or the letterhead would silently revert when the session closed
        await self.session.commit()
        return await self.get()

    async def set_logo(
        self,
        principal: Principal,
        *,
        filename: str,
        content_type: str,
        data: bytes,
        ip: str | None = None,
    ) -> dict[str, Any]:
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise ValidationFailedError(
                message_ar="صيغة الشعار غير مدعومة — المسموح PNG أو JPEG أو WEBP",
                message_en="Unsupported logo format — PNG, JPEG or WEBP only",
                field="logo",
            )
        if not data:
            raise ValidationFailedError(
                message_ar="الملف فارغ",
                message_en="The file is empty",
                field="logo",
            )
        if len(data) > MAX_LOGO_BYTES:
            raise ValidationFailedError(
                message_ar=f"حجم الشعار يتجاوز {MAX_LOGO_BYTES // (1024 * 1024)} ميغابايت",
                message_en=f"Logo exceeds {MAX_LOGO_BYTES // (1024 * 1024)} MB",
                field="logo",
            )

        body, stored_type, extension = _normalise_image(data, content_type)
        digest = hashlib.sha256(body).hexdigest()

        root = Path(get_settings().storage_path) / LOGO_DIR
        root.mkdir(parents=True, exist_ok=True)
        relative = f"{LOGO_DIR}/logo{extension}"
        target = root / f"logo{extension}"
        # write aside, then replace: a crash mid-write must not leave a half logo
        staging = target.with_suffix(target.suffix + ".part")
        staging.write_bytes(body)
        staging.replace(target)
        await blobstore.mirror(relative, content_type=stored_type, body=body)
        # a previous upload with another extension must not linger
        for other in root.glob("logo.*"):
            if other.name != target.name and not other.name.endswith(".part"):
                other.unlink(missing_ok=True)

        row = await self._row()
        if row is None:
            row = SystemSetting(key=HEADER_KEY, category=CATEGORY)
            self.session.add(row)
            await self.session.flush()
        value = dict(row.value_jsonb or {})
        previous = value.get("logo")
        value["logo"] = {
            "storage_path": relative,
            "content_type": stored_type,
            "original_type": content_type,
            "filename": Path(filename).name[:120] or f"logo{extension}",
            "bytes": len(body),
            "sha256": digest,
            "width": _image_size(body)[0],
            "height": _image_size(body)[1],
            "converted": stored_type != content_type,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": principal.username,
        }
        value.setdefault("header_ar", list(DEFAULT_HEADER_AR))
        value.setdefault("header_en", list(DEFAULT_HEADER_EN))
        value["updated_at"] = datetime.now(timezone.utc).isoformat()
        value["updated_by"] = principal.username
        row.value_jsonb = value
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by = principal.user_id

        await self.audit.record(
            action="REPORT_LOGO_UPDATED",
            entity_type="system_setting",
            entity_id=None,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=principal.department_id,
            old_values={"logo_sha256": (previous or {}).get("sha256")},
            new_values={
                "logo_sha256": digest,
                "bytes": len(body),
                "content_type": stored_type,
                "converted_from": content_type if stored_type != content_type else None,
            },
            reason="official logo replaced",
            ip_address=ip,
        )
        await self.session.commit()
        return await self.get()

    async def clear_logo(self, principal: Principal, *, ip: str | None = None) -> dict[str, Any]:
        row = await self._row()
        value = dict((row.value_jsonb if row else None) or {})
        previous = value.pop("logo", None)
        if row is not None:
            row.value_jsonb = value
            row.updated_at = datetime.now(timezone.utc)
            row.updated_by = principal.user_id
        root = Path(get_settings().storage_path) / LOGO_DIR
        if root.is_dir():
            for path in root.glob("logo.*"):
                path.unlink(missing_ok=True)
        if (previous or {}).get("storage_path"):
            await blobstore.forget(previous["storage_path"])
        await self.audit.record(
            action="REPORT_LOGO_REMOVED",
            entity_type="system_setting",
            entity_id=None,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=principal.department_id,
            old_values={"logo_sha256": (previous or {}).get("sha256")},
            reason="official logo removed",
            ip_address=ip,
        )
        await self.session.commit()
        return await self.get()

    async def reset_header(self, principal: Principal, *, ip: str | None = None) -> dict[str, Any]:
        return await self.update_header(
            principal, header_ar=list(DEFAULT_HEADER_AR), header_en=list(DEFAULT_HEADER_EN), ip=ip
        )

    # ----------------------------------------------------------------- helpers
    @staticmethod
    def _clean_lines(lines: list[str], *, field: str) -> list[str]:
        cleaned = [(line or "").strip() for line in lines]
        if len(cleaned) != HEADER_LINES:
            raise ValidationFailedError(
                message_ar=f"الترويسة تتكون من {HEADER_LINES} أسطر بالضبط",
                message_en=f"The letterhead is exactly {HEADER_LINES} lines",
                field=field,
            )
        if any(not line for line in cleaned):
            raise ValidationFailedError(
                message_ar="لا يجوز ترك سطر فارغ في الترويسة",
                message_en="No line may be empty",
                field=field,
            )
        too_long = [line for line in cleaned if len(line) > MAX_LINE_LENGTH]
        if too_long:
            raise ValidationFailedError(
                message_ar=f"كل سطر يجب ألا يتجاوز {MAX_LINE_LENGTH} حرفاً",
                message_en=f"Each line must be at most {MAX_LINE_LENGTH} characters",
                field=field,
            )
        return cleaned


def _image_size(body: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(io.BytesIO(body)) as image:
            return (image.width, image.height)
    except Exception:  # noqa: BLE001 - size is informative, never authoritative
        return (None, None)


def _normalise_image(data: bytes, content_type: str) -> tuple[bytes, str, str]:
    """Return ``(bytes, content_type, extension)`` that a PDF can actually embed.

    PNG and JPEG pass through untouched (byte-for-byte, so the checksum the QA
    officer sees in the audit trail is the file they uploaded). Anything else —
    today that means WEBP — is decoded and re-encoded as PNG.
    """
    if data.startswith(PNG_MAGIC) and content_type == "image/png":
        return data, "image/png", ".png"
    if data.startswith(JPEG_MAGIC) and content_type == "image/jpeg":
        return data, "image/jpeg", ".jpg"
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            buffer = io.BytesIO()
            converted = image.convert("RGBA")
            converted.save(buffer, format="PNG")
        return buffer.getvalue(), "image/png", ".png"
    except Exception as exc:  # noqa: BLE001
        raise ValidationFailedError(
            message_ar="تعذر قراءة صورة الشعار",
            message_en=f"The logo could not be decoded: {exc}",
            field="logo",
        ) from exc
