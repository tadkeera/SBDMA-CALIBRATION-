"""Report endpoints: calibration certificate (PDF), run data and registers (XLSX).

Every response is streamed as a download and recorded in the audit trail with the
caller, the document id and the byte size.
"""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.services.export_service import ExportService

router = APIRouter(prefix="/reports", tags=["reports"])

XLSX_MEDIA = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _download(blob: bytes, filename: str, media_type: str) -> Response:
    return Response(
        content=blob,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Length": str(len(blob)),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


@router.get("/runs/{run_id}/certificate.pdf", summary="شهادة المعايرة (PDF)")
async def certificate(
    run_id: uuid.UUID, request: Request, session: SessionDep, principal: PrincipalDep
):
    pdf, filename = await ExportService(session).certificate_pdf(
        run_id=run_id, principal=principal, ip=client_ip(request)
    )
    await session.commit()
    return _download(pdf, filename, "application/pdf")


@router.get(
    "/runs/{run_id}/tests/{test_code}/certificate.pdf",
    summary="شهادة معايرة لاختبار واحد (PDF)",
)
async def test_certificate(
    run_id: uuid.UUID,
    test_code: str,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    stage: str = Query(
        default="OFFICIAL",
        pattern="^(?i)(official|provisional)$",
        description="OFFICIAL = الشهادة الموقّعة، PROVISIONAL = مسودة غير صالحة كشهادة",
    ),
):
    """One test, one document — same letterhead, same gate as the run certificate.

    ``stage=PROVISIONAL`` returns the watermarked draft of the same document for a run that
    is executed but not yet reviewed and approved. It is not a certificate and says so on
    every page.
    """
    pdf, filename = await ExportService(session).test_certificate_pdf(
        run_id=run_id,
        test_code=test_code.upper(),
        principal=principal,
        ip=client_ip(request),
        stage=stage.upper(),
    )
    await session.commit()
    return _download(pdf, filename, "application/pdf")


@router.get("/runs/{run_id}/data.xlsx", summary="بيانات التشغيل (Excel)")
async def run_xlsx(
    run_id: uuid.UUID, request: Request, session: SessionDep, principal: PrincipalDep
):
    blob, filename = await ExportService(session).run_xlsx(
        run_id=run_id, principal=principal, ip=client_ip(request)
    )
    await session.commit()
    return _download(blob, filename, XLSX_MEDIA)


@router.get("/runs/register.xlsx", summary="سجل التشغيلات (Excel)")
async def runs_register(
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    limit: int = Query(default=500, ge=1, le=5000),
):
    blob, filename = await ExportService(session).runs_xlsx(
        principal=principal, ip=client_ip(request), limit=limit
    )
    await session.commit()
    return _download(blob, filename, XLSX_MEDIA)


@router.get("/audit.xlsx", summary="سجل التدقيق (Excel)")
async def audit_xlsx(
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
    limit: int = Query(default=2000, ge=1, le=20000),
):
    blob, filename = await ExportService(session).audit_xlsx(
        principal=principal, ip=client_ip(request), limit=limit
    )
    await session.commit()
    return _download(blob, filename, XLSX_MEDIA)
