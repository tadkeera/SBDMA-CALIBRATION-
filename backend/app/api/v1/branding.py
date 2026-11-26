"""Report letterhead endpoints.

Two of these are deliberately unauthenticated — ``GET /branding`` and
``GET /branding/logo`` — because the sign-in screen shows the same official
letterhead, and a login page that needs a session to fetch its own logo is a
chicken-and-egg problem. Nothing here is confidential: it is the agency's public
letterhead, and the two public routes never expose anything else. Writing requires
``settings.manage``.
"""

from __future__ import annotations

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.schemas.common import ok
from app.services.branding_service import HEADER_LINES, BrandingService

router = APIRouter(prefix="/branding", tags=["branding"])


class HeaderUpdate(BaseModel):
    header_ar: list[str] = Field(min_length=HEADER_LINES, max_length=HEADER_LINES)
    header_en: list[str] = Field(min_length=HEADER_LINES, max_length=HEADER_LINES)


def _public_payload(branding: dict) -> dict:
    logo = branding.get("logo")
    return {
        "header_ar": branding["header_ar"],
        "header_en": branding["header_en"],
        "is_default": branding["is_default"],
        "updated_at": branding.get("updated_at"),
        "updated_by": branding.get("updated_by"),
        "logo": (
            {
                "filename": logo["filename"],
                "content_type": logo["content_type"],
                "bytes": logo["bytes"],
                "sha256": logo["sha256"],
                "width": logo.get("width"),
                "height": logo.get("height"),
                "converted": logo.get("converted", False),
                "original_type": logo.get("original_type"),
                "updated_at": logo.get("updated_at"),
                "updated_by": logo.get("updated_by"),
                "bundled": bool(logo.get("bundled")),
                "url": "/api/v1/branding/logo",
            }
            if logo
            else None
        ),
    }


@router.get("", summary="ترويسة التقارير الرسمية")
async def read_branding(session: SessionDep):
    """The letterhead in force — public, so the sign-in screen can print it too."""
    return ok(_public_payload(await BrandingService(session).get()))


@router.get("/logo", summary="الشعار الرسمي")
async def read_logo(session: SessionDep, sha: str | None = None):
    """The logo bytes.

    Cached with the checksum in the URL: a new upload changes the hash, so the
    browser picks it up without the platform ever serving a stale logo under a
    fresh letterhead.
    """
    branding = await BrandingService(session).load()
    body = branding.get("logo_bytes")
    if not body:
        return Response(status_code=404)
    logo = branding["logo"]
    from urllib.parse import quote

    return Response(
        content=body,
        media_type=logo["content_type"],
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(logo['filename'])}",
            "Content-Length": str(len(body)),
            "Cache-Control": "public, max-age=300, must-revalidate",
            "ETag": f'"{logo["sha256"]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.put("", summary="تعديل سطور الترويسة")
async def update_header(
    payload: HeaderUpdate, request: Request, session: SessionDep, principal: PrincipalDep
):
    principal.require("settings.manage")
    branding = await BrandingService(session).update_header(
        principal,
        header_ar=payload.header_ar,
        header_en=payload.header_en,
        ip=client_ip(request),
    )
    return ok(_public_payload(branding))


@router.post("/reset", summary="استعادة الترويسة الافتراضية")
async def reset_header(request: Request, session: SessionDep, principal: PrincipalDep):
    principal.require("settings.manage")
    branding = await BrandingService(session).reset_header(
        principal, ip=client_ip(request)
    )
    return ok(_public_payload(branding))


@router.post("/logo", summary="رفع الشعار الرسمي")
async def upload_logo(
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    file: UploadFile = File(...),
):
    principal.require("settings.manage")
    try:
        data = await file.read()
    finally:
        await file.close()
    branding = await BrandingService(session).set_logo(
        principal,
        filename=file.filename or "",
        content_type=(file.content_type or "").split(";")[0].strip().lower(),
        data=data,
        ip=client_ip(request),
    )
    return ok(_public_payload(branding))


@router.delete("/logo", summary="إزالة الشعار الرسمي")
async def delete_logo(request: Request, session: SessionDep, principal: PrincipalDep):
    principal.require("settings.manage")
    branding = await BrandingService(session).clear_logo(principal, ip=client_ip(request))
    return ok(_public_payload(branding))
