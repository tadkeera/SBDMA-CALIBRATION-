"""Reference Manual API — the scientific documentation behind every test.

Three reads and two documents:

  * ``GET /reference-manual``                     — index of the twenty tests
  * ``GET /reference-manual/{test_code}``          — everything one section shows
  * ``GET /reference-manual/{test_code}/manual.pdf`` — that section as a printed document
  * ``GET /reference-manual/manual.pdf``           — the whole manual, one section per test

Reading needs ``instruments.view`` (it is reference information every analyst may
consult); printing needs ``reports.export``, and every printed document is audited with
its document id and byte size, because a manual that leaves the building is a controlled
document like any other.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.core.exceptions import NotFoundError
from app.domain.protocol.blueprint import PROTOCOL_CODE
from app.schemas.common import ok
from app.services.audit_service import AuditService
from app.services.branding_service import BrandingService
from app.services.manual_pdf import build_manual_pdf
from app.services.manual_service import load_manual
from app.services.report_service import document_id

router = APIRouter(prefix="/reference-manual", tags=["reference-manual"])


def _index_item(entry: dict) -> dict:
    return {
        "code": entry["code"],
        "sequence_order": entry["sequence_order"],
        "name_en": entry["name_en"],
        "name_ar": entry["name_ar"],
        "module": entry["module"],
        "standard_ref": entry["standard_ref"],
        "is_active": entry["is_active"],
        "overview_en": entry["overview_en"],
        "readings_count": len(entry["readings"]),
        "equations_count": len(entry["equations"]),
        "limits_count": len(entry["limits"]),
        "references_count": len(entry["references"]),
    }


@router.get("", summary="فهرس الدليل المرجعي للاختبارات العشرين")
async def manual_index(session: SessionDep, principal: PrincipalDep):
    principal.require("instruments.view")
    protocol, entries = await load_manual(session, protocol_code=PROTOCOL_CODE)
    if protocol is None:  # pragma: no cover - the seed guarantees the protocol
        raise NotFoundError(message_ar="البروتوكول غير موجود", message_en="Protocol not found")
    return ok(
        {
            "protocol_code": protocol.protocol_code,
            "protocol_version": protocol.version,
            "title_en": f"Reference Manual — {protocol.title_en}",
            "items": [_index_item(entry) for entry in entries],
            "count": len(entries),
        }
    )


# Declared before /{test_code} so that the literal path wins the match.
@router.get("/manual.pdf", summary="الدليل المرجعي الكامل (PDF)")
async def manual_full_pdf(request: Request, session: SessionDep, principal: PrincipalDep):
    principal.require("reports.export")
    protocol, entries = await load_manual(session, protocol_code=PROTOCOL_CODE)
    if protocol is None or not entries:  # pragma: no cover
        raise NotFoundError(message_ar="لا يوجد محتوى", message_en="No manual content")
    pdf = await _render(session, protocol, entries, principal, request, scope="ALL")
    return _download(pdf, "SBDMA-Reference-Manual.pdf")


@router.get("/{test_code}", summary="قسم واحد من الدليل المرجعي")
async def manual_entry(test_code: str, session: SessionDep, principal: PrincipalDep):
    principal.require("instruments.view")
    protocol, entries = await load_manual(
        session, protocol_code=PROTOCOL_CODE, test_codes=[test_code.upper()]
    )
    if protocol is None or not entries:
        raise NotFoundError(
            message_ar=f"الاختبار {test_code} غير موجود في الدليل",
            message_en=f"Test {test_code} is not in the manual",
        )
    entry = entries[0]
    return ok(
        entry
        | {
            "protocol_code": protocol.protocol_code,
            "protocol_version": protocol.version,
            "pdf_path": f"/reference-manual/{entry['code']}/manual.pdf",
        }
    )


@router.get("/{test_code}/manual.pdf", summary="قسم واحد من الدليل (PDF)")
async def manual_entry_pdf(
    test_code: str, request: Request, session: SessionDep, principal: PrincipalDep
):
    principal.require("reports.export")
    code = test_code.upper()
    protocol, entries = await load_manual(session, protocol_code=PROTOCOL_CODE, test_codes=[code])
    if protocol is None or not entries:
        raise NotFoundError(
            message_ar=f"الاختبار {test_code} غير موجود في الدليل",
            message_en=f"Test {test_code} is not in the manual",
        )
    pdf = await _render(session, protocol, entries, principal, request, scope=code)
    return _download(pdf, f"SBDMA-Reference-Manual-{code}.pdf")


async def _render(session, protocol, entries, principal, request, *, scope: str) -> bytes:
    payload = {
        "document_id": document_id("MANUAL", scope),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title_en": (
            f"Reference Manual — {entries[0]['name_en']} ({entries[0]['code']})"
            if len(entries) == 1
            else f"Reference Manual — {protocol.title_en}"
        ),
        "subtitle": (
            f"{protocol.protocol_code} · version {protocol.version} · "
            f"{len(entries)} test{'s' if len(entries) != 1 else ''} · English"
        ),
        "protocol": {"code": protocol.protocol_code, "version": protocol.version},
        "entries": entries,
        "page_total": 1,
        "branding": await BrandingService(session).load(),
    }
    pdf = await asyncio.to_thread(build_manual_pdf, payload)
    await AuditService(session).record(
        action="REFERENCE_MANUAL_EXPORTED",
        entity_type="calibration_protocol",
        entity_id=protocol.id,
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        new_values={
            "document_id": payload["document_id"],
            "scope": scope,
            "tests": [e["code"] for e in entries],
            "bytes": len(pdf),
        },
        reason="تصدير الدليل المرجعي كملف PDF",
        ip_address=client_ip(request),
    )
    await session.commit()
    return pdf


def _download(blob: bytes, filename: str) -> Response:
    return Response(
        content=blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Length": str(len(blob)),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
