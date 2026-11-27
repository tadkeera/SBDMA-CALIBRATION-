"""Assembles report payloads from stored rows and writes the access to the audit trail."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.core.rbac import Principal
from app.models.assets import Instrument, ReferenceEquipment
from app.models.audit import AuditLog
from app.models.protocol import AcceptanceLimit, CalibrationProtocol, TestDefinition
from app.models.rbac import LabDepartment, User
from app.models.runs import CalibrationRun, CalibrationTestResult
from app.services.audit_service import AuditService
from app.services.branding_service import BrandingService
from app.services.report_service import (
    build_certificate_pdf,
    build_run_xlsx,
    document_id,
    _fmt,
)
from app.services.test_certificate import build_test_certificate_pdf


class ExportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _run(self, run_id: uuid.UUID, principal: Principal) -> CalibrationRun:
        run = await self.session.get(CalibrationRun, run_id)
        if run is None:
            raise NotFoundError(message_ar="التشغيل غير موجود", message_en="Run not found")
        principal.assert_department(run.department_id)
        return run

    async def _load(self, run_id: uuid.UUID, principal: Principal) -> dict[str, Any]:
        run = await self._run(run_id, principal)
        instrument = await self.session.get(Instrument, run.instrument_id)
        protocol = await self.session.get(CalibrationProtocol, run.protocol_id)
        department = await self.session.get(LabDepartment, run.department_id)

        reference = None
        if run.reference_equipment_id:
            reference = await self.session.get(ReferenceEquipment, run.reference_equipment_id)

        results = (
            await self.session.execute(
                select(CalibrationTestResult)
                .where(CalibrationTestResult.run_id == run.id)
                .order_by(CalibrationTestResult.test_code)
            )
        ).scalars().all()

        user_ids = {run.analyst_id, run.reviewer_id, run.qa_approver_id} - {None}
        users = {
            u.id: u
            for u in (
                await self.session.execute(select(User).where(User.id.in_(user_ids)))
            ).scalars().all()
        } if user_ids else {}

        audit_rows = (
            await self.session.execute(
                select(AuditLog)
                .where(AuditLog.entity_id == str(run.id))
                .order_by(AuditLog.at)
            )
        ).scalars().all()

        return {
            "run": run,
            "instrument": instrument,
            "protocol": protocol,
            "department": department,
            "reference": reference,
            "results": results,
            "users": users,
            "audit": audit_rows,
        }

    async def _limits_for_protocol(self, protocol_id: uuid.UUID) -> list[list[Any]]:
        rows = (
            await self.session.execute(
                select(TestDefinition.test_code, AcceptanceLimit)
                .join(AcceptanceLimit, AcceptanceLimit.test_definition_id == TestDefinition.id)
                .where(TestDefinition.protocol_id == protocol_id)
                .order_by(TestDefinition.sequence_order, AcceptanceLimit.metric_key)
            )
        ).all()
        return [
            [
                code,
                limit.metric_key,
                limit.source_type,
                limit.operator,
                str(limit.min_value) if limit.min_value is not None else "",
                str(limit.max_value) if limit.max_value is not None else "",
                limit.unit,
                limit.approval_status,
            ]
            for code, limit in rows
        ]

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None

    def _common_payload(self, data: dict[str, Any], kind: str) -> dict[str, Any]:
        run: CalibrationRun = data["run"]
        instrument: Instrument = data["instrument"]
        protocol: CalibrationProtocol = data["protocol"]
        users = data["users"]
        reference = data["reference"]

        summary = {"pass": 0, "fail": 0, "review": 0, "incomplete": 0}
        metric_total = 0
        for result in data["results"]:
            summary[result.status.lower()] = summary.get(result.status.lower(), 0) + 1
            metric_total += len(result.metric_evaluations_jsonb or [])

        signatures = [
            {
                "role": "Analyst",
                "role_ar": "المحلل",
                "name": users[run.analyst_id].username if run.analyst_id in users else str(run.analyst_id),
                "at": self._iso(run.started_at),
                "meaning": "Executed the calibration and captured raw data",
            },
            {
                "role": "Supervisor review",
                "role_ar": "مشرف المختبر",
                "name": users[run.reviewer_id].username if run.reviewer_id in users else "—",
                "at": self._iso(run.reviewed_at),
                "meaning": "Supervisor reviewed the calculations and compliance with the protocol",
            },
            {
                "role": "QA approver",
                "role_ar": "معتمد ضمان الجودة",
                "name": users[run.qa_approver_id].username if run.qa_approver_id in users else "—",
                "at": self._iso(run.qa_approved_at),
                "meaning": "Approved the run; results are now locked and immutable",
            },
        ]

        raw_rows: list[list[Any]] = []
        for result in data["results"]:
            for key, value in (result.raw_inputs_jsonb or {}).items():
                raw_rows.append(
                    [result.test_code, key, ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)]
                )

        return {
            "document_id": document_id(kind, run.execution_code),
            "generated_at": self._iso(datetime.now(timezone.utc)),
            "page_total": 1,
            "subtitle": (
                f"{protocol.title_en} · v{protocol.version} · {instrument.asset_code} · "
                f"{data['department'].code if data['department'] else '—'}"
            ),
            "protocol": {"code": protocol.protocol_code, "version": protocol.version},
            "instrument": {
                "asset_code": instrument.asset_code,
                "category": instrument.category,
                "manufacturer": instrument.manufacturer,
                "model": instrument.model,
                "part_number": instrument.part_number,
                "serial_number": instrument.serial_number,
                "department_code": data["department"].code if data["department"] else None,
            },
            "reference": {
                "label": (
                    f"{reference.equipment_code} · {reference.certificate_no} · "
                    f"expires {reference.expiry_date.isoformat()}"
                    if reference
                    else "— none recorded —"
                )
            },
            "run": {
                "execution_code": run.execution_code,
                "run_type": run.run_type,
                "overall_status": run.overall_status,
                "limit_source_policy": run.limit_source_policy,
                "ambient_temp_c": f"{Decimal(str(run.ambient_temp_c)).normalize():f}"
                if run.ambient_temp_c is not None
                else None,
                "ambient_humidity": f"{Decimal(str(run.ambient_humidity)).normalize():f}"
                if run.ambient_humidity is not None
                else None,
                "started_at": self._iso(run.started_at),
                "completed_at": self._iso(run.completed_at),
                "reviewed_at": self._iso(run.reviewed_at),
                "qa_approved_at": self._iso(run.qa_approved_at),
                "certificate_hash": run.certificate_hash,
                "is_locked": run.is_locked,
                "revision": run.revision,
                "results": [
                    {
                        "test_code": r.test_code,
                        "status": r.status,
                        "notes_ar": r.notes_ar,
                        "metric_evaluations": r.metric_evaluations_jsonb or [],
                    }
                    for r in data["results"]
                ],
            },
            "summary": summary,
            "metric_total": metric_total,
            "signatures": signatures,
            "raw_rows": raw_rows,
            "audit": [
                [
                    a.at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    a.actor_label,
                    a.role_label or "",
                    a.action,
                    a.reason or "",
                    a.hash[:16],
                ]
                for a in data["audit"]
            ],
            "limits": [],
        }

    # ───────────────────────────── public API ────────────────────────────── #

    async def certificate_pdf(
        self, *, run_id: uuid.UUID, principal: Principal, ip: str | None = None
    ) -> tuple[bytes, str]:
        principal.require("reports.export")
        data = await self._load(run_id, principal)
        run: CalibrationRun = data["run"]

        if not run.is_locked or run.qa_approved_at is None or not run.certificate_hash:
            raise ConflictError(
                message_ar=(
                    "لا يمكن إصدار شهادة قبل الاعتماد النهائي من ضمان الجودة — "
                    "الشهادة تُصدر فقط لتشغيل مقفل وموقّع."
                ),
                message_en=(
                    "A certificate can only be issued for an approved, locked and signed run."
                ),
            )
        if run.overall_status != "PASS":
            raise ConflictError(
                message_ar="لا تُصدر شهادة معايرة لتشغيل غير مطابق أو غير مكتمل",
                message_en="A calibration certificate is only issued for a PASS verdict",
            )

        payload = self._common_payload(data, "CERT")
        payload["limit_total"] = len(await self._limits_for_protocol(run.protocol_id))
        # the official letterhead is read at render time, so an approved logo or an
        # edited header is on the very next certificate without a deployment
        payload["branding"] = await BrandingService(self.session).load()
        # ReportLab lays out thousands of glyphs and shapes Arabic text; that is CPU
        # work, and on the event loop it froze the API for over a second per
        # certificate (see docs/load-test.md).
        pdf = await asyncio.to_thread(build_certificate_pdf, payload)

        await AuditService(self.session).record(
            action="CERTIFICATE_PDF_EXPORTED",
            entity_type="calibration_run",
            entity_id=run.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=run.department_id,
            new_values={"document_id": payload["document_id"], "bytes": len(pdf)},
            reason="إصدار شهادة معايرة PDF لتشغيل معتمد ومقفل",
            ip_address=ip,
        )
        filename = f"{run.execution_code}-certificate.pdf"
        return pdf, filename

    async def test_certificate_pdf(
        self,
        *,
        run_id: uuid.UUID,
        test_code: str,
        principal: Principal,
        ip: str | None = None,
        stage: str = "OFFICIAL",
    ) -> tuple[bytes, str]:
        """A certificate for a single test of an approved run.

        Same gate as the run certificate — approved, locked and signed — because what
        makes a certificate a record rather than a printout is that it refers to a
        frozen run with a recorded fingerprint. Only a PASS test is certified: a
        certificate attests conformity, and a FAIL verdict is a deviation, not a
        certificate.

        ``stage="PROVISIONAL"`` produces the *draft* of the same document for a run that
        has been executed but not yet reviewed and approved. It exists because the
        laboratory has to see where a result stands in the approval cycle — "Pending
        Review" or "Pending QA Approval", with the names and dates that are already known
        — without that sheet ever passing for a certificate. It is watermarked across the
        page, its footer says DRAFT, and it is audited under its own action, so a draft in
        a folder can never be mistaken for the signed record.
        """
        provisional = str(stage).upper() == "PROVISIONAL"
        principal.require("reports.export")
        data = await self._load(run_id, principal)
        run: CalibrationRun = data["run"]

        if provisional:
            if run.overall_status == "INCOMPLETE":
                raise ConflictError(
                    message_ar="لا يمكن إصدار مسودة شهادة لتشغيل غير منفّذ بعد",
                    message_en="A provisional document cannot be issued for an unexecuted run",
                )
        elif not run.is_locked or run.qa_approved_at is None or not run.certificate_hash:
            raise ConflictError(
                message_ar=(
                    "لا يمكن إصدار شهادة اختبار قبل الاعتماد النهائي من ضمان الجودة — "
                    "الشهادة تُصدر فقط لتشغيل مقفل وموقّع."
                ),
                message_en="A test certificate can only be issued for an approved and locked run.",
            )

        result = next((r for r in data["results"] if r.test_code == test_code), None)
        if result is None:
            raise NotFoundError(
                message_ar=f"الاختبار {test_code} غير موجود في هذا التشغيل",
                message_en=f"Test {test_code} is not part of this run",
            )
        if result.status != "PASS" and not provisional:
            raise ConflictError(
                message_ar=(
                    f"لا تُصدر شهادة للاختبار {test_code} حالته {result.status} — "
                    "الشهادة تُصدر فقط لاختبار مطابق."
                ),
                message_en=(
                    f"Test {test_code} is {result.status}; a certificate is only issued for a PASS."
                ),
            )

        definition = await self.session.get(TestDefinition, result.test_definition_id)
        if definition is None:  # pragma: no cover - FK guarantees it
            raise NotFoundError(message_ar="تعريف الاختبار غير موجود", message_en="Test definition missing")

        fields = ((definition.input_schema_jsonb or {}).get("fields")) or []
        labels = {f.get("key"): (f.get("label_en"), f.get("unit")) for f in fields}

        readings: list[list[str]] = []
        for key, value in (result.raw_inputs_jsonb or {}).items():
            label, unit = labels.get(key, (key, ""))
            shown = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
            readings.append([label or key, shown, unit or "—"])

        metrics_payload: list[list[str]] = []
        for metric in result.metric_evaluations_jsonb or []:
            unit = metric.get("unit") or ""
            # The stored value keeps full precision; the certificate prints six
            # significant digits (the same rule as the run certificate) so a
            # repeatability figure reads 0.104881 nm instead of forty digits.
            shown = _fmt(metric.get("value"))
            metrics_payload.append(
                [
                    metric.get("metric_key", ""),
                    f"{shown} {unit}".strip() if shown != "—" else "—",
                    metric.get("limit_text") or "—",
                    metric.get("applied_source") or "—",
                    metric.get("status", ""),
                    (metric.get("message_ar") or "—"),
                ]
            )

        payload = self._common_payload(data, "TCERT")
        payload["document_id"] = document_id("TCERT", f"{run.execution_code}-{test_code}")
        payload["branding"] = await BrandingService(self.session).load()
        payload["test"] = {
            "code": definition.test_code,
            "name_en": definition.name_en,
            "name_ar": definition.name_ar,
            "module": definition.module,
            "standard_ref": definition.standard_ref,
            "status": result.status,
            "notes_ar": result.notes_ar,
        }
        payload["readings"] = readings
        payload["metrics"] = metrics_payload
        # The chart page reads the stored row directly rather than the formatted table:
        # "0.9998" is what is printed, 0.9998 is what is drawn, and neither is re-entered.
        payload["raw_inputs"] = dict(result.raw_inputs_jsonb or {})
        payload["outputs"] = dict(result.calculated_outputs_jsonb or {})
        payload["metrics_structured"] = [
            {
                "metric_key": metric.get("metric_key"),
                "value": metric.get("value"),
                "unit": metric.get("unit"),
                "limit_text": metric.get("limit_text"),
                "applied_source": metric.get("applied_source"),
                "status": metric.get("status"),
                # bounds, when the stored evaluation carries them; the chart falls back to
                # parsing the printed limit text for older rows that do not
                "min_value": metric.get("min_value"),
                "max_value": metric.get("max_value"),
                "comparator": metric.get("comparator"),
            }
            for metric in (result.metric_evaluations_jsonb or [])
        ]
        payload["chart"] = (definition.chart_config_jsonb or {}).get("type") or "none"
        payload["stage"] = "PROVISIONAL" if provisional else "OFFICIAL"
        payload["approval"] = self._approval_state(data)
        # the renderer resolves the page total itself (two passes) so the footer is right
        pdf = await asyncio.to_thread(build_test_certificate_pdf, payload)

        await AuditService(self.session).record(
            action=(
                "TEST_CERTIFICATE_PROVISIONAL_EXPORTED" if provisional else "TEST_CERTIFICATE_EXPORTED"
            ),
            entity_type="calibration_test_result",
            entity_id=result.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=run.department_id,
            new_values={
                "document_id": payload["document_id"],
                "test_code": test_code,
                "run_code": run.execution_code,
                "bytes": len(pdf),
                "stage": payload["stage"],
            },
            reason=(
                f"إصدار مسودة شهادة للاختبار {test_code}"
                if provisional
                else f"إصدار شهادة معايرة للاختبار {test_code}"
            ),
            ip_address=ip,
        )
        suffix = "draft" if provisional else "certificate"
        filename = f"{run.execution_code}-{test_code}-{suffix}.pdf"
        return pdf, filename

    @staticmethod
    def _approval_state(data: dict[str, Any]) -> dict[str, Any]:
        """Who has signed, who has not — the two rows the certificate must always print.

        Derived from the stored reviewer/approver columns rather than from a separate
        status field, so there is one truth: a name and a timestamp are either on the run
        or they are not.
        """
        run: CalibrationRun = data["run"]
        users: dict[uuid.UUID, Any] = data.get("users") or {}
        analyst = users.get(run.analyst_id) if run.analyst_id in users else None
        reviewer = users.get(run.reviewer_id) if run.reviewer_id in users else None
        approver = users.get(run.qa_approver_id) if run.qa_approver_id in users else None
        return {
            "analyst": {
                "name": analyst.username if analyst else "—",
                "at": ExportService._iso(run.started_at),
                "status": "Executed",
            },
            "supervisor": {
                "name": reviewer.username if reviewer else "—",
                "at": ExportService._iso(run.reviewed_at),
                "status": "Approved" if run.reviewed_at else "Pending Review",
            },
            "qa": {
                "name": approver.username if approver else "—",
                "at": ExportService._iso(run.qa_approved_at),
                "status": "Approved" if run.qa_approved_at else "Pending QA Approval",
            },
        }

    async def run_xlsx(
        self, *, run_id: uuid.UUID, principal: Principal, ip: str | None = None
    ) -> tuple[bytes, str]:
        principal.require("reports.export")
        data = await self._load(run_id, principal)
        run: CalibrationRun = data["run"]

        payload = self._common_payload(data, "XLSX")
        payload["limits"] = await self._limits_for_protocol(run.protocol_id)
        payload["branding"] = await BrandingService(self.session).load()
        blob = await asyncio.to_thread(build_run_xlsx, payload)

        await AuditService(self.session).record(
            action="RUN_XLSX_EXPORTED",
            entity_type="calibration_run",
            entity_id=run.id,
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=run.department_id,
            new_values={"document_id": payload["document_id"], "bytes": len(blob)},
            reason="تصدير بيانات التشغيل إلى Excel للمراجعة والتوثيق",
            ip_address=ip,
        )
        return blob, f"{run.execution_code}-data.xlsx"

    async def runs_xlsx(
        self, *, principal: Principal, ip: str | None = None, limit: int = 500
    ) -> tuple[bytes, str]:
        """Register export: every run visible to the caller, with its verdict."""
        principal.require("reports.export")
        stmt = select(CalibrationRun).order_by(CalibrationRun.started_at.desc()).limit(limit)
        if not principal.is_supervisor():
            stmt = stmt.where(CalibrationRun.department_id == principal.department_id)
        runs = (await self.session.execute(stmt)).scalars().all()

        from openpyxl import Workbook

        from app.services.report_service import _write_sheet

        wb = Workbook()
        ws = wb.active
        ws.title = "Runs"
        instrument_ids = {r.instrument_id for r in runs}
        instruments = {
            i.id: i
            for i in (
                await self.session.execute(
                    select(Instrument).where(Instrument.id.in_(instrument_ids))
                )
            ).scalars().all()
        } if instrument_ids else {}

        rows = [
            [
                r.execution_code,
                instruments[r.instrument_id].asset_code if r.instrument_id in instruments else str(r.instrument_id),
                r.run_type,
                r.overall_status,
                r.limit_source_policy,
                self._iso(r.started_at),
                self._iso(r.qa_approved_at),
                "YES" if r.is_locked else "NO",
                r.certificate_hash or "",
            ]
            for r in runs
        ]
        _write_sheet(
            ws,
            "Calibration runs register",
            f"Generated {self._iso(datetime.now(timezone.utc))} · {len(rows)} runs · "
            f"scope: {'all departments' if principal.is_supervisor() else 'own department'}",
            ["Run code", "Instrument", "Type", "Verdict", "Limit policy", "Started", "Approved",
             "Locked", "Certificate SHA-256"],
            rows,
            [22, 16, 16, 14, 18, 22, 22, 8, 68],
            branding=await BrandingService(self.session).load(),
        )
        buf = __import__("io").BytesIO()
        wb.save(buf)
        blob = buf.getvalue()

        await AuditService(self.session).record(
            action="RUNS_REGISTER_XLSX_EXPORTED",
            entity_type="calibration_run",
            entity_id="*",
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            department_id=principal.department_id,
            new_values={"rows": len(rows), "bytes": len(blob)},
            reason="تصدير سجل التشغيلات إلى Excel",
            ip_address=ip,
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return blob, f"SBDMA-runs-register-{stamp}.xlsx"

    async def audit_xlsx(
        self, *, principal: Principal, ip: str | None = None, limit: int = 2000
    ) -> tuple[bytes, str]:
        principal.require("audit.view")
        stmt = select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)
        if not principal.is_supervisor() and principal.department_id:
            stmt = stmt.where(AuditLog.department_id == principal.department_id)
        rows = (await self.session.execute(stmt)).scalars().all()

        from openpyxl import Workbook

        from app.services.report_service import _write_sheet

        wb = Workbook()
        ws = wb.active
        ws.title = "Audit trail"
        _write_sheet(
            ws,
            "Audit trail export",
            "Append-only at the database level: UPDATE, DELETE and TRUNCATE are rejected.",
            ["Timestamp (UTC)", "Actor", "Role", "Action", "Entity", "Entity id", "Reason",
             "Previous hash", "Hash"],
            [
                [
                    a.at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    a.actor_label,
                    a.role_label or "",
                    a.action,
                    a.entity_type,
                    a.entity_id[:36],
                    a.reason or "",
                    a.prev_hash[:16],
                    a.hash,
                ]
                for a in rows
            ],
            [22, 18, 14, 30, 18, 38, 50, 20, 66],
            branding=await BrandingService(self.session).load(),
        )
        buf = __import__("io").BytesIO()
        wb.save(buf)
        blob = buf.getvalue()

        await AuditService(self.session).record(
            action="AUDIT_XLSX_EXPORTED",
            entity_type="audit_log",
            entity_id="*",
            actor_label=principal.username,
            actor_id=principal.user_id,
            role_label=principal.primary_role,
            new_values={"rows": len(rows), "bytes": len(blob)},
            reason="تصدير سجل التدقيق إلى Excel",
            ip_address=ip,
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return blob, f"SBDMA-audit-trail-{stamp}.xlsx"
