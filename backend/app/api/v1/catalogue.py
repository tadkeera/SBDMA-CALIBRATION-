"""Instruments, reference items, protocol/limits, maintenance and audit reads."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.api.deps import PrincipalDep, SessionDep, client_ip
from app.core.exceptions import NotFoundError, ValidationFailedError
from app.domain.protocol.blueprint import tests_for_component
from app.schemas.assets import (
    AuditOut,
    InstrumentCreate,
    InstrumentOut,
    InstrumentUpdate,
    LimitApproveRequest,
    LimitOut,
    MaintenanceTicketCreate,
    MaintenanceTicketOut,
    ProtocolOut,
    ReferenceEquipmentOut,
    ReferenceStandardOut,
    TestDefinitionOut,
)
from app.schemas.auth import SignaturePayload
from app.schemas.common import ok
from app.core.security import verify_password
from app.core.rbac import Principal
from app.models.assets import Instrument, ReferenceEquipment, ReferenceStandard
from app.models.audit import AuditLog
from app.models.protocol import AcceptanceLimit, CalibrationProtocol, TestDefinition
from app.models.rbac import User
from app.models.runs import MaintenanceTicket
from app.services.audit_service import AuditService

router = APIRouter(tags=["catalogue"])


# ────────────────────────────── departments ───────────────────────────────── #


@router.get("/departments", summary="أقسام ومختبرات الهيئة")
async def list_departments(session: SessionDep, principal: PrincipalDep):
    from app.models.rbac import LabDepartment

    principal.require("instruments.view")
    rows = (
        await session.execute(
            select(LabDepartment).where(LabDepartment.deleted_at.is_(None)).order_by(LabDepartment.code)
        )
    ).scalars().all()
    return ok(
        [
            {
                "id": str(d.id),
                "code": d.code,
                "name_ar": d.name_ar,
                "name_en": d.name_en,
                "location": d.location,
                "is_active": d.is_active,
            }
            for d in rows
        ]
    )


# ────────────────────────────── instruments ───────────────────────────────── #


@router.get("/instruments", summary="سجل الأجهزة")
async def list_instruments(
    session: SessionDep,
    principal: PrincipalDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    category: str | None = None,
    status: str | None = None,
    department_id: uuid.UUID | None = None,
):
    principal.require("instruments.view")
    stmt = select(Instrument).where(Instrument.deleted_at.is_(None))
    count_stmt = select(func.count()).select_from(Instrument).where(Instrument.deleted_at.is_(None))

    conditions = []
    if not principal.is_supervisor():
        conditions.append(Instrument.department_id == principal.department_id)
    elif department_id:
        conditions.append(Instrument.department_id == department_id)
    if category:
        conditions.append(Instrument.category == category)
    if status:
        conditions.append(Instrument.status == status)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(Instrument.asset_code).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return ok(
        [InstrumentOut.model_validate(r).model_dump(mode="json") for r in rows],
        meta={
            "page": page,
            "page_size": page_size,
            "total": int(total),
            "pages": (int(total) + page_size - 1) // page_size,
        },
    )


@router.post("/instruments", summary="تسجيل جهاز جديد", status_code=201)
async def create_instrument(
    payload: InstrumentCreate, request: Request, session: SessionDep, principal: PrincipalDep
):
    principal.require("instruments.create")
    principal.assert_department(payload.department_id)
    existing = (
        await session.execute(
            select(Instrument).where(Instrument.asset_code == payload.asset_code)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ValidationFailedError(
            message_ar="رمز الأصل مسجل مسبقاً",
            message_en="Asset code already registered",
            field="asset_code",
        )
    last = payload.last_calibration_date
    instrument = Instrument(
        id=uuid.uuid4(),
        department_id=payload.department_id,
        asset_code=payload.asset_code.strip(),
        category=payload.category,
        manufacturer=payload.manufacturer,
        model=payload.model,
        part_number=payload.part_number,
        serial_number=payload.serial_number,
        software_version=payload.software_version,
        configuration_jsonb=payload.configuration_jsonb,
        calibration_freq_days=payload.calibration_freq_days,
        last_calibration_date=last,
        next_due_date=last + timedelta(days=payload.calibration_freq_days) if last else None,
        status="ACTIVE",
        d2_lamp_hours=payload.d2_lamp_hours,
    )
    session.add(instrument)
    await session.flush()
    await AuditService(session).record(
        action="INSTRUMENT_CREATED",
        entity_type="instrument",
        entity_id=instrument.id,
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        department_id=instrument.department_id,
        new_values={
            "asset_code": instrument.asset_code,
            "model": instrument.model,
            "serial": instrument.serial_number,
        },
        reason="تسجيل جهاز جديد في سجل الأجهزة",
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok(InstrumentOut.model_validate(instrument).model_dump(mode="json"))


@router.patch("/instruments/{instrument_id}", summary="تحديث جهاز")
async def update_instrument(
    instrument_id: uuid.UUID,
    payload: InstrumentUpdate,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    principal.require("instruments.update")
    instrument = await session.get(Instrument, instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise NotFoundError(message_ar="الجهاز غير موجود", message_en="Instrument not found")
    principal.assert_department(instrument.department_id)

    before = {"status": instrument.status, "freq": instrument.calibration_freq_days}
    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(instrument, key, value)
    if "last_calibration_date" in data and data["last_calibration_date"]:
        instrument.next_due_date = data["last_calibration_date"] + timedelta(
            days=instrument.calibration_freq_days
        )

    await AuditService(session).record(
        action="INSTRUMENT_UPDATED",
        entity_type="instrument",
        entity_id=instrument.id,
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        department_id=instrument.department_id,
        old_values=before,
        new_values={k: str(v) for k, v in data.items()},
        reason="تحديث بيانات الجهاز",
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok(InstrumentOut.model_validate(instrument).model_dump(mode="json"))


@router.delete("/instruments/{instrument_id}", summary="حذف ناعم للجهاز")
async def delete_instrument(
    instrument_id: uuid.UUID, request: Request, session: SessionDep, principal: PrincipalDep
):
    principal.require("instruments.delete")
    instrument = await session.get(Instrument, instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise NotFoundError()
    principal.assert_department(instrument.department_id)
    from datetime import datetime, timezone

    instrument.deleted_at = datetime.now(timezone.utc)
    await AuditService(session).record(
        action="INSTRUMENT_SOFT_DELETED",
        entity_type="instrument",
        entity_id=instrument.id,
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        department_id=instrument.department_id,
        new_values={"deleted_at": instrument.deleted_at.isoformat()},
        reason="حذف ناعم لجهاز من السجل",
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok({"deleted": True, "soft": True})


# ───────────────────────────── reference items ────────────────────────────── #


@router.get("/reference-equipment", summary="الأدوات المرجعية")
async def list_reference_equipment(session: SessionDep, principal: PrincipalDep):
    principal.require("instruments.view")
    stmt = select(ReferenceEquipment)
    if not principal.is_supervisor():
        stmt = stmt.where(ReferenceEquipment.department_id == principal.department_id)
    rows = (await session.execute(stmt.order_by(ReferenceEquipment.equipment_code))).scalars().all()
    today = date.today()
    return ok(
        [
            {
                **ReferenceEquipmentOut.model_validate(r).model_dump(mode="json"),
                "expired": r.expiry_date < today,
                "days_to_expiry": (r.expiry_date - today).days,
            }
            for r in rows
        ]
    )


@router.get("/reference-standards", summary="المواد والمحاليل القياسية")
async def list_reference_standards(session: SessionDep, principal: PrincipalDep):
    principal.require("instruments.view")
    stmt = select(ReferenceStandard)
    if not principal.is_supervisor():
        stmt = stmt.where(ReferenceStandard.department_id == principal.department_id)
    rows = (await session.execute(stmt.order_by(ReferenceStandard.name))).scalars().all()
    today = date.today()
    return ok(
        [
            {
                **ReferenceStandardOut.model_validate(r).model_dump(mode="json"),
                "expired": r.expiry_date < today,
                "days_to_expiry": (r.expiry_date - today).days,
            }
            for r in rows
        ]
    )


# ─────────────────────────────── protocols ────────────────────────────────── #


@router.get("/protocols", summary="البروتوكولات المعتمدة")
async def list_protocols(session: SessionDep, principal: PrincipalDep):
    principal.require("instruments.view")
    rows = (
        await session.execute(
            select(CalibrationProtocol).order_by(CalibrationProtocol.protocol_code)
        )
    ).scalars().all()
    return ok(
        [
            {
                "id": str(p.id),
                "protocol_code": p.protocol_code,
                "instrument_category": p.instrument_category,
                "title_ar": p.title_ar,
                "title_en": p.title_en,
                "version": p.version,
                "status": p.status,
            }
            for p in rows
        ]
    )


@router.get("/protocols/{protocol_code}", summary="تفاصيل بروتوكول مع اختباراته وحدوده")
async def get_protocol(protocol_code: str, session: SessionDep, principal: PrincipalDep):
    principal.require("instruments.view")
    protocol = (
        await session.execute(
            select(CalibrationProtocol)
            .where(CalibrationProtocol.protocol_code == protocol_code)
            .order_by(CalibrationProtocol.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if protocol is None:
        raise NotFoundError(message_ar="البروتوكول غير موجود", message_en="Protocol not found")
    await session.refresh(protocol, attribute_names=["tests"])
    tests = sorted(protocol.tests, key=lambda t: t.sequence_order)
    return ok(
        {
            "id": str(protocol.id),
            "protocol_code": protocol.protocol_code,
            "version": protocol.version,
            "status": protocol.status,
            "title_ar": protocol.title_ar,
            "title_en": protocol.title_en,
            "tests": [
                TestDefinitionOut(
                    id=t.id,
                    test_code=t.test_code,
                    sequence_order=t.sequence_order,
                    module=t.module,
                    name_ar=t.name_ar,
                    name_en=t.name_en,
                    standard_ref=t.standard_ref,
                    procedure_ar=t.procedure_ar,
                    input_schema_jsonb=t.input_schema_jsonb,
                    chart_config_jsonb=t.chart_config_jsonb,
                    is_mandatory=t.is_mandatory,
                    limits=[
                        LimitOut(
                            id=lim.id,
                            metric_key=lim.metric_key,
                            source_type=lim.source_type,
                            operator=lim.operator,
                            min_value=str(lim.min_value) if lim.min_value is not None else None,
                            max_value=str(lim.max_value) if lim.max_value is not None else None,
                            unit=lim.unit,
                            approval_status=lim.approval_status,
                            note_ar=lim.note_ar,
                            flagged=lim.flagged,
                        )
                        for lim in t.limits
                    ],
                    formulas=[
                        {
                            "id": str(f.id),
                            "formula_key": f.formula_key,
                            "description_ar": f.description_ar,
                            "description_en": f.description_en,
                            "expression_text": f.expression_text,
                            "rounding_decimals": f.rounding_decimals,
                            "version": f.version,
                            "is_active": f.is_active,
                        }
                        for f in t.formulas
                    ],
                ).model_dump(mode="json")
                for t in tests
            ],
        }
    )


@router.post("/limits/{limit_id}/approve", summary="اعتماد حد قبول بتوقيع إلكتروني")
async def approve_limit(
    limit_id: uuid.UUID,
    payload: SignaturePayload,
    body_status: str | None = None,
    request: Request = None,  # type: ignore[assignment]
    session: SessionDep = None,  # type: ignore[assignment]
    principal: PrincipalDep = None,  # type: ignore[assignment]
):
    principal.require("limits.approve")
    limit = await session.get(AcceptanceLimit, limit_id)
    if limit is None:
        raise NotFoundError(message_ar="حد القبول غير موجود", message_en="Acceptance limit not found")
    user = await session.get(User, principal.user_id)
    valid, _ = verify_password(payload.password, user.password_hash) if user else (False, None)
    if not valid:
        raise ValidationFailedError(
            message_ar="كلمة المرور غير صحيحة — التوقيع مرفوض",
            message_en="Incorrect password — signature rejected",
        )
    before = {"approval_status": limit.approval_status}
    limit.approval_status = "APPROVED"
    limit.approved_by = principal.user_id
    from datetime import datetime, timezone

    limit.approved_at = datetime.now(timezone.utc)
    await AuditService(session).record(
        action="ACCEPTANCE_LIMIT_APPROVED",
        entity_type="acceptance_limit",
        entity_id=limit.id,
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        old_values=before,
        new_values={
            "approval_status": limit.approval_status,
            "metric_key": limit.metric_key,
            "source_type": limit.source_type,
        },
        reason=payload.reason,
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok(LimitOut(
        id=limit.id,
        metric_key=limit.metric_key,
        source_type=limit.source_type,
        operator=limit.operator,
        min_value=str(limit.min_value) if limit.min_value is not None else None,
        max_value=str(limit.max_value) if limit.max_value is not None else None,
        unit=limit.unit,
        approval_status=limit.approval_status,
        note_ar=limit.note_ar,
        flagged=limit.flagged,
    ).model_dump(mode="json"))


# ────────────────────────────── maintenance ───────────────────────────────── #


@router.get("/maintenance/tickets", summary="تذاكر الصيانة")
async def list_tickets(session: SessionDep, principal: PrincipalDep, status: str | None = None):
    principal.require("instruments.view")
    stmt = select(MaintenanceTicket)
    if status:
        stmt = stmt.where(MaintenanceTicket.status == status)
    rows = (await session.execute(stmt.order_by(MaintenanceTicket.created_at.desc()))).scalars().all()
    return ok(
        [
            {
                "id": str(t.id),
                "instrument_id": str(t.instrument_id),
                "component_affected": t.component_affected,
                "description": t.description,
                "required_tests": t.required_tests_jsonb or [],
                "status": t.status,
                "reported_by": str(t.reported_by) if t.reported_by else None,
                "resolved_by": str(t.resolved_by) if t.resolved_by else None,
                "resolved_at": t.resolved_at.isoformat() if t.resolved_at else None,
            }
            for t in rows
        ]
    )


@router.post("/maintenance/tickets", summary="فتح تذكرة صيانة", status_code=201)
async def create_ticket(
    payload: MaintenanceTicketCreate,
    request: Request,
    session: SessionDep,
    principal: PrincipalDep,
):
    principal.require("maintenance.manage")
    instrument = await session.get(Instrument, payload.instrument_id)
    if instrument is None or instrument.deleted_at is not None:
        raise NotFoundError(message_ar="الجهاز غير موجود", message_en="Instrument not found")
    principal.assert_department(instrument.department_id)

    required = list(tests_for_component(payload.component_affected))
    if not required:
        raise ValidationFailedError(
            message_ar="المكوّن غير موجود في مصفوفة ما بعد الأعطال",
            message_en="Component is not part of the post-breakdown matrix",
            field="component_affected",
        )
    ticket = MaintenanceTicket(
        id=uuid.uuid4(),
        instrument_id=instrument.id,
        component_affected=payload.component_affected,
        description=payload.description,
        required_tests_jsonb=required,
        status="OPEN",
        reported_by=principal.user_id,
    )
    session.add(ticket)
    instrument.status = "UNDER_MAINTENANCE"
    await session.flush()
    await AuditService(session).record(
        action="MAINTENANCE_TICKET_OPENED",
        entity_type="maintenance_ticket",
        entity_id=ticket.id,
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        department_id=instrument.department_id,
        new_values={
            "component": payload.component_affected,
            "required_tests": required,
            "instrument": instrument.asset_code,
        },
        reason=payload.description,
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok(
        {
            "id": str(ticket.id),
            "component_affected": ticket.component_affected,
            "required_tests": required,
            "status": ticket.status,
        }
    )


@router.post("/maintenance/tickets/{ticket_id}/resolve", summary="إنجاز تذكرة صيانة")
async def resolve_ticket(
    ticket_id: uuid.UUID, request: Request, session: SessionDep, principal: PrincipalDep
):
    principal.require("maintenance.manage")
    ticket = await session.get(MaintenanceTicket, ticket_id)
    if ticket is None:
        raise NotFoundError(message_ar="التذكرة غير موجودة", message_en="Ticket not found")
    if ticket.status == "RESOLVED":
        raise ValidationFailedError(message_ar="التذكرة منجزة مسبقاً", message_en="Ticket already resolved")
    from datetime import datetime, timezone

    ticket.status = "RESOLVED"
    ticket.resolved_by = principal.user_id
    ticket.resolved_at = datetime.now(timezone.utc)
    instrument = await session.get(Instrument, ticket.instrument_id)
    if instrument is not None:
        instrument.status = "ACTIVE"
    await AuditService(session).record(
        action="MAINTENANCE_TICKET_RESOLVED",
        entity_type="maintenance_ticket",
        entity_id=ticket.id,
        actor_label=principal.username,
        actor_id=principal.user_id,
        role_label=principal.primary_role,
        new_values={"status": "RESOLVED", "resolved_by": principal.username},
        reason="إنجاز التذكرة بعد تنفيذ الصيانة",
        ip_address=client_ip(request),
    )
    await session.commit()
    return ok({"id": str(ticket.id), "status": ticket.status, "required_tests": ticket.required_tests_jsonb})


# ──────────────────────────────── audit ───────────────────────────────────── #


@router.get("/audit", summary="سجل التدقيق")
async def list_audit(
    session: SessionDep,
    principal: PrincipalDep,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    action: str | None = None,
    entity_type: str | None = None,
):
    principal.require("audit.view")
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)
    conditions = []
    if not principal.is_supervisor() and principal.department_id:
        conditions.append(AuditLog.department_id == principal.department_id)
    if action:
        conditions.append(AuditLog.action == action)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)
    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(AuditLog.at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()
    return ok(
        [
            {
                "id": str(r.id),
                "at": r.at.isoformat(),
                "actor_label": r.actor_label,
                "role_label": r.role_label,
                "action": r.action,
                "entity_type": r.entity_type,
                "entity_id": r.entity_id,
                "reason": r.reason,
                "request_id": r.request_id,
                "prev_hash": r.prev_hash,
                "hash": r.hash,
            }
            for r in rows
        ],
        meta={"page": page, "page_size": page_size, "total": int(total)},
    )


@router.get("/audit/verify", summary="التحقق من سلامة سلسلة التدقيق")
async def verify_audit(session: SessionDep, principal: PrincipalDep):
    principal.require("audit.view")
    result = await AuditService.verify_chain(session)
    return ok(result)
